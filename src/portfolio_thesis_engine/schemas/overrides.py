"""Phase 1.5.10 — user-authored overrides for Module D classification.

Lives at ``{portfolio_dir}/<ticker>/overrides.yaml``. The analyst
reviews the flagged / low-confidence sub-items in ``pte show --detail``
and adds an :class:`OverrideRule` for each one whose classification
needs to be pinned:

.. code-block:: yaml

    version: 1
    sub_item_classifications:
      - label_pattern: "government subsidies"
        operational: operational
        recurring: recurring
        rationale: >
          Subsidy tied to the German medical-devices operating licence,
          confirmed recurring over 2020-2024 history.
      - label_pattern: "(?i)fair value.*contingent consideration"
        operational: non_operational
        recurring: non_recurring
        rationale: >
          One-off remeasurement of the 2019 acquisition earnout.

When an override matches a sub-item's label, it wins over the regex
rules. An override can leave either dimension ``None`` to fall through
to the regex classifier for the unspecified dimension.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.decomposition import (
    OperationalClass,
    RecurrenceClass,
)


class OverrideRule(BaseSchema):
    """One override rule. ``label_pattern`` is a regex (case-
    insensitive by default). ``operational`` / ``recurring`` are the
    forced classifications — leave ``None`` to fall through to the
    regex classifier for that dimension."""

    label_pattern: str = Field(min_length=1)
    operational: OperationalClass | None = None
    recurring: RecurrenceClass | None = None
    rationale: str = Field(min_length=1)

    @field_validator("label_pattern", mode="after")
    @classmethod
    def _validate_regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regex {value!r}: {exc}") from exc
        return value

    def matches(self, label: str) -> bool:
        return bool(re.search(self.label_pattern, label, re.IGNORECASE))


class ModuleDOverrides(BaseSchema):
    """Container for all per-ticker overrides.

    Versioned so the format can evolve; Phase 1.5.10 is ``version: 1``.
    """

    version: int = 1
    sub_item_classifications: list[OverrideRule] = Field(default_factory=list)

    @classmethod
    def empty(cls) -> ModuleDOverrides:
        return cls(version=1, sub_item_classifications=[])

    def match(self, label: str) -> OverrideRule | None:
        """First-match wins — the file is an ordered list, so put
        specific patterns above generic ones."""
        for rule in self.sub_item_classifications:
            if rule.matches(label):
                return rule
        return None

    @classmethod
    def from_yaml(cls, payload: str | dict[str, Any]) -> ModuleDOverrides:
        """Parse from a YAML string or a pre-parsed dict."""
        import yaml

        if isinstance(payload, str):
            data = yaml.safe_load(payload) or {}
        else:
            data = payload
        return cls.model_validate(data)
