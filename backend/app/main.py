from contextlib import asynccontextmanager

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
    yield
    await app.state.worlds.stop_all()


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
