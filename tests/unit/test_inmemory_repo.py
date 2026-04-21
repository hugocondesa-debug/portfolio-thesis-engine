"""Unit tests for storage/inmemory.py.

These verify the in-memory fakes adhere to the same contracts as the
YAML-backed concretes — so downstream modules can swap either in.
"""

from __future__ import annotations

import pytest

from portfolio_thesis_engine.schemas.position import Position
from portfolio_thesis_engine.schemas.valuation import ValuationSnapshot
from portfolio_thesis_engine.storage.base import NotFoundError, Repository, VersionedRepository
from portfolio_thesis_engine.storage.inmemory import (
    InMemoryRepository,
    InMemoryVersionedRepository,
)


class TestInMemoryRepository:
    @pytest.fixture
    def repo(self) -> InMemoryRepository[Position]:
        return InMemoryRepository(key_fn=lambda p: p.ticker)

    def test_is_repository(self, repo: InMemoryRepository[Position]) -> None:
        assert isinstance(repo, Repository)

    def test_crud(self, repo: InMemoryRepository[Position], sample_position: Position) -> None:
        assert repo.get("ACME") is None
        assert repo.exists("ACME") is False
        repo.save(sample_position)
        assert repo.get("ACME") == sample_position
        assert repo.exists("ACME") is True
        assert repo.list_keys() == ["ACME"]
        repo.delete("ACME")
        assert repo.get("ACME") is None

    def test_list_keys_sorted(
        self, repo: InMemoryRepository[Position], sample_position: Position
    ) -> None:
        repo.save(sample_position)
        other = sample_position.model_copy(update={"ticker": "AAPL"})
        repo.save(other)
        assert repo.list_keys() == ["AAPL", "ACME"]


class TestInMemoryVersionedRepository:
    @pytest.fixture
    def repo(self) -> InMemoryVersionedRepository[ValuationSnapshot]:
        return InMemoryVersionedRepository(
            key_fn=lambda s: s.ticker,
            version_fn=lambda s: s.snapshot_id,
        )

    def test_is_versioned_repository(
        self, repo: InMemoryVersionedRepository[ValuationSnapshot]
    ) -> None:
        assert isinstance(repo, VersionedRepository)

    def test_save_and_get_current(
        self,
        repo: InMemoryVersionedRepository[ValuationSnapshot],
        sample_valuation_snapshot: ValuationSnapshot,
    ) -> None:
        repo.save(sample_valuation_snapshot)
        assert repo.get_current("ACME") == sample_valuation_snapshot
        assert repo.get("ACME") == sample_valuation_snapshot

    def test_multiple_versions(
        self,
        repo: InMemoryVersionedRepository[ValuationSnapshot],
        sample_valuation_snapshot: ValuationSnapshot,
    ) -> None:
        repo.save(sample_valuation_snapshot)
        second = sample_valuation_snapshot.model_copy(update={"snapshot_id": "val_v2"})
        repo.save(second)
        assert repo.list_versions("ACME") == [
            "val_2025_01_20_acme_001",
            "val_v2",
        ]
        assert repo.get_current("ACME") == second
        assert repo.get_version("ACME", "val_2025_01_20_acme_001") == (sample_valuation_snapshot)

    def test_set_current_retargets(
        self,
        repo: InMemoryVersionedRepository[ValuationSnapshot],
        sample_valuation_snapshot: ValuationSnapshot,
    ) -> None:
        repo.save(sample_valuation_snapshot)
        second = sample_valuation_snapshot.model_copy(update={"snapshot_id": "val_v2"})
        repo.save(second)
        repo.set_current("ACME", "val_2025_01_20_acme_001")
        assert repo.get_current("ACME") == sample_valuation_snapshot

    def test_set_current_unknown_raises(
        self,
        repo: InMemoryVersionedRepository[ValuationSnapshot],
        sample_valuation_snapshot: ValuationSnapshot,
    ) -> None:
        repo.save(sample_valuation_snapshot)
        with pytest.raises(NotFoundError):
            repo.set_current("ACME", "nope")

    def test_delete_removes_all_versions(
        self,
        repo: InMemoryVersionedRepository[ValuationSnapshot],
        sample_valuation_snapshot: ValuationSnapshot,
    ) -> None:
        repo.save(sample_valuation_snapshot)
        repo.delete("ACME")
        assert repo.exists("ACME") is False
        assert repo.list_versions("ACME") == []

    def test_get_missing_returns_none(
        self, repo: InMemoryVersionedRepository[ValuationSnapshot]
    ) -> None:
        assert repo.get("MISSING") is None
        assert repo.get_current("MISSING") is None
        assert repo.get_version("MISSING", "any") is None
