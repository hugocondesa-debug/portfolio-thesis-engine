# `DocumentType` reference

Every `raw_extraction.yaml` declares a `metadata.document_type` from this
closed list of 42 values. Pick the most specific match — the document
type drives which note-completeness checks the validator applies.

Organised by bucket. Within each bucket, alphabetical.

## Numeric (statements + regulatory filings)

Documents that produce structured financial statements. `extraction_type`
is always `"numeric"`.

| Value                         | When to use                                                                                              | Expected sections                                                      |
| ----------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `aif`                         | Canadian Annual Information Form — goes with the audited annual report.                                  | IS, BS, CF (by reference), governance + risk narrative.                |
| `annual_report`               | Generic listed-company annual report (UK, EU, AU, HK, SG, LatAm).                                        | Full IS + BS + CF; full notes set; segments; 5-year summary.           |
| `form_6k`                     | Foreign private issuer filing an SEC 6-K (material events outside the 20-F cadence).                     | Usually partial statements or press-release-style disclosure.          |
| `form_8k`                     | US material-event filing. Press release attached.                                                        | Usually one-off: acquisition, guidance, executive change.              |
| `form_10k`                    | US domestic issuer annual filing.                                                                        | Full IS + BS + CF; notes; MD&A; risk factors.                          |
| `form_10q`                    | US domestic issuer quarterly filing (Q1, Q2, Q3).                                                        | Condensed IS + BS + CF; MD&A; limited notes.                           |
| `form_20f`                    | Foreign private issuer annual filing on US markets.                                                      | Full IS + BS + CF; US-GAAP reconciliation notes when applicable.       |
| `hkex_announcement`           | Hong Kong Exchange one-off announcement.                                                                 | Varies; often segment updates or transaction disclosures.              |
| `interim_report`              | UK / EU / HK / SG / AU semi-annual report.                                                               | Condensed IS + BS + (sometimes) CF; limited notes.                     |
| `operating_statistics`        | Real-estate / airline / telco operating stats — occupancy, ASK/RPK, ARPU.                                | Operational KPIs dominate; populate `operational_kpis.metrics`.        |
| `prc_annual`                  | Chinese-domestic (Shanghai / Shenzhen) annual report.                                                    | Full statements + CAS-specific notes; watch for subsidiary currencies. |
| `preliminary_announcement`    | Provisional annual / interim results ahead of the audited filing.                                        | Headline statements; notes usually deferred to full filing.            |
| `press_release`               | Corporate press release containing financial numbers.                                                    | Usually a trading update or material transaction.                      |
| `quarterly_update`            | Trading update (not a 10-Q equivalent) — e.g. UK Q3 trading updates.                                     | Headline revenue / guidance; rarely full statements.                   |
| `reit_supplement`             | REIT supplemental package (FFO, AFFO, NAV).                                                              | FFO bridge; property-level detail; occupancy; NAV.                     |
| `tdnet_disclosure`            | Japanese TDnet disclosure (TSE).                                                                         | Full or partial statements; Japanese-GAAP specifics.                   |

## Narrative (investor materials)

Documents that produce qualitative content. `extraction_type` is
typically `"narrative"`.

| Value                         | When to use                                                                                                | Expected sections                                                |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `analyst_day`                 | Multi-hour analyst day / capital-markets day.                                                              | Strategic themes, forward guidance, Q&A highlights.              |
| `cdp_submission`              | Carbon Disclosure Project submission (climate / water / forests).                                          | ESG metrics; rarely financial.                                   |
| `directors_report`            | UK Directors' Report companion to the annual accounts.                                                     | Governance narrative; dividend policy; director holdings.        |
| `earnings_call`               | Earnings-call transcript (Q1–Q4 / H1 / FY).                                                                | Prepared remarks + Q&A.                                          |
| `earnings_call_slides`        | Slide deck accompanying the earnings call.                                                                 | KPI tables; chart annotations.                                   |
| `esg_report`                  | Standalone ESG report.                                                                                     | Emissions, social, governance KPIs.                              |
| `form_def14a`                 | US proxy statement (DEF 14A).                                                                              | Executive compensation; governance; shareholder proposals.       |
| `investor_day`                | In-person investor day (broader than analyst day).                                                         | Medium-term targets; segment deep-dives.                         |
| `investor_letter`             | Quarterly investor letter (common in asset managers / holding companies).                                  | Commentary; holdings; capital allocation.                        |
| `investor_presentation`       | Standalone investor pitch deck.                                                                            | Strategy; market opportunity; financials summary.                |
| `mda_standalone`              | MD&A extracted as a separate document (when not part of an AR).                                            | Management commentary; forward-looking statements.               |
| `prospectus`                  | IPO / follow-on / bond prospectus.                                                                         | Full historical statements + risk factors + use of proceeds.     |
| `proxy_circular`              | Canadian / UK equivalent of DEF 14A.                                                                       | Director slate; remuneration.                                    |
| `research_report_company_produced` | Sell-side-style research produced by the company itself (rare).                                       | Analyst-style narrative.                                         |
| `strategic_report`            | UK strategic report (separate filing from the directors' report).                                          | Strategy; KPIs; sustainability.                                  |
| `sustainability_report`       | Separate sustainability/impact report.                                                                     | Emissions; social metrics; frameworks (TCFD, SASB).              |

## Regulatory correspondence

| Value                         | When to use                                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------- |
| `fda_warning_letter`          | FDA warning / 483 letter (biotech, pharma, medical devices).                           |
| `sec_comment_letter`          | SEC comments issued on a filing (public after ~20 business days).                      |
| `sec_no_action_letter`        | SEC no-action letter.                                                                  |
| `sec_response_letter`         | Registrant's response to an SEC comment letter.                                        |

## Industry-specific

| Value           | When to use                                                                                                             |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `icaap`         | Bank's Internal Capital Adequacy Assessment Process. Usually not public; use when available via supervisory release.    |
| `ni_43_101`     | Canadian NI 43-101 technical report for a mining project. Feeds reserve/resource modelling for P4.                      |
| `orsa`          | Insurer's Own Risk and Solvency Assessment. Usually private; public summaries for some EU insurers.                     |
| `pillar_3`      | Basel III Pillar 3 disclosure — banks' regulatory capital + RWA breakdown.                                              |
| `sfcr`          | Solvency and Financial Condition Report — EU insurers' public Solvency II disclosure.                                   |

## Catchall

| Value    | When to use                                                                                                    |
| -------- | -------------------------------------------------------------------------------------------------------------- |
| `other`  | Everything that genuinely doesn't map to the above. Rare. Flag in `extraction_notes` what the document is.     |

## Picking the right type — rule of thumb

- **Start with the filing jurisdiction.** US → `form_10k` / `form_10q` /
  `form_20f`. UK/EU/HK → `annual_report` / `interim_report`. Chinese
  domestic → `prc_annual`.
- **If it's not a periodic filing**, ask: does it produce statements
  (`numeric`) or is it narrative? Press releases with full statements
  = `press_release` + `numeric`. Earnings call slides with no statements
  = `earnings_call_slides` + `narrative`.
- **Industry-specific formats always win** over the generic bucket:
  a bank's annual Pillar 3 goes to `pillar_3`, not `annual_report`.
- **When in doubt, pick the more specific type.** The app only uses
  `document_type` for completeness-check selection; it never changes
  parsing behaviour.
