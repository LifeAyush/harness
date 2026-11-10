import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.fixture()
def client(project, monkeypatch):
    monkeypatch.setenv("HARNESS_MODEL", "demo")
    monkeypatch.setenv("HARNESS_ROOT", str(project))
    with TestClient(app) as c:
        yield c


def test_health_lists_model_and_tools(client):
    assert client.get("/health").json() == {"status": "ok", "model": "demo", "tools": ["filesystem.list", "filesystem.read"]}


def test_run_returns_answer_and_trace(client):
    res = client.post("/v1/runs", json={"task": "Which Python files contain FastAPI endpoints?"})
    assert res.status_code == 200
    data = res.json()
    assert data["stop_reason"] == "final_answer" and data["iterations"] == 3
    assert "app/main.py" in data["answer"] and "app/users.py" in data["answer"]
    assert data["steps"][1]["data"]["name"] == "filesystem.list"
    assert data["usage"]["prompt"] > 0


def test_run_respects_max_iterations(client):
    data = client.post("/v1/runs", json={"task": "anything", "max_iterations": 1}).json()
    assert data["stop_reason"] == "max_iterations" and data["answer"] is None


@pytest.mark.parametrize("body", [{}, {"task": ""}, {"task": "x", "max_iterations": 0}])
def test_bad_requests_are_rejected(client, body):
    assert client.post("/v1/runs", json=body).status_code == 422
