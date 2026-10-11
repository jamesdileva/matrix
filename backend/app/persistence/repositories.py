"""Repository layer: persistence for engine artifacts.

The engine stays pure — this module subscribes to the EventBus
(`DatabaseEventRecorder`) and answers event queries (`EventRepository`)
for the API and future UI layers.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.config import model_configuration as active_model_configuration
from app.persistence.models import (
    AgentModel,
    CheckpointModel,
    EventModel,
    ExperimentModel,
    PopulationModel,
)
from app.simulation.events import Event, EventTypes


class DatabaseEventRecorder:
    """EventBus subscriber that persists one world's events to the database.

    Each event commits in its own short-lived session by default —
    simple and safe at current scale, and what live watched worlds want
    (the database is their durable archive).

    ``batch_size > 1`` is the scale switch (S12): events buffer in
    memory and commit in one transaction per batch. No session is held
    between events — SQLite would lock out concurrent writers
    (checkpoints, agent rows). Callers that batch must ``flush()``; the
    experiment runner does, and a hard crash loses at most one batch.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        world_id: int,
        *,
        batch_size: int = 1,
    ) -> None:
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        self._session_factory = session_factory
        self._world_id = world_id
        self._batch_size = batch_size
        self._buffer: list[EventModel] = []

    def __call__(self, event: Event) -> None:
        if self._batch_size == 1:
            with self._session_factory() as session:
                session.add(self._to_model(event))
                session.commit()
            return
        self._buffer.append(self._to_model(event))
        if len(self._buffer) >= self._batch_size:
            self._commit_buffer()

    def flush(self) -> None:
        """Commit whatever is buffered."""
        self._commit_buffer()

    def _commit_buffer(self) -> None:
        if not self._buffer:
            return
        rows, self._buffer = self._buffer, []
        with self._session_factory() as session:
            session.add_all(rows)
            session.commit()

    def _to_model(self, event: Event) -> EventModel:
        return EventModel(
            world_id=self._world_id,
            sequence=event.id,
            tick=event.tick,
            type=event.type,
            actor_id=event.actor_id,
            target_id=event.target_id,
            payload=event.payload,
        )


class EventRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def recent(
        self,
        world_id: int,
        limit: int = 50,
        *,
        event_type: str | None = None,
        actor_id: int | None = None,
        since_id: int | None = None,
    ) -> list[EventModel]:
        """The world's most recent `limit` events, oldest first.

        Filters narrow the stream before the limit is applied, so
        `recent(type="ACTION_REJECTED", limit=5)` is the last five
        rejections, not five rows that happen to be rejections.
        """
        stmt = select(EventModel).where(EventModel.world_id == world_id)
        if event_type is not None:
            stmt = stmt.where(EventModel.type == event_type)
        if actor_id is not None:
            stmt = stmt.where(EventModel.actor_id == actor_id)
        if since_id is not None:
            stmt = stmt.where(EventModel.id > since_id)
        stmt = stmt.order_by(EventModel.id.desc()).limit(limit)

        with Session(self._engine) as session:
            rows = list(session.scalars(stmt))
        return list(reversed(rows))

    def count(self, world_id: int) -> int:
        stmt = select(EventModel.id).where(EventModel.world_id == world_id)
        with Session(self._engine) as session:
            return len(list(session.scalars(stmt)))


