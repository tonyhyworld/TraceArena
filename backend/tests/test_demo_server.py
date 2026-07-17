from fastapi.testclient import TestClient

from app.demo_server import app
from app.public_demo_server import app as public_app


def test_local_demo_exposes_only_local_safe_metadata_and_scenarios():
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "localhost-only"
    scenarios = client.get("/api/scenarios")
    assert scenarios.status_code == 200
    assert scenarios.json()[0]["locales"] == ["zh-CN", "en-US"]


def test_public_demo_exposes_replay_only_security_boundary():
    client = TestClient(public_app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "mode": "public-replay-only",
        "llm": "disabled",
        "api_keys": "not-accepted",
        "brokerage": "disabled",
        "network_tools": "disabled",
    }
    scenario = client.get("/api/scenarios").json()[0]
    assert scenario["data"] == "synthetic-fixture"
    assert "path" not in scenario
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_public_demo_rejects_provider_model_and_api_key_fields():
    client = TestClient(public_app)
    response = client.post("/api/runs", json={
        "locale": "en-US",
        "mode": "llm",
        "provider": "openai",
        "model": "gpt-example",
        "api_key": "must-not-be-accepted",
    })
    assert response.status_code == 422
    body = response.text
    assert "extra_forbidden" in body
    assert "must-not-be-accepted" not in body


def test_public_demo_rejects_large_requests_and_sets_security_headers():
    client = TestClient(public_app)
    large = client.post(
        "/api/runs",
        content=b"x" * 4097,
        headers={"content-type": "application/json"},
    )
    assert large.status_code == 413
    health = client.get("/api/health")
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in health.headers["content-security-policy"]


def test_public_demo_runs_the_reviewed_no_key_replay():
    client = TestClient(public_app)
    response = client.post("/api/runs", json={"locale": "en-US"})
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "deterministic-replay"
    assert result["manifest"]["provider"] == "replay"
    assert result["manifest"]["network"] == "disabled"
    assert result["manifest"]["brokerage"] == "disabled"
    assert len(result["manifest"]["canonical_replay_sha256"]) == 64
    assert result["replay"]
