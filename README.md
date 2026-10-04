# Wharton Investment Competition Toolkit

Tools for the Laura Gao case study: a live-trading tracker/analytics pair for the
real 6-week WInS competition window, and two Excel models for the written
case-study deliverables (IPS / Final Report).

## What's in this repo

```
apps-script/
  investment_tracker_builder.js   Run ONCE to create the tracker spreadsheet
  portfolio_analytics.js          Paste into that spreadsheet's Apps Script editor
models/
  laura_gao_monte_carlo_model.xlsx    16-year (2027-2042) case-study projection
  stock_weighting_model.xlsx          % allocation per stock, given your picks
```

## The two completely separate workflows

**1. Tracking your real WInS trades (6-week competition window)**
- `investment_tracker_builder.js` → creates a Google Sheet with Transactions,
  Holdings Summary, Yearly Summary, and Dashboard tabs.
- `portfolio_analytics.js` → adds Snapshots + Analytics tabs to that *same*
  spreadsheet. Computes Sharpe Ratio and Max Drawdown from your actual trading
  history, using your own risk-free rate assumption (WInS's built-in Sharpe
  uses a different one — its internal cash-interest rate).
- Note: WInS/StockTrak already natively provides transaction history export
  and per-trade Trading Notes — this toolkit only adds what WInS doesn't.

**2. Deciding what to buy and projecting the long-term plan (written report)**
- `stock_weighting_model.xlsx` → give it candidate tickers + expected
  return/volatility, it outputs a suggested % allocation per holding (risk-
  adjusted weighting, respects WInS's 25% position cap, and a correlation-
  group cap so similar stocks can't secretly dominate the portfolio).
- `laura_gao_monte_carlo_model.xlsx` → the 16-year case-study math: Monte
  Carlo + Markov regime-switching projection of the growth bucket (2027-2032),
  reserve-funding certainty test for the 2033-2042 payments, and the
  co-sponsor communication range for the facility contribution.

## Setup — tracking tools

1. Go to script.google.com → New project → paste in `investment_tracker_builder.js`
   → Run `createInvestmentTracker` → check Executions/Logs for the sheet URL.
2. Open that sheet → Extensions → Apps Script → paste in `portfolio_analytics.js`
   → Run `buildSnapshotsSheet` once.
3. Ongoing: log trades in Transactions, update prices in Holdings Summary, run
   `logSnapshotFromTracker` every few days, run `calculateSharpeRatio` /
   `calculateMaxDrawdown` once you have 3+ snapshots.

## Setup — Excel models

Just open either `.xlsx` file directly (Excel or Google Sheets both work).

- **stock_weighting_model.xlsx**: open the **Summary** tab to see the answer.
  Add new candidates on the **Model** tab (Ticker, Name, Bucket, Correlation
  Group, Expected Return, Volatility) — Summary updates instantly.
- **laura_gao_monte_carlo_model.xlsx**: open the **Dashboard** tab for the
  headline numbers (percentile outcomes, Sharpe/Sortino, reserve funding
  success rate, facility-contribution range). Assumptions live on the
  **Assumptions** tab.

## Known limitations (be upfront about these in your report)

- Weighting model assumes zero correlation *within* a bucket except where you
  tag a Correlation Group — it's not a full covariance-matrix optimizer.
- Return/Volatility inputs in both models are illustrative starting points,
  not live market data — verify/replace before finalizing.
- Monte Carlo/Markov/walk-forward validation stubs in `portfolio_analytics.js`
  are intentionally unimplemented until there's real multi-week snapshot data
  to fit them to.
