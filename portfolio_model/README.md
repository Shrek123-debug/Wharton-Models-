# Portfolio Modeling Agent

Complete portfolio-analysis and forward-simulation system: ingestion, validation,
market data, Monte Carlo, Markov regime, and historical-bootstrap engines,
sensitivity analysis, stress tests, risk metrics, deterministic rule-based risk
flags, and polished Excel + DOCX reporting — with a **fully local interactive
web dashboard**. No LLM / AI API / cloud inference is used anywhere.

## Quick start

```bash
# from the repository root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd portfolio_model
python main.py --check          # environment + data self-test
```

### Web UI (recommended)

```bash
python run_web.py               # opens http://127.0.0.1:8000
python run_web.py --port 8080
```

1. Open the dashboard. The sidebar runs an **environment pre-flight** first and shows any
   blocking problem with the command that fixes it.
2. Upload a portfolio `.xlsx` (or press *Run with example portfolio*).
3. Adjust run options (simulations, seed, MC model, glide method, bands, caps, bootstrap,
   market-data mode) and press **Run Analysis**.
4. Explore 16 tabs: Overview, Holdings & Sectors, History, Monte Carlo, Markov Regime,
   Historical Bootstrap, Model Comparison, Sensitivity, Stress Tests, Risk & Concentration,
   Rebalance & Glide, Flags & Actions, Data Quality, Methodology, **Tutorial**, **Definitions**.
5. Interactive Plotly charts render from a locally vendored `plotly.min.js` — no CDN.
6. Click the **_i_** button on any KPI card or table header to open that metric's definition:
   formula, what it measures, how to read it for this portfolio, what to do, and the trap.
7. Download the full **Excel workbook** (20 sheets incl. *Rule Flags* and *Definitions*) and
   **written DOCX report**.

All analysis runs on your machine. Prices resolve from `data/cache/`, then the network if
allowed, then the committed snapshots in `data/offline/` — so a fresh clone runs everything
with `--offline` and no network at all.

### Rule-based flags (non-AI recommendations)

`src/rules/rule_engine.py` evaluates explicit thresholds from `config/model_config.yaml`
(position cap, correlated-group cap, sector cap/target bands, cash floor, correlation
threshold, drawdown review trigger, tail CVaR, reserve-funding probability, model
disagreement, data confidence, thesis completeness, rebalancing bands, sensitivity
fragility). Every flag reports: **metric → current value → threshold → rule →
suggested action → severity** (CRITICAL/HIGH/WARNING/MONITOR). Flags appear in the
dashboard *Flags & Actions* tab, the Excel *Rule Flags* sheet, and report section 19.5.

### CLI

```bash
python main.py                 # uses config/model_config.yaml input path
python main.py --check         # environment + data self-test
python main.py --offline       # never touch the network
python main.py --input data/input/example_portfolio_full.xlsx
python main.py --sims 50000 --seed 7 --model student_t
```

To use a different portfolio spreadsheet, either pass `--input path.xlsx` or change
`input.spreadsheet` in `config/model_config.yaml`. The ingestion layer auto-detects
column names (Ticker/Symbol, Shares/Quantity, Market Value, Weight, Sector, Bucket, etc.).

## Input spreadsheet format

**Required:** at least one sheet containing a header row with a **ticker column** plus at
least one sizing column — `Weight`, `Market Value`, or `Shares` + `Price`. The header may
appear below title rows. Values must be static numbers or formula results cached by
Excel/LibreOffice (open and save the file before uploading).

**Ticker rules:** US-listed symbols matching `^[A-Z][A-Z0-9.-]{0,11}$` (e.g. `VOO`, `BRK.B`).
Cash must appear as `CASH`. Foreign/currency-mismatched and unrecognized tickers are
flagged and excluded (no FX conversion is applied).

**Recognized columns (aliases auto-detected):**

| Canonical | Accepted headers |
|---|---|
| `ticker` | Ticker, Symbol, Security, Name |
| `quantity` | Shares, Quantity, Units |
| `price` | Current Price, Price, Market Price |
| `market_value` | Market Value, Current Value, Value |
| `portfolio_weight` | Weight, % of Portfolio, Portfolio Weight |
| `target_weight` | Target Weight, Target Allocation |
| `sector` / `industry` | Sector, GICS Sector, Industry |
| `asset_class` | Asset Class, Bucket, Class |
| `currency` | Currency (must equal `input.base_currency`, default USD) |
| `cost_basis` | Cost Basis, Avg Cost |
| `expected_return` / `volatility` | Expected Return, Volatility, Std Dev |
| `correlation_group` | Correlation Group, Group, Cluster |
| `thesis` | Investment Thesis, Thematic Rationale, Why Own |
| `stop_loss`, `notes`, `dividend_yield`, `purchase_date` | as named |

**Automatic handling:** duplicate tickers merged; negative/zero positions dropped with a
flag; weights normalized to 100%; missing sectors assigned via GICS lookup; short
histories flagged low-confidence.

**Examples:** `data/input/example_portfolio_full.xlsx` (all columns) and
`data/input/example_portfolio_minimal.xlsx` (Ticker + Weight only).

