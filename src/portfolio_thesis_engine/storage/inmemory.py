"""In-memory Repository implementations for unit tests.

These are interface-compatible drop-ins for the YAML/DuckDB-backed concretes.
Downstream modules (valuation, portfolio, guardrails) take a :class:`Repository`
in their constructors and tests substitute these fakes to keep tests fast
and hermetic.
"""

from __future__ import annotations

from collections.abc import Callable

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.storage.base import (
    NotFoundError,
    Repository,
    VersionedRepository,
)


class InMemoryRepository[T: BaseSchema](Repository[T]):
    """Dict-backed :class:`Repository`.

    Requires a ``key_fn`` that derives the primary key from the entity —
    mirrors the contract the YAML concretes encode via ``_get_key`` plus
    ticker normalisation. Pass ``key_fn=lambda e: e.ticker`` for the
    common case.
    """

    def __init__(self, key_fn: Callable[[T], str]) -> None:
        self._store: dict[str, T] = {}
        self._key_fn = key_fn

    def get(self, key: str) -> T | None:
        return self._store.get(key)

    def save(self, entity: T) -> None:
        self._store[self._key_fn(entity)] = entity

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def list_keys(self) -> list[str]:
        return sorted(self._store.keys())

    def exists(self, key: str) -> bool:
        return key in self._store


class InMemoryVersionedRepository[T: BaseSchema](VersionedRepository[T]):
    """Dict-of-dicts-backed :class:`VersionedRepository`.

    ``key_fn`` maps an entity to its primary key (e.g., ticker);
    ``version_fn`` maps it to the version identifier (e.g., ``snapshot_id``).
    The most recently saved version becomes current unless :meth:`set_current`
    is called to override.
    """

    def __init__(
        self,
        key_fn: Callable[[T], str],
        version_fn: Callable[[T], str],
    ) -> None:
        self._versions: dict[str, dict[str, T]] = {}
        self._current: dict[str, str] = {}
        self._key_fn = key_fn
        self._version_fn = version_fn

    def get(self, key: str) -> T | None:
        return self.get_current(key)

    def save(self, entity: T) -> None:
        key = self._key_fn(entity)
        version = self._version_fn(entity)
        self._versions.setdefault(key, {})[version] = entity
        self._current[key] = version

    def delete(self, key: str) -> None:
        self._versions.pop(key, None)
        self._current.pop(key, None)

    def list_keys(self) -> list[str]:
        return sorted(self._versions.keys())

    def exists(self, key: str) -> bool:
        return key in self._current

    def get_version(self, key: str, version: str) -> T | None:
        return self._versions.get(key, {}).get(version)

    def list_versions(self, key: str) -> list[str]:
        return sorted(self._versions.get(key, {}).keys())

    def get_current(self, key: str) -> T | None:
        current_version = self._current.get(key)
        if current_version is None:
            return None
        return self._versions[key][current_version]

    def set_current(self, key: str, version: str) -> None:
        if version not in self._versions.get(key, {}):
            raise NotFoundError(f"No version {version!r} for {key!r}")
        self._current[key] = version
