"""End-to-end smoke tests that wire multiple Phase 0 modules together.

These run in the default suite (no ``integration`` marker) so regressions
that span module boundaries surface immediately. External-API smoke
tests stay in :mod:`tests.integration.test_llm_real` and
:mod:`tests.integration.test_market_data_real`, gated by
``PTE_SMOKE_HIT_REAL_APIS``.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.request import urlopen

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app as cli_app
from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.guardrails.results import ReportWriter, ResultAggregator
from portfolio_thesis_engine.guardrails.runner import GuardrailRunner
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.base import LLMRequest
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.llm.router import TaskType, model_for_task
from portfolio_thesis_engine.schemas.common import Currency, GuardrailStatus
from portfolio_thesis_engine.schemas.position import Position, PositionStatus
from portfolio_thesis_engine.storage.inmemory import InMemoryRepository
from portfolio_thesis_engine.storage.yaml_repo import PositionRepository

REPO_ROOT = Path(__file__).resolve().parents[2]

runner = CliRunner()


# ======================================================================
# 1. Full storage workflow — InMemory → YAML with ticker edge cases
# ======================================================================


class TestFullStorageWorkflow:
    def test_inmemory_then_yaml_roundtrip(self, tmp_path: Path) -> None:
        """A Position moves through both repository types; ticker with a
        dot survives each hop and round-trips via either form."""
        dotted_ticker = "TEST.L"
        position = Position(
            ticker=dotted_ticker,
            company_name="Integration Test Co",
            status=PositionStatus.WATCHLIST,
            currency=Currency.GBP,
        )

        # Stage 1: InMemoryRepository holds the in-progress record.
        in_memory: InMemoryRepository[Position] = InMemoryRepository(
            key_fn=lambda p: p.ticker.replace(".", "-")
        )
        in_memory.save(position)
        assert in_memory.get("TEST-L") == position
        assert in_memory.list_keys() == ["TEST-L"]

        # Stage 2: promote to YAMLRepository (durable).
        yaml_repo = PositionRepository(base_path=tmp_path)
        yaml_repo.save(position)

        # On-disk name is always the hyphenated form.
        assert (tmp_path / "TEST-L.yaml").exists()

        # Retrieval works via either the dotted OR hyphenated form — proves
        # the Sprint 4/5 fix is still in place across the whole flow.
        assert yaml_repo.get("TEST.L") == position
        assert yaml_repo.get("TEST-L") == position
        assert yaml_repo.exists("TEST.L") is True
        assert yaml_repo.exists("TEST-L") is True

        # Stage 3: remove via the dotted form, confirm both repos agree.
        yaml_repo.delete("TEST.L")
        in_memory.delete("TEST-L")
        assert yaml_repo.exists("TEST-L") is False
        assert in_memory.get("TEST-L") is None

    def test_yaml_list_keys_returns_canonical_form(self, tmp_path: Path) -> None:
        """list_keys always returns on-disk (normalised) names so UI code
        can use the result as a stable key without re-normalising."""
        repo = PositionRepository(base_path=tmp_path)
        for ticker in ("AAPL", "TEST.L", "BRK.B"):
            repo.save(
                Position(
                    ticker=ticker,
                    company_name=ticker,
                    status=PositionStatus.ACTIVE,
                    currency=Currency.USD,
                )
            )
        assert repo.list_keys() == ["AAPL", "BRK-B", "TEST-L"]


# ======================================================================
# 2. LLM call → CostTracker persistence
# ======================================================================


def _mocked_anthropic(input_tokens: int, output_tokens: int) -> AnthropicProvider:
    fake = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )
    async_client = MagicMock()
    async_client.messages = MagicMock()
    async_client.messages.create = AsyncMock(return_value=fake)
    sync_client = MagicMock()
    sync_client.messages = MagicMock()
    sync_client.messages.create = MagicMock(return_value=fake)
    return AnthropicProvider(api_key="mock", sync_client=sync_client, async_client=async_client)


class TestLLMToCostTracker:
    def test_provider_call_recorded_in_tracker(self, tmp_path: Path) -> None:
        provider = _mocked_anthropic(input_tokens=1000, output_tokens=500)
        tracker = CostTracker(log_path=tmp_path / "llm_costs.jsonl")

        req = LLMRequest(
            prompt="ping",
            model=model_for_task(TaskType.CLASSIFICATION),
            max_tokens=32,
        )
        # complete_sync delegates to asyncio.run when outside a loop —
        # exercising the real entry path used by synchronous CLI code.
        resp = provider.complete_sync(req)
        assert resp.content == "ok"
        assert resp.input_tokens == 1000
        assert resp.output_tokens == 500
        assert resp.cost_usd > Decimal("0")

        tracker.record(
            operation="integration_smoke",
            model=resp.model_used,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_usd=resp.cost_usd,
            ticker="ACME",
        )

        # In-memory session_total reflects the call.
        assert tracker.session_total() == resp.cost_usd

        # Persistent ticker_total re-reads the JSONL file — confirms the
        # append happened and the schema survives roundtrip.
        assert tracker.ticker_total("ACME") == resp.cost_usd
        assert tracker.ticker_total("OTHER") == Decimal("0")

        # Raw JSONL line shape sanity-check.
        line = (tmp_path / "llm_costs.jsonl").read_text().strip()
        payload = json.loads(line)
        assert payload["operation"] == "integration_smoke"
        assert payload["ticker"] == "ACME"
        assert Decimal(payload["cost_usd"]) == resp.cost_usd

    def test_multiple_calls_per_ticker_accumulate(self, tmp_path: Path) -> None:
        provider = _mocked_anthropic(input_tokens=100, output_tokens=50)
        tracker = CostTracker(log_path=tmp_path / "llm_costs.jsonl")
        req = LLMRequest(prompt="x", model="claude-sonnet-4-6", max_tokens=16)

        for _ in range(3):
            resp = asyncio.run(provider.complete(req))
            tracker.record(
                operation="op",
                model=resp.model_used,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_usd=resp.cost_usd,
                ticker="ACME",
            )

        # sonnet: 100*$3/M + 50*$15/M = 0.0003 + 0.00075 = 0.00105 per call
        per_call = Decimal("0.00105000")
        assert tracker.session_total() == per_call * 3
        assert tracker.ticker_total("ACME") == per_call * 3


# ======================================================================
# 3. Guardrail runner → aggregator → report writer
# ======================================================================


class _IntPass(Guardrail):
    @property
    def check_id(self) -> str:
        return "INT.P"

    @property
    def name(self) -> str:
        return "integration pass"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.PASS, "ok")


class _IntWarn(Guardrail):
    @property
    def check_id(self) -> str:
        return "INT.W"

    @property
    def name(self) -> str:
        return "integration warn"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.WARN, "careful now")


class _IntFail(Guardrail):
    @property
    def check_id(self) -> str:
        return "INT.F"

    @property
    def name(self) -> str:
        return "integration fail"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.FAIL, "simulated failure")


class TestGuardrailWorkflow:
    def test_runner_aggregator_report_pipeline(self) -> None:
        runner = GuardrailRunner([_IntPass(), _IntWarn(), _IntFail()])
        results = runner.run({})
        assert len(results) == 3

        agg = ResultAggregator.aggregate(results)
        assert agg.total == 3
        assert agg.by_status[GuardrailStatus.PASS] == 1
        assert agg.by_status[GuardrailStatus.WARN] == 1
        assert agg.by_status[GuardrailStatus.FAIL] == 1
        assert agg.overall == GuardrailStatus.FAIL

        text_report = ReportWriter.to_text(agg)
        assert "Overall: FAIL" in text_report
        assert "INT.P" in text_report
        assert "INT.W" in text_report
        assert "INT.F" in text_report

        json_report = json.loads(ReportWriter.to_json(agg))
        assert json_report["overall"] == "FAIL"
        assert json_report["total"] == 3
        ids = {r["check_id"] for r in json_report["results"]}
        assert ids == {"INT.P", "INT.W", "INT.F"}


# ======================================================================
# 4. CLI end-to-end — setup → health-check → smoke-test
# ======================================================================


class TestCLIEndToEnd:
    def test_setup_then_health_then_smoke(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        backup_dir = tmp_path / "backup"
        monkeypatch.setattr("portfolio_thesis_engine.shared.config.settings.data_dir", data_dir)
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.backup_dir",
            backup_dir,
        )
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.smoke_hit_real_apis",
            False,
        )

        setup_result = runner.invoke(cli_app, ["setup"])
        assert setup_result.exit_code == 0, setup_result.output
        assert (data_dir / "yamls" / "companies").is_dir()
        assert (data_dir / "yamls" / "portfolio" / "positions").is_dir()
        assert backup_dir.is_dir()

        health_result = runner.invoke(cli_app, ["health-check"])
        assert health_result.exit_code == 0, health_result.output
        assert "Python" in health_result.output
        assert "Data directory" in health_result.output

        smoke_result = runner.invoke(cli_app, ["smoke-test"])
        assert smoke_result.exit_code == 0, smoke_result.output
        assert "4/4 tests passed" in smoke_result.output


# ======================================================================
# 5. Streamlit subprocess smoke
# ======================================================================


def _free_port() -> int:
    """Bind to port 0 on localhost to let the OS pick a free port, then
    release it. Small race window but acceptable for local smoke."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http(url: str, timeout: float = 15.0) -> int:
    """Poll ``url`` until it returns a status code or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as resp:  # noqa: S310
                return int(resp.status)
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise TimeoutError(f"{url} did not respond within {timeout}s")


@pytest.mark.slow
class TestStreamlitSmoke:
    def test_streamlit_app_serves_http_200(self) -> None:
        port = _free_port()
        proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "src/portfolio_thesis_engine/ui/app.py",
                f"--server.port={port}",
                "--server.address=127.0.0.1",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Put streamlit in its own process group so SIGTERM reaches
            # every child (including the tornado worker).
            start_new_session=True,
        )
        try:
            status = _wait_for_http(f"http://127.0.0.1:{port}/")
            assert status == 200
        finally:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=5)
        # On clean SIGTERM streamlit exits with 0 or -15; either is fine
        # here — the point is that it didn't crash while bound to the port.
        assert proc.returncode in (0, -signal.SIGTERM, -signal.SIGKILL)
