"""Phase 1.5.10.1 regression tests — display scope + parent-aware
defaults. 7 tests per the 1.5.10.1 scope doc.

Part A — Display filter (3 tests):
- ``test_display_filter_skips_revenue_in_sustainable_oi_table``
- ``test_display_filter_skips_finance_in_sustainable_oi_table``
- ``test_display_includes_operating_section_items``

Part B — Parent-aware classification (3 tests):
- ``test_parent_aware_default_revenue_parent``
- ``test_parent_aware_default_does_not_override_explicit_classification``
- ``test_non_operating_parent_no_default_applied``

Skeleton gen (1 test):
- ``test_skeleton_generation_uses_parent_aware_defaults``
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console

from portfolio_thesis_engine.cli import generate_overrides_cmd, show_cmd
from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.module_d import ModuleD
from portfolio_thesis_engine.ficha import FichaBundle
from portfolio_thesis_engine.schemas.common import Currency, FiscalPeriod, Profile
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    CanonicalCompanyState,
    CompanyIdentity,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    ModuleAdjustment,
    NOPATBridge,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.decomposition import LineDecomposition, SubItem

from .conftest import build_raw, make_context


def _op_tax(rate: str = "25") -> ModuleAdjustment:
    return ModuleAdjustment(
        module="A.1",
        description="op tax rate",
        amount=Decimal(rate),
        affected_periods=[FiscalPeriod(year=2024, label="FY2024")],
        rationale="",
    )


def _build_bundle_with_decomps(decomps: dict[str, LineDecomposition]) -> FichaBundle:
    """Minimal canonical state wrapping the provided decompositions."""
    period = FiscalPeriod(year=2024, label="FY2024")
    state = CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=CompanyIdentity(
            ticker="TST",
            name="Test Co",
            reporting_currency=Currency.USD,
            profile=Profile.P1_INDUSTRIAL,
            fiscal_year_end_month=12,
            country_domicile="US",
            exchange="NYSE",
            shares_outstanding=Decimal("100"),
        ),
        reclassified_statements=[],
        adjustments=AdjustmentsApplied(module_d_note_decompositions=decomps),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("100"),
                    operating_liabilities=Decimal("0"),
                    invested_capital=Decimal("100"),
                    financial_assets=Decimal("0"),
                    financial_liabilities=Decimal("0"),
                    equity_claims=Decimal("100"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=Decimal("0"),
                    operating_taxes=Decimal("0"),
                    nopat=Decimal("0"),
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("0"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=Decimal("0"),
                )
            ],
            ratios_by_period=[KeyRatios(period=period)],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.0", name="s", status="PASS", detail="ok"
                )
            ],
            profile_specific_checksums=[],
            confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test",
            profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=[],
        ),
    )
    return FichaBundle(
        ticker="TST",
        canonical_state=state,
        valuation_snapshot=None,
        ficha=None,
    )


def _render(bundle: FichaBundle, monkeypatch: pytest.MonkeyPatch) -> str:
    buf = io.StringIO()
    test_console = Console(file=buf, width=300, record=True)
    monkeypatch.setattr(show_cmd, "console", test_console)
    tables = show_cmd._sustainable_oi_derivation_tables(bundle)
    for t in tables:
        test_console.print(t)
    return buf.getvalue()


# ======================================================================
# Part A — Display filter (3 tests)
# ======================================================================


class TestDisplayFilter:
    def _flagged_sub(self, label: str, value: str) -> SubItem:
        return SubItem(
            label=label,
            value=Decimal(value),
            operational_classification="ambiguous",
            recurrence_classification="ambiguous",
            action="flag_for_review",
            matched_rule="regex:ambiguous+ambiguous",
            rationale="",
            confidence="low",
        )

    def test_display_filter_skips_revenue_in_sustainable_oi_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        decomps = {
            "IS:Revenue": LineDecomposition(
                parent_statement="IS",
                parent_label="Revenue",
                parent_value=Decimal("1000"),
                method="note_table",
                confidence="medium",
                sub_items=[self._flagged_sub("Vision correction services", "700")],
            ),
        }
        bundle = _build_bundle_with_decomps(decomps)
        rendered = _render(bundle, monkeypatch)
        # Revenue is outside the non-recurring-candidate gate, so the
        # derivation section skips it entirely.
        assert "Vision correction services" not in rendered
        assert "Sustainable OI derivation · Revenue" not in rendered

    def test_display_filter_skips_finance_in_sustainable_oi_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        decomps = {
            "IS:Finance income": LineDecomposition(
                parent_statement="IS",
                parent_label="Finance income",
                parent_value=Decimal("50"),
                method="note_table",
                confidence="medium",
                sub_items=[self._flagged_sub("Interest on bank deposits", "50")],
            ),
            "IS:Finance expenses": LineDecomposition(
                parent_statement="IS",
                parent_label="Finance expenses",
                parent_value=Decimal("-20"),
                method="note_table",
                confidence="medium",
                sub_items=[self._flagged_sub("Lease interest", "-20")],
            ),
        }
        bundle = _build_bundle_with_decomps(decomps)
        rendered = _render(bundle, monkeypatch)
        # Finance lines are below OP, outside the sustainable-OI scope.
        assert "Interest on bank deposits" not in rendered
        assert "Lease interest" not in rendered

    def test_display_includes_operating_section_items(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        decomps = {
            # "Other gains, net" matches _NON_RECURRING_OP → in scope.
            "IS:Other gains, net": LineDecomposition(
                parent_statement="IS",
                parent_label="Other gains, net",
                parent_value=Decimal("26"),
                method="note_table",
                confidence="medium",
                sub_items=[
                    SubItem(
                        label="Government subsidy",
                        value=Decimal("8"),
                        operational_classification="operational",
                        recurrence_classification="recurring",
                        action="include",
                        matched_rule="regex:operational+recurring",
                        rationale="",
                        confidence="medium",
                    ),
                    SubItem(
                        label="Fair value gain on contingent consideration",
                        value=Decimal("15"),
                        operational_classification="non_operational",
                        recurrence_classification="non_recurring",
                        action="exclude",
                        matched_rule="regex:non_operational+non_recurring",
                        rationale="",
                        confidence="high",
                    ),
                ],
            ),
        }
        bundle = _build_bundle_with_decomps(decomps)
        rendered = _render(bundle, monkeypatch)
        # In-scope parent is displayed.
        assert "Sustainable OI derivation · Other gains, net" in rendered
        assert "Government subsidy" in rendered
        assert "Fair value gain on contingent consideration" in rendered


# ======================================================================
# Part B — Parent-aware classification (3 tests)
# ======================================================================


class TestParentAwareClassification:
    def test_parent_aware_default_revenue_parent(self) -> None:
        """Sub-item with no regex match but parent = Revenue defaults
        to operational × recurring, action=include, confidence=medium."""
        sub = ModuleD().classify_sub_item(
            label="Vision correction services",
            value=Decimal("710"),
            parent_label="Revenue",
        )
        assert sub.operational_classification == "operational"
        assert sub.recurrence_classification == "recurring"
        assert sub.action == "include"
        assert sub.confidence == "medium"
        assert sub.matched_rule.startswith("parent_aware_default:")

    def test_parent_aware_default_does_not_override_explicit_classification(
        self,
    ) -> None:
        """When an explicit pattern matches (e.g. "Gain on disposal"),
        the parent-aware default must NOT override it — even if the
        parent is Revenue-like."""
        sub = ModuleD().classify_sub_item(
            label="Gain on disposal of equipment",
            value=Decimal("5"),
            parent_label="Other operating income",  # revenue-ish
        )
        # Explicit non-operational + non-recurring wins.
        assert sub.operational_classification == "non_operational"
        assert sub.recurrence_classification == "non_recurring"
        assert sub.action == "exclude"
        assert "parent_aware_default" not in sub.matched_rule

    def test_non_operating_parent_no_default_applied(self) -> None:
        """Ambiguous sub-item under a non-revenue parent stays
        ambiguous → flag_for_review (conservative)."""
        sub = ModuleD().classify_sub_item(
            label="Miscellaneous",
            value=Decimal("1"),
            parent_label="Finance income",  # not revenue-like
        )
        assert sub.operational_classification == "ambiguous"
        assert sub.recurrence_classification == "ambiguous"
        assert sub.action == "flag_for_review"

    def test_no_parent_label_provided_stays_ambiguous(self) -> None:
        """Calling classify_sub_item with parent_label=None (e.g.
        label_fallback path) still goes through the ambiguous branch."""
        sub = ModuleD().classify_sub_item(
            label="Miscellaneous", value=Decimal("1")
        )
        assert sub.action == "flag_for_review"


# ======================================================================
# Skeleton generation (1 test)
# ======================================================================


class TestSkeletonGeneration:
    def test_skeleton_generation_uses_parent_aware_defaults(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After parent-aware defaults fire, revenue sub-items have
        action=include (not flag_for_review), so the skeleton template
        no longer lists them — only genuinely ambiguous items show up.
        """
        # Build a state with one revenue sub-item (now include via
        # parent-aware) and one genuinely ambiguous one.
        revenue_sub = SubItem(
            label="Vision correction services",
            value=Decimal("710"),
            operational_classification="operational",
            recurrence_classification="recurring",
            action="include",
            matched_rule="parent_aware_default:Revenue",
            rationale="Sub-item of revenue-like parent.",
            confidence="medium",
        )
        ambiguous_sub = SubItem(
            label="Miscellaneous other",
            value=Decimal("5"),
            operational_classification="ambiguous",
            recurrence_classification="ambiguous",
            action="flag_for_review",
            matched_rule="regex:ambiguous+ambiguous",
            rationale="",
            confidence="low",
        )

        class _StubState:
            def __init__(self) -> None:
                self.adjustments = AdjustmentsApplied(
                    module_d_note_decompositions={
                        "IS:Revenue": LineDecomposition(
                            parent_statement="IS",
                            parent_label="Revenue",
                            parent_value=Decimal("710"),
                            method="note_table",
                            confidence="medium",
                            sub_items=[revenue_sub],
                        ),
                        "IS:Other gains, net": LineDecomposition(
                            parent_statement="IS",
                            parent_label="Other gains, net",
                            parent_value=Decimal("5"),
                            method="note_table",
                            confidence="low",
                            sub_items=[ambiguous_sub],
                        ),
                    }
                )

        class _StubRepo:
            def load_latest(self, ticker: str) -> object:
                return _StubState()

        monkeypatch.setattr(
            generate_overrides_cmd,
            "CompanyStateRepository",
            lambda base_path: _StubRepo(),
        )
        out_path = tmp_path / "template.yaml"
        generate_overrides_cmd.generate_overrides(
            ticker="TST",
            output=out_path,
        )
        content = out_path.read_text(encoding="utf-8")
        # Revenue sub-item (parent_aware_default, action=include) NOT in
        # the template — nothing to flag.
        assert "Vision correction services" not in content
        # Genuinely ambiguous item IS in the template.
        assert "Miscellaneous other" in content


