import json
from contextlib import contextmanager

import httpx
import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness.web.server import WebServer, WebSettings
from vector_harness.web.sessions import create_session


@contextmanager
def api(workspace, provider=None):
    server = WebServer(WebSettings(workspace=workspace), provider or object())
    server.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.port}", trust_env=False, timeout=10) as client:
            yield server, client
    finally:
        server.shutdown()


def test_research_api_owns_prompt_and_recovers_without_browser_storage(tmp_path):
    provider = ScriptedProvider([ScriptedTurn(content="研究结论 [文献](https://example.com/paper)")])
    with api(tmp_path, provider) as (server, client):
        invalid = client.post("/api/deepresearch/tasks", json={"topic": " "})
        assert invalid.status_code == 400
        created = client.post("/api/deepresearch/tasks", json={"topic": " agents ", "engine": "advanced"})
        assert created.status_code == 201
        task = created.json()
        session_id = task["id"]
        assert task["config"] == {"topic": "agents", "engine": "advanced"}
        response = client.post(f"/api/deepresearch/tasks/{session_id}/run", json={})
        assert response.status_code == 200
        assert '"kind": "task_snapshot"' in response.text
        assert '"status": "complete"' in response.text
        assert "高级搜索" in provider.calls[0]["messages"][-1]["content"]
        detail = client.get(f"/api/deepresearch/tasks/{session_id}").json()
        assert detail["task"]["status"] == "completed"
        assert "研究结论" in detail["task"]["report"]
        assert client.get("/api/sessions?kind=agent").json()["sessions"] == []
        assert client.post(f"/api/deepresearch/tasks/{session_id}/run", json={}).status_code == 409
        assert client.post(f"/api/sessions/{session_id}/mode", json={"mode": "react"}).status_code == 409
    with api(tmp_path) as (_, client):
        assert client.get("/api/deepresearch/tasks").json()["tasks"][0]["id"] == session_id
        assert client.get(f"/api/deepresearch/tasks/{session_id}").json() == detail
        assert client.delete(f"/api/deepresearch/tasks/{session_id}").status_code == 200
        assert client.get("/api/deepresearch/tasks").json()["tasks"] == []


def test_modeling_api_validates_ranks_and_loads_parent_on_server(tmp_path):
    report = '```modeling-report\n' + json.dumps({"experiments": [
        {"id": 0, "title": "baseline", "score": 0.7}, {"id": 1, "title": "better", "score": 0.8}
    ]}) + '\n```'
    provider = ScriptedProvider([ScriptedTurn(content=report), ScriptedTurn(content=report)])
    with api(tmp_path, provider) as (_, client):
        config = client.get("/api/autoresearch/options").json()["defaults"]
        config.update(dataPath="train.csv", target="label", description="预测风险")
        assert client.post("/api/autoresearch/tasks", json={"config": {**config, "parallel": True}}).status_code == 400
        created = client.post("/api/autoresearch/tasks", json={"config": config})
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert client.post(f"/api/autoresearch/tasks/{session_id}/run", json={}).status_code == 200
        task = client.get(f"/api/autoresearch/tasks/{session_id}").json()["task"]
        assert task["bestId"] == 1
        assert task["baselineId"] == 0
        assert task["metricDirection"] == "maximize"
        assert task["experiments"][1]["improved"] is True
        assert client.get(f"/api/deepresearch/tasks/{session_id}").status_code == 404
        assert client.post(f"/api/sessions/{session_id}/messages", json={"text": "bypass"}).status_code == 409
        derived = client.post("/api/autoresearch/tasks",
                              json={"config": config, "parentSessionId": session_id, "parentExperimentId": 1})
        assert derived.status_code == 201
        child_id = derived.json()["id"]
        client.post(f"/api/autoresearch/tasks/{child_id}/run", json={})
        assert '"score": 0.8' in provider.calls[-1]["messages"][-1]["content"]


def test_legacy_import_is_per_item_idempotent_and_never_accepts_browser_output(tmp_path):
    session_id = create_session(tmp_path)
    with api(tmp_path) as (_, client):
        record = {"id": session_id, "kind": "deepresearch", "config": {"topic": "old"}, "output": "untrusted"}
        payload = {"tasks": [record, {"id": "../escape", "kind": "deepresearch", "config": {"topic": "bad"}}]}
        result = client.post("/api/tasks/import-legacy", json=payload).json()["results"]
        assert [item["status"] for item in result] == ["imported", "invalid"]
        repeated = client.post("/api/tasks/import-legacy", json={"tasks": [record]}).json()["results"]
        assert repeated[0]["status"] == "already_imported"
        record["config"]["topic"] = "conflicting"
        assert client.post("/api/tasks/import-legacy", json={"tasks": [record]}).json()["results"][0][
                   "status"] == "conflict"
        detail = client.get(f"/api/deepresearch/tasks/{session_id}").json()
        assert detail["task"]["config"]["topic"] == "old"
        assert detail["task"]["report"] == ""


def test_domain_run_respects_global_busy_lock_and_keeps_created_task_idle(tmp_path):
    with api(tmp_path) as (server, client):
        session_id = client.post("/api/deepresearch/tasks", json={"topic": "topic"}).json()["id"]
        assert server.runs.acquire()
        try:
            assert client.post(f"/api/deepresearch/tasks/{session_id}/run", json={}).status_code == 409
            assert client.get(f"/api/deepresearch/tasks/{session_id}").json()["task"]["status"] == "idle"
            assert client.delete(f"/api/deepresearch/tasks/{session_id}").status_code == 409
        finally:
            server.runs.release()


@pytest.mark.parametrize("body", [
    '{"topic":' + '[' * 1100 + '0' + ']' * 1100 + '}',
    '{"topic":' + '1' * 5000 + '}',
    '{"topic":"\\ud800"}',
])
def test_invalid_json_values_are_client_errors_and_leave_no_task(tmp_path, body):
    with api(tmp_path) as (_, client):
        response = client.post("/api/deepresearch/tasks", content=body.encode("utf-8"))
        assert response.status_code == 400
        assert client.get("/api/deepresearch/tasks").json()["tasks"] == []
