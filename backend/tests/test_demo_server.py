from fastapi.testclient import TestClient

from app.demo_server import app


def test_local_demo_exposes_only_local_safe_metadata_and_scenarios():
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "localhost-only"
    scenarios = client.get("/api/scenarios")
    assert scenarios.status_code == 200
    assert scenarios.json()[0]["locales"] == ["zh-CN", "en-US"]
