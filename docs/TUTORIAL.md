# Tutorial — from a spreadsheet to a defensible portfolio decision

This is the file to read if you have never run this project before. It assumes no
background in quantitative finance. Every command is copy-pasteable, and every step says
what you should see if it worked.

**What this project does.** It reads a portfolio spreadsheet, measures the allocation,
simulates it forward under three independent engines (Monte Carlo, Markov regimes,
historical bootstrap), measures the risk, tests it against real crises, and produces an
Excel workbook, a Word report, PNG figures and an interactive local web dashboard.

**What it does not do.** It does not predict markets, it does not use AI or an LLM, and it
does not invent data you did not supply. Every number traces to a formula, a config value,
or a row in your spreadsheet.

---

## 1. Five-minute quick start

```bash
git clone https://github.com/Shrek123-debug/Wharton-Models-.git
cd Wharton-Models-
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd portfolio_model
python main.py --check             # environment self-test, no simulation
python main.py --offline --sims 5000 --input data/input/example_portfolio_full.xlsx
```

You should see, in order:

1. `Self-test PASSED` with a line for Python, each package, the input workbook, and
   `offline dataset present: .../data/offline (92 tickers)`.
2. `Holdings: [...] (weights supplied)` and `Offline mode: 8/8 tickers resolved from local data`.
3. `Sanity checks passed.` then `Wrote .../portfolio_analysis.xlsx and .../portfolio_analysis_report.docx`.
4. A three-line summary of Monte Carlo, bootstrap and Markov results.

**Nothing here needs the internet.** Prices come from `portfolio_model/data/offline/`,
which is committed to the repository. If a run does need the internet, it is because you
asked for a ticker that is not in that dataset — the self-test tells you which one.

---

## 2. Step 1 — prepare your spreadsheet

The model needs one table with a header row. The header may sit below title rows; the
ingestion scans the first 60 rows of every sheet to find it.

### Minimum viable table

| Ticker | Weight |
|---|---|
| VOO | 0.45 |
| ADBE | 0.15 |
| IEF | 0.20 |
| SHY | 0.10 |
| CASH | 0.10 |

That is enough. Weights must sum to 1.0 (they are renormalised if they do not).

### Full table (recommended)

| Column | Required | Accepted header names | What it is for |
|---|---|---|---|
| `Ticker` | **yes** | ticker, symbol, security, company, name | identifies the holding and the price series |
| `Portfolio Weight` | one of these three | portfolio weight, weight, % of portfolio | the allocation being analysed |
| `Market Value` | one of these three | market value, current value, value, position value | weights derived as value ÷ total |
| `Shares` + `Price` | one of these three | shares/quantity + current price | weights derived from shares × price |
| `Asset Class` | recommended | asset class, class, bucket, type | drives equity/bond/cash logic and stress mapping |
| `Sector` | recommended | sector, GICS sector, industry sector | sector caps and sector attribution |
| `Expected Return` | recommended | expected return, exp return, mean return | the simulation's central assumption |
| `Volatility` | recommended | volatility, volatility (std dev), std dev, risk | dispersion used by every engine |
| `Investment Thesis` | recommended | investment thesis, thesis, why own | missing theses become governance flags |
| `Target Weight` | optional | target weight, target allocation | enables drift flags |
| `Correlation Group` | optional | correlation group, group, cluster | enables correlated-group caps |
| `Cost Basis` | optional | cost basis, avg cost, cost | enables dollar P&L |
| `Currency` | optional | currency, ccy | non-USD rows are excluded and reported |

### Formats the reader accepts

- `0.15`, `15%`, `15 %` and `0.1500` are all read as 15%.
- `$1,234.50` and `1,234.50` are read as 1234.50.
- `(450)` is read as −450.
- Tickers must look like `[A-Z][A-Z0-9.-]{0,11}`. `Apple Inc.` is skipped and reported as a
  skipped row — put the ticker in the column and the name elsewhere.
- Formulas are fine **only if the workbook was saved by Excel/LibreOffice** so cached values
  exist. If a column is formulas with no cached values, the run warns and tells you to open
  and re-save the file.

Two ready-made files are in the repo:

