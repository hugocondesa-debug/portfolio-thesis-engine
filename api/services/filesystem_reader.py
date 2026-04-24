"""Filesystem readers for PTE artefacts.

Resolves "latest" via the ``current`` symlinks the storage layer
maintains. Forecast snapshots and cross-check logs are timestamp-sorted
since they don't have a `current` pointer. All public functions raise
:class:`FileNotFoundError` on missing artefacts — the FastAPI exception
handler in :mod:`api.main` translates these to HTTP 404.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from api.config import settings


def _fs_ticker(ticker: str) -> str:
    """Filesystem-safe ticker form. ``1846.HK`` → ``1846-HK``."""
    return ticker.replace(".", "-")


def _ticker_dir(ticker: str) -> Path:
    return settings.data_root / "yamls" / "companies" / _fs_ticker(ticker)


def _follow_current_symlink(symlink: Path) -> Path | None:
    """Resolve ``current`` to its target. Accepts plain files too — if
    the storage layer ever stops using symlinks the reader keeps working.
    Returns ``None`` when the path is missing entirely.
    """
    if not symlink.exists():
        return None
    if symlink.is_symlink():
        return symlink.resolve()
    return symlink


def _file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


# ----------------------------------------------------------------------
# Single-artefact loaders
# ----------------------------------------------------------------------
def load_canonical(ticker: str) -> dict[str, Any]:
    """Latest canonical state via ``extraction/current`` symlink."""
    target = _follow_current_symlink(
        _ticker_dir(ticker) / "extraction" / "current"
    )
    if target is None:
        raise FileNotFoundError(
            f"No canonical state for {ticker} — extraction/current missing"
        )
    return yaml.safe_load(target.read_text())


def load_valuation(ticker: str) -> dict[str, Any]:
    """Latest valuation snapshot via ``valuation/current`` symlink."""
    target = _follow_current_symlink(
        _ticker_dir(ticker) / "valuation" / "current"
    )
    if target is None:
        raise FileNotFoundError(
            f"No valuation for {ticker} — valuation/current missing"
        )
    return yaml.safe_load(target.read_text())


def load_ficha(ticker: str) -> dict[str, Any]:
    path = _ticker_dir(ticker) / "ficha.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No ficha for {ticker}")
    return yaml.safe_load(path.read_text())


def load_forecast(ticker: str) -> dict[str, Any]:
    """Latest forecast snapshot — newest ``.json`` by mtime under
    ``data/forecast_snapshots/<ticker>/``."""
    forecast_dir = (
        settings.data_root / "forecast_snapshots" / _fs_ticker(ticker)
    )
    if not forecast_dir.exists():
        raise FileNotFoundError(f"No forecast directory for {ticker}")
    json_files = sorted(
        forecast_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        raise FileNotFoundError(f"No forecast snapshots for {ticker}")
    return json.loads(json_files[0].read_text())


def load_peers_yaml(ticker: str) -> dict[str, Any]:
    path = _ticker_dir(ticker) / "peers.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No peers.yaml for {ticker}")
    return yaml.safe_load(path.read_text())


def load_latest_cross_check(ticker: str) -> dict[str, Any]:
    """Most recent cross-check log under ``data/logs/cross_check/``."""
    log_dir = settings.data_root / "logs" / "cross_check"
    if not log_dir.exists():
        raise FileNotFoundError("No cross-check logs directory")
    json_files = sorted(
        log_dir.glob(f"{_fs_ticker(ticker)}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        raise FileNotFoundError(f"No cross-check logs for {ticker}")
    return json.loads(json_files[0].read_text())


def list_pipeline_runs(ticker: str, limit: int = 20) -> list[dict[str, Any]]:
    """Recent pipeline runs from ``data/logs/runs/<ticker>_*.jsonl``."""
    log_dir = settings.data_root / "logs" / "runs"
    if not log_dir.exists():
        return []
    jsonl_files = sorted(
        log_dir.glob(f"{_fs_ticker(ticker)}_*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]

    runs: list[dict[str, Any]] = []
    for f in jsonl_files:
        try:
            lines = [
                json.loads(line)
                for line in f.read_text().splitlines()
                if line.strip()
            ]
        except (json.JSONDecodeError, OSError):
            continue
        runs.append(
            {
                "run_id": f.stem,
                "ticker": ticker,
                "started_at": _file_mtime(f).isoformat(),
                "stages": lines,
            }
        )
    return runs


# ----------------------------------------------------------------------
# Discovery + metadata
# ----------------------------------------------------------------------
def discover_tickers() -> list[str]:
    """List ticker directories under ``data/yamls/companies/``.

    Filesystem is the authoritative source for ticker discovery — the
    sqlite ``companies`` table only carries placeholder currency /
    exchange values today. Sprint 0 uses filesystem + canonical-state
    enrichment instead.
    """
    base = settings.data_root / "yamls" / "companies"
    if not base.exists():
        return []
    # Filesystem stores tickers with `-`; convert back to `.` for the
    # canonical Yahoo-style symbol the rest of the system expects.
    fs_tickers = sorted(
        d.name for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    return [t.replace("-", ".", 1) if "-" in t else t for t in fs_tickers]


def latest_artifact_metadata(ticker: str) -> dict[str, datetime | None]:
    """``mtime`` of each artefact (or ``None`` when absent)."""
    result: dict[str, datetime | None] = {
        "extraction": None,
        "valuation": None,
        "forecast": None,
        "ficha": None,
    }
    extraction = _follow_current_symlink(
        _ticker_dir(ticker) / "extraction" / "current"
    )
    if extraction is not None and extraction.exists():
        result["extraction"] = _file_mtime(extraction)

    valuation = _follow_current_symlink(
        _ticker_dir(ticker) / "valuation" / "current"
    )
    if valuation is not None and valuation.exists():
        result["valuation"] = _file_mtime(valuation)

    forecast_dir = (
        settings.data_root / "forecast_snapshots" / _fs_ticker(ticker)
    )
    if forecast_dir.exists():
        json_files = list(forecast_dir.glob("*.json"))
        if json_files:
            newest = max(json_files, key=lambda p: p.stat().st_mtime)
            result["forecast"] = _file_mtime(newest)

    ficha = _ticker_dir(ticker) / "ficha.yaml"
    if ficha.exists():
        result["ficha"] = _file_mtime(ficha)

    return result


def canonical_identity(ticker: str) -> dict[str, Any] | None:
    """Pull the ``identity`` block from the latest canonical state.

    Used to enrich :func:`sqlite_reader.list_companies` rows whose
    SQLite columns are placeholders. Returns ``None`` when the canonical
    state is unavailable so callers can fall back to defaults without
    raising.
    """
    try:
        canonical = load_canonical(ticker)
    except FileNotFoundError:
        return None
    return canonical.get("identity")


__all__ = [
    "canonical_identity",
    "discover_tickers",
    "latest_artifact_metadata",
    "list_pipeline_runs",
    "load_canonical",
    "load_ficha",
    "load_forecast",
    "load_latest_cross_check",
    "load_peers_yaml",
    "load_valuation",
]
