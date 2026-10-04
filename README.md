# Wharton Models — Local Portfolio Analysis & Risk Management

A complete **local** portfolio-analysis web application: upload a spreadsheet, and the app
validates it, runs Monte Carlo / Markov-regime / historical-bootstrap simulations, computes
risk metrics, stress tests, sensitivity grids, concentration analysis, a 2033 glide path,
deterministic rule-based risk flags, and exports an Excel workbook + written report — all
displayed in an interactive browser dashboard.

**No LLM. No AI API. No cloud inference.** Every number is computed on your machine from
explicit formulas, a fixed random seed, and thresholds you configure. After installation the
app runs entirely locally (market data is fetched once and cached).

---

## 1. First-time setup

```bash
cd portfolio_model
python3 -m venv .venv
.venv/bin/pip install numpy pandas scipy yfinance matplotlib openpyxl python-docx pyyaml pytest pyarrow fastapi "uvicorn[standard]" python-multipart
```

> The repo already contains a ready `.venv` at the project root — if you are using it, skip
> the venv creation and use `../.venv/bin/...` in place of `.venv/bin/...` below.

---

## 2. Run the web dashboard

```bash
cd portfolio_model
../.venv/bin/python run_web.py            # → http://127.0.0.1:8000
../.venv/bin/python run_web.py --port 8080   # optional custom port
```

Then, in your browser at `http://127.0.0.1:8000`:

1. **Upload** your portfolio spreadsheet (`.xlsx`) in the left panel — or press
   **Run with example portfolio** to try the bundled model first.
2. **Adjust run options** (all deterministic, seed-controlled):
   - Simulations per engine (2,000 – 25,000) and random seed
   - Monte Carlo model: Gaussian / Lognormal / Student-t / Historical-residual
   - Glide path method (none / linear / accelerating / stepwise) and 2033 equity target
   - Rebalancing band, transaction cost
   - Risk caps: max position, max sector, max correlated group, min cash
   - Correlation threshold, bootstrap method (block / IID) and block size
3. Press **Run Analysis**. The pipeline runs locally (typically 15–90s depending on
   simulation count) and the dashboard renders.
4. Explore the **14 tabs** (see section 5).
5. Press **Excel Workbook** / **Written Report** in the top bar to download the full exports.

The dashboard's charts are rendered with a locally vendored `plotly.min.js` — no CDN, no
external requests.

---

## 3. Input spreadsheet format

**Required:** at least one sheet with a header row containing a **ticker column** plus at
least one sizing column — `Weight`, `Market Value`, or `Shares` + `Price`. The header may
appear below title rows. Values must be static numbers or formula results **cached by
Excel/LibreOffice** (open and save the file before uploading).

**Ticker rules:** US-listed symbols matching `^[A-Z][A-Z0-9.-]{0,11}$` (e.g. `VOO`, `BRK.B`).
Cash must appear as `CASH`. Foreign tickers and non-USD currency rows are flagged and
excluded (no FX conversion).

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
flag; weights normalized to 100%; missing sectors assigned via a documented GICS lookup;
short price histories flagged low-confidence.

**Examples:** `portfolio_model/data/input/example_portfolio_full.xlsx` (all columns) and
`portfolio_model/data/input/example_portfolio_minimal.xlsx` (Ticker + Weight only).

---

## 4. Market data (local cache)

Historical prices are dividend/split-adjusted daily closes pulled once via yfinance and
cached under `portfolio_model/data/cache/` (parquet). Cached tickers work offline. New
tickers in an uploaded portfolio require one fetch.

---

## 5. What the dashboard shows

| Tab | Contents |
|---|---|
| Overview | KPI tiles, allocation donut, sector bars, executive summary, top rule flags, scorecard |
| Holdings & Sectors | Holdings table, contribution bars, concentration vs cap, sector attribution, sector correlations, investment theses |
| History | Growth of $100 vs SPY/AGG/60-40, drawdown chart, recovery events, monthly history |
| Monte Carlo | Value fan (p5–p95), terminal distributions, max-drawdown distribution, percentile tables |
| Markov Regime | 5-state transition-matrix heatmap, projected state probabilities by year, state statistics |
| Historical Bootstrap | Block-bootstrap fan of real 2000–2025 joint return sequences |
| Model Comparison | MC vs Markov vs bootstrap percentile bars + disagreement analysis |
| Sensitivity | Return-shift × volatility-multiplier heatmaps (success probability, median terminal) |
| Stress Tests | 2008 / 2020 / 2022 crisis tests + hypothetical forward scenarios |
| Risk & Concentration | VaR/CVaR (historical, parametric, simulated), HHI, correlation heatmap, stop-loss backtests |
| Rebalance & Glide | Band triggers with suggested trades, 2033 glide path + impact table, max-Sharpe diagnostic |
| Flags & Actions | All rule-based flags, key risks, prioritized recommendations, decision matrix, monitoring checklist |
| Data Quality | Validation flags, assumptions, limitations |
| Methodology | Seed / sim count / versions (reproducibility manifest), methodology notes |

