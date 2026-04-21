"""Unit tests for all Pydantic schemas.

Structured by module (common → base → company → valuation → position →
peer → market_context → ficha). Each group covers:

1. Valid instantiation
2. Invalid-input rejection (ValidationError)
3. YAML roundtrip equivalence (to_yaml → from_yaml == original)
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.schemas.base import (
    AuditableMixin,
    BaseSchema,
    ImmutableSchema,
    VersionedMixin,
)
from portfolio_thesis_engine.schemas.common import (
    BasisPoints,
    ConfidenceTag,
    ConvictionLevel,
    Currency,
    DateRange,
    FiscalPeriod,
    GuardrailStatus,
    Money,
    MoneyWithCurrency,
    Percentage,
    Profile,
    Source,
)
from portfolio_thesis_engine.schemas.company import (
    CanonicalCompanyState,
    CompanyIdentity,
)
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.market_context import MarketContext
from portfolio_thesis_engine.schemas.peer import Peer, PeerExtractionLevel, PeerStatus
from portfolio_thesis_engine.schemas.position import (
    Position,
    PositionStatus,
    PositionTransaction,
)
from portfolio_thesis_engine.schemas.valuation import (
    Scenario,
    ScenarioDrivers,
    ValuationSnapshot,
)

# ============================================================
# schemas/common.py — enums + aliases + value objects
# ============================================================


class TestEnums:
    def test_currency_values(self) -> None:
        assert Currency.EUR.value == "EUR"
        assert Currency.USD.value == "USD"
        assert Currency("GBP") is Currency.GBP

    def test_profile_values(self) -> None:
        assert Profile.P1_INDUSTRIAL.value == "P1"
        assert Profile.P3A_INSURANCE.value == "P3a"
        assert Profile("P2") is Profile.P2_BANKS

    def test_conviction_level_values(self) -> None:
        assert ConvictionLevel.HIGH.value == "high"

    def test_guardrail_status_values(self) -> None:
        assert GuardrailStatus.PASS.value == "PASS"
        assert GuardrailStatus.NOTA.value == "NOTA"

    def test_confidence_tag_values(self) -> None:
        assert ConfidenceTag.REPORTED.value == "REPORTED"

    def test_unknown_currency_rejected(self) -> None:
        with pytest.raises(ValueError):
            Currency("XYZ")


class _AliasHost(BaseSchema):
    """Test-only model to exercise Money / Percentage / BasisPoints aliases."""

    amount: Money
    pct: Percentage
    bps: BasisPoints


class TestAliases:
    def test_aliases_accept_valid_values(self) -> None:
        m = _AliasHost(amount=Decimal("100.50"), pct=Decimal("12.5"), bps=250)
        assert m.amount == Decimal("100.50")
        assert m.pct == Decimal("12.5")
        assert m.bps == 250

    def test_percentage_rejects_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            _AliasHost(amount=Decimal("0"), pct=Decimal("-200"), bps=0)
        with pytest.raises(ValidationError):
            _AliasHost(amount=Decimal("0"), pct=Decimal("1500"), bps=0)


class TestMoneyWithCurrency:
    def test_instantiation(self) -> None:
        m = MoneyWithCurrency(amount=Decimal("123.45"), currency=Currency.EUR)
        assert m.amount == Decimal("123.45")
        assert m.currency is Currency.EUR

    def test_frozen(self) -> None:
        m = MoneyWithCurrency(amount=Decimal("1"), currency=Currency.EUR)
        with pytest.raises(ValidationError):
            m.amount = Decimal("2")  # type: ignore[misc]

    def test_yaml_roundtrip_preserves_decimal(self) -> None:
        m = MoneyWithCurrency(amount=Decimal("123456789.123456789"), currency=Currency.USD)
        loaded = MoneyWithCurrency.from_yaml(m.to_yaml())
        assert loaded == m
        assert loaded.amount == Decimal("123456789.123456789")
        assert type(loaded.amount) is Decimal


class TestDateRange:
    def test_valid(self) -> None:
        dr = DateRange(start="2024-01-01", end="2024-12-31")
        assert dr.start == "2024-01-01"

    def test_rejects_bad_format(self) -> None:
        with pytest.raises(ValidationError):
            DateRange(start="01/01/2024", end="2024-12-31")

    def test_yaml_roundtrip(self) -> None:
        dr = DateRange(start="2024-01-01", end="2024-12-31")
        assert DateRange.from_yaml(dr.to_yaml()) == dr


class TestFiscalPeriod:
    def test_valid_full_year(self) -> None:
        fp = FiscalPeriod(year=2024, label="FY2024")
        assert str(fp) == "FY2024"
        assert fp.quarter is None

    def test_valid_quarter(self) -> None:
        fp = FiscalPeriod(year=2024, quarter=3, label="Q3 2024")
        assert fp.quarter == 3

    def test_rejects_year_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            FiscalPeriod(year=1500, label="FY1500")

    def test_rejects_quarter_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            FiscalPeriod(year=2024, quarter=5, label="Q5 2024")

    def test_yaml_roundtrip(self) -> None:
        fp = FiscalPeriod(year=2024, quarter=2, label="Q2 2024")
        assert FiscalPeriod.from_yaml(fp.to_yaml()) == fp


class TestSource:
    def test_defaults(self) -> None:
        s = Source(document="AR2024")
        assert s.confidence is ConfidenceTag.REPORTED
        assert s.page is None

    def test_yaml_roundtrip(self) -> None:
        s = Source(
            document="AR2024",
            page=12,
            confidence=ConfidenceTag.CALCULATED,
            accessed="2025-01-01",
        )
        assert Source.from_yaml(s.to_yaml()) == s


# ============================================================
# schemas/base.py — BaseSchema / ImmutableSchema / mixins
# ============================================================


class _SampleSchema(BaseSchema):
    name: str
    count: int = 0


class _SampleImmutable(ImmutableSchema):
    name: str


class _SampleVersioned(BaseSchema, VersionedMixin):
    name: str


class _SampleAuditable(BaseSchema, AuditableMixin):
    name: str


class TestBaseSchema:
    def test_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            _SampleSchema(name="x", count=1, unexpected="oops")  # type: ignore[call-arg]

    def test_strips_whitespace(self) -> None:
        m = _SampleSchema(name="  hello  ", count=1)
        assert m.name == "hello"

    def test_validate_assignment(self) -> None:
        m = _SampleSchema(name="x", count=0)
        with pytest.raises(ValidationError):
            m.count = "not-an-int"  # type: ignore[assignment]

    def test_yaml_roundtrip(self) -> None:
        m = _SampleSchema(name="hello", count=5)
        assert _SampleSchema.from_yaml(m.to_yaml()) == m


class TestImmutableSchema:
    def test_frozen(self) -> None:
        m = _SampleImmutable(name="x")
        with pytest.raises(ValidationError):
            m.name = "y"  # type: ignore[misc]

    def test_hashable(self) -> None:
        # frozen=True models are hashable
        m1 = _SampleImmutable(name="x")
        m2 = _SampleImmutable(name="x")
        assert hash(m1) == hash(m2)


class TestVersionedMixin:
    def test_defaults_version_one(self) -> None:
        m = _SampleVersioned(name="x")
        assert m.version == 1
        assert m.created_by == "system"
        assert m.previous_version is None

    def test_rejects_version_zero(self) -> None:
        with pytest.raises(ValidationError):
            _SampleVersioned(name="x", version=0)

    def test_created_at_is_utc_aware(self) -> None:
        m = _SampleVersioned(name="x")
        assert m.created_at.tzinfo is not None


class TestAuditableMixin:
    def test_changelog_empty_by_default(self) -> None:
        m = _SampleAuditable(name="x")
        assert m.changelog == []

    def test_add_change_appends(self) -> None:
        m = _SampleAuditable(name="x")
        m.add_change("Added field X", actor="hugo")
        assert len(m.changelog) == 1
        entry = m.changelog[0]
        assert entry["actor"] == "hugo"
        assert entry["description"] == "Added field X"
        # ISO timestamp with timezone suffix
        assert "T" in entry["timestamp"]


# ============================================================
# schemas/company.py
# ============================================================


class TestCompanyIdentity:
    def test_valid(self, sample_identity: CompanyIdentity) -> None:
        assert sample_identity.ticker == "ACME"
        assert sample_identity.profile is Profile.P1_INDUSTRIAL

    def test_rejects_bad_isin(self) -> None:
        with pytest.raises(ValidationError):
            CompanyIdentity(
                ticker="ACME",
                isin="not-an-isin",
                name="Acme",
                reporting_currency=Currency.USD,
                profile=Profile.P1_INDUSTRIAL,
                fiscal_year_end_month=12,
                country_domicile="US",
                exchange="NYSE",
            )

    def test_rejects_bad_fiscal_year_end_month(self) -> None:
        with pytest.raises(ValidationError):
            CompanyIdentity(
                ticker="ACME",
                name="Acme",
                reporting_currency=Currency.USD,
                profile=Profile.P1_INDUSTRIAL,
                fiscal_year_end_month=13,
                country_domicile="US",
                exchange="NYSE",
            )


class TestCanonicalCompanyState:
    def test_valid(self, sample_company_state: CanonicalCompanyState) -> None:
        assert sample_company_state.identity.ticker == "ACME"
        assert len(sample_company_state.reclassified_statements) == 1

    def test_is_frozen(self, sample_company_state: CanonicalCompanyState) -> None:
        with pytest.raises(ValidationError):
            sample_company_state.extraction_id = "something-else"  # type: ignore[misc]

    def test_yaml_roundtrip(self, sample_company_state: CanonicalCompanyState) -> None:
        yaml_str = sample_company_state.to_yaml()
        loaded = CanonicalCompanyState.from_yaml(yaml_str)
        assert loaded == sample_company_state

    def test_yaml_preserves_nested_decimal_precision(
        self, sample_company_state: CanonicalCompanyState
    ) -> None:
        loaded = CanonicalCompanyState.from_yaml(sample_company_state.to_yaml())
        original_nopat = sample_company_state.analysis.nopat_bridge_by_period[0].nopat
        loaded_nopat = loaded.analysis.nopat_bridge_by_period[0].nopat
        assert original_nopat == loaded_nopat
        assert type(loaded_nopat) is Decimal


# ============================================================
# schemas/valuation.py
# ============================================================


class TestScenario:
    def test_valid(self, sample_scenario: Scenario) -> None:
        assert sample_scenario.label == "base"
        assert sample_scenario.probability == Decimal("50")

    def test_probability_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Scenario(
                label="base",
                description="x",
                probability=Decimal("150"),
                drivers=ScenarioDrivers(),
            )

    def test_horizon_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Scenario(
                label="base",
                description="x",
                probability=Decimal("50"),
                horizon_years=20,
                drivers=ScenarioDrivers(),
            )

    def test_yaml_roundtrip(self, sample_scenario: Scenario) -> None:
        assert Scenario.from_yaml(sample_scenario.to_yaml()) == sample_scenario


class TestValuationSnapshot:
    def test_valid(self, sample_valuation_snapshot: ValuationSnapshot) -> None:
        assert sample_valuation_snapshot.ticker == "ACME"
        assert sample_valuation_snapshot.version == 1
        assert sample_valuation_snapshot.conviction.forecast is ConvictionLevel.HIGH

    def test_is_frozen(self, sample_valuation_snapshot: ValuationSnapshot) -> None:
        with pytest.raises(ValidationError):
            sample_valuation_snapshot.ticker = "OTHER"  # type: ignore[misc]

    def test_yaml_roundtrip(self, sample_valuation_snapshot: ValuationSnapshot) -> None:
        loaded = ValuationSnapshot.from_yaml(sample_valuation_snapshot.to_yaml())
        assert loaded == sample_valuation_snapshot

    def test_versioned_mixin_wired(self, sample_valuation_snapshot: ValuationSnapshot) -> None:
        assert sample_valuation_snapshot.created_by == "claude-sonnet-4-6"
        assert sample_valuation_snapshot.created_at.tzinfo is not None


# ============================================================
# schemas/position.py
# ============================================================


class TestPosition:
    def test_valid(self, sample_position: Position) -> None:
        assert sample_position.status is PositionStatus.ACTIVE
        assert len(sample_position.transactions) == 1

    def test_auditable_changelog_works(self, sample_position: Position) -> None:
        sample_position.add_change("Reduced by 20 shares", actor="hugo")
        assert sample_position.changelog[-1]["description"] == "Reduced by 20 shares"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Position(
                ticker="X",
                company_name="X",
                status="unknown",  # type: ignore[arg-type]
                currency=Currency.USD,
            )

    def test_yaml_roundtrip(self, sample_position: Position) -> None:
        loaded = Position.from_yaml(sample_position.to_yaml())
        # Changelog is intentionally not compared across roundtrip because
        # add_change may have mutated the fixture during an earlier test
        # (fixtures are function-scoped so each test gets a fresh one).
        assert loaded == sample_position

    def test_transaction_type_freeform(self) -> None:
        tx = PositionTransaction(
            date="2024-01-01",
            type="open",
            quantity=Decimal("10"),
            price=Decimal("100"),
            currency=Currency.USD,
            rationale="reason",
        )
        assert tx.type == "open"


# ============================================================
# schemas/peer.py
# ============================================================


class TestPeer:
    def test_valid(self, sample_peer: Peer) -> None:
        assert sample_peer.extraction_level is PeerExtractionLevel.LEVEL_C
        assert sample_peer.status is PeerStatus.ACTIVE

    def test_yaml_roundtrip(self, sample_peer: Peer) -> None:
        loaded = Peer.from_yaml(sample_peer.to_yaml())
        assert loaded == sample_peer

    def test_invalid_extraction_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Peer(
                ticker="X",
                name="X",
                profile=Profile.P1_INDUSTRIAL,
                currency=Currency.USD,
                exchange="NYSE",
                peer_of_ticker="Y",
                extraction_level="Z",  # type: ignore[arg-type]
                last_update=datetime(2025, 1, 1, tzinfo=UTC),
            )


# ============================================================
# schemas/market_context.py
# ============================================================


class TestMarketContext:
    def test_valid(self, sample_market_context: MarketContext) -> None:
        assert sample_market_context.cluster_id == "us_industrials"
        assert len(sample_market_context.dimensions) == 1

    def test_extensions_accept_arbitrary_values(self, sample_market_context: MarketContext) -> None:
        sample_market_context.extensions["custom_field"] = {"nested": [1, 2, 3]}
        assert sample_market_context.extensions["custom_field"]["nested"] == [1, 2, 3]

    def test_yaml_roundtrip(self, sample_market_context: MarketContext) -> None:
        loaded = MarketContext.from_yaml(sample_market_context.to_yaml())
        assert loaded == sample_market_context


# ============================================================
# schemas/ficha.py
# ============================================================


class TestFicha:
    def test_valid(self, sample_ficha: Ficha) -> None:
        assert sample_ficha.ticker == "ACME"
        assert sample_ficha.thesis is not None
        assert sample_ficha.position is not None

    def test_yaml_roundtrip(self, sample_ficha: Ficha) -> None:
        loaded = Ficha.from_yaml(sample_ficha.to_yaml())
        assert loaded == sample_ficha

    def test_defaults(self, sample_identity: CompanyIdentity) -> None:
        f = Ficha(ticker="ACME", identity=sample_identity)
        assert f.is_stale is False
        assert f.tags == []
        assert f.monitorables == []
