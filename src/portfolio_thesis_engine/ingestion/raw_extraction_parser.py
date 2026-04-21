"""Parser helper for ``raw_extraction.yaml`` → :class:`RawExtraction`.

Reads the YAML file Hugo + Claude.ai produced from the source annual
report, validates it against :class:`RawExtraction`, and returns the
typed object. Every error path raises :class:`IngestionError` with a
clear message so the CLI surfaces "your YAML is malformed on line X"
instead of a naked `ValidationError` traceback.

The parser is deliberately thin — the schema does the heavy lifting.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction


def parse_raw_extraction(path: Path) -> RawExtraction:
    """Return a validated :class:`RawExtraction` read from ``path``.

    Raises :class:`IngestionError` on I/O failure, YAML syntax error,
    or schema violation. Callers catch one exception class regardless
    of the underlying cause.
    """
    if not path.exists():
        raise IngestionError(f"raw_extraction: file not found at {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise IngestionError(f"raw_extraction: cannot read {path}: {e}") from e

    try:
        return RawExtraction.from_yaml(content)
    except ValidationError as e:
        # Pydantic raises ValidationError for schema violations AND for
        # top-level type mismatches (e.g. list where dict expected).
        raise IngestionError(
            f"raw_extraction: schema validation failed for {path}:\n{e}"
        ) from e
    except yaml.YAMLError as e:
        # PyYAML syntax / structure errors (unclosed list, bad scalar)
        # surface as YAMLError — wrap with a pointer to the file.
        raise IngestionError(
            f"raw_extraction: YAML syntax error in {path}: {e}"
        ) from e
