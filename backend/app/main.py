from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.worlds import router as worlds_router
from app.config.settings import settings
from app.persistence.database import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.host import WorldRegistry

    app.state.worlds = WorldRegistry(SessionLocal)
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
