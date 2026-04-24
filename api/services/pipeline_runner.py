"""Async subprocess runner for ``pte`` CLI commands.

Spawns ``pte process / forecast / valuation`` in a detached
subprocess, streams combined stdout+stderr to a per-run log file
under ``data/logs/api_runs/<run_id>.log`` and persists status meta
to ``<run_id>.meta.json``. Returns immediately to the caller; the
client polls :func:`get_run_status` for completion.

Subprocess pattern is :func:`asyncio.create_subprocess_exec` — never
imports PTE Python modules directly. This keeps the API service
process light and decouples it from PTE's runtime requirements.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api.config import settings


# In-memory state — augments the meta.json on disk so pollers don't
# always hit the filesystem during an active run.
_active_runs: dict[str, dict[str, Any]] = {}


def _log_dir() -> Path:
    log_dir = settings.data_root / "logs" / "api_runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _run_log_path(run_id: str) -> Path:
    return _log_dir() / f"{run_id}.log"


def _run_meta_path(run_id: str) -> Path:
    return _log_dir() / f"{run_id}.meta.json"


def _persist_meta(run_id: str) -> None:
    if run_id not in _active_runs:
        return
    _run_meta_path(run_id).write_text(
        json.dumps(_active_runs[run_id], indent=2)
    )


async def trigger_pipeline(
    ticker: str,
    command: str,
    extraction_path: str | None = None,
    base_period: str | None = None,
    skip_cross_check: bool = False,
) -> dict[str, Any]:
    """Spawn ``pte <command> <ticker>`` in the background and return
    the initial run metadata. Status is pollable via
    :func:`get_run_status`.
    """
    run_id = uuid.uuid4().hex[:12]

    cmd_parts = settings.pte_command.split() + [command, ticker]
    if command == "process":
        if extraction_path:
            cmd_parts.extend(["--extraction-path", extraction_path])
        if base_period:
            cmd_parts.extend(["--base-period", base_period])
        if skip_cross_check:
            cmd_parts.append("--skip-cross-check")

    started_at = datetime.now(UTC)
    meta = {
        "run_id": run_id,
        "ticker": ticker,
        "command": " ".join(cmd_parts),
        "status": "queued",
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "exit_code": None,
    }
    _active_runs[run_id] = meta
    _persist_meta(run_id)

    asyncio.create_task(_run_subprocess(run_id, cmd_parts))
    return meta


async def _run_subprocess(run_id: str, cmd_parts: list[str]) -> None:
    """Background coroutine — run the subprocess, stream to log,
    update meta on completion."""
    log_path = _run_log_path(run_id)

    _active_runs[run_id]["status"] = "running"
    _persist_meta(run_id)

    exit_code: int | None = None
    try:
        with log_path.open("w") as log_f:
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=str(settings.pte_workdir),
            )
            try:
                exit_code = await asyncio.wait_for(
                    process.wait(),
                    timeout=settings.pipeline_timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                exit_code = -9
                _active_runs[run_id]["status"] = "timeout"
                log_f.write(
                    f"\n\n[TIMEOUT after "
                    f"{settings.pipeline_timeout_seconds}s]\n"
                )

        if _active_runs[run_id]["status"] != "timeout":
            _active_runs[run_id]["status"] = (
                "done" if exit_code == 0 else "failed"
            )
        _active_runs[run_id]["exit_code"] = exit_code
        _active_runs[run_id]["completed_at"] = datetime.now(UTC).isoformat()
    except Exception as exc:  # noqa: BLE001 — capture any spawn failure
        _active_runs[run_id]["status"] = "failed"
        _active_runs[run_id]["completed_at"] = datetime.now(UTC).isoformat()
        try:
            with log_path.open("a") as log_f:
                log_f.write(f"\n\n[EXCEPTION] {type(exc).__name__}: {exc}\n")
        except OSError:
            pass
    finally:
        _persist_meta(run_id)


def get_run_status(run_id: str, tail_lines: int = 30) -> dict[str, Any]:
    """Return live status with an optional log-tail snippet. Falls back
    to the persisted meta.json once the run leaves the in-memory map
    (after API restart, for instance)."""
    if run_id in _active_runs:
        meta = dict(_active_runs[run_id])
    else:
        meta_path = _run_meta_path(run_id)
        if not meta_path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        meta = json.loads(meta_path.read_text())

    if meta.get("completed_at") and meta.get("started_at"):
        try:
            started = datetime.fromisoformat(meta["started_at"])
            completed = datetime.fromisoformat(meta["completed_at"])
            meta["duration_seconds"] = (completed - started).total_seconds()
        except ValueError:
            meta["duration_seconds"] = None

    log_path = _run_log_path(run_id)
    if log_path.exists():
        try:
            lines = log_path.read_text().splitlines()
            meta["output_tail"] = "\n".join(lines[-tail_lines:])
        except OSError:
            meta["output_tail"] = None

    return meta


__all__ = ["get_run_status", "trigger_pipeline"]
