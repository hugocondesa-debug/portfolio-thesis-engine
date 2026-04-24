"""Phase 2 Sprint 4A-alpha.6 regression tests — CF validator
dual-convention support.

14 tests covering:

Convention A (standalone fx_effect section) — 4:
- ``test_cf_convention_a_separate_fx_passes``
- ``test_cf_convention_a_subtotal_walks_with_fx_reconciling``
- ``test_cf_fx_effect_standalone_single_subtotal_ok``
- ``test_cf_fx_effect_standalone_with_leaves_validates_internal``

Convention B (embedded fx) — 2:
- ``test_cf_convention_b_embedded_fx_passes``
- ``test_cf_convention_b_subtotal_walks_without_fx``

Edge cases — 3:
- ``test_cf_fx_effect_zero_subtotals_warn``
- ``test_cf_fx_effect_multiple_subtotals_warn``
- ``test_cf_validator_handles_value_none_gracefully``

Walker parameter — 2:
- ``test_walk_subtotals_with_extra_reconciling_value``
- ``test_walk_subtotals_without_extra_reconciling_value_unchanged``

EuroEyes-shaped fixtures — 2:
- ``test_cf_euroeyes_shaped_fy2021_passes``
- ``test_cf_euroeyes_shaped_h1_2023_passes``

Backward compat — 1:
- ``test_cf_validator_backward_compatible_existing_fixtures``
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.ingestion.raw_extraction_validator import (
    ExtractionValidator,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    CashFlowPeriod,
    LineItem,
)


# ======================================================================
# Fixture helpers
# ======================================================================
def _leaf(
    order: int, label: str, value: Decimal, section: str
) -> LineItem:
    return LineItem(
        order=order, label=label, value=value,
        is_subtotal=False, section=section,
    )


def _sub(
    order: int, label: str, value: Decimal, section: str
) -> LineItem:
    return LineItem(
        order=order, label=label, value=value,
        is_subtotal=True, section=section,
    )


def _cf_convention_a() -> CashFlowPeriod:
    """IFRS Asia/Europe convention: fx_effect as its own section.

    operating: 3 leaves sum to 600
    investing: 2 leaves sum to -400
    financing: 2 leaves sum to -56
    fx_effect: standalone reconciling -60
    subtotal:
       Net change = 144  (600 - 400 - 56)
       Cash begin = 762 leaf
       Cash end   = 846  (144 + 762 - 60)
    """
    items = [
        _leaf(1, "CFO item 1", Decimal("300"), "operating"),
        _leaf(2, "CFO item 2", Decimal("500"), "operating"),
        _leaf(3, "CFO item 3", Decimal("-200"), "operating"),
        _sub(4, "Net cash from operating", Decimal("600"), "operating"),

        _leaf(5, "CFI item 1", Decimal("-300"), "investing"),
        _leaf(6, "CFI item 2", Decimal("-100"), "investing"),
        _sub(7, "Net cash from investing", Decimal("-400"), "investing"),

        _leaf(8, "CFF item 1", Decimal("-30"), "financing"),
        _leaf(9, "CFF item 2", Decimal("-26"), "financing"),
        _sub(10, "Net cash from financing", Decimal("-56"), "financing"),

        _sub(11, "Effect of FX on cash", Decimal("-60"), "fx_effect"),

        _sub(12, "Net change in cash", Decimal("144"), "subtotal"),
        _leaf(13, "Cash at beginning", Decimal("762"), "subtotal"),
        _sub(14, "Cash at end", Decimal("846"), "subtotal"),
    ]
    return CashFlowPeriod(line_items=items)


def _cf_convention_b() -> CashFlowPeriod:
    """US GAAP / embedded-fx convention: no standalone fx_effect.

    subtotal section: Net change = sum of the three sections.
    """
    items = [
        _leaf(1, "CFO item 1", Decimal("300"), "operating"),
        _leaf(2, "CFO item 2", Decimal("300"), "operating"),
        _sub(3, "Net cash from operating", Decimal("600"), "operating"),

        _leaf(4, "CFI item 1", Decimal("-400"), "investing"),
        _sub(5, "Net cash from investing", Decimal("-400"), "investing"),

        _leaf(6, "CFF item 1", Decimal("-56"), "financing"),
        _sub(7, "Net cash from financing", Decimal("-56"), "financing"),

        _sub(8, "Net change in cash", Decimal("144"), "subtotal"),
        _leaf(9, "Cash at beginning", Decimal("762"), "subtotal"),
        _sub(10, "Cash at end", Decimal("906"), "subtotal"),
    ]
    return CashFlowPeriod(line_items=items)


def _cf_fx_zero_subtotals() -> CashFlowPeriod:
    """fx_effect section with no subtotal — degenerate shape."""
    items = [
        _leaf(1, "CFO item 1", Decimal("600"), "operating"),
        _sub(2, "Net cash from operating", Decimal("600"), "operating"),

        _leaf(3, "FX component", Decimal("-30"), "fx_effect"),

        _sub(4, "Net change in cash", Decimal("600"), "subtotal"),
        _leaf(5, "Cash at beginning", Decimal("100"), "subtotal"),
        _sub(6, "Cash at end", Decimal("670"), "subtotal"),
    ]
    return CashFlowPeriod(line_items=items)


def _cf_fx_multiple_subtotals() -> CashFlowPeriod:
    """fx_effect section with two subtotals — degenerate shape."""
    items = [
        _leaf(1, "CFO item 1", Decimal("600"), "operating"),
        _sub(2, "Net cash from operating", Decimal("600"), "operating"),

        _sub(3, "FX subtotal 1", Decimal("-20"), "fx_effect"),
        _sub(4, "FX subtotal 2", Decimal("-10"), "fx_effect"),

        _sub(5, "Net change in cash", Decimal("600"), "subtotal"),
        _leaf(6, "Cash at beginning", Decimal("100"), "subtotal"),
        _sub(7, "Cash at end", Decimal("670"), "subtotal"),
    ]
    return CashFlowPeriod(line_items=items)


def _cf_fx_with_leaves() -> CashFlowPeriod:
    """fx_effect with component leaves + a subtotal — walker validates
    leaves sum to subtotal internally."""
    items = [
        _leaf(1, "CFO item 1", Decimal("600"), "operating"),
        _sub(2, "Net cash from operating", Decimal("600"), "operating"),

        _leaf(3, "FX leaf A", Decimal("-40"), "fx_effect"),
        _leaf(4, "FX leaf B", Decimal("-20"), "fx_effect"),
        _sub(5, "Total FX effect", Decimal("-60"), "fx_effect"),

        _sub(6, "Net change in cash", Decimal("600"), "subtotal"),
        _leaf(7, "Cash at beginning", Decimal("762"), "subtotal"),
        _sub(8, "Cash at end", Decimal("1302"), "subtotal"),
    ]
    return CashFlowPeriod(line_items=items)


# ======================================================================
# Convention A (separate fx_effect)
# ======================================================================
class TestConventionA:
    def test_cf_convention_a_separate_fx_passes(self) -> None:
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_convention_a(), "FY2023"
        )
        # Every subtotal check + fx_effect.RECONCILING → OK.
        failing = [r for r in results if r.status == "FAIL"]
        assert failing == [], f"Unexpected failures: {[r.check_id for r in failing]}"

    def test_cf_convention_a_subtotal_walks_with_fx_reconciling(self) -> None:
        """The subtotal section's last check (Cash-end) should include
        the fx_effect reconciling value. Under the Sprint 4A-alpha.6
        walker semantics the first subtotal (Net change) is anchored
        as the baseline (not checked), so Cash end lands as SUB1."""
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_convention_a(), "FY2023"
        )
        cash_end = next(
            r for r in results
            if r.check_id.startswith("S.CF.subtotal.SUB")
            and "Cash at end" in r.message
        )
        assert cash_end.status == "OK"
        assert "Convention A" in cash_end.message
        assert cash_end.data.get("extra_reconciling") == "-60"

    def test_cf_fx_effect_standalone_single_subtotal_ok(self) -> None:
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_convention_a(), "FY2023"
        )
        fx_rec = next(
            r for r in results if r.check_id == "S.CF.fx_effect.RECONCILING"
        )
        assert fx_rec.status == "OK"
        assert fx_rec.data.get("fx_value") == "-60"

    def test_cf_fx_effect_standalone_with_leaves_validates_internal(
        self,
    ) -> None:
        """fx_effect with internal leaves that sum to the subtotal —
        walker emits the normal internal S.CF.fx_effect.SUB1 result."""
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_fx_with_leaves(), "FY2023"
        )
        internal = next(
            (r for r in results if r.check_id == "S.CF.fx_effect.SUB1"),
            None,
        )
        assert internal is not None
        assert internal.status == "OK"


# ======================================================================
# Convention B (embedded fx)
# ======================================================================
class TestConventionB:
    def test_cf_convention_b_embedded_fx_passes(self) -> None:
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_convention_b(), "FY2023"
        )
        failing = [r for r in results if r.status == "FAIL"]
        assert failing == []
        # No fx_effect.RECONCILING result emitted for Convention B.
        assert all(r.check_id != "S.CF.fx_effect.RECONCILING" for r in results)

    def test_cf_convention_b_subtotal_walks_without_fx(self) -> None:
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_convention_b(), "FY2023"
        )
        cash_end = next(
            r for r in results
            if r.check_id.startswith("S.CF.subtotal.SUB")
            and "Cash at end" in r.message
        )
        assert cash_end.status == "OK"
        # No reconciling value injected.
        assert cash_end.data.get("extra_reconciling") in (None, "None")


# ======================================================================
# Edge cases
# ======================================================================
class TestEdgeCases:
    def test_cf_fx_effect_zero_subtotals_warn(self) -> None:
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_fx_zero_subtotals(), "FY2023"
        )
        warn = next(
            (r for r in results if r.check_id == "S.CF.fx_effect.STRUCTURE"),
            None,
        )
        assert warn is not None
        assert warn.status == "WARN"
        assert warn.data.get("subtotal_count") == "0"

    def test_cf_fx_effect_multiple_subtotals_warn(self) -> None:
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_fx_multiple_subtotals(), "FY2023"
        )
        warn = next(
            (r for r in results if r.check_id == "S.CF.fx_effect.STRUCTURE"),
            None,
        )
        assert warn is not None
        assert warn.status == "WARN"
        assert warn.data.get("subtotal_count") == "2"

    def test_cf_validator_handles_value_none_gracefully(self) -> None:
        """A None-valued leaf or subtotal must not crash the walker."""
        items = [
            _leaf(1, "CFO ok", Decimal("500"), "operating"),
            LineItem(
                order=2, label="CFO missing", value=None,
                is_subtotal=False, section="operating",
            ),
            _sub(3, "Net cash from operating", Decimal("500"), "operating"),
        ]
        cf = CashFlowPeriod(line_items=items)
        validator = ExtractionValidator()
        results = validator._check_cf_sections(cf, "FY2023")  # noqa: SLF001
        # Should not crash; produces at least one result.
        assert results


# ======================================================================
# Walker parameter (extra_reconciling_value)
# ======================================================================
class TestWalkerParameter:
    def test_walk_subtotals_with_extra_reconciling_value(self) -> None:
        validator = ExtractionValidator()
        items = [
            _sub(1, "Sub A", Decimal("100"), "subtotal"),
            _leaf(2, "Leaf X", Decimal("50"), "subtotal"),
            _sub(3, "Sub B", Decimal("170"), "subtotal"),
        ]
        # Without reconciling: 100 + 50 = 150, vs reported 170 → FAIL.
        results_without = validator._walk_subtotals(  # noqa: SLF001
            items, period_label="FY",
            check_id_prefix="X", tolerance=Decimal("0.02"),
            scope_name="X",
        )
        # Inspect the LAST SUB check.
        sub_b = next(r for r in results_without if "SUB" in r.check_id and "Sub B" in r.message)
        assert sub_b.status == "FAIL"

        # With reconciling +20: 100 + 50 + 20 = 170 → OK.
        results_with = validator._walk_subtotals(  # noqa: SLF001
            items, period_label="FY",
            check_id_prefix="X", tolerance=Decimal("0.02"),
            scope_name="X",
            extra_reconciling_value=Decimal("20"),
        )
        sub_b_ok = next(r for r in results_with if "Sub B" in r.message)
        assert sub_b_ok.status == "OK"

    def test_walk_subtotals_without_extra_reconciling_value_unchanged(
        self,
    ) -> None:
        """Default signature (no extra_reconciling_value) behaves
        exactly like the Sprint 4A-alpha.5 walker — backward compat."""
        validator = ExtractionValidator()
        items = [
            _leaf(1, "L1", Decimal("10"), "operating"),
            _leaf(2, "L2", Decimal("20"), "operating"),
            _sub(3, "Total", Decimal("30"), "operating"),
        ]
        results = validator._walk_subtotals(  # noqa: SLF001
            items, period_label="FY",
            check_id_prefix="X", tolerance=Decimal("0.02"),
            scope_name="X",
        )
        assert results[0].status == "OK"


# ======================================================================
# EuroEyes-shaped fixtures (realistic numbers)
# ======================================================================
class TestEuroEyesShape:
    def test_cf_euroeyes_shaped_fy2021_passes(self) -> None:
        """EuroEyes-like FY2021 CF with Convention A."""
        items = [
            _leaf(1, "Cash generated from operations", Decimal("180"), "operating"),
            _leaf(2, "Tax paid", Decimal("-30"), "operating"),
            _leaf(3, "Interest received", Decimal("5"), "operating"),
            _sub(4, "Net cash from operating", Decimal("155"), "operating"),

            _leaf(5, "Capex", Decimal("-50"), "investing"),
            _sub(6, "Net cash from investing", Decimal("-50"), "investing"),

            _leaf(7, "Dividends paid", Decimal("-10"), "financing"),
            _leaf(8, "Lease payments", Decimal("-40"), "financing"),
            _sub(9, "Net cash from financing", Decimal("-50"), "financing"),

            _sub(10, "Effect of FX on cash", Decimal("-15"), "fx_effect"),

            _sub(11, "Net change in cash", Decimal("55"), "subtotal"),
            _leaf(12, "Cash at beginning", Decimal("700"), "subtotal"),
            _sub(13, "Cash at end", Decimal("740"), "subtotal"),
        ]
        cf = CashFlowPeriod(line_items=items)
        results = ExtractionValidator()._check_cf_sections(cf, "FY2021")  # noqa: SLF001
        failing = [r for r in results if r.status == "FAIL"]
        assert failing == []

    def test_cf_euroeyes_shaped_h1_2023_passes(self) -> None:
        """EuroEyes-shaped H1 2023 interim CF — smaller magnitudes."""
        items = [
            _leaf(1, "Cash generated from operations", Decimal("90"), "operating"),
            _leaf(2, "Tax paid", Decimal("-15"), "operating"),
            _sub(3, "Net cash from operating", Decimal("75"), "operating"),

            _leaf(4, "Capex", Decimal("-25"), "investing"),
            _sub(5, "Net cash from investing", Decimal("-25"), "investing"),

            _leaf(6, "Dividends paid", Decimal("-5"), "financing"),
            _leaf(7, "Lease payments", Decimal("-20"), "financing"),
            _sub(8, "Net cash from financing", Decimal("-25"), "financing"),

            _sub(9, "Effect of FX on cash", Decimal("-7"), "fx_effect"),

            _sub(10, "Net change in cash", Decimal("25"), "subtotal"),
            _leaf(11, "Cash at beginning", Decimal("720"), "subtotal"),
            _sub(12, "Cash at end", Decimal("738"), "subtotal"),
        ]
        cf = CashFlowPeriod(line_items=items)
        results = ExtractionValidator()._check_cf_sections(cf, "H1_2023")  # noqa: SLF001
        failing = [r for r in results if r.status == "FAIL"]
        assert failing == []


# ======================================================================
# Backward compatibility
# ======================================================================
class TestBackwardCompat:
    def test_cf_validator_backward_compatible_existing_fixtures(self) -> None:
        """Feed a Convention B CF (no standalone fx_effect) through and
        confirm zero S.CF.fx_effect.* results emitted. This locks in
        that the Sprint 4A-alpha.6 change didn't alter pre-existing
        validator behaviour for the absent-fx-section case."""
        validator = ExtractionValidator()
        results = validator._check_cf_sections(  # noqa: SLF001
            _cf_convention_b(), "FY2023"
        )
        fx_results = [r for r in results if "fx_effect" in r.check_id]
        assert fx_results == []
