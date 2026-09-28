"""Database schema. Fields follow architecture.md §6 (Core Domain Model).

JSON columns hold free-form structures (locations, budgets, rule sets) so
early sprints can iterate without migrations; when a field's shape settles,
it gets promoted to real columns.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class World(Base):
    __tablename__ = "worlds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    seed: Mapped[str] = mapped_column(String(120))
    tick: Mapped[int] = mapped_column(default=0)
    dimensions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ruleset: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    environment_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    populations: Mapped[list["Population"]] = relationship(back_populates="world")
    agents: Mapped[list["Agent"]] = relationship(back_populates="world")
    events: Mapped[list["Event"]] = relationship(back_populates="world")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="world")


class Population(Base):
    __tablename__ = "populations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    # Plain integer, not a FK: the root agent may be created after the
    # population, and a real FK would make populations/agents circularly
    # dependent. Enforced in application logic when lineage lands (S09).
    root_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    population_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_configuration: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resource_limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    world: Mapped["World"] = relationship(back_populates="populations")
    agents: Mapped[list["Agent"]] = relationship(back_populates="population")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    population_id: Mapped[int | None] = mapped_column(
        ForeignKey("populations.id"), nullable=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    generation: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    birth_tick: Mapped[int | None] = mapped_column(nullable=True)
    death_tick: Mapped[int | None] = mapped_column(nullable=True)
    location: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    inherited_traits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    inherited_knowledge: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acquired_knowledge: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    working_memory: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    goals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compute_budget: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remaining_budget: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    world: Mapped["World"] = relationship(back_populates="agents")
    population: Mapped["Population | None"] = relationship(back_populates="agents")
    parent: Mapped["Agent | None"] = relationship(
        remote_side="Agent.id", back_populates="children"
    )
    children: Mapped[list["Agent"]] = relationship(back_populates="parent")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_world_tick", "world_id", "tick"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    tick: Mapped[int] = mapped_column(default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    type: Mapped[str] = mapped_column(String(64))
    # Actor/target are loosely typed on purpose: participant (human) and
    # system actors exist alongside agents, so no FK here.
    actor_id: Mapped[int | None] = mapped_column(nullable=True)
    target_id: Mapped[int | None] = mapped_column(nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    world: Mapped["World"] = relationship(back_populates="events")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    world_id: Mapped[int | None] = mapped_column(
        ForeignKey("worlds.id"), nullable=True
    )
    scenario: Mapped[str] = mapped_column(String(120))
    seed: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="created")
    model_configuration: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compute_budget: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_limit: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    world: Mapped["World | None"] = relationship(back_populates="experiments")
