# Sprint 03 — Pydantic Schemas

**Date:** 2026-04-21
**Step (Parte K):** 3 — Schemas
**Status:** ✅ Complete

---

## What was done

Implemented the full schema layer under `src/portfolio_thesis_engine/schemas/`: the contract every future Phase 0 module (storage, LLM, valuation, portfolio) reads and writes. Eight modules built top-down, following spec Parte C:

1. `base.py` — `BaseSchema`, `ImmutableSchema`, `VersionedMixin`, `AuditableMixin` + shared YAML roundtrip helpers.
2. `common.py` — enums (`Currency`, `Profile`, `ConvictionLevel`, `GuardrailStatus`, `ConfidenceTag`) and small value objects (`Money`, `Percentage`, `BasisPoints`, `MoneyWithCurrency`, `DateRange`, `FiscalPeriod`, `Source`).
3. `company.py` — `CanonicalCompanyState` with 19 sub-entities (identity, reclassified statements, adjustments by module, analysis derivations, quarterly data, validation, vintage, methodology).
4. `valuation.py` — `ValuationSnapshot` with scenarios, reverse analysis, cross-checks, EPS bridge, catalysts, factor exposures, conviction, guardrails.
5. `position.py` — `Position` with transaction history, current state, linkage, and `AuditableMixin` changelog.
6. `peer.py` — `Peer` with extraction levels A/B/C.
7. `market_context.py` — cluster-level context with MVP minimum + `extensions` dict escape hatch.
8. `ficha.py` — composed aggregate (thesis + monitorables + links to other entities).

Plus `tests/conftest.py` with reusable sample fixtures for every top-level schema, and `tests/unit/test_schemas.py` covering instantiation, invalid-input rejection, and YAML roundtrip for each.

## Decisions taken

1. **Shared YAML helpers live on `BaseSchema`.** Added `to_yaml()` / `from_yaml()` methods using `model_dump(mode="json")` for the intermediate dict and `yaml.safe_dump` / `yaml.safe_load` for the wire format. This mode serialises `Decimal` as a string and `datetime` as ISO — both round-trip losslessly through PyYAML and back through `model_validate`. Decimal precision preservation is explicitly tested with `Decimal("123456789.123456789")`.
2. **`common.py` value objects inherit from `BaseSchema` / `ImmutableSchema`** rather than raw `BaseModel` as shown in spec C.1. This was the only way to share the YAML helpers uniformly (spec-style `BaseModel` subclasses had no `to_yaml`). `MoneyWithCurrency` → `ImmutableSchema` (frozen per spec). `DateRange`, `FiscalPeriod`, `Source` → `BaseSchema`. No cycle introduced — `common.py` depends on `base.py`, not the reverse.
3. **`PositionStatus`, `PeerStatus`, `PeerExtractionLevel`, and all `common.py` enums are `StrEnum` (PEP 663 / Python 3.11+)** instead of spec-style `(str, Enum)`. `ruff UP042` requires this on 3.12; identical runtime semantics (enum value IS its string).
4. **`Scenario.probability` uses `Annotated[Decimal, Field(ge=0, le=100)]`** directly rather than spec's `Percentage = Field(ge=0, le=100)`. Reason: when you set default-value `Field(ge=..., le=...)` on a field already typed as `Annotated[..., Field(...)]` (which `Percentage` is), Pydantic v2 keeps only the inner-`Annotated` constraints — the outer default's constraints silently get discarded. Verified: `probability=150` was accepted until this was corrected. See "Spec auto-corrections".
5. **`CanonicalCompanyState.analysis.*` dicts typed as `dict[str, Any]`** (not bare `dict` as in spec). `strict` mypy rejects bare `dict`. `Any` values allow future flexibility for deep-dive payloads that haven't been modelled yet.
6. **`ValuationSnapshot.scenario_response: dict[str, Any] | None`** — same reasoning as above.
7. **Did not alias `Percentage` to tighter bounds anywhere else.** Spec's `Percentage` allows −100 to 1000, which is wide on purpose (some ratios can exceed 100% or go deeply negative). Only `Scenario.probability` needs a true 0–100 clamp; everything else keeps the permissive alias.
8. **`AuditableMixin.add_change` is not tested for YAML roundtrip equality after mutation.** `add_change` appends a timestamp that captures wall-clock time; a fixture that's been mutated by one test can't be compared byte-for-byte to a reloaded copy from another test. Fixtures are function-scoped, so each test that cares about roundtrip gets a fresh object.
9. **Added `types-pyyaml>=6.0` to dev deps.** Without the stubs, mypy strict treats `yaml.safe_dump` return as `Any` and flags the `to_yaml` return type. No runtime impact.
10. **Test layout: one `tests/unit/test_schemas.py` file** grouped by `Test<ModuleClass>` per spec J.2 ("Schemas (`test_schemas.py`): instantiation, validation, serialization"). Keeping it in one file makes discovery of coverage gaps easier than splitting across modules.

## Spec auto-corrections