class ExperimentRepository:
    """Experiment rows: the durable record of a run's configuration.

    ``create`` stamps the active model configuration by default (guide:
    "model configuration is recorded with experiment") — credentials
    are never part of it (see app/models/config.py).
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        name: str,
        scenario: str,
        seed: str,
        world_id: int | None = None,
        model_configuration: dict | None = None,
        compute_budget: dict | None = None,
        generation_limit: int | None = None,
    ) -> int:
        """Insert an experiment row; returns its id."""
        config = active_model_configuration() if model_configuration is None else model_configuration
        with self._session_factory() as session:
            row = ExperimentModel(
                name=name,
                world_id=world_id,
                scenario=scenario,
                seed=seed,
                model_configuration=config,
                compute_budget=compute_budget,
                generation_limit=generation_limit,
            )
            session.add(row)
            session.commit()
            return row.id


class AgentRecorder:
    """EventBus subscriber that persists lineage to the agents table (S09).

    Engine agent ids are per-world; ``AgentModel.id`` is a global row id
    (that is what ``parent_id`` FKs reference). The recorder keeps the
    local -> global mapping for one world, seeded by the registry with
    the founding agents and extended by every birth it sees.

    Only ``AGENT_BORN`` matters here — action and decision events are
    ``DatabaseEventRecorder``'s job.

    Each birth commits in its own short session: the next birth's parent
    is this child, so its global id must exist immediately — a held
    transaction would lock out concurrent writers for no gain.
    """

    def __init__(self, session_factory, world_id: int, population_id: int | None, local_to_global: dict) -> None:
        self._session_factory = session_factory
        self._world_id = world_id
        self._population_id = population_id
        self._local_to_global = dict(local_to_global)

    def remember(self, local_id: int, global_id: int) -> None:
        """Teach the recorder an agent that was not born here (S27).

        A population founded later has members with global ids assigned
        by the registry; their births will be recorded against those
        parents like any other.
        """
        self._local_to_global[local_id] = global_id

    def __call__(self, event: Event) -> None:
        if event.type != EventTypes.AGENT_BORN:
            return
        payload = event.payload
        parent_global = self._local_to_global.get(payload["parent_id"])
        if parent_global is None:  # parent outside this world's recorded agents
            return
        package = payload.get("inheritance") or {}
        with self._session_factory() as session:
            row = AgentModel(
                world_id=self._world_id,
                local_id=payload["child_id"],
                population_id=payload.get("population_id") or self._population_id,
                parent_id=parent_global,
                generation=payload["generation"],
                birth_tick=event.tick,
                status="active",
                location=payload.get("position"),
                inherited_traits=package.get("traits"),
                inherited_knowledge=package.get("knowledge"),
                cultural_artifacts=package.get("cultural_artifacts"),
                goals=({"goal": payload.get("goal")} if payload.get("goal") else None),
                working_memory=(
                    [{"kind": "inheritance", "from": payload["parent_id"],
                      "message": package.get("message")}]
                    if package.get("message") is not None
                    else None
                ),
            )
            session.add(row)
            session.flush()  # assigns the global id the parent of the next birth will need
            self._local_to_global[payload["child_id"]] = row.id
            session.commit()


class CheckpointRepository:
    """Checkpoint rows: the resumable snapshots of a run (S12)."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def save(self, experiment_id: int, generation: int, state: dict) -> int:
        """Write one checkpoint; returns its id."""
        with self._session_factory() as session:
            row = CheckpointModel(
                experiment_id=experiment_id, generation=generation, state=state
            )
            session.add(row)
            session.commit()
            return row.id

    def latest(self, experiment_id: int) -> CheckpointModel | None:
        """The highest-generation checkpoint of a run, if any."""
        stmt = (
            select(CheckpointModel)
            .where(CheckpointModel.experiment_id == experiment_id)
            .order_by(CheckpointModel.generation.desc(), CheckpointModel.id.desc())
            .limit(1)
        )
        with self._session_factory() as session:
            return session.scalars(stmt).first()

    def for_experiment(self, experiment_id: int) -> list[CheckpointModel]:
        """All checkpoints of a run, oldest first."""
        stmt = (
            select(CheckpointModel)
            .where(CheckpointModel.experiment_id == experiment_id)
            .order_by(CheckpointModel.generation, CheckpointModel.id)
        )
        with self._session_factory() as session:
            return list(session.scalars(stmt))


class AgentRepository:
    """Lineage queries: who descends from whom, and from which generation."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def for_world(self, world_id: int) -> list[AgentModel]:
        """All recorded agents of a world, in creation order."""
        stmt = (
            select(AgentModel)
            .where(AgentModel.world_id == world_id)
            .order_by(AgentModel.id)
        )
        with self._session_factory() as session:
            return list(session.scalars(stmt))

    def lineage(self, world_id: int) -> list[dict]:
        """One entry per recorded agent: local id, parent's local id, generation.

        The chain's verifiable form — this is what the roadmap's
        0 -> 1 -> ... -> 100 check reads.
        """
        rows = self.for_world(world_id)
        by_global = {row.id: row for row in rows}
        return [
            {
                "local_id": row.local_id,
                "parent_local_id": (
                    by_global[row.parent_id].local_id
                    if row.parent_id is not None and row.parent_id in by_global
                    else None
                ),
                "generation": row.generation,
            }
            for row in rows
        ]
