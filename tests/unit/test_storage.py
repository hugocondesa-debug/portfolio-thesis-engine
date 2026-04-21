"""Unit tests for storage/base.py and storage/yaml_repo.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.market_context import MarketContext
from portfolio_thesis_engine.schemas.peer import Peer
from portfolio_thesis_engine.schemas.position import Position
from portfolio_thesis_engine.schemas.valuation import ValuationSnapshot
from portfolio_thesis_engine.storage.base import (
    NotFoundError,
    Repository,
    StorageError,
    UnitOfWork,
    VersionedRepository,
)
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    MarketContextRepository,
    PeerRepository,
    PositionRepository,
    ValuationRepository,
    YAMLRepository,
    _atomic_write_text,
)

# ============================================================
# storage/base.py
# ============================================================


class TestBaseContracts:
    def test_repository_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            Repository()  # type: ignore[abstract]

    def test_versioned_repository_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            VersionedRepository()  # type: ignore[abstract]

    def test_unit_of_work_stub_is_usable(self) -> None:
        with UnitOfWork() as uow:
            uow.commit()
            uow.rollback()
        # Context manager swallows the body; exit path returns None
        assert True


# ============================================================
# _atomic_write_text
# ============================================================


class TestAtomicWrite:
    def test_writes_file_when_parent_exists(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        _atomic_write_text(target, "hello\n")
        assert target.read_text() == "hello\n"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "out.txt"
        _atomic_write_text(target, "x")
        assert target.read_text() == "x"

    def test_no_temp_file_left_behind(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        _atomic_write_text(target, "x")
        # Only the final file should exist — no tempfile residue
        remaining = sorted(p.name for p in tmp_path.iterdir())
        assert remaining == ["out.txt"]

    def test_crash_between_write_and_replace_preserves_original(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("original\n")

        with (
            patch.object(
                Path,
                "replace",
                side_effect=RuntimeError("simulated crash between write and rename"),
            ),
            pytest.raises(RuntimeError),
        ):
            _atomic_write_text(target, "new content\n")

        # Original untouched, no temp file lingering
        assert target.read_text() == "original\n"
        tmp_files = [p for p in tmp_path.iterdir() if p.name != "out.txt"]
        assert tmp_files == [], f"temp residue: {tmp_files}"


# ============================================================
# YAMLRepository (generic)
# ============================================================


class TestYAMLRepositoryGeneric:
    def test_save_then_get_roundtrip(self, tmp_path: Path, sample_position: Position) -> None:
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)
        loaded = repo.get("ACME")
        assert loaded == sample_position

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        repo = PositionRepository(base_path=tmp_path)
        assert repo.get("NOPE") is None

    def test_exists(self, tmp_path: Path, sample_position: Position) -> None:
        repo = PositionRepository(base_path=tmp_path)
        assert repo.exists("ACME") is False
        repo.save(sample_position)
        assert repo.exists("ACME") is True

    def test_list_keys(self, tmp_path: Path, sample_position: Position) -> None:
        repo = PositionRepository(base_path=tmp_path)
        assert repo.list_keys() == []
        repo.save(sample_position)
        assert repo.list_keys() == ["ACME"]

    def test_delete(self, tmp_path: Path, sample_position: Position) -> None:
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)
        repo.delete("ACME")
        assert repo.exists("ACME") is False

    def test_delete_missing_is_noop(self, tmp_path: Path) -> None:
        repo = PositionRepository(base_path=tmp_path)
        repo.delete("NOPE")  # must not raise

    def test_ticker_with_dot_is_normalised(self, tmp_path: Path, sample_position: Position) -> None:
        # Set ticker to include a dot, verify it's on disk as a hyphen
        sample_position.ticker = "ASML.AS"
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)
        assert (tmp_path / "ASML-AS.yaml").exists()
        assert repo.get("ASML-AS") is not None

    def test_corrupt_yaml_raises_storage_error(self, tmp_path: Path) -> None:
        repo = PositionRepository(base_path=tmp_path)
        (tmp_path / "BAD.yaml").write_text("not: valid: yaml: structure:")
        with pytest.raises(StorageError):
            repo.get("BAD")

    def test_get_key_without_ticker_raises(self, tmp_path: Path) -> None:
        """Verify the fallback path for entities without a ticker attribute."""
        from portfolio_thesis_engine.schemas.base import BaseSchema

        class _NoKey(BaseSchema):
            value: int

        repo: YAMLRepository[_NoKey] = YAMLRepository(_NoKey, tmp_path)
        with pytest.raises(NotImplementedError):
            repo.save(_NoKey(value=1))


# ============================================================
# CompanyRepository / PeerRepository / MarketContextRepository
# ============================================================


class TestCompanyRepository:
    def test_ficha_roundtrip(self, tmp_path: Path, sample_ficha: Ficha) -> None:
        repo = CompanyRepository(base_path=tmp_path)
        repo.save(sample_ficha)
        assert (tmp_path / "ACME" / "ficha.yaml").exists()
        assert repo.get("ACME") == sample_ficha

    def test_list_keys_only_companies_with_ficha(self, tmp_path: Path, sample_ficha: Ficha) -> None:
        repo = CompanyRepository(base_path=tmp_path)
        repo.save(sample_ficha)
        # Add an empty company dir — should not appear until a ficha exists
        (tmp_path / "EMPTY").mkdir()
        assert repo.list_keys() == ["ACME"]


class TestPeerRepository:
    def test_peer_under_parent(self, tmp_path: Path, sample_peer: Peer) -> None:
        repo = PeerRepository(parent_ticker="ACME", base_path=tmp_path)
        repo.save(sample_peer)
        assert (tmp_path / "ACME" / "peers" / "PEER.yaml").exists()
        assert repo.get("PEER") == sample_peer


class TestMarketContextRepository:
    def test_context_roundtrip(self, tmp_path: Path, sample_market_context: MarketContext) -> None:
        repo = MarketContextRepository(base_path=tmp_path)
        repo.save(sample_market_context)
        assert (tmp_path / "us_industrials" / "context.yaml").exists()
        assert repo.get("us_industrials") == sample_market_context

    def test_list_keys_scans_cluster_dirs(
        self, tmp_path: Path, sample_market_context: MarketContext
    ) -> None:
        repo = MarketContextRepository(base_path=tmp_path)
        repo.save(sample_market_context)
        (tmp_path / "empty_cluster").mkdir()
        assert repo.list_keys() == ["us_industrials"]


# ============================================================
# VersionedYAMLRepository — ValuationRepository + CompanyStateRepository
# ============================================================


class TestValuationRepository:
    def test_save_creates_version_file_and_current_symlink(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)

        version_file = (
            tmp_path / "ACME" / "valuation" / f"{sample_valuation_snapshot.snapshot_id}.yaml"
        )
        current = tmp_path / "ACME" / "valuation" / "current"
        assert version_file.exists()
        assert current.is_symlink()
        assert str(current.readlink()) == f"{sample_valuation_snapshot.snapshot_id}.yaml"

    def test_get_current_returns_latest(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)
        assert repo.get_current("ACME") == sample_valuation_snapshot
        # get() delegates to get_current for versioned repos
        assert repo.get("ACME") == sample_valuation_snapshot

    def test_list_versions(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)
        # Simulate a second snapshot for the same ticker
        second = sample_valuation_snapshot.model_copy(
            update={"snapshot_id": "val_2025_02_15_acme_002"}
        )
        repo.save(second)
        assert repo.list_versions("ACME") == [
            "val_2025_01_20_acme_001",
            "val_2025_02_15_acme_002",
        ]
        # After saving "second", current points to the second snapshot
        assert repo.get_current("ACME") == second

    def test_get_version_specific(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)
        v = repo.get_version("ACME", sample_valuation_snapshot.snapshot_id)
        assert v == sample_valuation_snapshot
        assert repo.get_version("ACME", "does_not_exist") is None

    def test_set_current_retargets(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)
        second = sample_valuation_snapshot.model_copy(
            update={"snapshot_id": "val_2025_02_15_acme_002"}
        )
        repo.save(second)
        # Roll back current to the first snapshot
        repo.set_current("ACME", "val_2025_01_20_acme_001")
        assert repo.get_current("ACME") == sample_valuation_snapshot

    def test_set_current_unknown_version_raises(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)
        with pytest.raises(NotFoundError):
            repo.set_current("ACME", "nope")

    def test_exists(self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        assert repo.exists("ACME") is False
        repo.save(sample_valuation_snapshot)
        assert repo.exists("ACME") is True

    def test_delete_removes_entire_subdir(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)
        repo.delete("ACME")
        assert not (tmp_path / "ACME" / "valuation").exists()
        assert repo.list_versions("ACME") == []

    def test_list_keys(self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot) -> None:
        repo = ValuationRepository(base_path=tmp_path)
        assert repo.list_keys() == []
        repo.save(sample_valuation_snapshot)
        assert repo.list_keys() == ["ACME"]


class TestCompanyStateRepository:
    def test_save_and_get_current(
        self, tmp_path: Path, sample_company_state: CanonicalCompanyState
    ) -> None:
        repo = CompanyStateRepository(base_path=tmp_path)
        repo.save(sample_company_state)
        assert (
            tmp_path / "ACME" / "extraction" / f"{sample_company_state.extraction_id}.yaml"
        ).exists()
        assert repo.get_current("ACME") == sample_company_state

    def test_multiple_extractions_independent(
        self, tmp_path: Path, sample_company_state: CanonicalCompanyState
    ) -> None:
        repo = CompanyStateRepository(base_path=tmp_path)
        repo.save(sample_company_state)
        second = sample_company_state.model_copy(
            update={"extraction_id": "ext_2025_03_15_acme_002"}
        )
        repo.save(second)
        assert sorted(repo.list_versions("ACME")) == sorted(
            [
                sample_company_state.extraction_id,
                "ext_2025_03_15_acme_002",
            ]
        )
        assert repo.get_current("ACME") == second


# ============================================================
# Atomic-write crash simulation via repo.save
# ============================================================


class TestVersionedSaveAtomicity:
    def test_save_crash_leaves_prior_current_intact(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        """If os.replace fails mid-save, the prior current must remain valid."""
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(sample_valuation_snapshot)

        # Attempt to save a second version but force a crash inside the
        # atomic-write of the version file.
        second = sample_valuation_snapshot.model_copy(
            update={"snapshot_id": "val_2025_02_15_acme_002"}
        )
        with (
            patch.object(
                Path,
                "replace",
                side_effect=RuntimeError("simulated crash"),
            ),
            pytest.raises(StorageError),
        ):
            repo.save(second)

        # The previously-current snapshot is still current, readable, and
        # equal to the original — corruption did not leak.
        assert repo.get_current("ACME") == sample_valuation_snapshot
