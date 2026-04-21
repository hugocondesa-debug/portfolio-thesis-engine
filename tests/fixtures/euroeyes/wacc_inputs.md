---
# SYNTHETIC DATA — do not interpret as real EuroEyes financials.
# This fixture exercises the Phase 1 pipeline; numbers are fabricated
# but structurally plausible for a mid-cap HK-listed healthcare operator.

ticker: 1846.HK
profile: P1
valuation_date: 2025-03-31
current_price: "12.50"

cost_of_capital:
  risk_free_rate: 3.5          # 10Y HKGB proxy
  equity_risk_premium: 6.0     # HK market ERP
  beta: 1.2                    # Synthetic
  cost_of_debt_pretax: 4.5     # Average recent bond issuance
  tax_rate_for_wacc: 16.5      # HK corporate tax rate

capital_structure:
  debt_weight: 30
  equity_weight: 70
  preferred_weight: 0

scenarios:
  bear:
    probability: 25
    revenue_cagr_explicit_period: 3.0
    terminal_growth: 2.0
    terminal_operating_margin: 15.0
  base:
    probability: 50
    revenue_cagr_explicit_period: 8.0
    terminal_growth: 2.5
    terminal_operating_margin: 18.0
  bull:
    probability: 25
    revenue_cagr_explicit_period: 12.0
    terminal_growth: 3.0
    terminal_operating_margin: 22.0

explicit_period_years: 10

notes: |
  Synthetic fixture for Phase 1 integration tests.
  Bear assumes market share loss in Greater China, margin compression.
  Base assumes continued expansion at steady margins.
  Bull assumes EUR-subsidiary acquisition accretive from year 2.
---

# WACC inputs — EuroEyes Medical Group (1846.HK)

**Synthetic fixture.** Free-form analyst prose below the frontmatter is
ignored by the parser but helps human readers calibrate scenarios.

## Rationale

Three-scenario DCF with probabilities 25/50/25 per Phase 1 convention.
WACC derives from HK-market CAPM (Rf + β·ERP) on 70 % equity weight and
after-tax cost of debt on the remaining 30 %.