## Simulation timeline (Laura Gao portfolio)

- 2027: invest $300,000; 2028: invest $150,000
- 2027-2032: growth phase with configurable glide path (default linear 70% -> 55% equity)
- 2031: sponsor range = projected facility-contribution percentiles
- 2033: split into reserve (PV of ten $50,000 payments at 2.9%) + facility contribution (surplus)
- 2033-2042: reserve phase, $50,000 paid at start of each year; success = all 10 funded

## Outputs

- `outputs/spreadsheet/portfolio_analysis.xlsx` — 20 sheets (dashboard, holdings, sectors,
  correlations, history, MC, Markov, bootstrap, comparison, sensitivity, risk, stress,
  glide path, rebalancing, rule flags, theses, data quality, scorecard, stop-loss,
  **definitions**)
- `outputs/report/portfolio_analysis_report.docx` — 24-section written report
- `outputs/figures/` — 16 charts
- `outputs/report/run_manifest.yaml` — config, seed, versions, data provenance (reproducibility)

## Architecture / module map

```
main.py                  CLI entry: argument parsing, exit codes, self-test
run_web.py               uvicorn launcher for the FastAPI dashboard
src/config.py            config loading + package-root-relative path resolution
src/runtime_env.py       writable matplotlib / yfinance caches, headless MPLBACKEND
src/selfcheck.py         environment + data readiness (CLI --check and /api/selfcheck)
src/ingestion/ingest.py  header detection, column aliases, numeric coercion, formula detection
src/validation/validate.py  weights resolution, currency/ticker exclusion, missing-weight errors
src/market_data/fetch.py cache -> network -> bundled snapshot, with per-ticker provenance
src/sectors/sectors.py   GICS assignment, sector tables, sector correlations
src/portfolio/portfolio.py  rebalanced index, covariance (nearest-PSD), correlation, portfolio stats
src/returns/returns.py   simple/log returns, monthly compounding, annualisation
src/monte_carlo/mc.py    return generators + the shared path simulator (contributions, glide,
                         rebalancing bands, 2033 split, reserve payments) + summary statistics
src/bootstrap/bootstrap.py  block/iid bootstrap of real joint daily returns -> same path simulator
src/markov/markov.py     5-regime classification, transition matrix, stationary distribution,
                          durations, regime-driven simulation
src/sensitivity/sensitivity.py  return-shift x volatility grid + grid interpretation
src/stress_tests/stress.py  historical crisis replays + hypothetical asset-class shocks
src/risk/risk.py         VaR/CVaR (historical + parametric), HHI, concentration, correlation
                         clusters, drawdown distribution, recovery events
src/risk/stoploss.py     hard/trailing stop backtests with re-entry
src/attribution/attribution.py  holding/sector contribution attribution, P&L basis note
src/optimization/optimize.py  constrained max-Sharpe diagnostic
src/rules/rule_engine.py deterministic threshold rules -> flags with action + evidence
src/metric_glossary.py   THE definition source: 70 metrics + label->definition aliases
src/reporting/charts.py  16 matplotlib figures
src/reporting/excel.py   20-sheet workbook incl. the Definitions sheet
src/reporting/docx_report.py  written report
src/pipeline.py          orchestration, glide targets, expected-return parameters, scorecard,
                         recommendations, run manifest, whitelisted+validated overrides
web/app.py               FastAPI routes: analyze/job/results/latest/export/glossary/selfcheck/guide
web/serialize.py         pipeline results -> JSON payload (charts + tables + narrative)
web/static/              index.html, app.js, styles.css, vendored plotly.min.js
scripts/                 build_offline_dataset.py, build_definitions_doc.py, build_example_workbooks.py
```

## Scripts

```bash
python scripts/build_offline_dataset.py       # (re)build the committed price snapshots
python scripts/build_definitions_doc.py       # regenerate docs/METRIC_DEFINITIONS.md
python scripts/build_definitions_doc.py --check   # fail if the page drifted from the glossary
python scripts/build_example_workbooks.py     # regenerate the example input workbooks
```

## Tests and CI

```bash
cd portfolio_model && python -m pytest tests -q
```

100 tests: returns math, ingestion/validation robustness, covariance and portfolio stats,
VaR/CVaR, HHI, correlation clusters, Markov transitions, Monte Carlo path mechanics,
bootstrap, sensitivity interpretation, the rule-flag engine, the offline data layer, override
validation, glossary completeness, documentation freshness, example-workbook ingestion,
degenerate inputs, and an end-to-end offline pipeline run (determinism, no silent NaNs, every
deliverable present). CI runs the suite with `PORTFOLIO_OFFLINE=1` on Python 3.11 and 3.12.

## Key modeling principles

- Every forward-looking number is labeled as model estimate / simulation / scenario / assumption.
- Historical observations, model assumptions, model outputs, and recommendations are kept distinct.
- Monte Carlo vs historical-bootstrap disagreement is reported prominently, not hidden.
- Survivorship bias, look-ahead conventions, transaction costs, and missing tax lots are disclosed.
