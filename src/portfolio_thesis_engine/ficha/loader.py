"""FichaLoader — convenience wrapper that fetches everything about a
ticker in one call.

:class:`FichaBundle` packs :class:`Ficha` + :class:`CanonicalCompanyState`
+ :class:`ValuationSnapshot` so UI / CLI renderers can fan out to the
sub-views without re-querying the repositories.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.valuation import ValuationSnapshot
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    ValuationRepository,
)


@dataclass(frozen=True)
class FichaBundle:
    """Everything a Ficha view needs in one struct.

    Any of the three fields can be ``None`` — downstream renderers
    should handle missing data gracefully (e.g., no valuation yet,
    ticker processed but ficha not saved).
    """

    ticker: str
    ficha: Ficha | None
    canonical_state: CanonicalCompanyState | None
    valuation_snapshot: ValuationSnapshot | None

    @property
    def has_data(self) -> bool:
        """True when at least the canonical state is available — the
        minimum the UI needs to render anything."""
        return self.canonical_state is not None


class FichaLoader:
    """Load the full :class:`FichaBundle` for a ticker from the three
    YAML repositories.

    Repositories are injected so tests can feed in-memory stubs; the
    default constructor wires the on-disk defaults.
    """

    def __init__(
        self,
        company_repo: CompanyRepository | None = None,
        state_repo: CompanyStateRepository | None = None,
        valuation_repo: ValuationRepository | None = None,
    ) -> None:
        self.company_repo = company_repo or CompanyRepository()
        self.state_repo = state_repo or CompanyStateRepository()
        self.valuation_repo = valuation_repo or ValuationRepository()

    # ------------------------------------------------------------------
    def load(self, ticker: str) -> FichaBundle:
        """Return a :class:`FichaBundle` for ``ticker``.

        Never raises on missing data — a fresh ticker with no saved
        ficha yet still returns a bundle with ``ficha=None``.
        """
        return FichaBundle(
            ticker=ticker,
            ficha=self.company_repo.get(ticker),
            canonical_state=self.state_repo.get(ticker),
            valuation_snapshot=self.valuation_repo.get(ticker),
        )

    # ------------------------------------------------------------------
    def list_tickers(self) -> list[str]:
        """Return every ticker that has at least a saved ficha or a
        canonical state. Used by the UI for the ticker selector."""
        seen: set[str] = set()
        for repo in (self.company_repo, self.state_repo, self.valuation_repo):
            try:
                seen.update(repo.list_keys())
            except Exception:
                # Robustness: don't let a single repo failure kill the
                # list. The UI surfaces an empty list in that case.
                continue
        return sorted(seen)
