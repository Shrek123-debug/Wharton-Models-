# Wharton Models — Local Portfolio Analysis, Simulation & Risk Management

A complete **local** portfolio-analysis system: upload a spreadsheet, and it validates the
input, runs Monte Carlo / Markov-regime / historical-bootstrap simulations, computes risk
metrics, stress tests, sensitivity grids, concentration analysis, a 2033 glide path and
deterministic rule-based flags, then produces an Excel workbook, a written report, PNG
figures and an interactive browser dashboard.

**No LLM. No AI API. No cloud inference.** Every number comes from an explicit formula, a
fixed random seed, and thresholds you configure.

**Runs with zero network.** Price history is committed to the repository
(`portfolio_model/data/offline/`), so a fresh clone can run every model offline.

**Everything is explained.** 70 metric definitions live in one file
(`portfolio_model/src/metric_glossary.py`) and are rendered into the docs page, the workbook
**Definitions** sheet and the web UI **Definitions** tab, so the three can never disagree.

Start with **[docs/TUTORIAL.md](docs/TUTORIAL.md)**.

---

## 1. Setup

```bash
git clone https://github.com/Shrek123-debug/Wharton-Models-.git
cd Wharton-Models-
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements.txt           # exact known-good set: requirements.lock.txt

cd portfolio_model
python main.py --check                    # environment + data self-test, no simulation
```

`--check` verifies Python version, every package, the config, the input workbook, local
price coverage and writable outputs. Each failure prints the command that fixes it.

---

## 2. First run

```bash
cd portfolio_model
python main.py --offline --input data/input/example_portfolio_full.xlsx
```

Expected output:

```
INFO pipeline: Holdings: [...] (weights supplied)
INFO src.market_data.fetch: Offline mode: 9/9 tickers resolved from local data
INFO pipeline: Rule flags: N triggered (M high/critical)
INFO pipeline: Sanity checks passed.
INFO pipeline: Wrote .../portfolio_analysis.xlsx and .../portfolio_analysis_report.docx
```

Web dashboard:

```bash
python run_web.py                # → http://127.0.0.1:8000
python run_web.py --port 8080
```

---

## 3. Market data: three-tier, offline-first

For every ticker the data layer resolves in this order and records which tier answered:

1. **project cache** — `portfolio_model/data/cache/` from a previous run, if fresh
2. **network** — yfinance, only when allowed and reachable
3. **bundled snapshot** — `portfolio_model/data/offline/` (92 committed tickers, adjusted
   close / total-return basis)
4. **unavailable** — an explicit provenance row plus a HIGH data flag naming the fix

Cache keys are stable (`TICKER__<start>__<end|live>.parquet`), so a new day no longer forces
a re-download, and a wider cached window answers a narrower request. `yfinance` is imported
lazily: the offline path works even if it is not installed.

```bash
python scripts/build_offline_dataset.py                          # refresh the committed dataset (online)
python scripts/build_offline_dataset.py --from-workbook your.xlsx
python scripts/build_offline_dataset.py --list
python main.py --offline          # never touch the network
python main.py --refresh          # force a fresh download
```

Config: `historical_data.offline` (`auto` | `always` | `never`), `bundled_dir`,
`max_cache_age_days`, `allow_stale_cache`. Environment override: `PORTFOLIO_OFFLINE=1`.

---

## 4. CLI reference

```bash
python main.py --input path/to.xlsx        # your spreadsheet
python main.py --config path/to.yaml       # alternative config
python main.py --out /tmp/run1             # keep runs separate
python main.py --sims 25000 --seed 7
python main.py --model student_t           # gaussian | lognormal | student_t | historical_residual
python main.py --glide-method none         # none | linear | accelerating | stepwise | custom
python main.py --start-date 2010-01-01 --end-date 2025-12-31
python main.py --offline | --refresh | --no-charts | --quiet
python main.py --check                     # self-test only
```

Exit codes: `0` success · `2` an input or run-option problem you can fix · `3` unexpected
internal error (traceback printed).

Run options are whitelisted **and range-validated**: a bad value raises a message naming the
option instead of crashing mid-simulation.

---

## 5. Web dashboard

