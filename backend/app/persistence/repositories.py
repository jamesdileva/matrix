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
from app.persistence.models import EventModel, ExperimentModel
from app.simulation.events import Event


class DatabaseEventRecorder:
    """EventBus subscriber that persists one world's events to the database.

    Each event commits in its own short-lived session — simple and safe at
    current scale; batching belongs to the S12 retention/perf sprint.
    """

    def __init__(self, session_factory: sessionmaker, world_id: int) -> None:
        self._session_factory = session_factory
        self._world_id = world_id

    def __call__(self, event: Event) -> None:
        with self._session_factory() as session:
            session.add(
                EventModel(
                    world_id=self._world_id,
                    sequence=event.id,
                    tick=event.tick,
                    type=event.type,
                    actor_id=event.actor_id,
                    target_id=event.target_id,
                    payload=event.payload,
                )
            )
            session.commit()


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