# ======================================================================
# Bonus: end-to-end EuroEyes-style revenue flow stays math-equivalent
# ======================================================================


class TestEuroEyesStyleRegression:
    def test_revenue_sub_items_now_classified_operational_recurring(
        self, wacc_inputs
    ) -> None:
        """With parent-aware defaults, Revenue sub-items get
        operational × recurring labels — without affecting the
        sustainable OI math (Revenue was never in scope anyway)."""
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000", "source_note": "2"},
            {"order": 2, "label": "Operating profit", "value": "200",
             "is_subtotal": True},
            {"order": 3, "label": "Profit for the year", "value": "140",
             "is_subtotal": True},
        ]
        notes = [
            {
                "note_number": "2",
                "title": "Revenue",
                "tables": [
                    {
                        "table_label": "Revenue breakdown 2024",
                        "columns": ["Item", "Total"],
                        "rows": [
                            ["Vision correction services", "700"],
                            ["Training services", "200"],
                            ["Pharmaceutical sales", "100"],
                        ],
                    }
                ],
            }
        ]
        raw = build_raw(is_lines=is_lines, notes=notes)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax("25"))
        decomps = ModuleD().decompose_all(raw)
        key = "IS:Revenue"
        revenue_decomp = decomps[key]
        # All three sub-items default to op+rec via parent-aware rule.
        for sub in revenue_decomp.sub_items:
            assert sub.operational_classification == "operational"
            assert sub.recurrence_classification == "recurring"
            assert sub.action == "include"

        # Math unchanged: Revenue isn't in sustainable-OI scope, so the
        # NOPAT bridge doesn't subtract anything.
        analysis = AnalysisDeriver().derive(ctx, decompositions=decomps)
        bridge = analysis.nopat_bridge_by_period[0]
        assert bridge.non_recurring_operating_items == Decimal("0")
        assert bridge.operating_income == Decimal("200")
