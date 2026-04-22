"""Phase 1.5.10 regression tests — Module D universal note decomposer.

16 tests per the Phase 1.5.10 scope doc:

Decomposition paths:
- ``test_module_d_decomposes_other_gains_from_note_table``
- ``test_module_d_fallback_when_no_note_reference``
- ``test_module_d_fallback_when_note_has_no_matching_table``

Sub-item classification:
- ``test_sub_item_classification_operational_recurring_includes``
- ``test_sub_item_classification_non_operational_excludes``
- ``test_sub_item_classification_ambiguous_flags``

Overrides + CLI:
- ``test_overrides_file_loaded``
- ``test_override_precedence_over_regex``
- ``test_skeleton_generation_creates_template``

Analysis consumption:
- ``test_sustainable_margin_uses_module_d_when_available``
- ``test_sustainable_margin_falls_back_to_regex_when_no_decomposition``
- ``test_nopat_bridge_preserves_backward_compat``

Display:
- ``test_show_detail_renders_decomposition_section``
- ``test_show_detail_renders_coverage_section``

Pipeline:
- ``test_decompose_notes_pipeline_stage_ok``
- ``test_decompose_notes_pipeline_warn_high_fallback_rate``
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.module_d import ModuleD
from portfolio_thesis_engine.extraction.module_d_overrides import (
    load_overrides,
    overrides_path_for,
)
from portfolio_thesis_engine.schemas.common import FiscalPeriod, Profile
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    ModuleAdjustment,
)
from portfolio_thesis_engine.schemas.overrides import (
    ModuleDOverrides,
    OverrideRule,
)
from portfolio_thesis_engine.schemas.raw_extraction import LineItem

from .conftest import build_raw, make_context


def _op_tax_rate_adj(rate: str = "25") -> ModuleAdjustment:
    return ModuleAdjustment(
        module="A.1",
        description="op tax rate",
        amount=Decimal(rate),
        affected_periods=[FiscalPeriod(year=2024, label="FY2024")],
        rationale="",
    )


# ======================================================================
# Decomposition paths (3 tests)
# ======================================================================


class TestDecompositionPaths:
    def _euroeyes_style_fixture(self) -> dict:
        """Build a fixture with Other gains, net + a matching Note 9 that
        breaks it into contingent FV, subsidies, and disposal gains."""
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {
                "order": 2,
                "label": "Other gains, net",
                "value": "25",
                "source_note": "9",
            },
            {
                "order": 3,
                "label": "Operating profit",
                "value": "200",
                "is_subtotal": True,
            },
            {
                "order": 4,
                "label": "Profit for the year",
                "value": "140",
                "is_subtotal": True,
            },
        ]
        notes = [
            {
                "note_number": "9",
                "title": "Other gains, net",
                "tables": [
                    {
                        "table_label": "Other gains breakdown 2024",
                        "columns": ["Item", "Total"],
                        "rows": [
                            ["Fair value gain on contingent consideration", "15"],
                            ["Government subsidies", "8"],
                            ["Gain on disposal of property, plant and equipment", "1"],
                            ["Miscellaneous", "1"],
                        ],
                    }
                ],
            }
        ]
        return {"is_lines": is_lines, "notes": notes}

    def test_module_d_decomposes_other_gains_from_note_table(self) -> None:
        fixture = self._euroeyes_style_fixture()
        raw = build_raw(**fixture)
        decompositions = ModuleD().decompose_all(raw)
        key = "IS:Other gains, net"
        assert key in decompositions
        decomp = decompositions[key]
        assert decomp.method == "note_table"
        assert len(decomp.sub_items) == 4
        labels = [s.label for s in decomp.sub_items]
        assert "Fair value gain on contingent consideration" in labels
        assert "Government subsidies" in labels

    def test_module_d_fallback_when_no_note_reference(self) -> None:
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {
                "order": 2,
                "label": "Fair value loss on contingent consideration",
                "value": "-5",
            },
            {"order": 3, "label": "Operating profit", "value": "195",
             "is_subtotal": True},
            {"order": 4, "label": "Profit for the year", "value": "140",
             "is_subtotal": True},
        ]
        raw = build_raw(is_lines=is_lines)
        decompositions = ModuleD().decompose_all(raw)
        key = "IS:Fair value loss on contingent consideration"
        assert decompositions[key].method == "label_fallback"

    def test_module_d_fallback_when_note_has_no_matching_table(self) -> None:
        # Source note exists but the table sums to something very
        # different from the parent.
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Other gains, net", "value": "25", "source_note": "9"},
            {"order": 3, "label": "Operating profit", "value": "200",
             "is_subtotal": True},
            {"order": 4, "label": "Profit for the year", "value": "140",
             "is_subtotal": True},
        ]
        notes = [
            {
                "note_number": "9",
                "title": "Other gains",
                "tables": [
                    {
                        "table_label": "Unrelated roll-forward",
                        "columns": ["Item", "Total"],
                        "rows": [["Other", "999"]],  # far from 25
                    }
                ],
            }
        ]
        raw = build_raw(is_lines=is_lines, notes=notes)
        decompositions = ModuleD().decompose_all(raw)
        key = "IS:Other gains, net"
        # Should fall through to label_fallback since no table matched.
        assert decompositions[key].method in ("label_fallback", "not_decomposable")


# ======================================================================
# Sub-item classification (3 tests)
# ======================================================================


class TestSubItemClassification:
    def test_sub_item_classification_operational_recurring_includes(self) -> None:
        sub = ModuleD().classify_sub_item(
            label="Government subsidies for R&D",
            value=Decimal("100"),
        )
        assert sub.operational_classification == "operational"
        assert sub.recurrence_classification == "recurring"
        assert sub.action == "include"

    def test_sub_item_classification_non_operational_excludes(self) -> None:
        sub = ModuleD().classify_sub_item(
            label="Gain on disposal of property, plant and equipment",
            value=Decimal("50"),
        )
        assert sub.operational_classification == "non_operational"
        assert sub.recurrence_classification == "non_recurring"
        assert sub.action == "exclude"

    def test_sub_item_classification_ambiguous_flags(self) -> None:
        sub = ModuleD().classify_sub_item(
            label="Miscellaneous other items",
            value=Decimal("5"),
        )
        assert sub.operational_classification == "ambiguous"
        assert sub.recurrence_classification == "ambiguous"
        assert sub.action == "flag_for_review"


# ======================================================================
# Overrides (3 tests)
# ======================================================================


class TestOverrides:
    def test_overrides_file_loaded(self, tmp_path: Path) -> None:
        # Write an overrides file and load it.
        override_dir = tmp_path / "1846.HK"
        override_dir.mkdir()
        (override_dir / "overrides.yaml").write_text(
            "version: 1\n"
            "sub_item_classifications:\n"
            "  - label_pattern: government subsidies\n"
            "    operational: operational\n"
            "    recurring: recurring\n"
            "    rationale: Recurring over 2020-2024 history.\n",
            encoding="utf-8",
        )
        overrides = load_overrides("1846.HK", portfolio_dir=tmp_path)
        assert len(overrides.sub_item_classifications) == 1
        rule = overrides.sub_item_classifications[0]
        assert rule.matches("Government subsidies for R&D")
        assert rule.operational == "operational"

    def test_override_precedence_over_regex(self) -> None:
        # Regex says "disposal" → non-operational. Override says
        # operational (e.g. core routine PPE refresh for a retailer).
        overrides = ModuleDOverrides(
            version=1,
            sub_item_classifications=[
                OverrideRule(
                    label_pattern=r"disposal of .*leasehold",
                    operational="operational",
                    recurring="recurring",
                    rationale="Routine leasehold refresh.",
                )
            ],
        )
        sub = ModuleD(overrides=overrides).classify_sub_item(
            label="Gain on disposal of a leasehold", value=Decimal("10")
        )
        assert sub.matched_rule.startswith("user_override:")
        assert sub.action == "include"

    def test_skeleton_generation_creates_template(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from portfolio_thesis_engine.cli import generate_overrides_cmd
        from portfolio_thesis_engine.schemas.decomposition import (
            LineDecomposition,
            SubItem,
        )

        # Build a minimal state-like object that exposes
        # adjustments.module_d_note_decompositions.
        class _StubState:
            def __init__(self) -> None:
                self.adjustments = AdjustmentsApplied(
                    module_d_note_decompositions={
                        "IS:Other gains, net": LineDecomposition(
                            parent_statement="IS",
                            parent_label="Other gains, net",
                            parent_value=Decimal("10"),
                            method="note_table",
                            confidence="low",
                            sub_items=[
                                SubItem(
                                    label="Unknown item",
                                    value=Decimal("5"),
                                    operational_classification="ambiguous",
                                    recurrence_classification="ambiguous",
                                    action="flag_for_review",
                                    matched_rule="regex:ambiguous+ambiguous",
                                    rationale="No pattern matched",
                                    confidence="low",
                                ),
                            ],
                        )
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
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "label_pattern" in content
        assert "Unknown item" in content


# ======================================================================
# Analysis layer — Module D consumption (3 tests)
# ======================================================================


class TestAnalysisConsumption:
    _IS_LINES = [
        {"order": 1, "label": "Revenue", "value": "1000"},
        {
            "order": 2,
            "label": "Other gains, net",
            "value": "25",
            "source_note": "9",
        },
        {"order": 3, "label": "Operating profit", "value": "200",
         "is_subtotal": True},
        {"order": 4, "label": "Profit for the year", "value": "140",
         "is_subtotal": True},
    ]
    _NOTES = [
        {
            "note_number": "9",
            "title": "Other gains, net",
            "tables": [
                {
                    "table_label": "Other gains breakdown 2024",
                    "columns": ["Item", "Total"],
                    "rows": [
                        ["Fair value gain on contingent consideration", "15"],
                        ["Government subsidies", "8"],
                        ["Gain on disposal of equipment", "1"],
                        ["Miscellaneous", "1"],
                    ],
                }
            ],
        }
    ]

    def test_sustainable_margin_uses_module_d_when_available(
        self, wacc_inputs
    ) -> None:
        raw = build_raw(is_lines=self._IS_LINES, notes=self._NOTES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        decompositions = ModuleD().decompose_all(raw)

        analysis = AnalysisDeriver().derive(ctx, decompositions=decompositions)
        bridge = analysis.nopat_bridge_by_period[0]

        # Module D flagged: Misc (ambiguous), excluded: FV gain 15 +
        # disposal 1 = 16. Plus flagged 1. Non-recurring = 15 + 1 + 1 = 17.
        # Sustainable OI = 200 − 17 = 183.
        assert bridge.non_recurring_operating_items == Decimal("17")
        assert bridge.operating_income_sustainable == Decimal("183")
        assert len(bridge.non_recurring_items_detail) == 3
        # Government subsidies is operational + recurring → stays in.
        labels = [
            s.label for s in bridge.non_recurring_items_detail
        ]
        assert "Government subsidies" not in labels

    def test_sustainable_margin_falls_back_to_regex_when_no_decomposition(
        self, wacc_inputs
    ) -> None:
        raw = build_raw(is_lines=self._IS_LINES)  # no notes → fallback
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        # No decompositions passed → Phase 1.5.9 regex path.
        analysis = AnalysisDeriver().derive(ctx, decompositions=None)
        bridge = analysis.nopat_bridge_by_period[0]
        # Regex catches "Other gains, net" as non-recurring (full 25).
        assert bridge.non_recurring_operating_items == Decimal("25")
        # Sustainable = 200 − 25 = 175.
        assert bridge.operating_income_sustainable == Decimal("175")

    def test_nopat_bridge_preserves_backward_compat(self, wacc_inputs) -> None:
        """Omitting ``decompositions`` entirely (old callers) must still
        yield a populated NOPAT bridge — Phase 1.5.9 behaviour intact."""
        raw = build_raw(is_lines=self._IS_LINES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        analysis = AnalysisDeriver().derive(ctx)
        bridge = analysis.nopat_bridge_by_period[0]
        assert bridge.nopat > Decimal("0")
        assert bridge.operating_income == Decimal("200")


# ======================================================================
# Display (2 tests)
# ======================================================================


class TestShowDisplay:
    def _build_bundle(self, wacc_inputs) -> object:
        """Build a FichaBundle with a canonical state carrying Module D
        decompositions + coverage."""
        from portfolio_thesis_engine.ficha import FichaBundle

        is_lines = TestAnalysisConsumption._IS_LINES
        notes = TestAnalysisConsumption._NOTES
        raw = build_raw(is_lines=is_lines, notes=notes)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        decompositions = ModuleD().decompose_all(raw)
        coverage = ModuleD().compute_coverage(raw, decompositions)

        # Build a minimal canonical state with the Module D output on
        # adjustments; full coordinator is overkill for a display test.
        from datetime import UTC, datetime

        from portfolio_thesis_engine.schemas.common import Currency
        from portfolio_thesis_engine.schemas.company import (
            AdjustmentsApplied,
            AnalysisDerived,
            CanonicalCompanyState,
            CompanyIdentity,
            InvestedCapital,
            KeyRatios,
            MethodologyMetadata,
            ValidationResult,
            ValidationResults,
            VintageAndCascade,
        )

        analysis = AnalysisDeriver().derive(ctx, decompositions=decompositions)
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
            adjustments=AdjustmentsApplied(
                module_d_note_decompositions=decompositions,
                module_d_coverage=coverage,
            ),
            analysis=analysis,
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
                protocols_activated=["A"],
            ),
        )

        return FichaBundle(
            ticker="TST",
            canonical_state=state,
            valuation_snapshot=None,
            ficha=None,
        )

    def test_show_detail_renders_decomposition_section(
        self, wacc_inputs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from portfolio_thesis_engine.cli import show_cmd

        bundle = self._build_bundle(wacc_inputs)
        buf = io.StringIO()
        test_console = Console(file=buf, width=320, record=True)
        monkeypatch.setattr(show_cmd, "console", test_console)
        show_cmd._render_detail(bundle, scenario_filter=None)
        rendered = buf.getvalue()
        assert "Sustainable OI derivation" in rendered
        assert "Fair value gain on contingent consideration" in rendered
        assert "Government subsidies" in rendered

    def test_show_detail_renders_coverage_section(
        self, wacc_inputs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from portfolio_thesis_engine.cli import show_cmd

        bundle = self._build_bundle(wacc_inputs)
        buf = io.StringIO()
        test_console = Console(file=buf, width=320, record=True)
        monkeypatch.setattr(show_cmd, "console", test_console)
        show_cmd._render_detail(bundle, scenario_filter=None)
        rendered = buf.getvalue()
        assert "Module D decomposition coverage" in rendered


# ======================================================================
# Pipeline stage (2 tests)
# ======================================================================


class TestPipelineStage:
    def test_decompose_notes_pipeline_stage_ok(self) -> None:
        """ModuleD.decompose_all + compute_coverage return OK shape
        regardless of coverage — the pipeline stage is non-blocking."""
        is_lines = TestAnalysisConsumption._IS_LINES
        notes = TestAnalysisConsumption._NOTES
        raw = build_raw(is_lines=is_lines, notes=notes)
        module_d = ModuleD()
        decompositions = module_d.decompose_all(raw)
        coverage = module_d.compute_coverage(raw, decompositions)
        # At least one IS line should have decomposed via note_table.
        assert coverage.is_decomposed >= 1

    def test_decompose_notes_pipeline_warn_high_fallback_rate(self) -> None:
        """When every IS leaf falls back (no note references), the
        coverage summary reflects that — the pipeline doesn't blow up,
        it just records the high fallback rate."""
        # IS with no source_note references → all not_decomposable.
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Cost of sales", "value": "-500"},
            {"order": 3, "label": "Administrative expenses", "value": "-200"},
            {"order": 4, "label": "Operating profit", "value": "300",
             "is_subtotal": True},
            {"order": 5, "label": "Profit for the year", "value": "200",
             "is_subtotal": True},
        ]
        raw = build_raw(is_lines=is_lines)
        module_d = ModuleD()
        decompositions = module_d.decompose_all(raw)
        coverage = module_d.compute_coverage(raw, decompositions)
        # Non-subtotal leaves (Revenue, COGS, Admin) = 3.
        assert coverage.is_total == 3
        # None decomposed via note_table.
        assert coverage.is_decomposed == 0
        # High fallback / not_decomposable rate.
        assert (
            coverage.is_not_decomposable + coverage.is_fallback
            == coverage.is_total
        )
