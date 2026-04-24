"""Pipeline trigger + status endpoints — subprocess mocked.

Real ``pte`` invocations take ~10–15 minutes per scenario; tests
monkeypatch :func:`pipeline_runner._run_subprocess` to a coroutine
that flips the in-memory state directly. The trigger / poll wiring
(uuid generation, status transitions, log-file resolution) is what
the tests exercise.
"""

from __future__ import annotations


def test_S0_PIPELINES_01_trigger_requires_auth(client):
    response = client.post(
        "/api/pipelines/1846.HK/run", json={"base_period": "FY2024"}
    )
    assert response.status_code == 401


def test_S0_PIPELINES_02_trigger_returns_run_id(client, auth, monkeypatch):
    from api.services import pipeline_runner

    async def _mock(run_id, _cmd_parts):
        pipeline_runner._active_runs[run_id]["status"] = "done"
        pipeline_runner._active_runs[run_id]["exit_code"] = 0

    monkeypatch.setattr(pipeline_runner, "_run_subprocess", _mock)

    response = client.post(
        "/api/pipelines/1846.HK/run",
        auth=auth,
        json={"base_period": "FY2024"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "run_id" in body
    assert body["ticker"] == "1846.HK"
    assert body["status"] in {"queued", "running", "done"}
    # Command line includes the ticker + base_period flag.
    assert "1846.HK" in body["command"]
    assert "--base-period" in body["command"]


def test_S0_PIPELINES_03_forecast_endpoint(client, auth, monkeypatch):
    from api.services import pipeline_runner

    async def _mock(run_id, _cmd_parts):
        pipeline_runner._active_runs[run_id]["status"] = "done"
        pipeline_runner._active_runs[run_id]["exit_code"] = 0

    monkeypatch.setattr(pipeline_runner, "_run_subprocess", _mock)

    response = client.post(
        "/api/pipelines/1846.HK/forecast", auth=auth
    )
    assert response.status_code == 200
    body = response.json()
    assert "forecast" in body["command"]


def test_S0_PIPELINES_04_valuation_endpoint(client, auth, monkeypatch):
    from api.services import pipeline_runner

    async def _mock(run_id, _cmd_parts):
        pipeline_runner._active_runs[run_id]["status"] = "done"
        pipeline_runner._active_runs[run_id]["exit_code"] = 0

    monkeypatch.setattr(pipeline_runner, "_run_subprocess", _mock)

    response = client.post(
        "/api/pipelines/1846.HK/valuation", auth=auth
    )
    assert response.status_code == 200


def test_S0_PIPELINES_10_get_run_unknown_returns_404(client, auth):
    response = client.get(
        "/api/pipelines/1846.HK/runs/nonexistent", auth=auth
    )
    assert response.status_code == 404


def test_S0_PIPELINES_11_status_after_trigger(client, auth, monkeypatch):
    """Status endpoint returns the meta the trigger wrote."""
    from api.services import pipeline_runner

    async def _mock(run_id, _cmd_parts):
        pipeline_runner._active_runs[run_id]["status"] = "done"
        pipeline_runner._active_runs[run_id]["exit_code"] = 0

    monkeypatch.setattr(pipeline_runner, "_run_subprocess", _mock)

    trigger_resp = client.post(
        "/api/pipelines/1846.HK/run",
        auth=auth,
        json={"base_period": "FY2024"},
    )
    run_id = trigger_resp.json()["run_id"]

    status_resp = client.get(
        f"/api/pipelines/1846.HK/runs/{run_id}", auth=auth
    )
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["run_id"] == run_id
    assert body["ticker"] == "1846.HK"
    assert body["status"] in {"queued", "running", "done"}
