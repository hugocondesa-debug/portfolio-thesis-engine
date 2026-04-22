# Phase 1.5.5 — Validator IFRS-pattern enhancements

**Date:** 2026-04-22
**Scope:** teach the walking-subtotals validator four common IFRS IS
patterns Hugo's first real EuroEyes extraction surfaced. Core
LineItem structure + base walking-subtotals algorithm unchanged —
only enhanced with pattern recognition.

## Before / after on the real EuroEyes YAML

| Tier                           | Phase 1.5.4     | Phase 1.5.5        |
| ------------------------------ | --------------- | ------------------ |
| Pydantic parse                 | ✅ 0 errors     | ✅ 0 errors        |
| `strict`                        | ❌ FAIL (4)    | ✅ **OK**          |
| `warn`                          | ⚠ WARN          | ⚠ WARN (real ones) |
| `completeness`                  | ✅ OK           | ✅ OK               |

The four strict FAILs in 1.5.4 (IS.SUB3, IS.SUB4, IS.SUB6/7,
BS.IDENTITY) all resolved; the remaining W.CF + W.DIV warns are
real business-logic discrepancies the human should review
(FX-timing on Δcash and a small RE-walk residual from OCI reclass).

## Bugs fixed

### 1. Nested subtotals (S.IS.SUB3 + SUB4)

IFRS income statements include sub-sums like **"Finance income/
(expenses), net"** that sum the preceding 1-2 finance lines but do
**NOT** reset the Op → PBT → PFY waterfall. The previous validator
treated every `is_subtotal=true` as waterfall, reset the running
sum to the nested value, then FAILed the next waterfall subtotal
by a huge margin.

**Fix:**

- Added `skip_in_waterfall: bool = False` to `LineItem`. Extractors
  can mark nested subtotals explicitly.
- **Auto-detection**: when a subtotal's waterfall check fails AND
  the "sum since last waterfall anchor" matches, the validator
  reclassifies it as a nested subtotal (emits `S.IS.NESTED*` with
  a hint to mark `skip_in_waterfall: true` in the extraction).

### 2. OCI section semantics (S.IS.SUB6 + SUB7)

IFRS IS has a PnL section followed by an OCI (Other Comprehensive
Income) section. OCI items and the OCI subtotal are independent
from the PFY waterfall; TCI (Total Comprehensive Income) = PFY +
OCI subtotal, not a cumulative waterfall.

**Fix:**

- Detect the OCI header by label pattern
  (`/other comprehensive (income|loss|...)/i` + `value is None`).
- Detect OCI sub-headers by label pattern
  (`/items that (may|will) (not )?be reclassified/i`).
- On entering OCI: snapshot PFY (= last waterfall anchor), reset
  the running sum to zero for OCI accumulation.
- Emit dedicated check IDs: `S.IS.OCI` (OCI subtotal = Σ OCI
  items) and `S.IS.TCI` (TCI = PFY snapshot + OCI subtotal).

### 3. BS identity uses the wrong equity total (S.BS.IDENTITY)

When the BS has both "Total equity attributable to owners" (TEP,
excl. NCI) and "Total equity" (grand total incl. NCI) as equity
subtotals, the old validator picked the first match — causing the
A = L + E identity to fail by exactly the NCI amount.

**Fix:** `_find_last_equity_subtotal` returns the LAST
`is_subtotal=true` line in `section="equity"`. The BS identity
check uses it.

### 4. CF Δcash picks memo line (W.CF)

Some CF statements append opening + closing cash balances as
memo / reconciliation lines (tagged `notes: "memo"`). Both carry
`is_subtotal=true` and `section="subtotal"`, so the previous
validator picked the last one (cash closing balance) as the
Δcash anchor, producing a huge delta.

**Fix:** `_find_cf_net_change`

- Priority 1: line with label matching `/net (increase|decrease|
  change) in cash/` and `notes` NOT containing `memo|
  reconciliation`.
- Priority 2: any non-memo subtotal in `section="subtotal"`.

## Files changed

**Schema (`src/portfolio_thesis_engine/schemas/raw_extraction.py`):**

- `LineItem.skip_in_waterfall: bool = False` added with docstring.

**Validator (`src/portfolio_thesis_engine/ingestion/raw_extraction_validator.py`):**

- `_check_is_arithmetic` rewritten as an IFRS-aware walker
  (waterfall / nested / OCI / TCI modes). ~140 LOC.
- `_find_last_equity_subtotal` new helper.
- `_find_cf_net_change` new helper with memo-line skip.
- `_check_bs_identity` uses `_find_last_equity_subtotal`.
- `_check_cf_identity` uses `_find_cf_net_change`.
- Five new label-regex constants:
  `_OCI_HEADER_LABEL`, `_OCI_SUBHEADER_LABEL`, `_TCI_LABEL`,
  `_NET_CHANGE_IN_CASH_LABEL`, `_MEMO_NOTE_PATTERN`.

**Tests (`tests/unit/test_raw_extraction_validator.py`):**

- `TestNestedSubtotals` — auto-detected nested subtotal + explicit
  `skip_in_waterfall`.
- `TestOCITCI` — OCI + TCI happy path, OCI mismatch FAIL, TCI
  mismatch FAIL.
- `TestEquityMultiSubtotal` — BS identity uses last equity
  subtotal; label assertion on `equity_subtotal_label`.
- `TestCFMemoLines` — W.CF prefers the labelled Δcash line over
  memo lines.
- `TestRealFixture.test_real_claude_ai_fixture_strict_ok` —
  regression: Hugo's real 4288-line EuroEyes YAML validates
  strictly OK.

**Docs (`docs/claude_ai_extraction_guide.md`):**

- New section 1c "IFRS IS patterns" with worked examples for the
  four patterns (nested subtotals, OCI + TCI, multi-level equity,
  CF memo lines).

## Invariants preserved

- LineItem core fields (`order`, `label`, `value`, `is_subtotal`,
  `section`, `source_note`, `source_page`, `notes`) — unchanged.
- Walking-subtotals core algorithm — preserved; new behaviours
  layered on top.
- Modules A / B / C — untouched (they read notes + IS labels, not
  subtotals).
- Zero LLM calls.

## Final metrics

- **Tests:** 791 passed (+8 from 783), 6 skipped. 94 % coverage.
- **Ruff + mypy --strict:** clean.
- **Real EuroEyes YAML:** `strict=OK · warn=WARN · completeness=OK`.
  Remaining warns are business-logic (W.CF FX-timing, W.DIV RE
  reconciliation via OCI) not schema/validator bugs.
