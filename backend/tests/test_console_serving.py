"""S54 — the console served by the app itself.

When the console has been built (frontend/dist), the packaged server
mounts it at / so one process serves the API and the research console.
When it has not, nothing is mounted and / is a plain 404. The API keeps
precedence in both worlds.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.experiments import router as experiments_router
from app.api.health import router as health_router
from app import main as app_main


def _make_app(monkeypatch, dist_dir: Path | None):
    application = FastAPI()
    application.include_router(health_router, prefix="/api")
    application.include_router(experiments_router, prefix="/api")
    monkeypatch.setattr(app_main, "_console_dist", lambda: dist_dir)

    @asynccontextmanager
    async def lifespan(app):
        # the same hook main.py runs at startup
        app_main._mount_console(app)
        yield

    application.router.lifespan_context = lifespan
    return application


def test_a_built_console_is_served_at_root(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<html><body><h1>FLOOD</h1></body></html>", encoding="utf-8"
    )
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("// console", encoding="utf-8")

    application = _make_app(monkeypatch, dist)
    with TestClient(application) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "FLOOD" in page.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200

        # the API keeps precedence over the console mount
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        unknown_api = client.get("/api/does-not-exist")
        assert unknown_api.status_code == 404


def test_without_a_built_console_root_is_404(tmp_path, monkeypatch):
    application = _make_app(monkeypatch, None)
    with TestClient(application) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200


def test_the_real_dev_console_mounts_when_built():
    """In the source tree the mount decision is a pure lookup: if
    frontend/dist exists the packaged server will serve it."""
    dist = app_main._console_dist()
    if dist is None:
        pytest.skip("frontend/dist has not been built on this machine")
    assert (dist / "index.html").exists()