- `portfolio_model/data/input/example_portfolio_minimal.xlsx` — ticker + weight only.
- `portfolio_model/data/input/example_portfolio_full.xlsx` — the full column set, with an
  `Instructions` sheet inside the workbook.

---

## 3. Step 2 — run it

```bash
python main.py                                   # uses config input path
python main.py --input path/to/your.xlsx         # your spreadsheet
python main.py --offline                         # never touch the network
python main.py --refresh                         # re-download prices (needs internet)
python main.py --sims 25000 --model student_t    # heavier tails, more simulations
python main.py --glide-method none               # compare against no de-risking
python main.py --no-charts --quiet               # fast smoke run
python main.py --out /tmp/run1                   # keep runs separate
python main.py --variant glide_end_equity=0.35   # run again with that change and diff them
```

`--variant` is the assumption experiment, done for you: the portfolio runs twice, and the CLI
prints baseline versus variant for the decision-relevant metrics — median terminal value, tail
percentile, reserve-funding probability, CVaR, drawdown probabilities, effective independent
bets and the rule-flag counts — each with the absolute change, the percentage change, and
whether it moved better or worse. Flags that appear or disappear between the two runs are
listed with the action attached. The table is also written to `outputs/compare/run_comparison.csv`.

Exit codes: `0` success, `2` an input or run-option problem you can fix, `3` an unexpected
internal error (the traceback is printed).

Outputs land in `portfolio_model/outputs/`:

```
outputs/spreadsheet/portfolio_analysis.xlsx     21 sheets, opening on Read Me, including Definitions
outputs/report/portfolio_analysis_report.docx   written report
outputs/figures/*.png                           16 charts
outputs/report/run_manifest.yaml                seed, sims, versions, data provenance
```

---

## 4. Step 3 — read the workbook in the right order

Do not read it front to back. Read it as answers to six questions.

| Your question | Go to | Read this |
|---|---|---|
| Can the 2033 obligation actually be funded? | **Model Comparison**, **Risk** | *Probability reserve fully funded* — compare Monte Carlo with bootstrap and believe the lower one |
| How bad can it get? | **Monte Carlo**, **Historical Bootstrap** | p5 and p10 terminal values, CVaR 95%, P(>20% drawdown) |
| Is this actually diversified? | **Holdings**, **Risk** | *Effective number of independent bets*, top-3 weight, correlation clusters |
| Which decisions dominate the outcome? | **Rule Flags** | flags sorted CRITICAL → INFO, each with value, threshold, rule and action |
| How much do my assumptions matter? | **Sensitivity** | the grid: find the base cell, then walk outward until success collapses |
| What would a real crisis do to this mix? | **Stress Tests** | 2008 / 2020 / 2022 replays versus the 60/40 benchmark |

The **Definitions** sheet defines every column in every other sheet. The same text is in
[docs/METRIC_DEFINITIONS.md](METRIC_DEFINITIONS.md), generated from the same source file.

---

## 5. Step 4 — the web dashboard

```bash
python run_web.py                # http://127.0.0.1:8000
python run_web.py --port 8080
```

The page loads a self-test panel first: if your machine or your tickers are missing
something, it says what and how to fix it **before** you press Run.

- **Upload & Run** — drop an `.xlsx`, or press *Run with example portfolio*.
- **Run options** — simulations, seed, MC model, glide method, 2033 equity target, bands,
  caps, bootstrap method/block size, and market-data mode (auto / offline only / live
  required). Every option is validated: a bad value is rejected with a message naming the
  option, not a crash mid-simulation.
- **Tabs** — Overview, Holdings & Sectors, History, Monte Carlo, Markov Regime, Historical
  Bootstrap, Model Comparison, Sensitivity, Stress Tests, Risk & Concentration, Rebalance &
  Glide, Flags & Actions, What-If Compare, Data Quality, Methodology, Tutorial, Definitions,
  Guided Walkthrough, Run History.
- **Run History** — every completed run on this machine, newest first, with its headline numbers
  and the options it used. Mark one row A and another B to compare two runs you already made,
  using the same better/worse semantics as What-If Compare. Runs are stored under
  `portfolio_model/outputs/web/runs/`, so the history survives a restart.
