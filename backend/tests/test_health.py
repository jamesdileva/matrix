from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "flood-backend"


def test_unknown_api_route_is_not_found():
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
