# Portfolio Modeling Agent

Complete portfolio-analysis and forward-simulation system: ingestion, validation,
market data, Monte Carlo, Markov regime, and historical-bootstrap engines,
sensitivity analysis, stress tests, risk metrics, deterministic rule-based risk
flags, and polished Excel + DOCX reporting — with a **fully local interactive
web dashboard**. No LLM / AI API / cloud inference is used anywhere.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install numpy pandas scipy yfinance matplotlib openpyxl python-docx pyyaml pytest pyarrow fastapi "uvicorn[standard]" python-multipart
cd portfolio_model
```

### Web UI (recommended)

```bash
../.venv/bin/python run_web.py            # opens http://127.0.0.1:8000
../.venv/bin/python run_web.py --port 8080
```

1. Open the dashboard in your browser.
2. Upload a portfolio `.xlsx` (or press *Run with example portfolio*).
3. Adjust run options (simulations, seed, MC model, glide method, bands, caps) and press **Run Analysis**.
4. Explore 14 tabs: Overview, Holdings & Sectors, History, Monte Carlo, Markov Regime,
   Historical Bootstrap, Model Comparison, Sensitivity, Stress Tests, Risk & Concentration,
   Rebalance & Glide, Flags & Actions, Data Quality, Methodology.
5. Interactive Plotly charts (donut, heatmaps, fan charts, distributions, sensitivity
   heatmaps, glide area, scorecard) render from a locally vendored `plotly.min.js` — no CDN.
6. Download the full **Excel workbook** (19 sheets incl. *Rule Flags*) and **written DOCX report**.

All analysis runs on your machine. Market data is fetched once via yfinance and cached
under `data/cache/`; subsequent runs work offline for cached tickers.

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
../.venv/bin/python main.py                 # uses config/model_config.yaml input path
../.venv/bin/python main.py --input ../models/stock_weighting_model.xlsx
../.venv/bin/python main.py --sims 50000 --seed 7
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

- `outputs/spreadsheet/portfolio_analysis.xlsx` — 19 sheets (dashboard, holdings, sectors,
  correlations, history, MC, Markov, bootstrap, comparison, sensitivity, risk, stress,
  glide path, rebalancing, rule flags, theses, data quality, scorecard, stop-loss)
- `outputs/report/portfolio_analysis_report.docx` — 23-section written report
- `outputs/figures/` — 15 charts
- `outputs/report/run_manifest.yaml` — config, seed, versions (reproducibility)

## Tests

```bash
cd portfolio_model && ../.venv/bin/python -m pytest tests/ -q
```

## Key modeling principles

- Every forward-looking number is labeled as model estimate / simulation / scenario / assumption.
- Historical observations, model assumptions, model outputs, and recommendations are kept distinct.
- Monte Carlo vs historical-bootstrap disagreement is reported prominently, not hidden.
- Survivorship bias, look-ahead conventions, transaction costs, and missing tax lots are disclosed.
