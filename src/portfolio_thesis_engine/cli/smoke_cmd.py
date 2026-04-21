"""``pte smoke-test`` — end-to-end sanity checks.

Default mode (``PTE_SMOKE_HIT_REAL_APIS=false``) exercises every subsystem
against in-memory / mocked providers — zero network calls, zero cost.
When ``PTE_SMOKE_HIT_REAL_APIS=true`` is set, the command additionally
issues one minimal request per external API (Anthropic, OpenAI
embeddings, FMP quote).
"""

from __future__ import annotations

import asyncio
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.guardrails.runner import GuardrailRunner
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.base import LLMRequest
from portfolio_thesis_engine.llm.openai_provider import OpenAIEmbeddingsProvider
from portfolio_thesis_engine.llm.router import TaskType, model_for_task
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.schemas.common import Currency, GuardrailStatus
from portfolio_thesis_engine.schemas.position import Position, PositionStatus
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.yaml_repo import PositionRepository

console = Console()


# ----------------------------------------------------------------------
# Individual smoke checks — each returns (name, passed, detail, cost_usd)
# ----------------------------------------------------------------------


def _check_storage_roundtrip() -> tuple[str, bool, str, Decimal]:
    try:
        with tempfile.TemporaryDirectory() as td:
            repo = PositionRepository(base_path=Path(td))
            p = Position(
                ticker="TEST.L",
                company_name="Smoke Test",
                status=PositionStatus.ACTIVE,
                currency=Currency.GBP,
            )
            repo.save(p)
            # Ticker-normalisation edge case must round-trip via both forms.
            for form in ("TEST.L", "TEST-L"):
                loaded = repo.get(form)
                if loaded != p:
                    return (
                        "Storage roundtrip",
                        False,
                        f"get('{form}') returned {loaded!r}",
                        Decimal("0"),
                    )
            repo.delete("TEST.L")
            if repo.exists("TEST-L"):
                return (
                    "Storage roundtrip",
                    False,
                    "delete('TEST.L') did not remove TEST-L/",
                    Decimal("0"),
                )
    except Exception as e:
        return ("Storage roundtrip", False, f"{type(e).__name__}: {e}", Decimal("0"))
    return ("Storage roundtrip", True, "save+get+delete symmetric", Decimal("0"))


class _Pass(Guardrail):
    @property
    def check_id(self) -> str:
        return "SMK.P"

    @property
    def name(self) -> str:
        return "pass"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.PASS, "ok")


class _Warn(Guardrail):
    @property
    def check_id(self) -> str:
        return "SMK.W"

    @property
    def name(self) -> str:
        return "warn"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.WARN, "careful")


class _Crash(Guardrail):
    @property
    def check_id(self) -> str:
        return "SMK.X"

    @property
    def name(self) -> str:
        return "crash"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        raise RuntimeError("simulated smoke-test crash")


def _check_guardrail_runner() -> tuple[str, bool, str, Decimal]:
    try:
        runner = GuardrailRunner([_Pass(), _Warn(), _Crash()])
        results = runner.run({})
        overall = runner.overall_status(results)
        # Crash must have been converted to FAIL; overall must be FAIL.
        if len(results) != 3:
            return (
                "Guardrail runner",
                False,
                f"expected 3 results, got {len(results)}",
                Decimal("0"),
            )
        if results[2].status != GuardrailStatus.FAIL:
            return (
                "Guardrail runner",
                False,
                f"crash-check not converted to FAIL: {results[2].status}",
                Decimal("0"),
            )
        if overall != GuardrailStatus.FAIL:
            return (
                "Guardrail runner",
                False,
                f"overall_status = {overall}, expected FAIL",
                Decimal("0"),
            )
    except Exception as e:
        return ("Guardrail runner", False, f"{type(e).__name__}: {e}", Decimal("0"))
    return ("Guardrail runner", True, "3 checks; runner converted crash→FAIL", Decimal("0"))


def _build_mocked_anthropic() -> AnthropicProvider:
    fake_usage = SimpleNamespace(input_tokens=4, output_tokens=2)
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=fake_usage,
        stop_reason="end_turn",
    )
    async_client = MagicMock()
    async_client.messages = MagicMock()
    async_client.messages.create = AsyncMock(return_value=fake_response)
    sync_client = MagicMock()
    sync_client.messages = MagicMock()
    sync_client.messages.create = MagicMock(return_value=fake_response)
    return AnthropicProvider(api_key="mock", sync_client=sync_client, async_client=async_client)


def _check_llm_mocked() -> tuple[str, bool, str, Decimal]:
    try:
        provider = _build_mocked_anthropic()
        req = LLMRequest(
            prompt="say ok", model=model_for_task(TaskType.CLASSIFICATION), max_tokens=16
        )
        resp = asyncio.run(provider.complete(req))
        if resp.content != "ok":
            return (
                "LLM (mocked)",
                False,
                f"unexpected content: {resp.content!r}",
                Decimal("0"),
            )
    except Exception as e:
        return ("LLM (mocked)", False, f"{type(e).__name__}: {e}", Decimal("0"))
    return ("LLM (mocked)", True, "Anthropic mock returned 'ok'", Decimal("0"))


