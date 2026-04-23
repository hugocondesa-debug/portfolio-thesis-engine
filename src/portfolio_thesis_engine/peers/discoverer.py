"""Phase 2 Sprint 3 — :class:`PeerDiscoverer`.

Loads (or creates) the ``peers.yaml`` file for a ticker, merges
FMP-sourced peer suggestions with the analyst's manual overrides,
preserves the ``included`` flag across FMP re-syncs, and persists back
to YAML. External provider is injected via the :class:`PeerProvider`
protocol so tests can use deterministic stubs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import yaml

from portfolio_thesis_engine.schemas.peers import PeerCompany, PeerSet
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker


class PeerProvider(Protocol):
    """Protocol for an external peer-discovery provider (FMP, EODHD,
    ...). Returns raw peer suggestions. Sprint 3 uses FMP in
    production; tests inject a stub that returns canned responses."""

    def fetch_peers(
        self, ticker: str
    ) -> tuple[str | None, str | None, list[PeerCompany]]:
        """Return ``(sector, industry, peers)``. Empty list ≡ no
        suggestions (analyst writes peers.yaml manually)."""


class _NoopPeerProvider:
    """Stub provider for environments without FMP configured.
    Returns no peers — analyst populates peers.yaml manually."""

    def fetch_peers(
        self, ticker: str
    ) -> tuple[str | None, str | None, list[PeerCompany]]:
        _ = ticker
        return None, None, []


class PeerDiscoverer:
    def __init__(
        self, provider: PeerProvider | None = None
    ) -> None:
        self.provider: PeerProvider = provider or _NoopPeerProvider()

    # ------------------------------------------------------------------
    def load_or_create(self, ticker: str) -> PeerSet:
        """Return the peers.yaml contents, generating from the provider
        when the file doesn't exist yet. Never auto-syncs if the file
        already exists — use :meth:`sync_with_provider` for explicit
        re-sync."""
        existing = self._load_yaml(ticker)
        if existing is not None:
            return existing
        return self._generate_fresh(ticker)

    def sync_with_provider(self, peer_set: PeerSet) -> PeerSet:
        """Refresh FMP-sourced peers, preserving user overrides and
        previously-set ``included`` flags."""
        prior_flags = {
            p.ticker: p.included for p in peer_set.peers
        }
        user_overrides = [
            p for p in peer_set.peers if p.source == "USER_OVERRIDE"
        ]
        sector, industry, fmp_peers = self.provider.fetch_peers(
            peer_set.target_ticker
        )
        refreshed: list[PeerCompany] = list(user_overrides)
        for fmp in fmp_peers:
            # Preserve the analyst's previous include/exclude decision.
            included = prior_flags.get(fmp.ticker, fmp.included)
            refreshed.append(
                fmp.model_copy(update={"included": included, "source": "FMP_AUTO"})
            )
        return peer_set.model_copy(
            update={
                "peers": refreshed[: peer_set.max_peers_display],
                "fmp_sector": sector or peer_set.fmp_sector,
                "fmp_industry": industry or peer_set.fmp_industry,
                "last_fmp_sync": datetime.now(UTC),
                "discovery_method": (
                    "HYBRID" if user_overrides else "FMP_AUTO"
                ),
            }
        )

    def save(self, peer_set: PeerSet) -> Path:
        path = self._yaml_path(peer_set.target_ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = peer_set.model_dump(mode="json")
        with path.open("w") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False)
        return path

    # ------------------------------------------------------------------
    def _generate_fresh(self, ticker: str) -> PeerSet:
        sector, industry, fmp_peers = self.provider.fetch_peers(ticker)
        method = "FMP_AUTO" if fmp_peers else "USER_MANUAL"
        return PeerSet(
            target_ticker=ticker,
            peers=fmp_peers,
            discovery_method=method,  # type: ignore[arg-type]
            fmp_sector=sector,
            fmp_industry=industry,
            generated_at=datetime.now(UTC),
            last_fmp_sync=datetime.now(UTC) if fmp_peers else None,
        )

    def _yaml_path(self, ticker: str) -> Path:
        return (
            settings.data_dir
            / "yamls"
            / "companies"
            / normalise_ticker(ticker)
            / "peers.yaml"
        )

    def _load_yaml(self, ticker: str) -> PeerSet | None:
        path = self._yaml_path(ticker)
        if not path.exists():
            return None
        with path.open() as fh:
            payload = yaml.safe_load(fh) or {}
        return PeerSet.model_validate(payload)


__all__ = ["PeerDiscoverer", "PeerProvider"]