- **Guided Walkthrough** — every headline metric recalculated with *your* portfolio's numbers:
  the HHI written out as the sum of your squared weights, the required reserve written out as
  the discounting that produced it, success probabilities written as "962 of 1,000 paths", the
  clusters with their combined weight, and each high-severity flag as "measured 0.3000 against
  threshold 0.2500". Deterministic — these are the engine's own values, shown as arithmetic.
- **What-If Compare** — fill in *Compare against a variant* in Run options (for example
  `glide_end_equity=0.35`) and the same portfolio runs twice. The tab shows every
  decision-relevant metric side by side with the change, the percentage change, whether it
  moved better or worse, and the rule flags that appear or disappear.
- **"What this means for your portfolio"** — the first card on Overview. It states the
  reserve-funding verdict, the tail shortfall against the typical outcome, how many
  independent bets the holdings really represent, the tail cost, and the action behind the
  highest-severity flags. Each claim carries its own *i* button.
- **Chart captions** — under every figure: what it shows, how to read it, and the trap that
  makes people read it wrong. Captions are generated from the same file as the Definitions
  tab, so a chart can never ship without an explanation.
- **Correlated clusters** — on Risk & Concentration, a table of holdings that move together,
  with the weight they carry *combined*. This is where "12 holdings, 4 bets" becomes visible.
- **The *i* buttons** — every KPI card and every table column header that has a definition
  shows a small *i*. Click it: the definition, how to read it for this portfolio, what to do
  about it, and the trap that makes people misread it.
- **Definitions tab** — all 70 metric definitions with a search box.

---

## 6. Step 5 — make the numbers move on purpose

The fastest way to understand the model is to change one assumption and watch which
answers move.

| Change | Where | What moves | What it teaches you |
|---|---|---|---|
| Equity returns −2pp | `Expected Return` column | median terminal, success probability, reserve funding | the plan's dependence on your return assumption |
| `--model student_t` | CLI / web option | p5, CVaR, reserve funding fall | the price of assuming normal returns |
| `--bootstrap-method iid` | CLI / web option | bootstrap gets friendlier | how much of the risk is *sequences* of bad days |
| `--glide-method none` | CLI / web option | drawdowns and reserve risk rise, median barely changes | a glide path buys safety, not return |
| `reserve_discount_rate` 0.029 → 0.045 | config | required reserve falls | how much of the obligation is an assumption |
| `max_position_weight` 0.25 → 0.20 | config / web | new position flags, different rebalancing trades | caps are policy, and policy generates the suggestions |

Do this once with the example portfolio. It takes four runs and about two minutes, and it
explains the model better than any description.

---

## 7. Read your first result, number by number

Open `docs/sample_output/sample_output.xlsx` (or run the example yourself) and follow the same
order a decision actually takes. Every figure below is from that committed sample run: 8 holdings,
4,000 simulations, seed 42, offline data.

**1. Start with the obligation, not the portfolio.** You put in **$450,000** across 2027-2028. The
plan promises **10 payments of $50,000 from 2033 to 2042**, which discounted at 2.9% is a required
reserve of **$441,127** standing still in 2033. Everything else in the report is measured against
that one number.

**2. Then look at the bad end of the range, not the middle.** Monte Carlo's median 2033 value is
**$639,725** — comfortable. The 5th percentile is **$472,144** and the 95th is **$876,201**. The
median is what usually happens; the 5th percentile is what you have to survive. A plan sized on
$639,725 is a plan with no plan for the unlucky 5%.

**3. The decision metric is funding, not growth.** "Terminal value above what I put in" passes in
**97.2%** of Monte Carlo runs and **99.0%** of bootstrap runs — nearly meaningless, because the
obligation is bigger than "not losing money". The metric that matters is *all ten payments funded*:
**2,392 of 4,000 Monte Carlo paths (59.8%)** and **1,689 of 4,000 bootstrap paths (42.2%)**. The
planning standard is 90%. Plan against **42.2%**, the lower of the two, because the bootstrap only
uses sequences that actually happened.

**4. Concentration, shown as arithmetic.** Eight holdings, and the HHI is

```
0.063² + 0.210² + 0.044² + 0.030² + 0.190² + 0.123² + 0.300² + 0.040² = 0.1937
```

