"""Per-call cost tracking with JSONL persistence.

Every LLM call records a :class:`CostEntry` — in-memory for the session,
append-only to ``llm_costs.jsonl`` on disk. Thread-safe via a single lock.
The module also exposes a lazy singleton via :func:`get_cost_tracker` for
call sites that don't want to pass a tracker around.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock

from portfolio_thesis_engine.shared.config import settings


@dataclass
class CostEntry:
    timestamp: datetime
    operation: str
    ticker: str | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class CostTracker:
    """Thread-safe cost tracker."""

    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path or (settings.data_dir / "llm_costs.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._session_entries: list[CostEntry] = []

    def record(
        self,
        operation: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        ticker: str | None = None,
    ) -> CostEntry:
        entry = CostEntry(
            timestamp=datetime.now(UTC),
            operation=operation,
            ticker=ticker,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        with self._lock:
            self._session_entries.append(entry)
            self._append_jsonl(entry)
        return entry

    def _append_jsonl(self, entry: CostEntry) -> None:
        payload = {
            "timestamp": entry.timestamp.isoformat(),
            "operation": entry.operation,
            "ticker": entry.ticker,
            "model": entry.model,
            "input_tokens": entry.input_tokens,
            "output_tokens": entry.output_tokens,
            "cost_usd": str(entry.cost_usd),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def session_total(self) -> Decimal:
        with self._lock:
            total = Decimal("0")
            for entry in self._session_entries:
                total += entry.cost_usd
            return total

    def session_entries(self) -> list[CostEntry]:
        with self._lock:
            return list(self._session_entries)

    def ticker_total(self, ticker: str) -> Decimal:
        """Sum cost for ``ticker`` across the entire JSONL log file.

        Safe to call concurrently with :meth:`record` — reads the log file
        independently of the in-memory session list.
        """
        total = Decimal("0")
        if not self.log_path.exists():
            return total
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("ticker") == ticker:
                    total += Decimal(entry["cost_usd"])
        return total


_tracker: CostTracker | None = None
_tracker_lock = Lock()


def get_cost_tracker() -> CostTracker:
    """Return the process-wide singleton, creating it on first call."""
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = CostTracker()
        return _tracker


def reset_cost_tracker() -> None:
    """Clear the singleton — exposed for tests that need isolation."""
    global _tracker
    with _tracker_lock:
        _tracker = None
