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
    normalise_ticker,
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

    def test_save_then_get_dotted_ticker_roundtrips(
        self, tmp_path: Path, sample_position: Position
    ) -> None:
        """Regression guard: ``save(entity)`` + ``get(entity.ticker)`` must round-trip
        even when the ticker contains a ``.`` (which the filesystem layer normalises to ``-``)."""
        sample_position.ticker = "TEST.L"
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)

        hit_dotted = repo.get("TEST.L")
        hit_normalised = repo.get("TEST-L")
        assert hit_dotted is not None, "get('TEST.L') must find the saved entity"
        assert hit_normalised == hit_dotted, "dotted and normalised lookups must agree"
        assert repo.exists("TEST.L") is True
        assert repo.exists("TEST-L") is True
        repo.delete("TEST.L")
        assert repo.exists("TEST.L") is False

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

    def test_save_then_get_dotted_ticker_roundtrips(
        self, tmp_path: Path, sample_ficha: Ficha
    ) -> None:
        """Exact scenario that failed in Hugo's manual smoke test:
        save a Ficha with ``ticker='TEST.L'`` then retrieve it via the same
        dotted ticker. Bug was that save normalised but get did not."""
        dotted = sample_ficha.model_copy(
            update={
                "ticker": "TEST.L",
                "identity": sample_ficha.identity.model_copy(update={"ticker": "TEST.L"}),
            }
        )
        repo = CompanyRepository(base_path=tmp_path)
        repo.save(dotted)

        # File lands at the normalised path
        assert (tmp_path / "TEST-L" / "ficha.yaml").exists()
        # Both lookup forms must resolve
        assert repo.get("TEST.L") == dotted
        assert repo.get("TEST-L") == dotted
        assert repo.exists("TEST.L") is True


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
    def test_save_then_get_dotted_ticker_roundtrips(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        """Versioned variant of the ticker-normalisation regression guard."""
        snap = sample_valuation_snapshot.model_copy(update={"ticker": "BRK.B"})
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(snap)

        assert (tmp_path / "BRK-B" / "valuation" / "current").is_symlink()
        assert repo.get_current("BRK.B") == snap
        assert repo.get_current("BRK-B") == snap
        assert repo.list_versions("BRK.B") == [snap.snapshot_id]
        repo.set_current("BRK.B", snap.snapshot_id)  # must not raise

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


# ============================================================
# Ticker normalisation — explicit contract tests
#
# Every ticker-keyed repository must honour the storage.base contract:
# callers may pass either the dotted form (``TEST.L``) or the hyphenated
# form (``TEST-L``); both resolve to the same on-disk/in-DB entity. The
# transform is idempotent. These tests guard against the asymmetric
# save/get bug that would otherwise leave files orphaned on disk.
# ============================================================


class TestNormaliseTickerHelper:
    def test_converts_dot_to_hyphen(self) -> None:
        assert normalise_ticker("TEST.L") == "TEST-L"
        assert normalise_ticker("ASML.AS") == "ASML-AS"
        assert normalise_ticker("BRK.B") == "BRK-B"

    def test_already_hyphenated_is_unchanged(self) -> None:
        assert normalise_ticker("TEST-L") == "TEST-L"
        assert normalise_ticker("BRK-B") == "BRK-B"

    def test_no_dot_no_hyphen_is_unchanged(self) -> None:
        assert normalise_ticker("AAPL") == "AAPL"

    def test_idempotent(self) -> None:
        """normalise_ticker(normalise_ticker(x)) == normalise_ticker(x)."""
        for ticker in ("TEST.L", "TEST-L", "BRK.B", "9988.HK", "AAPL"):
            once = normalise_ticker(ticker)
            twice = normalise_ticker(once)
            assert once == twice, f"not idempotent for {ticker!r}"

    def test_both_forms_normalise_to_same(self) -> None:
        """The regression Hugo flagged: ``TEST.L`` and ``TEST-L`` must
        collapse to one canonical key."""
        assert normalise_ticker("TEST-L") == normalise_ticker("TEST.L") == "TEST-L"


class TestYAMLRepositoryTickerNormalisation:
    """Symmetric CRUD across dotted / hyphenated ticker forms for the
    simple (non-versioned) ticker-keyed repositories."""

    def test_save_get_roundtrip_with_dotted_ticker(
        self, tmp_path: Path, sample_position: Position
    ) -> None:
        sample_position.ticker = "ACME.L"
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)
        loaded = repo.get("ACME.L")
        assert loaded is not None
        assert loaded == sample_position

    def test_save_get_roundtrip_with_normalized_ticker(
        self, tmp_path: Path, sample_position: Position
    ) -> None:
        """save with the dotted form, get with the hyphenated form still works."""
        sample_position.ticker = "ACME.L"
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)
        loaded = repo.get("ACME-L")
        assert loaded is not None
        assert loaded == sample_position

    def test_delete_with_dotted_ticker_removes_file(
        self, tmp_path: Path, sample_position: Position
    ) -> None:
        sample_position.ticker = "ACME.L"
        repo = PositionRepository(base_path=tmp_path)
        repo.save(sample_position)
        assert (tmp_path / "ACME-L.yaml").exists()
        repo.delete("ACME.L")
        assert not (tmp_path / "ACME-L.yaml").exists()
        assert repo.exists("ACME.L") is False
        assert repo.exists("ACME-L") is False

    def test_exists_with_both_formats(self, tmp_path: Path, sample_position: Position) -> None:
        sample_position.ticker = "ACME.L"
        repo = PositionRepository(base_path=tmp_path)
        assert repo.exists("ACME.L") is False
        assert repo.exists("ACME-L") is False
        repo.save(sample_position)
        assert repo.exists("ACME.L") is True
        assert repo.exists("ACME-L") is True

    def test_company_repository_hugo_smoke_scenario(
        self, tmp_path: Path, sample_ficha: Ficha
    ) -> None:
        """The exact sequence Hugo ran manually that previously failed:
        save(ficha with ticker='TEST.L') → get('TEST.L') must return the ficha."""
        dotted = sample_ficha.model_copy(
            update={
                "ticker": "TEST.L",
                "identity": sample_ficha.identity.model_copy(update={"ticker": "TEST.L"}),
            }
        )
        repo = CompanyRepository(base_path=tmp_path)
        repo.save(dotted)
        assert (tmp_path / "TEST-L" / "ficha.yaml").exists()
        assert repo.get("TEST.L") == dotted
        assert repo.get("TEST-L") == dotted
        assert repo.exists("TEST.L") is True