| Tab | Contents |
|---|---|
| Overview | KPI tiles, allocation donut, sector bars, executive summary, top rule flags, scorecard |
| Holdings & Sectors | Holdings table, contribution bars, concentration vs cap, sector attribution, sector correlations, theses |
| History | Growth of $100 vs SPY/AGG/60-40, drawdown chart, recovery events, monthly history |
| Monte Carlo | Value fan (p5–p95), terminal distributions, max-drawdown distribution, percentile tables |
| Markov Regime | Transition-matrix heatmap, projected state probabilities by year, state statistics |
| Historical Bootstrap | Block-bootstrap fan of real historical joint return sequences |
| Model Comparison | MC vs Markov vs bootstrap percentiles + disagreement analysis |
| Sensitivity | Return-shift × volatility-multiplier heatmaps |
| Stress Tests | 2008 / 2020 / 2022 crisis replays + hypothetical forward scenarios |
| Risk & Concentration | VaR/CVaR (historical, parametric, simulated), HHI, correlation heatmap, stop-loss backtests |
| Rebalance & Glide | Band triggers with suggested trades, glide path + impact table, max-Sharpe diagnostic |
| Flags & Actions | All rule flags, key risks, prioritized recommendations, decision matrix, monitoring checklist |
| Data Quality | Validation flags, data provenance, assumptions, limitations |
| Methodology | Seed / sims / versions (reproducibility manifest), methodology notes |
| **Tutorial** | `docs/TUTORIAL.md` rendered in the app |
| **Definitions** | All 70 metric definitions with search |

Interpretability features:

- an **_i_ button on every KPI card and table column header** that has a definition — click
  it for what the metric is, what it measures, how to read it for this portfolio, what to do
  about it, and the trap that makes people misread it;
- an **environment pre-flight panel** showing blocking problems and warnings, with fixes,
  before you press Run;
- a **Market data** option (auto / offline only / live required) in Run options.

Charts render from a locally vendored `plotly.min.js` — no CDN, no external requests.

---

## 6. Input spreadsheet format

**Required:** a sheet with a header row containing a **ticker column** plus at least one
sizing column — `Weight`, `Market Value`, or `Shares` + `Price`. The header may sit below
title rows (the first 60 rows are scanned). Values must be static numbers or formula results
**cached by Excel/LibreOffice**.

**Tickers:** `^[A-Z][A-Z0-9.-]{0,11}$` (e.g. `VOO`, `BRK.B`). Cash appears as `CASH`.
Foreign tickers and non-USD rows are flagged and excluded (no FX conversion).

| Canonical | Accepted headers |
|---|---|
| `ticker` | Ticker, Symbol, Security, Company, Name |
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

Numbers: `0.15`, `15%` and `15 %` all read as 15%; `$1,234.50` reads as 1234.50; `(450)`
reads as −450. Duplicate tickers merge; total/subtotal rows are ignored; weights are
normalised to 100% and the run says so; short histories are flagged low-confidence.

Examples (regenerate them with `python scripts/build_example_workbooks.py`):

- `portfolio_model/data/input/example_portfolio_minimal.xlsx` — Ticker + Weight only
- `portfolio_model/data/input/example_portfolio_full.xlsx` — every supported column

Both contain an **Instructions** sheet explaining the columns inside the workbook.

---

## 7. Configuration

`portfolio_model/config/model_config.yaml` — simulation counts, seed, timeline, cashflows,
glide path, risk caps, rebalancing, bootstrap, Markov thresholds, sensitivity grid, crisis
windows, hypothetical shocks, success definitions, stop-loss levels, sector targets, and the
offline-first data settings. Run options override a whitelisted subset; the values used are
recorded in the run manifest.

Simulation timeline: 2027 invest $300k · 2028 invest $150k · 2027–2032 glide phase · 2033
split into reserve (PV of ten $50k payments at 2.9%) plus facility surplus · 2033–2042
reserve phase (success = all ten payments funded).

---

## 8. Outputs

- **Excel** — 20 sheets: Executive Summary, Holdings, Sector Allocation, Correlation Matrix,
  Historical Performance, Monte Carlo, Markov Model, Historical Bootstrap, Model Comparison,
  Sensitivity, Risk, Stress Tests, Glide Path, Rebalancing, Rule Flags, Investment Theses,
  Data Quality, Scorecard, Stop-Loss Backtests, **Definitions**.
