"""Unit tests for storage/sqlite_repo.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_thesis_engine.storage.base import NotFoundError
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository


@pytest.fixture
def repo(tmp_path: Path) -> MetadataRepository:
    return MetadataRepository(db_path=tmp_path / "meta.sqlite")


class TestCompanies:
    def test_add_and_get(self, repo: MetadataRepository) -> None:
        repo.add_company("ACME", "Acme Industrial", "P1", "USD", "NYSE", isin="US0001")
        c = repo.get_company("ACME")
        assert c is not None
        assert c.ticker == "ACME"
        assert c.profile == "P1"
        assert c.isin == "US0001"

    def test_get_missing_returns_none(self, repo: MetadataRepository) -> None:
        assert repo.get_company("NOPE") is None

    def test_add_is_idempotent(self, repo: MetadataRepository) -> None:
        repo.add_company("ACME", "Acme", "P1", "USD", "NYSE")
        repo.add_company("ACME", "Acme Industrial Renamed", "P1", "USD", "NYSE")
        assert repo.get_company("ACME").name == "Acme Industrial Renamed"

    def test_list_sorted(self, repo: MetadataRepository) -> None:
        repo.add_company("ZEBRA", "Z", "P1", "USD", "NYSE")
        repo.add_company("ACME", "A", "P1", "USD", "NYSE")
        assert [c.ticker for c in repo.list_companies()] == ["ACME", "ZEBRA"]


class TestArchetypes:
    def test_add_and_get(self, repo: MetadataRepository) -> None:
        repo.add_archetype("P1", "Industrial", "Capital-heavy industrial companies")
        row = repo.get_archetype("P1")
        assert row is not None
        assert row.name == "Industrial"


class TestClustersAndJoins:
    def test_link_and_list(self, repo: MetadataRepository) -> None:
        repo.add_company("ACME", "Acme", "P1", "USD", "NYSE")
        repo.add_company("PEER", "Peer", "P1", "USD", "NYSE")
        repo.add_cluster("us_industrials", "US Industrials")
        repo.link_company_to_cluster("ACME", "us_industrials")
        repo.link_company_to_cluster("PEER", "us_industrials")
        assert repo.list_companies_in_cluster("us_industrials") == ["ACME", "PEER"]

    def test_link_unknown_company_raises(self, repo: MetadataRepository) -> None:
        repo.add_cluster("foo", "Foo")
        with pytest.raises(NotFoundError):
            repo.link_company_to_cluster("UNKNOWN", "foo")

    def test_link_unknown_cluster_raises(self, repo: MetadataRepository) -> None:
        repo.add_company("ACME", "Acme", "P1", "USD", "NYSE")
        with pytest.raises(NotFoundError):
            repo.link_company_to_cluster("ACME", "unknown_cluster")

    def test_empty_cluster_returns_empty_list(self, repo: MetadataRepository) -> None:
        assert repo.list_companies_in_cluster("empty") == []


class TestPeers:
    def test_add_and_list(self, repo: MetadataRepository) -> None:
        repo.add_company("ACME", "Acme", "P1", "USD", "NYSE")
        repo.add_peer("ACME", "PEER1", "A")
        repo.add_peer("ACME", "PEER2", "C")
        peers = repo.list_peers("ACME")
        assert [p.peer_ticker for p in peers] == ["PEER1", "PEER2"]
        assert [p.extraction_level for p in peers] == ["A", "C"]

    def test_add_peer_for_unknown_company_raises(self, repo: MetadataRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.add_peer("GHOST", "PEER", "C")
