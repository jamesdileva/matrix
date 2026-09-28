from fastapi import APIRouter

from app.config.settings import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "flood-backend",
        "version": "0.1.0",
        "environment": settings.environment,
    }
