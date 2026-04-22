# Operational KPIs — sector reference

> **READ THIS BEFORE USING THE LIST.**
>
> This is a **reference** of commonly-disclosed KPIs by sector. **It is
> not prescriptive.**
>
> - Companies report **different KPIs** than the ones listed here.
>   Their choices, not ours.
> - **Capture additional sector-specific KPIs** even if not listed
>   below. The schema's `operational_kpis.metrics` is free-form.
> - **Different naming conventions are fine** — preserve the
>   company's naming. Don't rename "same-clinic growth" to
>   "same-store sales" just because retail vocabulary is more
>   familiar.
> - **If a listed KPI isn't reported, DO NOT extract zero or null.**
>   Omit the entry. Nothing = nothing.
> - **No derived KPIs.** If ARR is not reported but MRR is, extract
>   MRR. Do not compute `ARR = MRR × 12`.

The list below is a **starting point for recall**, not a checklist to
satisfy.

## Healthcare providers (clinics, hospitals, labs)

Common disclosures:

- **Facility counts** — `clinics_total`, `hospitals_total`,
  `labs_total`. Sometimes split by region: `clinics_greater_china`,
  `clinics_germany`.
- **Volume** — `patient_visits_thousands`, `procedures_performed_thousands`,
  `surgeries_total`, `inpatient_admissions`, `outpatient_visits`.
- **Price** — `avg_revenue_per_visit_<currency>`,
  `average_selling_price_<currency>`.
- **Mix** — `lasik_share_of_revenue_pct`, `private_payer_share_pct`.
- **Throughput** — `patients_per_clinic_per_day`, `bed_turnover_ratio`,
  `occupancy_rate_pct`.
- **Growth** — `same_clinic_growth_pct`, `new_clinics_opened`.
- **Outcomes** — `readmission_rate_pct`, `revision_surgery_rate_pct`.

EuroEyes example:

```yaml
operational_kpis:
  metrics:
    clinics_total:
      "FY2024": "38"
    patient_visits_thousands:
      "FY2024": "285"
    avg_revenue_per_visit_hkd:
      "FY2024": "2035"
    procedures_performed_thousands:
      "FY2024": "52"
```

## Retail

Common disclosures:

- **Footprint** — `stores_total`, `stores_owned`, `stores_franchised`,
  `total_sqft_thousands`, `selling_sqft_thousands`.
- **Same-store sales** — `same_store_sales_growth_pct`,
  `comparable_stores_growth_pct`. The company's naming wins
  ("SSS" vs. "comps" vs. "LFL" vs. "same-store").
- **Productivity** — `sales_per_sqft_<currency>`,
  `sales_per_employee_<currency>`.
- **Basket** — `aov_<currency>` (average order value),
  `items_per_transaction`, `transactions_thousands`.
- **Digital** — `online_share_of_revenue_pct`, `active_customers_millions`.
- **Store life-cycle** — `new_stores_opened`, `stores_closed`,
  `net_store_growth`.

## Banking

Common disclosures:

- **Income** — `net_interest_margin_pct`, `net_interest_income_<currency>`,
  `non_interest_income_<currency>`.
- **Efficiency** — `cost_income_ratio_pct`, `cost_of_risk_bps`.
- **Asset quality** — `npl_ratio_pct` (non-performing loan),
  `coverage_ratio_pct`, `provision_coverage_pct`.
- **Capital** — `cet1_ratio_pct`, `tier1_ratio_pct`, `total_capital_ratio_pct`,
  `leverage_ratio_pct`.
- **Funding** — `loan_to_deposit_ratio_pct`, `lcr_pct` (liquidity coverage),
  `nsfr_pct` (net stable funding).
- **Profitability** — `roa_pct`, `rote_pct` (return on tangible equity).
- **Book** — `loans_gross_<currency>`, `deposits_<currency>`,
  `rwa_<currency>` (risk-weighted assets).

## Software / SaaS

Common disclosures:

- **Recurring revenue** — `arr_<currency>` (annual recurring),
  `mrr_<currency>` (monthly recurring), `bookings_<currency>`.
- **Retention** — `nrr_pct` (net revenue retention),
  `grr_pct` (gross revenue retention), `dbnrr_pct` (dollar-based
  net retention), `logo_retention_pct`.
- **Customers** — `customers_total`, `customers_over_100k_arr`,
  `customers_over_1m_arr`.
- **Efficiency** — `cac_payback_months` (customer acquisition cost
  payback), `magic_number` (net-new ARR / S&M spend, quarterly),
  `rule_of_40_pct` (growth + margin).
- **Capacity / pipeline** — `rpo_<currency>` (remaining performance
  obligations), `backlog_<currency>`.
- **Engagement** — `mau_millions` (monthly active users),
  `dau_millions`, `paying_users_thousands`.

