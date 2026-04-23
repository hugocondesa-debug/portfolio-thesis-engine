# Phase 2 Sprint 2A.2 — Analytical polish

**Status:** pending — to run before Sprint 2B.
**Context:** Sprint 2A + 2A.1 (tag `v0.5.0-phase2-sprint2a-analytics-core`)
delivered the analytical core and fixed 8 issues surfaced by the
EuroEyes 3-document end-to-end validation. Five micro-polish issues
remain, all behavioural (numbers render, but the semantics can mislead
an analyst). Sprint 2A.2 closes them before Sprint 2B builds on top.

## Scope

Five issues, total estimated effort 2–3h Claude Code. Tests: ~12
regression tests.

### Issue 1 (LOW) — FY2023 Economic BS IC column empty

**Symptom.** `pte analyze 1846.HK` Economic BS row for FY2023 shows
`IC = —` even though the comparative BS carries the inputs
(non-current + current assets, trade payables, leases, borrowings).

**Root cause.** `EconomicBSBuilder.build()` sets
`invested_capital = ic.invested_capital if ic is not None else None`.
For comparatives `ic is None` → field stays `None`. The BS-only view
has all the operating + financial building blocks already computed
(PPE, WC, cash, debt) — the IC identity is reconstructible:

```
IC ≈ operating_assets (PPE + ROU + goodwill + intangibles + WC)
   − operating_liabilities (trade payables, provisions)
```

**Proposed fix.** When building a comparative BS view, compute
`invested_capital` from the operating-side aggregates already summed in
the same method (`ppe_net + rou_assets + goodwill + operating_intangibles
+ working_capital + associates_jvs + investment_property`). Leave
`cross_check_residual` at `None` since we can't reconcile without the
financial-side claims from AnalysisDeriver.

**Tests.**
- `test_comparative_economic_bs_computes_invested_capital_from_aggregates`
- `test_comparative_economic_bs_cross_check_stays_none`

**Files.** `src/portfolio_thesis_engine/analytical/economic_bs.py`.

---

### Issue 2 (LOW) — AR/Revenue QoE component always null

**Symptom.** QoE table AR/Rev column is `—` for every record. Score
never populates. Composite for FY2024 is 89 (4/5 components), not the
full 5.

**Root cause.** `compute_qoe` short-circuits AR/Rev delta computation:

```python
# Record doesn't carry AR directly; callers should pass current
# AR via side channel (Phase 2 Sprint 2B adds AR to the record).
# For Sprint 2A we skip if AR current is absent — keeps the
# ratio honest.
ar_delta_pp = None
```

Sprint 2A.1 **did** add `accounts_receivable` to `HistoricalRecord`, so
the comment is now stale and the field is reachable. The caller already
passes `prior_ar` for the prior year. We just need to plug
`record.accounts_receivable` into the revenue-growth-vs-AR-growth delta.

**Proposed fix.**
```
ar_growth = (ar_current − prior_ar) / prior_ar × 100
rev_growth = (revenue − prior_revenue) / prior_revenue × 100
ar_delta_pp = ar_growth − rev_growth
```
Score unchanged (≤0 pp → 100, ≤2 → 80, ≤5 → 60, else 30).

**Tests.**
- `test_qoe_ar_rev_delta_computes_when_both_periods_have_ar`
- `test_qoe_ar_rev_delta_handles_zero_prior_ar_gracefully`

**Files.**
- `src/portfolio_thesis_engine/analytical/analyze.py` (`compute_qoe`)
- `src/portfolio_thesis_engine/analytical/historicals.py`
  (pass `prior_ar` correctly — already wired via `records_by_year`).

---

### Issue 3 (MEDIUM) — H1_2025 QoE 95 > FY2024 89 paradox

**Symptom.** H1_2025 composite QoE = 95; FY2024 composite QoE = 89. The
audited full-year report scores worse than an unaudited interim, which
is the inverse of what a ranking should encode. Root cause: FY2024
picks up a 75 on the non-recurring component (23.3M fair-value gain on
contingent consideration), and H1_2025's bridge just happens to report
no non-recurring items → 100.

**Root cause.** Two compounding factors:
1. Sprint 2A's QoE weight scheme scales non-available components to
   zero weight. H1_2025 has fewer components populated (interim
   canonical state has no Module D run), so the composite is
   implicitly "better" because the harsh non-recurring penalty doesn't
   fire.
2. No audit posture penalty baked into the rescaling — REVIEWED
   interims score identically to AUDITED annuals once the weight
   normalisation kicks in.

**Proposed fix.** Two-part:
1. When composite is computed with fewer than all five components,
   apply a `confidence_penalty` that caps the displayed composite at
   `100 − (missing_components × 5)`. For H1_2025 (3 missing components)
   the cap becomes 85; FY2024 (1 missing, AR/Rev) stays at 95. Result:
   FY2024 89 > H1_2025 85 (preserved ordering).