A perfectly even eight-holding portfolio would be 0.1250. Normalised, this portfolio is **5.16
independent bets**, not eight. That single number explains why the funding probabilities are lower
than the holding count suggests.

**5. Two holdings can be one bet.** IEF and SHY have a **0.78** correlation and carry **31.3%**
between them. They are labelled as bonds in two funds; in a rate shock they are one position. The
group cap is 40%, so this is legal and still worth knowing.

**6. Now read the flags, in severity order, with their arithmetic:**

| Flag | Measured | Against | What it actually says |
|---|---|---|---|
| **POS-01** HIGH | VOO 0.3000 | cap 0.2500 | One name carries 30% of the plan. Policy breach, not a market view. |
| **RESV-03** HIGH | 0.4223 | standard 0.9000 | **The most important finding in the report.** The obligation is likely not met. |
| **MODEL-04** HIGH | 17.6pp spread | — | Monte Carlo and bootstrap disagree on funding. Report a range, not a point. |
| **CORR-02** WARNING | IEF-SHY 0.7847 | threshold 0.70 | Two "different" bond funds move together. |
| **REBAL-06** WARNING | VOO 0.3000 | band 0.2500 | The same breach seen from the rebalancing side: a trade is triggered. |
| **THESIS-05** MONITOR | 1 holding | 0 expected | A position exists that the model cannot explain. |

Read flags in severity order and stop when the actions stop making sense — that is usually the
point where you need a different assumption, not a different portfolio.

**7. Change one assumption and re-read.** Run the same file with `--variant glide_end_equity=0.35`
(or type it in the dashboard's *Compare against a variant* box). The median terminal value moves,
but the funding probability moves **more**, and a drawdown flag disappears. That is the lesson:
the glide-path end target is a funding decision disguised as an allocation setting.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `CONFIG PROBLEM: … is missing (expected …)` | a key was deleted or mistyped in `model_config.yaml` | the message names each key and what it expected; restore that key from the shipped config |
| `must be one of gaussian, lognormal, student_t, historical_residual` | typo in `simulation.model` | use one of the listed values |
| `glide_end_year (…) is before simulation.start_year` | timeline keys disagree | make the glide end year at or after the start year |
| `Input validation failed: ...` | no usable weights column | add `Portfolio Weight`, or `Market Value`, or `Shares` + `Price` |
| `No holdings table detected` | header not found in the first 60 rows | put the header row higher, or set `input.sheet` in the config |
| Rows skipped with "invalid/unsupported ticker" | company names instead of tickers | use exchange tickers |
| Column "contains formula cells with no cached values" | file written by a tool that does not compute values | open in Excel/LibreOffice and save, or export static values |
| `Ticker unavailable` / holding dropped | no cache, no network, no bundled snapshot for that ticker | `python scripts/build_offline_dataset.py --tickers XYZ` while online |
| Yahoo returns 429 / rate limited | too many live downloads | run with `--offline`; the committed snapshots are enough |
| `no writable cache directory` | locked-down home directory | the code already redirects caches to `portfolio_model/.cache`; check permissions on that folder |
| Web UI shows "An analysis is already running" | one run at a time by design | wait for it to finish |
| Results differ from a previous run | different seed, sims, data vintage or options | check `run_manifest.yaml` and the Methodology tab |

---

## 9. Reproducibility and data provenance

Every run records its seed, simulation count, package versions and — importantly — where
each price series came from: `cache`, `network`, or `bundled snapshot`, with the data
as-of date. Two runs that disagree are usually disagreeing about data vintage, not about
mathematics. Check the **Data Quality** tab or the Data Quality sheet first.

To refresh the committed dataset while online:

```bash
python scripts/build_offline_dataset.py                 # default universe
python scripts/build_offline_dataset.py --from-workbook your.xlsx
python scripts/build_offline_dataset.py --list
```

---

## 10. Where to read next

- [docs/METRIC_DEFINITIONS.md](METRIC_DEFINITIONS.md) — every metric, what it indicates, and the ten most common misreadings.
- `portfolio_model/README.md` — configuration reference and architecture.
- `portfolio_model/config/model_config.yaml` — every assumption, commented.
- `portfolio_model/src/metric_glossary.py` — the single source of truth behind the docs page, the workbook Definitions sheet and the web UI Definitions tab.
