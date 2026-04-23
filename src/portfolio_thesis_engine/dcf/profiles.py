"""Phase 2 Sprint 4A-alpha Part A — profile taxonomy.

:func:`infer_profile_from_industry` maps a GICS-style industry / sector
label to a default :class:`DCFProfile` + confidence. Analysts can
override in ``data/yamls/companies/<ticker>/valuation_profile.yaml``;
:func:`load_valuation_profile` is the canonical accessor and records
whether the final choice came from the heuristic or the override.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from portfolio_thesis_engine.dcf.schemas import (
    DCFProfile,
    ProfileHeuristic,
    ProfileSelection,
    ValuationProfile,
)
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker


# ----------------------------------------------------------------------
# Heuristic mapping
# ----------------------------------------------------------------------
# Keyword → (profile, confidence). Matched case-insensitively against
# the industry / sector string. Earlier entries take precedence.
_INDUSTRY_HEURISTICS: tuple[tuple[str, DCFProfile, str], ...] = (
    # P2 — financials (HIGH confidence)
    ("bank", DCFProfile.P2_FINANCIAL, "HIGH"),
    ("insurance", DCFProfile.P2_FINANCIAL, "HIGH"),
    ("capital markets", DCFProfile.P2_FINANCIAL, "HIGH"),
    ("diversified financial", DCFProfile.P2_FINANCIAL, "MEDIUM"),
    # P3 — REITs / real estate (HIGH)
    ("reit", DCFProfile.P3_REIT, "HIGH"),
    ("real estate", DCFProfile.P3_REIT, "HIGH"),
    # P4 — cyclical / commodity (HIGH for obvious cases)
    ("oil", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("gas", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("energy equipment", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("metals", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("mining", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("auto", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("airline", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("shipping", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("homebuilder", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("building products", DCFProfile.P4_CYCLICAL_COMMODITY, "MEDIUM"),
    ("paper", DCFProfile.P4_CYCLICAL_COMMODITY, "MEDIUM"),
    ("forest products", DCFProfile.P4_CYCLICAL_COMMODITY, "MEDIUM"),
    ("chemicals (basic)", DCFProfile.P4_CYCLICAL_COMMODITY, "HIGH"),
    ("semiconductor", DCFProfile.P4_CYCLICAL_COMMODITY, "LOW"),
    # P5 — high-growth / pre-revenue (MEDIUM; analyst should confirm)
    ("biotech", DCFProfile.P5_HIGH_GROWTH, "MEDIUM"),
    ("clean energy", DCFProfile.P5_HIGH_GROWTH, "LOW"),
    # P6 — mature stable (HIGH for regulated utilities / staples)
    ("utilities", DCFProfile.P6_MATURE_STABLE, "HIGH"),
    ("utility", DCFProfile.P6_MATURE_STABLE, "HIGH"),
    ("consumer staples", DCFProfile.P6_MATURE_STABLE, "MEDIUM"),
    ("tobacco", DCFProfile.P6_MATURE_STABLE, "HIGH"),
    # P1 — default industrial/services (catch-all MEDIUM unless more
    # specific above). Healthcare, software, tech hardware, consumer
    # services all fall here in the absence of a more specific match.
    ("healthcare services", DCFProfile.P1_INDUSTRIAL_SERVICES, "HIGH"),
    ("health care services", DCFProfile.P1_INDUSTRIAL_SERVICES, "HIGH"),
    ("health care equipment", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("medical care", DCFProfile.P1_INDUSTRIAL_SERVICES, "HIGH"),
    ("pharma", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("software", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("it services", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("technology hardware", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("communication services", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("consumer services", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("restaurants", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("education", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("industrial services", DCFProfile.P1_INDUSTRIAL_SERVICES, "HIGH"),
    ("industrial machinery", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
    ("healthcare", DCFProfile.P1_INDUSTRIAL_SERVICES, "MEDIUM"),
)


def infer_profile_from_industry(
    industry: str | None,
    *,
    sector: str | None = None,
    sic_code: str | None = None,
) -> ProfileHeuristic:
    """Return a :class:`ProfileHeuristic` suggestion. Falls back to
    ``P1`` MEDIUM when nothing matches — the safest default for a
    typical operating company and the one Sprint 4A-alpha actually
    implements."""
    haystack = " ".join(
        filter(None, (industry, sector))
    ).lower()
    for keyword, profile, confidence in _INDUSTRY_HEURISTICS:
        if keyword in haystack:
            return ProfileHeuristic(
                sic_code=sic_code,
                gics_sector=sector,
                gics_industry=industry,
                suggested_profile=profile,
                confidence=confidence,  # type: ignore[arg-type]
                rationale=(
                    f"Matched industry keyword '{keyword}' → "
                    f"{profile.value}."
                ),
            )
    return ProfileHeuristic(
        sic_code=sic_code,
        gics_sector=sector,
        gics_industry=industry,
        suggested_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
        confidence="LOW",
        rationale=(
            "No specific industry/sector match; defaulting to P1 "
            "industrial/services (analyst should confirm)."
        ),
    )


# ----------------------------------------------------------------------
# YAML loader
# ----------------------------------------------------------------------
def _yaml_path(ticker: str) -> Path:
    return (
        settings.data_dir
        / "yamls"
        / "companies"
        / normalise_ticker(ticker)
        / "valuation_profile.yaml"
    )


def load_valuation_profile(
    ticker: str, *, fallback_industry: str | None = None
) -> ValuationProfile:
    """Load ``valuation_profile.yaml`` for ``ticker``. If the file is
    absent, synthesise a profile using :func:`infer_profile_from_industry`
    with ``fallback_industry`` (or ``None`` → defaults to P1)."""
    path = _yaml_path(ticker)
    if path.exists():
        with path.open() as fh:
            payload = yaml.safe_load(fh) or {}
        return ValuationProfile.model_validate(payload)
    heuristic = infer_profile_from_industry(fallback_industry)
    return ValuationProfile(
        target_ticker=ticker,
        profile=ProfileSelection(
            code=heuristic.suggested_profile,
            source="HEURISTIC_SUGGESTION",
            heuristic_suggestion=heuristic.suggested_profile,
            confidence=heuristic.confidence,
            rationale=heuristic.rationale,
        ),
    )


__all__ = [
    "infer_profile_from_industry",
    "load_valuation_profile",
]