2. Expose `qoe.methodology_note` on the schema ("composite includes
   X/5 components; Y capped due to interim posture") so the analyst
   sees *why* the number is what it is.

**Alternative (simpler).** Never show a composite >= 90 when
`audit_status != AUDITED`. Cap at 85 for REVIEWED, 60 for UNAUDITED.

**Decision pending.** The composite-cap approach is less mathematically
pure but easier to explain in the analytical report. Recommend
discussing before implementing.

**Tests.**
- `test_qoe_composite_caps_for_reviewed_interim`
- `test_qoe_composite_caps_for_unaudited_preliminary`
- `test_qoe_methodology_note_populated_when_cap_applied`

**Files.**
- `src/portfolio_thesis_engine/schemas/historicals.py` (add
  `methodology_note: str | None`)
- `src/portfolio_thesis_engine/analytical/analyze.py` (`compute_qoe`)

---

### Issue 4 (MEDIUM) — Investment signal picks preliminary as "current" quality

**Symptom.** `ts.investment_signal.earnings_quality_score` picks up the
**most recent** `quality_of_earnings.composite_score` — which for
EuroEyes is FY2025's preliminary = 40. An analyst reading "Earnings
quality composite: 40/100" on the dashboard doesn't realise this is an
unaudited investor presentation, not the reviewed interim (95) or the
audited FY (89).

**Root cause.** `_latest_qoe()` in
`analytical/historicals.py:988-993`:
```python
def _latest_qoe(records):
    for record in reversed(records):
        if record.quality_of_earnings is not None:
            return record.quality_of_earnings
    return None
```
No filter on audit posture or period type.

**Proposed fix.** Filter to highest-trust available:
```python
priority = [AUDITED, REVIEWED, UNAUDITED]
for audit in priority:
    for r in reversed(records):
        if r.audit_status == audit and r.quality_of_earnings is not None:
            return r.quality_of_earnings
return None
```
For EuroEyes this returns FY2024's 89 composite (AUDITED), not FY2025's
40. Same policy for `_latest_roic_decomposition`.

**Tests.**
- `test_investment_signal_picks_latest_audited_qoe`
- `test_investment_signal_picks_latest_audited_roic`
- `test_investment_signal_falls_back_to_reviewed_when_no_audited`

**Files.** `src/portfolio_thesis_engine/analytical/historicals.py`
(`_latest_qoe` + `_latest_roic_decomposition`).

---

### Issue 5 (LOW) — Growth trajectory STABLE despite preliminary +11.2 %

**Symptom.** EuroEyes FY2025 preliminary shows revenue 796M vs FY2024
715.68M = **+11.2 % YoY**, but the trend analysis shows
`revenue_trajectory = STABLE`. The trajectory is computed against the
*audited* annuals (FY2023 → FY2024, YoY +0.20 %) so the preliminary
signal doesn't feed in.

**Root cause (working as designed, but UX misleading).** Sprint 2A.1
correctly excluded preliminary from CAGR / trajectory math to prevent
fake 45 % CAGRs. But the analyst sees FY2025 in the periods table with
+11.2 % and wonders why the trajectory says STABLE.

**Proposed fix.** Emit a second-tier trajectory field:
```python
class TrendAnalysis(BaseSchema):
    ...
    revenue_trajectory: _Trajectory = "STABLE"         # annual audited only
    revenue_trajectory_incl_preliminary: _Trajectory = "STABLE"  # +preliminary
```
CLI renders both when they diverge:
```
Revenue trajectory:               STABLE (audited only, 2 annuals)
Revenue trajectory (incl. prelim): ACCELERATING (+11.2 % preliminary YoY)
```

**Tests.**
- `test_trajectory_includes_preliminary_when_divergent`
- `test_trajectory_incl_preliminary_matches_main_when_aligned`

**Files.**
- `src/portfolio_thesis_engine/schemas/historicals.py` (new field)
- `src/portfolio_thesis_engine/analytical/analyze.py` (`compute_trends`
  second pass with preliminaries included)
- `src/portfolio_thesis_engine/cli/analyze_cmd.py` (render when
  divergent)

---

## Deliverable

Single consolidated patch. ~12 regression tests. All 1065 existing
tests remain green. No schema-breaking changes (only additive fields
with sensible defaults).

**Target tag:** `v0.5.1-phase2-sprint2a-2-polish` (after Sprint 2A.2
validation).

**Sequencing.** Sprint 2A.2 runs before Sprint 2B (Economic IS +
capital-allocation decomposition). Sprint 2B builds on these QoE /
trajectory / investment-signal primitives, so polishing first prevents
Sprint 2B from inheriting the paradoxes.

**Issue 3 decision point.** Before implementation, confirm which of the
two approaches (confidence-penalty rescaling vs. audit-posture cap) is
preferred. Recommend the simpler audit-posture cap since it's easier
to explain to an analyst reading the composite.