def _build_mocked_openai() -> OpenAIEmbeddingsProvider:
    fake_response = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])
    async_client = MagicMock()
    async_client.embeddings = MagicMock()
    async_client.embeddings.create = AsyncMock(return_value=fake_response)
    sync_client = MagicMock()
    sync_client.embeddings = MagicMock()
    sync_client.embeddings.create = MagicMock(return_value=fake_response)
    return OpenAIEmbeddingsProvider(
        api_key="mock", sync_client=sync_client, async_client=async_client
    )


def _check_embeddings_mocked() -> tuple[str, bool, str, Decimal]:
    try:
        provider = _build_mocked_openai()
        vectors = asyncio.run(provider.embed(["smoke"]))
        if len(vectors) != 1 or len(vectors[0]) == 0:
            return (
                "Embeddings (mocked)",
                False,
                f"unexpected vectors: {vectors!r}",
                Decimal("0"),
            )
    except Exception as e:
        return (
            "Embeddings (mocked)",
            False,
            f"{type(e).__name__}: {e}",
            Decimal("0"),
        )
    return ("Embeddings (mocked)", True, "OpenAI mock returned 1 vector", Decimal("0"))


# ----------------------------------------------------------------------
# Real-API checks (gated)
# ----------------------------------------------------------------------


async def _real_anthropic_check() -> tuple[str, bool, str, Decimal]:
    try:
        provider = AnthropicProvider()
        req = LLMRequest(
            prompt="Reply with the two characters 'ok' and nothing else.",
            model=model_for_task(TaskType.CLASSIFICATION),
            max_tokens=16,
        )
        resp = await provider.complete(req)
        return (
            "Anthropic (real API)",
            bool(resp.content),
            f"{resp.input_tokens}+{resp.output_tokens} tokens",
            resp.cost_usd,
        )
    except Exception as e:
        return (
            "Anthropic (real API)",
            False,
            f"{type(e).__name__}: {e}",
            Decimal("0"),
        )


async def _real_openai_check() -> tuple[str, bool, str, Decimal]:
    try:
        provider = OpenAIEmbeddingsProvider()
        vectors = await provider.embed(["portfolio thesis engine smoke"])
        ok = len(vectors) == 1 and len(vectors[0]) >= 512
        return (
            "OpenAI embeddings (real API)",
            ok,
            f"dim={len(vectors[0]) if vectors else 0}",
            # Embedding cost is negligible for one call; report zero to avoid
            # a second pricing table just for embeddings.
            Decimal("0"),
        )
    except Exception as e:
        return (
            "OpenAI embeddings (real API)",
            False,
            f"{type(e).__name__}: {e}",
            Decimal("0"),
        )


async def _real_fmp_check() -> tuple[str, bool, str, Decimal]:
    try:
        async with FMPProvider() as p:
            quote = await p.get_quote("AAPL")
        ok = quote.get("symbol") == "AAPL" and "price" in quote
        return (
            "FMP (real API)",
            ok,
            f"AAPL price={quote.get('price')}",
            Decimal("0"),  # FMP is flat-fee subscription; no per-call attribution
        )
    except Exception as e:
        return ("FMP (real API)", False, f"{type(e).__name__}: {e}", Decimal("0"))


async def _run_real_api_checks() -> list[tuple[str, bool, str, Decimal]]:
    results = await asyncio.gather(
        _real_anthropic_check(),
        _real_openai_check(),
        _real_fmp_check(),
    )
    return list(results)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def smoke_test() -> None:
    """Run the smoke test suite and render a status table."""
    console.print("[bold]Portfolio Thesis Engine — Smoke Test[/bold]\n")

    checks: list[tuple[str, bool, str, Decimal]] = [
        _check_storage_roundtrip(),
        _check_guardrail_runner(),
        _check_llm_mocked(),
        _check_embeddings_mocked(),
    ]

    if settings.smoke_hit_real_apis:
        console.print("[yellow]PTE_SMOKE_HIT_REAL_APIS=true — hitting real APIs.[/yellow]\n")
        checks.extend(asyncio.run(_run_real_api_checks()))

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Test")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    table.add_column("Cost (USD)", justify="right")

    passed = 0
    total_cost = Decimal("0")
    for name, ok, detail, cost in checks:
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        if ok:
            passed += 1
        total_cost += cost
        table.add_row(name, status, detail, f"{cost:.6f}" if cost else "—")

    console.print(table)

    console.print(f"\n[bold]{passed}/{len(checks)} tests passed.[/bold]")
    if settings.smoke_hit_real_apis and total_cost > 0:
        console.print(f"[dim]Total real-API cost: ${total_cost:.6f}[/dim]")

    if passed != len(checks):
        raise SystemExit(1)