## Insurance

Common disclosures:

- **Premium** — `gwp_<currency>` (gross written premium),
  `nwp_<currency>` (net written premium), `gwp_growth_pct`.
- **Underwriting** — `combined_ratio_pct`, `loss_ratio_pct`,
  `expense_ratio_pct`. P&C focused.
- **Solvency (IFRS 17 / Solvency II)** — `solvency_ratio_pct`,
  `scr_coverage_pct` (Solvency Capital Requirement),
  `mcr_coverage_pct`.
- **Embedded value (Life)** — `ev_<currency>`, `vnb_<currency>`
  (value of new business), `apv_<currency>` (actuarial present value).
- **Investment** — `investment_yield_pct`, `aum_<currency>`.

## REITs

Common disclosures:

- **Occupancy** — `occupancy_rate_pct`, `same_property_occupancy_pct`.
- **Lease maturity** — `wault_years` (weighted-average unexpired
  lease term), `wale_years` (sometimes called WALE by Australian
  REITs — same thing).
- **Valuation** — `nav_per_share_<currency>`,
  `net_asset_value_<currency>`, `cap_rate_pct`.
- **Cash earnings** — `ffo_<currency>` (funds from ops),
  `ffo_per_share_<currency>`, `affo_<currency>` (adjusted FFO).
- **Debt** — `ltv_pct` (loan-to-value), `debt_service_coverage`.
- **Portfolio** — `properties_total`, `gla_thousands_sqft` (gross
  leasable area), `rental_income_<currency>`.

## Commodity / energy / mining

Common disclosures:

- **Production** — `production_oil_kboe_per_day`,
  `production_gas_mmcf_per_day`, `production_gold_oz_thousands`,
  `production_copper_tonnes_thousands`.
- **Reserves** — `reserves_1p_mboe` (proved), `reserves_2p_mboe`
  (proved + probable), `reserves_3p_mboe`, `reserves_gold_oz_thousands`.
- **Cost curve** — `aisc_<currency>_per_oz` (all-in sustaining cost),
  `lifting_cost_<currency>_per_boe`, `cash_cost_<currency>_per_tonne`.
- **Realisations** — `realised_price_oil_<currency>`,
  `realised_price_gold_<currency>`, `realised_price_copper_<currency>`.
- **Capacity / utilisation** — `capacity_utilisation_pct`,
  `refining_throughput_kbpd`.
- **Development** — `capex_growth_<currency>`,
  `capex_sustaining_<currency>`, `reserve_replacement_ratio_pct`.

## General-purpose KPIs (any sector)

Companies often report these regardless of sector:

- **Employee** — `headcount`, `headcount_growth_pct`,
  `revenue_per_employee_<currency>`.
- **ESG** — `scope1_emissions_tco2e_thousands`,
  `scope2_emissions_tco2e_thousands`, `water_withdrawal_megalitres`,
  `workforce_female_pct`, `gender_pay_gap_pct`.
- **R&D / innovation** — `r_and_d_intensity_pct`,
  `patents_granted`, `new_products_launched`.

## Naming conventions for `operational_kpis.metrics`

- **snake_case**. `patient_visits_thousands`, not `PatientVisits` or
  `patient-visits`.
- **Include units in the name.** Monetary: `<currency>_millions`
  (inherits `unit_scale`) or `_hkd_per_visit` when specifying a
  different unit. Counts: bare number, `_thousands`, `_millions` for
  scaled counts. Percentages: `_pct`. Days/months/years: `_days`,
  `_months`, `_years`. Basis points: `_bps`.
- **Inherit the company's name** where it's unambiguous. "Same-store
  sales" → `same_store_sales_growth_pct`. "Like-for-like growth"
  → `like_for_like_growth_pct`.
- **Period keys** match the IS / BS / CF period labels (e.g.
  `"FY2024"`, `"H1 2025"`). Year-only keys (e.g. `"2024"`) are for
  `historical.*_by_year`, not `operational_kpis`.

## What the pipeline does with KPIs

Phase 1.5: **KPIs flow through the ficha composer verbatim.** The
ficha YAML surfaces them for Hugo to inspect. The valuation engine
does not consume them.

Phase 2: cross-sectional peer comparison (ticker A's
`same_clinic_growth_pct` vs. ticker B's), segment-level analytics,
and quality-of-earnings overlays will start using the metrics dict.
Richer, more-complete `operational_kpis` at extraction time = better
Phase 2 output without re-extraction.

## Three rules before closing

1. **Missing > fabricated.** If the PDF doesn't report ARR, leave
   ARR out. Don't compute it.
2. **Company naming > our naming.** Preserve their label; encode
   units in the snake_case key; don't rename.
3. **When a disclosure looks sector-specific and isn't in the list
   above**, capture it. The list is a reminder, not a ceiling.