class TestVersionedRepositoryTickerNormalisation:
    """Same symmetric-CRUD contract applied to versioned repositories —
    every public method (save / get / get_current / get_version /
    list_versions / exists / delete / set_current) must tolerate both
    ticker forms."""

    def test_valuation_save_and_all_lookups_with_dotted_ticker(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        snap = sample_valuation_snapshot.model_copy(update={"ticker": "ACME.L"})
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(snap)

        # Every ticker-keyed method must resolve via either form.
        for form in ("ACME.L", "ACME-L"):
            assert repo.get(form) == snap
            assert repo.get_current(form) == snap
            assert repo.exists(form) is True
            assert repo.list_versions(form) == [snap.snapshot_id]
            assert repo.get_version(form, snap.snapshot_id) == snap
        # set_current with the dotted form resolves the same version file.
        repo.set_current("ACME.L", snap.snapshot_id)

    def test_valuation_delete_with_dotted_ticker_removes_subdir(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        """Previously a real bug: VersionedYAMLRepository.delete used raw
        `base_path / key / subdir` without normalisation, so
        delete('ACME.L') silently missed the real on-disk directory."""
        snap = sample_valuation_snapshot.model_copy(update={"ticker": "ACME.L"})
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(snap)
        assert (tmp_path / "ACME-L" / "valuation").exists()
        repo.delete("ACME.L")
        assert not (tmp_path / "ACME-L" / "valuation").exists()
        assert repo.exists("ACME.L") is False

    def test_company_state_save_and_lookups_with_dotted_ticker(
        self, tmp_path: Path, sample_company_state: CanonicalCompanyState
    ) -> None:
        state = sample_company_state.model_copy(
            update={
                "identity": sample_company_state.identity.model_copy(update={"ticker": "ACME.L"})
            }
        )
        repo = CompanyStateRepository(base_path=tmp_path)
        repo.save(state)
        assert repo.get_current("ACME.L") == state
        assert repo.get_current("ACME-L") == state
        assert repo.exists("ACME.L") is True
        repo.delete("ACME.L")
        assert repo.exists("ACME.L") is False

    def test_set_current_with_dotted_ticker(
        self, tmp_path: Path, sample_valuation_snapshot: ValuationSnapshot
    ) -> None:
        snap_v1 = sample_valuation_snapshot.model_copy(update={"ticker": "ACME.L"})
        repo = ValuationRepository(base_path=tmp_path)
        repo.save(snap_v1)
        snap_v2 = snap_v1.model_copy(update={"snapshot_id": "val_v2"})
        repo.save(snap_v2)
        # Now roll back via the dotted form.
        repo.set_current("ACME.L", snap_v1.snapshot_id)
        assert repo.get_current("ACME.L") == snap_v1
