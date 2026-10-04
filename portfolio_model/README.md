# Portfolio Modeling Agent

Complete portfolio-analysis and forward-simulation system: ingestion, validation,
market data, Monte Carlo, Markov regime, and historical-bootstrap engines,
sensitivity analysis, stress tests, risk metrics, and polished Excel + DOCX reporting.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install numpy pandas scipy yfinance matplotlib openpyxl python-docx pyyaml pytest pyarrow
cd portfolio_model
../.venv/bin/python main.py                 # uses config/model_config.yaml input path
../.venv/bin/python main.py --input ../models/stock_weighting_model.xlsx
../.venv/bin/python main.py --sims 50000 --seed 7
```

To use a different portfolio spreadsheet, either pass `--input path.xlsx` or change
`input.spreadsheet` in `config/model_config.yaml`. The ingestion layer auto-detects
column names (Ticker/Symbol, Shares/Quantity, Market Value, Weight, Sector, Bucket, etc.).

## Simulation timeline (Laura Gao portfolio)

- 2027: invest $300,000; 2028: invest $150,000
- 2027-2032: growth phase with configurable glide path (default linear 70% -> 55% equity)
- 2031: sponsor range = projected facility-contribution percentiles
- 2033: split into reserve (PV of ten $50,000 payments at 2.9%) + facility contribution (surplus)
- 2033-2042: reserve phase, $50,000 paid at start of each year; success = all 10 funded

## Outputs

- `outputs/spreadsheet/portfolio_analysis.xlsx` — 17 sheets (dashboard, holdings, sectors,
  correlations, history, MC, Markov, bootstrap, comparison, sensitivity, risk, stress,
  glide path, rebalancing, theses, data quality, scorecard)
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
