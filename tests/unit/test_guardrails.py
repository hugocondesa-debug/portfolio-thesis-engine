"""Unit tests for the guardrails framework."""

from __future__ import annotations

import json
from typing import Any

import pytest

from portfolio_thesis_engine.guardrails.base import Guardrail, GuardrailResult
from portfolio_thesis_engine.guardrails.results import ReportWriter, ResultAggregator
from portfolio_thesis_engine.guardrails.runner import GuardrailRunner
from portfolio_thesis_engine.schemas.common import GuardrailStatus

# ----------------------------------------------------------------------
# Trivial guardrails used as fixtures across the test suite.
# ----------------------------------------------------------------------


class TrivialPass(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.P"

    @property
    def name(self) -> str:
        return "trivial pass"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.PASS, "OK")


class TrivialWarn(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.W"

    @property
    def name(self) -> str:
        return "trivial warn"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.WARN, "just a warning")


class TrivialFail(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.F"

    @property
    def name(self) -> str:
        return "trivial fail"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.FAIL, "failed")


class BlockingFail(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.BF"

    @property
    def name(self) -> str:
        return "blocking fail"

    @property
    def blocking(self) -> bool:
        return True

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(
            self.check_id,
            self.name,
            GuardrailStatus.FAIL,
            "blocking failure",
            blocking=True,
        )


class Explodes(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.X"

    @property
    def name(self) -> str:
        return "explodes"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        raise RuntimeError("internal error in check()")


class Review(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.R"

    @property
    def name(self) -> str:
        return "needs review"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.REVIEW, "please review")


class Nota(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.N"

    @property
    def name(self) -> str:
        return "informational nota"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.NOTA, "fyi")


class Skipped(Guardrail):
    @property
    def check_id(self) -> str:
        return "T.S"

    @property
    def name(self) -> str:
        return "skipped"

    def check(self, context: dict[str, Any]) -> GuardrailResult:
        return GuardrailResult(self.check_id, self.name, GuardrailStatus.SKIP, "not applicable")


# ======================================================================
# Runner
# ======================================================================


class TestRunner:
    def test_empty_list(self) -> None:
        runner = GuardrailRunner([])
        results = runner.run({})
        assert results == []
        assert runner.overall_status(results) == GuardrailStatus.PASS

    def test_single_pass(self) -> None:
        runner = GuardrailRunner([TrivialPass()])
        results = runner.run({})
        assert len(results) == 1
        assert results[0].status == GuardrailStatus.PASS

    def test_runs_all_non_blocking(self) -> None:
        runner = GuardrailRunner([TrivialPass(), TrivialWarn(), TrivialFail()])
        results = runner.run({})
        assert [r.status for r in results] == [
            GuardrailStatus.PASS,
            GuardrailStatus.WARN,
            GuardrailStatus.FAIL,
        ]

    def test_blocking_fail_stops_run_by_default(self) -> None:
        runner = GuardrailRunner([TrivialPass(), BlockingFail(), TrivialWarn()])
        results = runner.run({})
        assert len(results) == 2
        assert results[-1].status == GuardrailStatus.FAIL
        assert results[-1].blocking is True

    def test_stop_on_blocking_fail_false_runs_all(self) -> None:
        runner = GuardrailRunner([TrivialPass(), BlockingFail(), TrivialWarn()])
        results = runner.run({}, stop_on_blocking_fail=False)
        assert len(results) == 3

    def test_non_blocking_fail_does_not_stop(self) -> None:
        runner = GuardrailRunner([TrivialFail(), TrivialPass()])
        results = runner.run({})
        assert len(results) == 2

    def test_exception_in_check_becomes_fail(self) -> None:
        runner = GuardrailRunner([TrivialPass(), Explodes(), TrivialPass()])
        results = runner.run({})
        assert len(results) == 3
        assert results[1].status == GuardrailStatus.FAIL
        assert "RuntimeError" in results[1].message

    def test_exception_with_blocking_guardrail_stops_run(self) -> None:
        class BlockingExplodes(Explodes):
            @property
            def blocking(self) -> bool:
                return True

        runner = GuardrailRunner([TrivialPass(), BlockingExplodes(), TrivialPass()])
        results = runner.run({})
        assert len(results) == 2
        assert results[-1].blocking is True
        assert results[-1].status == GuardrailStatus.FAIL

    def test_context_passed_through(self) -> None:
        received: dict[str, Any] = {}

        class Observes(Guardrail):
            @property
            def check_id(self) -> str:
                return "O.1"

            @property
            def name(self) -> str:
                return "observes context"

            def check(self, context: dict[str, Any]) -> GuardrailResult:
                received.update(context)
                return GuardrailResult(self.check_id, self.name, GuardrailStatus.PASS, "")

        runner = GuardrailRunner([Observes()])
        runner.run({"ticker": "ACME", "revenue": 1000})
        assert received == {"ticker": "ACME", "revenue": 1000}


# ======================================================================
# overall_status precedence
# ======================================================================


class TestOverallStatus:
    @pytest.mark.parametrize(
        "guardrails, expected",
        [
            ([TrivialPass()], GuardrailStatus.PASS),
            ([Skipped()], GuardrailStatus.SKIP),
            ([TrivialPass(), Nota()], GuardrailStatus.NOTA),
            ([TrivialPass(), TrivialWarn()], GuardrailStatus.WARN),
            ([TrivialPass(), Review()], GuardrailStatus.REVIEW),
            ([TrivialPass(), TrivialFail()], GuardrailStatus.FAIL),
            (
                [TrivialFail(), Review(), TrivialWarn(), Nota()],
                GuardrailStatus.FAIL,
            ),
            ([Review(), TrivialWarn()], GuardrailStatus.REVIEW),
            ([TrivialWarn(), Nota()], GuardrailStatus.WARN),
        ],
    )
    def test_precedence(self, guardrails: list[Guardrail], expected: GuardrailStatus) -> None:
        runner = GuardrailRunner(guardrails)
        results = runner.run({}, stop_on_blocking_fail=False)
        assert runner.overall_status(results) == expected

    def test_empty_returns_pass(self) -> None:
        assert GuardrailRunner.overall_status([]) == GuardrailStatus.PASS


# ======================================================================
# ResultAggregator
# ======================================================================


class TestAggregator:
    def test_counts_by_status(self) -> None:
        runner = GuardrailRunner([TrivialPass(), TrivialPass(), TrivialWarn(), TrivialFail()])
        agg = ResultAggregator.aggregate(runner.run({}))
        assert agg.total == 4
        assert agg.by_status[GuardrailStatus.PASS] == 2
        assert agg.by_status[GuardrailStatus.WARN] == 1
        assert agg.by_status[GuardrailStatus.FAIL] == 1
        assert agg.overall == GuardrailStatus.FAIL

    def test_captures_blocking_failures_only(self) -> None:
        runner = GuardrailRunner(
            [TrivialFail(), BlockingFail()],
        )
        agg = ResultAggregator.aggregate(runner.run({}, stop_on_blocking_fail=False))
        assert len(agg.blocking_failures) == 1
        assert agg.blocking_failures[0].check_id == "T.BF"


# ======================================================================
# ReportWriter
# ======================================================================


class TestReportWriter:
    def test_text_report_mentions_overall_and_counts(self) -> None:
        runner = GuardrailRunner([TrivialPass(), TrivialWarn()])
        agg = ResultAggregator.aggregate(runner.run({}))
        text = ReportWriter.to_text(agg)
        assert "Overall: WARN" in text
        assert "2 checks" in text
        assert "PASS" in text
        assert "WARN" in text

    def test_text_report_lists_blocking_failures(self) -> None:
        runner = GuardrailRunner([TrivialPass(), BlockingFail()])
        agg = ResultAggregator.aggregate(runner.run({}, stop_on_blocking_fail=False))
        text = ReportWriter.to_text(agg)
        assert "Blocking failures:" in text
        assert "T.BF" in text

    def test_json_report_is_valid_json(self) -> None:
        runner = GuardrailRunner([TrivialPass(), TrivialWarn(), TrivialFail()])
        agg = ResultAggregator.aggregate(runner.run({}))
        payload = json.loads(ReportWriter.to_json(agg))
        assert payload["overall"] == "FAIL"
        assert payload["total"] == 3
        assert payload["by_status"]["PASS"] == 1
        assert len(payload["results"]) == 3

    def test_json_report_includes_blocking_failures(self) -> None:
        runner = GuardrailRunner([BlockingFail()])
        agg = ResultAggregator.aggregate(runner.run({}, stop_on_blocking_fail=False))
        payload = json.loads(ReportWriter.to_json(agg))
        assert len(payload["blocking_failures"]) == 1
        assert payload["blocking_failures"][0]["check_id"] == "T.BF"
