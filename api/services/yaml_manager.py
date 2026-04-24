"""Yaml management — list, read, validate, version, write.

Two-stage validation on upload:

1. PyYAML parse (catches syntax errors → 422 with ``yaml_syntax``).
2. PTE Pydantic schema validation (catches semantic errors → 422 with
   field-level locations). Schemas are imported lazily so a PTE
   refactor of import paths can't break API service boot.

Versioning: every successful upload backs the prior file up under
``<ticker_dir>/.versions/<name>_<timestamp>.yaml.bak`` and prunes the
backup directory to ``settings.yaml_versions_keep`` (default 10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from api.config import settings

# Whitelist of yaml names the API will accept on upload. Adding a name
# here also exposes it via the GET / list endpoints.
_ALLOWED_YAMLS = frozenset(
    {
        "scenarios",
        "capital_allocation",
        "leading_indicators",
        "peers",
        "revenue_geography",
        "valuation_profile",
    }
)


def _fs_ticker(ticker: str) -> str:
    return ticker.replace(".", "-")


def _ticker_dir(ticker: str) -> Path:
    return settings.data_root / "yamls" / "companies" / _fs_ticker(ticker)


def _versions_dir(ticker: str) -> Path:
    return _ticker_dir(ticker) / ".versions"


# ----------------------------------------------------------------------
# List + read
# ----------------------------------------------------------------------
def list_available_yamls(ticker: str) -> list[dict[str, Any]]:
    base = _ticker_dir(ticker)
    if not base.exists():
        raise FileNotFoundError(f"Ticker directory not found: {ticker}")

    versions_dir = _versions_dir(ticker)
    out: list[dict[str, Any]] = []
    for name in sorted(_ALLOWED_YAMLS):
        path = base / f"{name}.yaml"
        if not path.exists():
            continue
        version_count = (
            len(list(versions_dir.glob(f"{name}_*.yaml.bak")))
            if versions_dir.exists()
            else 0
        )
        out.append(
            {
                "name": name,
                "filename": f"{name}.yaml",
                "last_modified": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=UTC
                ).isoformat(),
                "size_bytes": path.stat().st_size,
                "versions_count": version_count,
            }
        )
    return out


def read_yaml(ticker: str, yaml_name: str) -> str:
    if yaml_name not in _ALLOWED_YAMLS:
        raise ValueError(f"Yaml name not allowed: {yaml_name}")
    path = _ticker_dir(ticker) / f"{yaml_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Yaml not found: {ticker}/{yaml_name}")
    return path.read_text()


# ----------------------------------------------------------------------
# Upload
# ----------------------------------------------------------------------
def upload_yaml(
    ticker: str, yaml_name: str, content: str
) -> dict[str, Any]:
    """Validate + back up + write. Always returns a dict so the route
    can decide between 200 and 422 based on ``success``."""
    if yaml_name not in _ALLOWED_YAMLS:
        raise ValueError(f"Yaml name not allowed: {yaml_name}")

    base = _ticker_dir(ticker)
    if not base.exists():
        raise FileNotFoundError(f"Ticker directory not found: {ticker}")

    target = base / f"{yaml_name}.yaml"

    # Step 1 — YAML parse.
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return {
            "success": False,
            "validation_errors": [
                {"type": "yaml_syntax", "message": str(exc)}
            ],
            "backup_path": None,
            "new_filename": None,
        }

    # Step 2 — Pydantic semantic validation.
    semantic_errors = _validate_yaml_against_pydantic(yaml_name, parsed)
    if semantic_errors:
        return {
            "success": False,
            "validation_errors": semantic_errors,
            "backup_path": None,
            "new_filename": None,
        }

    # Step 3 — Backup (only if a prior file existed). Microsecond
    # precision in the timestamp prevents filename collisions when an
    # analyst (or a test loop) submits multiple uploads inside one
    # wall-clock second.
    backup_path: Path | None = None
    if target.exists():
        versions_dir = _versions_dir(ticker)
        versions_dir.mkdir(exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        backup_path = versions_dir / f"{yaml_name}_{timestamp}.yaml.bak"
        backup_path.write_text(target.read_text())

    # Step 4 — Atomic-ish write.
    target.write_text(content)

    # Step 5 — Cleanup old versions.
    _cleanup_old_versions(ticker, yaml_name)

    return {
        "success": True,
        "validation_errors": None,
        "backup_path": str(backup_path) if backup_path else None,
        "new_filename": str(target),
    }


def _validate_yaml_against_pydantic(
    yaml_name: str, parsed: Any
) -> list[dict[str, Any]]:
    """Lazy-import PTE schemas so API boot doesn't depend on PTE
    internals. Returns empty list when the yaml has no Pydantic
    counterpart (peers / revenue_geography / valuation_profile use
    free-form schemas today).
    """
    from pydantic import ValidationError

    schema_class = None
    try:
        if yaml_name == "scenarios":
            from portfolio_thesis_engine.dcf.schemas import ScenarioSet

            schema_class = ScenarioSet
        elif yaml_name == "capital_allocation":
            from portfolio_thesis_engine.forecast.capital_allocation_consumer import (
                ParsedCapitalAllocation,
            )

            schema_class = ParsedCapitalAllocation
        elif yaml_name == "leading_indicators":
            from portfolio_thesis_engine.briefing.leading_indicators import (
                LeadingIndicatorsSet,
            )

            schema_class = LeadingIndicatorsSet
    except (ImportError, AttributeError):
        # Schema not available — skip semantic validation.
        return []

    if schema_class is None:
        return []

    try:
        schema_class.model_validate(parsed)
        return []
    except ValidationError as exc:
        return [
            {
                "type": "pydantic_validation",
                "loc": list(err.get("loc", [])),
                "message": err.get("msg", ""),
                "input": err.get("input"),
            }
            for err in exc.errors()
        ]
    except Exception as exc:  # noqa: BLE001 — surface as soft failure
        return [
            {
                "type": "validation_error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        ]


def _cleanup_old_versions(ticker: str, yaml_name: str) -> None:
    versions_dir = _versions_dir(ticker)
    if not versions_dir.exists():
        return
    versions = sorted(
        versions_dir.glob(f"{yaml_name}_*.yaml.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in versions[settings.yaml_versions_keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def list_yaml_versions(ticker: str, yaml_name: str) -> list[dict[str, Any]]:
    if yaml_name not in _ALLOWED_YAMLS:
        raise ValueError(f"Yaml name not allowed: {yaml_name}")
    versions_dir = _versions_dir(ticker)
    if not versions_dir.exists():
        return []
    versions = sorted(
        versions_dir.glob(f"{yaml_name}_*.yaml.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "filename": v.name,
            "modified_at": datetime.fromtimestamp(
                v.stat().st_mtime, tz=UTC
            ).isoformat(),
            "size_bytes": v.stat().st_size,
        }
        for v in versions
    ]


__all__ = [
    "list_available_yamls",
    "list_yaml_versions",
    "read_yaml",
    "upload_yaml",
]