1. **C.4 `valuation.py` imports** — spec imports `ImmutableSchema, VersionedMixin` from `base` but then uses `BaseSchema` as parent for `ScenarioDrivers`, `SurvivalCondition`, `Scenario`, `MarketImpliedView`, `GapDecomposition`, `ReverseAnalysis`, `MonteCarloResult`, `CorrelatedStress`, `ConsensusComparison`, `CrossChecks`, `EPSBridgeComponent`, `EPSBridgeYear`, `EPSBridge`, `Catalyst`, `WeightedOutputs`, `GuardrailCategory`, `GuardrailsStatus`, `MarketSnapshot`, `FactorExposure`, `Conviction`. Added `BaseSchema` to the import.
2. **C.5 `position.py`** — spec imports `from datetime import datetime`, but nothing in the module uses `datetime` (`AuditableMixin.add_change` uses it internally, not as a field type). Removed the unused import — `ruff F401` would have flagged it.
3. **C.4 `Scenario.probability` constraint leak** — spec writes `probability: Percentage = Field(ge=0, le=100)` but Pydantic v2 silently drops the outer `ge=0, le=100` when the annotation is already `Annotated[..., Field(...)]`. Rewrote as `probability: Annotated[Decimal, Field(ge=0, le=100)]` — explicit and enforceable. Test `TestScenario::test_probability_out_of_range_rejected` exercises the boundary.
4. **`common.py` value-object parent class** — spec shows `MoneyWithCurrency/DateRange/FiscalPeriod/Source` extending raw `BaseModel`. Changed to `BaseSchema`/`ImmutableSchema` so YAML helpers propagate uniformly. See decision 2.
5. **Enum modernisation** — all `(str, Enum)` classes rewritten as `StrEnum` for `ruff UP042` compliance on Python 3.12. See decision 3.

## Files created / modified

```
A  src/portfolio_thesis_engine/schemas/__init__.py
A  src/portfolio_thesis_engine/schemas/base.py             (BaseSchema + mixins + YAML)
A  src/portfolio_thesis_engine/schemas/common.py           (enums, aliases, value objects)
A  src/portfolio_thesis_engine/schemas/company.py          (CanonicalCompanyState)
A  src/portfolio_thesis_engine/schemas/valuation.py        (ValuationSnapshot)
A  src/portfolio_thesis_engine/schemas/position.py         (Position)
A  src/portfolio_thesis_engine/schemas/peer.py             (Peer)
A  src/portfolio_thesis_engine/schemas/market_context.py   (MarketContext)
A  src/portfolio_thesis_engine/schemas/ficha.py            (Ficha aggregate)
A  tests/conftest.py                                       (schema fixtures)
A  tests/unit/test_schemas.py                              (89 test cases)
M  pyproject.toml                                          (add types-pyyaml)
M  uv.lock
A  docs/sprint_reports/03_schemas.md                       (this file)
```

## Verification

```bash
$ uv run pytest
# 89 passed in 0.51s

$ uv run ruff check src tests
# All checks passed!

$ uv run ruff format --check src tests
# 24 files already formatted

$ uv run mypy src
# Success: no issues found in 15 source files
```

Sample interactive smoke (confirms Decimal precision through full YAML roundtrip):

```bash
$ uv run python -c "
from decimal import Decimal
from portfolio_thesis_engine.schemas.common import MoneyWithCurrency, Currency
m = MoneyWithCurrency(amount=Decimal('123456789.123456789'), currency=Currency.USD)
loaded = MoneyWithCurrency.from_yaml(m.to_yaml())
assert loaded == m and type(loaded.amount) is Decimal and loaded.amount == Decimal('123456789.123456789')
print('Decimal roundtrip: OK')
"
Decimal roundtrip: OK
```

## Tests passing / failing + coverage

All 89 tests pass (61 new schema tests + 28 from Sprint 2).

| Module                    | Stmts | Miss | Cover |
| ------------------------- | ----- | ---- | ----- |
| `schemas/base.py`         |  24   |  0   | 100 % |
| `schemas/common.py`       |  58   |  0   | 100 % |
| `schemas/company.py`      | 169   |  0   | 100 % |
| `schemas/valuation.py`    | 159   |  0   | 100 % |
| `schemas/position.py`     |  45   |  0   | 100 % |
| `schemas/peer.py`         |  30   |  0   | 100 % |
| `schemas/market_context.py` | 38 |  0   | 100 % |
| `schemas/ficha.py`        |  33   |  0   | 100 % |
| **Schemas total**         | 556   |  0   | **100 %** |
| **Project total**         | 619   |  1   |  99 % |

Schemas comfortably clear the ≥90% target. The one uncovered line remains the non-default `ConsoleRenderer` branch of `logging_.py` (Sprint 2 known gap).

## Problems encountered

1. **Pydantic v2 constraint leak on `Annotated + Field()` defaults** — spent some time isolating why `probability=150` passed. Reproduced in isolation:
   ```python
   Pct = Annotated[Decimal, Field(ge=-100, le=1000)]
   class M(BaseModel):
       prob: Pct = Field(ge=0, le=100)   # ge=0, le=100 silently dropped
   M(prob=150)  # accepted — should have failed
   ```
   Fix was to use explicit `Annotated[Decimal, Field(ge=0, le=100)]`. Documented in report so future schema authors don't hit the same trap.
2. **`FiscalPeriod` initially extended `BaseModel`, missing `to_yaml`.** Caught immediately by smoke test. Rebased `common.py` on `BaseSchema`/`ImmutableSchema` (decision 2).
3. **Ruff `UP042` (StrEnum) + `UP040` (TypeAlias) + `E` import sort errors** surfaced on first lint run. Batch-fixed via `ruff format` + targeted edits. No underlying design issues.
4. **Missing `types-pyyaml`** flagged by mypy strict after YAML helpers landed. Added to dev deps, resolved.
5. **No architectural ambiguity encountered** that required pausing the batch.

## Next step

**Sprint 4 — Storage base.** Implement `storage/base.py` (Repository abstract base + interface) and `storage/yaml_repo.py` (YAML file repository built on the new `to_yaml` / `from_yaml` helpers). Tests: CRUD, atomic writes, versioning. After that, Sprint 5 fills in DuckDB/SQLite/Chroma/filesystem repos.