- **DOCX** — 24-section written report including rule-based flags and conclusions.
- **Figures** — 16 PNG charts under `outputs/figures/`.
- **Manifest** — `outputs/report/run_manifest.yaml` (config, seed, versions, data provenance).

CLI runs write to `portfolio_model/outputs/`; web runs write to `portfolio_model/outputs/web/`.

---

## 9. Rule-based flags (the suggestions, and where they come from)

`portfolio_model/src/rules/rule_engine.py` compares calculated values against configured
thresholds. Every flag carries:

**id → severity → category → metric → current value → threshold → rule → action → evidence**

Severity ladder: CRITICAL > HIGH > WARNING > MONITOR > INFO.

Rule families: single-position cap, target-weight drift, correlated-group cap, sector cap and
sector target bands, cash floor, pairwise correlation, effective-bet (HHI) concentration,
>20% drawdown review trigger, terminal CVaR tail threshold, reserve-funding probability,
success probability, model disagreement, data confidence, thesis completeness,
rebalancing-band breaches, glide-path discipline, sensitivity fragility.

No flag fires without a configured rule, and no flag is generated by AI.

---

## 10. Documentation

| File | What it is |
|---|---|
| [docs/TUTORIAL.md](docs/TUTORIAL.md) | Setup → spreadsheet → run → how to read the outputs → experiments → troubleshooting |
| [docs/METRIC_DEFINITIONS.md](docs/METRIC_DEFINITIONS.md) | Every metric: formula, what it measures, how to read it, what to do, the trap; plus the ten most common misreadings |
| `portfolio_model/src/metric_glossary.py` | The single source of truth behind the docs page, the workbook Definitions sheet and the web UI Definitions tab |
| `portfolio_model/README.md` | Architecture and module reference |

```bash
python scripts/build_definitions_doc.py           # regenerate the definitions page
python scripts/build_definitions_doc.py --check   # fail if it has drifted from the glossary
```

---

## 11. Tests and CI

```bash
python -m pytest              # from the repo root (pytest.ini configured)
cd portfolio_model && python -m pytest tests -q
```

100 tests cover returns math, ingestion/validation robustness, covariance and portfolio
stats, VaR/CVaR, HHI, correlation clusters, Markov transitions, Monte Carlo path mechanics,
bootstrap, sensitivity interpretation, the rule-flag engine, the offline data layer, override
validation, glossary completeness, documentation freshness, example-workbook ingestion,
degenerate inputs (single holding, all cash, unknown ticker, negative weight, foreign ticker,
crisis windows outside the price history), and an end-to-end offline pipeline run with
determinism and no-silent-NaN checks.

CI (`.github/workflows/ci.yml`) runs `ruff check .` and the suite on Python 3.11 and 3.12
with `PORTFOLIO_OFFLINE=1`, so an accidental dependency on the network fails the build
instead of passing on a laptop.

---

## 12. Key modeling principles

- Every forward-looking number is labelled model estimate / simulation / scenario / assumption.
- Historical observations, assumptions, model outputs and recommendations are kept distinct.
- Monte Carlo vs historical-bootstrap disagreement is reported prominently, not averaged away.
- Survivorship bias, return basis, transaction costs and missing tax lots are disclosed.
- Missing input data is reported as missing; the model never invents it.
- Recommendations are threshold rules traceable to config — never AI-generated opinions.

---

## 13. Troubleshooting

| Problem | Fix |
|---|---|
| `Input validation failed: Missing weights for …` | Provide a weight, market value, or shares+price for **every** holding |
| "No holdings table detected" | Header row with a ticker column + a sizing column, within the first 60 rows; or set `input.sheet` |
| Formula cells read as blank | Open the workbook in Excel/LibreOffice and **save** so values are cached |
| Rows skipped with invalid tickers | Use exchange symbols (`BRK.B`), not company names |
| Ticker dropped: "Ticker unavailable" | `python scripts/build_offline_dataset.py --tickers XYZ` while online |
| Yahoo 429 / rate limited | Run with `--offline`; the committed snapshots are sufficient |
| "no writable cache directory" | Caches are redirected to `portfolio_model/.cache/`; check permissions there |
| Results differ from a previous run | Compare `run_manifest.yaml`: seed, sims, options, data vintage and provenance |
| Web UI: "An analysis is already running" | One run at a time by design; wait for it to finish |
