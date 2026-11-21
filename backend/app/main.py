from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.experiments import router as experiments_router
from app.api.health import router as health_router
from app.api.replay import router as replay_router
from app.api.worlds import router as worlds_router
from app.config.settings import settings
from app.persistence.database import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.host import WorldRegistry

    # S54: a packaged server starts against a fresh database — make sure
    # the current schema exists before anything reads it. create_all is a
    # no-op on a database Alembic already manages.
    from app.persistence.database import Base, engine

    Base.metadata.create_all(engine)

    # S40: the experiments API reads and writes studies through the same
    # storage the worlds use.
    app.state.session_factory = SessionLocal
    app.state.worlds = WorldRegistry(
        SessionLocal, autosave_every=settings.autosave_every
    )
    # S38: the restart path — worlds with snapshots come back.
    recovered = app.state.worlds.recover()
    if recovered:
        import logging

        logging.getLogger("flood").info("recovered %d world(s): %s", len(recovered), recovered)
    # S54: the built research console, served at / when it exists.
    _mount_console(app)
    yield
    await app.state.worlds.stop_all()


def _console_dist() -> Path | None:
    """Where the built console lives, if it was built.

    Source layout: frontend/dist next to backend/. Packaged layout:
    PyInstaller ships frontend_dist into the bundle (sys._MEIPASS in
    onedir mode is the bundle's _internal directory).
    """
    import sys

    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "frontend" / "dist",
        here.parent / "frontend_dist",
        here.parents[1] / "frontend_dist",
        Path(getattr(sys, "_MEIPASS", here.parent)) / "frontend_dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


def _mount_console(app: FastAPI) -> None:
    """Serve the built research console at / when it has been built.

    Routers keep precedence (they are registered before the mount), so
    the API is untouched; the console is the SPA at /.
    """
    dist = _console_dist()
    if dist is None:
        return
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=dist, html=True), name="console")


app = FastAPI(title="Flood", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(worlds_router, prefix="/api")
app.include_router(replay_router, prefix="/api")
app.include_router(experiments_router, prefix="/api")
