"""Base classes and mixins for all Pydantic schemas.

:class:`BaseSchema` is the default — forbids extra fields, strips string
whitespace, validates on assignment. :class:`ImmutableSchema` additionally
marks the model ``frozen`` (used for snapshots). :class:`VersionedMixin` and
:class:`AuditableMixin` add versioning and changelog functionality.

Every schema that inherits :class:`BaseSchema` gains symmetric YAML helpers
:meth:`BaseSchema.to_yaml` / :meth:`BaseSchema.from_yaml`. These use
Pydantic's JSON mode for the dict representation so ``Decimal`` values
serialize as strings (exact precision preserved) and ``datetime`` values as
ISO strings — both of which round-trip losslessly through PyYAML.
"""

from datetime import UTC, datetime
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Default base — strict field set, whitespace-stripped strings."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    def to_yaml(self) -> str:
        """Serialize to YAML via Pydantic's JSON-compatible dict.

        Decimal/datetime become strings, enums become their ``.value``.
        Uses block style (``sort_keys=False``) to preserve declaration order
        for human readability.
        """
        data = self.model_dump(mode="json")
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> Self:
        """Parse YAML and validate via Pydantic. Inverse of :meth:`to_yaml`."""
        data = yaml.safe_load(yaml_str)
        return cls.model_validate(data)


class ImmutableSchema(BaseSchema):
    """Base for snapshots / append-only records — frozen after creation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


class VersionedMixin(BaseModel):
    """Adds monotonically-increasing version + creation audit to a schema."""

    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str = Field(default="system")
    previous_version: str | None = None


class AuditableMixin(BaseModel):
    """Adds a mutable changelog of ``{timestamp, actor, description}`` entries."""

    changelog: list[dict[str, Any]] = Field(default_factory=list)

    def add_change(self, description: str, actor: str = "system") -> None:
        """Append a change entry. Requires the host model to be non-frozen."""
        self.changelog.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "actor": actor,
                "description": description,
            }
        )
