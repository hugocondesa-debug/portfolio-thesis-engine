# Schemas reference (Phase 0)

All schemas live under `src/portfolio_thesis_engine/schemas/`, use
Pydantic v2, and share `BaseSchema` (`extra="forbid"`,
`str_strip_whitespace=True`, `validate_assignment=True`) or
`ImmutableSchema` (same + `frozen=True`) as their root. Every schema
inherits `to_yaml()` / `from_yaml()` helpers that use JSON-compatible
mode so `Decimal` and `datetime` values round-trip losslessly.

Full field-level docstrings live inside each schema module; IDEs pick
them up via the Pydantic model. This page is an index for humans.

## Top-level schemas

### `CanonicalCompanyState`  — `schemas/company.py`
**Immutable** output of the extraction system for a company. Snapshot of
the full financial state as of a specific extraction date. Composed of
`CompanyIdentity`, `ReclassifiedStatements[]`, `AdjustmentsApplied`,
`AnalysisDerived` (IC/NOPAT bridge/ratios/capital allocation), optional
`QuarterlyData`, `ValidationResults`, `VintageAndCascade`, and
`MethodologyMetadata`. Keyed by `extraction_id`. Consumed read-only by
the valuation and portfolio modules.

### `ValuationSnapshot`  — `schemas/valuation.py`
**Immutable, versioned** output of the valuation system. References
the `CanonicalCompanyState` it was built from and carries scenarios
(bear/base/bull), weighted outputs, reverse analysis, cross-checks,
EPS bridge, catalysts, factor exposures, conviction levels, and
guardrail status. Each new valuation creates a new version; the
`VersionedRepository` tracks a `current` pointer. Keyed by
`snapshot_id`.

### `Position`  — `schemas/position.py`
A portfolio holding. Carries `PositionStatus` (active / exited /
watchlist / research), transaction history, optional auto-computed
current state (quantity, avg cost, last price, market value, PnL,
weight), exit metadata if closed, and linkage IDs to the latest
valuation snapshot / ficha / company state. Uses `AuditableMixin` for
a mutable changelog.

### `Peer`  — `schemas/peer.py`
A comparable company benchmarked against a target. `PeerExtractionLevel`
(A = full extraction / B = adjusted metrics / C = API data only)
governs how much data is present. Carries market data, reported and
adjusted metrics, and archetype-specific fields. Promotion to the
watchlist is tracked via `promotion_date` / `promoted_to`.

### `MarketContext`  — `schemas/market_context.py`
Cluster-level context (e.g., `us_industrials`, `uk_specialist_banks`).
Holds a list of `MarketParticipant`s, `MarketDimension`s (geography /
segment totals), `MarketCatalyst`s, and regulatory/dynamics notes.
The `extensions: dict[str, Any]` escape hatch lets Phase 1 add rich
content without a schema migration.

### `Ficha`  — `schemas/ficha.py`
Composed aggregate displayed by the portfolio UI. Identity +
`ThesisStatement` + references to the current extraction/valuation +
`Position` + `Conviction` + `Monitorable`s. Never stored as a single
file — composed on demand from its constituents.

## Supporting schemas (not top-level but frequently referenced)

### `Scenario`  — `schemas/valuation.py`
One scenario inside a `ValuationSnapshot`. Label + description +
`probability` (strictly 0–100 via an `Annotated[Decimal, Field(ge=0,
le=100)]` — see Sprint 3 report for why this bypasses the permissive
`Percentage` alias) + `ScenarioDrivers` + targets + IRR decomposition
+ upside_pct + survival conditions + kill signals.

### `FiscalPeriod`, `MoneyWithCurrency`, `DateRange`, `Source`
— `schemas/common.py`. Small value objects used across the other
schemas. `MoneyWithCurrency` is `frozen` (monetary atoms shouldn't
mutate); the others are `BaseSchema`-based so they pick up the YAML
helpers uniformly.

### Enums — `schemas/common.py`
`Currency` (EUR/USD/GBP/CHF/JPY/HKD), `Profile` (P1–P6 archetypes),
`ConvictionLevel` (high/medium/low), `GuardrailStatus` (PASS/WARN/FAIL/
SKIP/REVIEW/NOTA), `ConfidenceTag` (REPORTED/CALCULATED/ESTIMATED/
ADJUSTED/ALIGNED). All are `StrEnum` (Python 3.11+) — identical runtime
values to spec's `(str, Enum)` form, cleaner ruff-UP042 compatibility.

## Mixins and bases — `schemas/base.py`

| Class              | Purpose                                            |
| ------------------ | -------------------------------------------------- |
| `BaseSchema`       | Default. forbid extras + strip whitespace + validate on assignment + YAML helpers |
| `ImmutableSchema`  | `BaseSchema` + `frozen=True`. For snapshots        |
| `VersionedMixin`   | `version`, `created_at` (UTC), `created_by`, `previous_version`    |
| `AuditableMixin`   | `changelog: list[dict]` + `add_change()` helper    |

`ValuationSnapshot` uses `ImmutableSchema + VersionedMixin`;
`Position` uses `BaseSchema + AuditableMixin`;
`Ficha` uses `BaseSchema + VersionedMixin`;
`MarketContext` uses `BaseSchema + AuditableMixin`.

## YAML roundtrip contract

```python
from portfolio_thesis_engine.schemas.common import MoneyWithCurrency, Currency
from decimal import Decimal

m = MoneyWithCurrency(amount=Decimal("123456789.123456789"), currency=Currency.USD)
loaded = MoneyWithCurrency.from_yaml(m.to_yaml())
assert loaded == m
assert type(loaded.amount) is Decimal     # precision preserved exactly
```

Every top-level schema is tested for this round-trip in
`tests/unit/test_schemas.py`. `tests/unit/test_storage.py` exercises the
same schemas through the YAML repositories.

## Related

- `docs/architecture.md` — where each schema sits in the module graph.
- `SPEC_PHASE_0.md` Parte C — field-by-field definitions and validation
  rules.
