import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import Base


@pytest.fixture()
def db_engine(tmp_path):
    """Fresh SQLite file per test — databases are never shared between tests."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session = sessionmaker(bind=db_engine, expire_on_commit=False)()
    yield session
    session.close()
