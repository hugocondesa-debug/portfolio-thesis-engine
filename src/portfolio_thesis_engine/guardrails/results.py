"""Aggregate guardrail results and render them for humans/machines.

:class:`ResultAggregator` summarises a list of :class:`GuardrailResult`
(counts per status, list of blocking FAILs, overall verdict).
:class:`ReportWriter` renders the aggregate as either plain text (for the
CLI / logs) or JSON (for downstream systems and the CLI's ``--json`` mode).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from portfolio_thesis_engine.guardrails.base import GuardrailResult
from portfolio_thesis_engine.guardrails.runner import GuardrailRunner
from portfolio_thesis_engine.schemas.common import GuardrailStatus


@dataclass
class AggregatedResults:
    """Summary computed once, consumed many times."""

    total: int
    by_status: dict[GuardrailStatus, int]
    overall: GuardrailStatus
    blocking_failures: list[GuardrailResult] = field(default_factory=list)
    results: list[GuardrailResult] = field(default_factory=list)


class ResultAggregator:
    """Collapse a list of results into counts + blocking failures + overall."""

    @staticmethod
    def aggregate(results: list[GuardrailResult]) -> AggregatedResults:
        counts: Counter[GuardrailStatus] = Counter(r.status for r in results)
        blocking = [r for r in results if r.blocking and r.status == GuardrailStatus.FAIL]
        return AggregatedResults(
            total=len(results),
            by_status=dict(counts),
            overall=GuardrailRunner.overall_status(results),
            blocking_failures=blocking,
            results=results,
        )


class ReportWriter:
    """Render :class:`AggregatedResults` as text or JSON."""

    @staticmethod
    def to_text(agg: AggregatedResults) -> str:
        lines: list[str] = []
        lines.append(f"Overall: {agg.overall.value}  —  {agg.total} checks")
        for status, count in sorted(agg.by_status.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {status.value:<7} {count}")
        if agg.blocking_failures:
            lines.append("")
            lines.append("Blocking failures:")
            for r in agg.blocking_failures:
                lines.append(f"  [{r.check_id}] {r.name}: {r.message}")
        lines.append("")
        lines.append("Details:")
        for r in agg.results:
            prefix = f"  [{r.status.value}] {r.check_id} — {r.name}"
            if r.message:
                prefix += f": {r.message}"
            lines.append(prefix)
        return "\n".join(lines)

    @staticmethod
    def to_json(agg: AggregatedResults) -> str:
        payload: dict[str, Any] = {
            "overall": agg.overall.value,
            "total": agg.total,
            "by_status": {k.value: v for k, v in agg.by_status.items()},
            "blocking_failures": [
                {
                    "check_id": r.check_id,
                    "name": r.name,
                    "message": r.message,
                }
                for r in agg.blocking_failures
            ],
            "results": [
                {
                    "check_id": r.check_id,
                    "name": r.name,
                    "status": r.status.value,
                    "message": r.message,
                    "blocking": r.blocking,
                    "data": r.data,
                }
                for r in agg.results
            ],
        }
        return json.dumps(payload, indent=2, sort_keys=False)