---

## 6. Rule-based flags (non-AI recommendations)

`portfolio_model/src/rules/rule_engine.py` evaluates explicit thresholds from
`portfolio_model/config/model_config.yaml` (and the Run options panel). Every flag reports:

**metric → current value → threshold → rule → suggested action → severity**
(CRITICAL / HIGH / WARNING / MONITOR).

Example output:

```text
WARNING

Technology allocation: 38.4%
Target allocation: 25.0%
Allowed upper band: 30.0%

Rule:
Sector allocation > target + 5 percentage points

Suggested action:
Review/rebalance technology exposure.

This is a rule-based portfolio risk flag, not an AI-generated recommendation.
```

Rule families checked: single-position cap, correlated-group cap, sector cap and sector
target bands, cash floor, pairwise correlation threshold, >20% drawdown review trigger,
terminal CVaR tail threshold, reserve-funding probability, success probability, model
disagreement magnitude, data confidence, thesis completeness, rebalancing-band breaches,
glide-path discipline, and sensitivity fragility.

Flags appear in the **Flags & Actions** tab, the Excel **Rule Flags** sheet, and report
section 19.5.

---

## 7. Configuration

Central config: `portfolio_model/config/model_config.yaml` — simulation counts, seed,
timeline, cashflows, glide path, risk caps, rebalancing, bootstrap, Markov thresholds,
sensitivity grid, crisis windows, hypothetical shocks, success definitions, stop-loss
levels, sector targets. The Run options panel overrides a whitelisted subset per run;
the chosen values are recorded in the run manifest.

Simulation timeline (Laura Gao portfolio): 2027 invest $300k, 2028 invest $150k,
2027–2032 glide phase, 2033 split into reserve (PV of ten $50k payments at 2.9%) +
facility surplus, 2033–2042 reserve phase (success = all 10 payments funded).

---

## 8. Outputs

- **Excel** — 19 sheets: Executive Summary, Holdings, Sector Allocation, Correlation
  Matrix, Historical Performance, Monte Carlo, Markov Model, Historical Bootstrap, Model
  Comparison, Sensitivity, Risk, Stress Tests, Glide Path, Rebalancing, **Rule Flags**,
  Investment Theses, Data Quality, Scorecard, Stop-Loss Backtests.
- **DOCX** — 24-section written report including rule-based flags and conclusions.
- **Figures** — 15 static charts under `outputs/figures/`.
- **Manifest** — `outputs/report/run_manifest.yaml` (config, seed, versions) for
  reproducibility.

Web runs write to `portfolio_model/outputs/web/`; CLI runs write to `portfolio_model/outputs/`.

---

## 9. CLI (no browser)

```bash
cd portfolio_model
../.venv/bin/python main.py                 # uses config input path
../.venv/bin/python main.py --input ../models/stock_weighting_model.xlsx
../.venv/bin/python main.py --sims 50000 --seed 7
```

---

## 10. Tests

```bash
cd portfolio_model && ../.venv/bin/python -m pytest tests/ -q
```

Covers returns math, validation/ingestion robustness, portfolio covariance, VaR/CVaR,
HHI/concentration, Markov transitions, Monte Carlo path mechanics, bootstrap, sensitivity
grid, and the rule-flag engine (every flag must carry metric / value / threshold / rule /
action / severity).

---

## 11. Key modeling principles

- Every forward-looking number is labeled as model estimate / simulation / scenario / assumption.
- Historical observations, model assumptions, model outputs, and recommendations are kept distinct.
- Monte Carlo vs historical-bootstrap disagreement is reported prominently, not hidden.
- Survivorship bias, look-ahead conventions, transaction costs, and missing tax lots are disclosed.
- Recommendations are threshold rules traceable to config — never opinions generated by AI.

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| "No holdings table detected" | Ensure a header row with a ticker column + weight/value/shares×price. |
| Formula cells read as blank | Open the workbook in Excel/LibreOffice and **save** so values are cached, or paste as static values. |
| Rows skipped with invalid tickers | Only US-listed symbols and `CASH` are supported; foreign tickers are flagged. |
| Currency-mismatch exclusion | Non-USD rows are dropped (no FX conversion); convert before upload if desired. |
| "Missing weights for: …" | Provide a weight (or market value, or shares+price) for **every** holding. |
| New tickers slow the first run | One-time yfinance fetch; subsequent runs use the local cache. |
