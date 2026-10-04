/**
 * PORTFOLIO ANALYTICS ENGINE — TEMPLATE (v2, slimmed down)
 * ---------------------------------------------------------------------
 * IMPORTANT CONTEXT: WInS/StockTrak already natively provides Transaction
 * History (exportable to Excel), per-trade Trading Notes, and an
 * auto-calculated Sharpe/Treynor Ratio. This script is NOT trying to
 * rebuild any of that. It only covers what WInS does NOT give you:
 *   - Max Drawdown
 *   - A Sharpe Ratio using YOUR OWN risk-free rate assumption (for
 *     methodology transparency in your report)
 *   - Forward-looking Monte Carlo / Markov projections (WInS only
 *     reports what already happened, never what might happen next)
 *
 * The Snapshots tab below is your data source either way: type a value
 * in by hand, OR paste rows directly from a WInS Portfolio
 * Summary/Transaction History export — same two columns (Date, Value)
 * work for both.
 *
 * WHAT'S ACTUALLY WORKING RIGHT NOW:
 *   - buildSnapshotsSheet()      -> creates the log you'll fill in
 *   - getPortfolioValueSeries()  -> reads it
 *   - getPeriodReturns()         -> converts it to % returns
 *   - calculateSharpeRatio()     -> fully built
 *   - calculateMaxDrawdown()     -> fully built (the "one other metric")
 *
 * WHAT'S STUBBED (TODO — needs more real snapshots before it's worth running):
 *   - runMonteCarloSimulation()
 *   - runMarkovRegimeModel()
 *   - walkForwardValidateMarkov() -> validation ONLY applies here,
 *                                     not to Sharpe/drawdown (see note below)
 * ---------------------------------------------------------------------
 */

// ======================================================================
// CONFIG — edit these as your strategy/assumptions change
// ======================================================================
const RISK_FREE_RATE_ANNUAL = 0.041;   // ~3-month T-bill yield (update periodically)
const SNAPSHOT_SHEET_NAME   = 'Snapshots';
const ANALYTICS_SHEET_NAME  = 'Analytics';

// How often you plan to log a snapshot. This controls annualization math.
// If you log every trading day, use 252. If every week, use 52.
const PERIODS_PER_YEAR = 52; // default assumption: weekly snapshots

// ======================================================================
// SETUP — run this once to create the Snapshots tab
// ======================================================================
function buildSnapshotsSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (ss.getSheetByName(SNAPSHOT_SHEET_NAME)) return; // already exists

  const sheet = ss.insertSheet(SNAPSHOT_SHEET_NAME);
  sheet.getRange(1, 1, 1, 3)
    .setValues([['Date', 'Total Portfolio Value', 'Notes']])
    .setFontWeight('bold')
    .setBackground('#1c4587')
    .setFontColor('white');
  sheet.setFrozenRows(1);
  sheet.getRange('A2:A1000').setNumberFormat('yyyy-mm-dd');
  sheet.getRange('B2:B1000').setNumberFormat('$#,##0.00');

  // One example row. DELETE this once you start logging real snapshots.
  sheet.getRange('A2:C2').setValues([[new Date(), 450000, 'Example row - delete me']]);

  Logger.log('Snapshots tab created. Log a value every few days during trading.');
}

// ======================================================================
// STEP 1b: AUTO-SNAPSHOT — leeches off the ORIGINAL tracker's tabs
// (Transactions + Holdings Summary) instead of asking you to manually
// re-total your portfolio every time.
// ======================================================================
const HOLDINGS_SHEET_NAME = 'Holdings Summary';
const TRANSACTIONS_SHEET_NAME = 'Transactions';

/**
 * Reads the ORIGINAL tracker's tabs and logs today's total portfolio value
 * into Snapshots automatically:
 *   Total = SUM(Holdings Summary "Market Value" column)
 *         + latest "Running Cash Balance" from Transactions
 *
 * Requirement: Holdings Summary's "Current Price" column must be up to
 * date (you still have to type that in from WInS) — this function just
 * saves you from manually adding everything up and typing a grand total.
 */
function logSnapshotFromTracker() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  const holdings = ss.getSheetByName(HOLDINGS_SHEET_NAME);
  if (!holdings) throw new Error('Could not find "' + HOLDINGS_SHEET_NAME + '" tab.');
  const holdingsRows = holdings.getRange(2, 1, Math.max(holdings.getLastRow() - 1, 0), 5).getValues();
  // Column E (index 4) = Market Value
  const holdingsValue = holdingsRows.reduce((sum, row) => {
    const marketValue = row[4];
    return sum + (typeof marketValue === 'number' ? marketValue : 0);
  }, 0);

  const transactions = ss.getSheetByName(TRANSACTIONS_SHEET_NAME);
  if (!transactions) throw new Error('Could not find "' + TRANSACTIONS_SHEET_NAME + '" tab.');
  const txRows = transactions.getRange(2, 1, Math.max(transactions.getLastRow() - 1, 0), 9).getValues();
  // Column I (index 8) = Running Cash Balance — take the last non-blank value
  let cashBalance = 0;
  for (let i = txRows.length - 1; i >= 0; i--) {
    if (typeof txRows[i][8] === 'number') {
      cashBalance = txRows[i][8];
      break;
    }
  }

  const total = holdingsValue + cashBalance;

  buildSnapshotsSheet(); // no-op if it already exists
  const snapshots = ss.getSheetByName(SNAPSHOT_SHEET_NAME);
  snapshots.appendRow([new Date(), total, 'Auto-calculated from tracker']);

  Logger.log('Logged snapshot: Holdings $' + holdingsValue.toFixed(2) +
             ' + Cash $' + cashBalance.toFixed(2) + ' = $' + total.toFixed(2));
  return total;
}

// ======================================================================
// STEP 1c: SHARED DATA PIPELINE
// Every metric below (built or stubbed) reads from these two functions.
// ======================================================================

/**
 * Reads the Snapshots tab and returns a date-sorted array of
 * { date: Date, value: Number }, skipping blank/invalid rows.
 */
function getPortfolioValueSeries() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SNAPSHOT_SHEET_NAME);
  if (!sheet) throw new Error('Run buildSnapshotsSheet() first.');

  const rows = sheet.getRange(2, 1, Math.max(sheet.getLastRow() - 1, 0), 2).getValues();
  const series = rows
    .filter(r => r[0] instanceof Date && typeof r[1] === 'number')
    .map(r => ({ date: r[0], value: r[1] }))
    .sort((a, b) => a.date - b.date);

  return series;
}

/**
 * Converts a value series into simple period-over-period returns:
 * r_t = (V_t / V_(t-1)) - 1
 * Returns an array of numbers, one shorter than the input series.
 */
function getPeriodReturns(valueSeries) {
  const returns = [];
  for (let i = 1; i < valueSeries.length; i++) {
    const prev = valueSeries[i - 1].value;
    const curr = valueSeries[i].value;
    if (prev > 0) returns.push((curr / prev) - 1);
  }
  return returns;
}

function mean(arr) {
  return arr.reduce((s, x) => s + x, 0) / arr.length;
}

function stdev(arr) {
  const m = mean(arr);
  const variance = arr.reduce((s, x) => s + Math.pow(x - m, 2), 0) / (arr.length - 1);
  return Math.sqrt(variance);
}

// ======================================================================
// STEP 2: METRIC #1 — SHARPE RATIO (fully built, run this now)
// ======================================================================
/**
 * Sharpe Ratio = (annualized mean return - risk-free rate) / annualized std dev
 * This is a descriptive statistic computed directly from realized returns —
 * there is no fitting involved, so no train/test split or cross-validation
 * applies here. More data points just make the estimate less noisy.
 */
function calculateSharpeRatio() {
  const series = getPortfolioValueSeries();
  if (series.length < 3) {
    Logger.log('Need at least 3 snapshots to compute a meaningful Sharpe ratio. ' +
                'Currently have ' + series.length + '.');
    return null;
  }

  const periodReturns = getPeriodReturns(series);
  const periodMean = mean(periodReturns);
  const periodStd = stdev(periodReturns);

  const annualizedReturn = periodMean * PERIODS_PER_YEAR;
  const annualizedStd = periodStd * Math.sqrt(PERIODS_PER_YEAR);
  const sharpe = (annualizedReturn - RISK_FREE_RATE_ANNUAL) / annualizedStd;

  writeAnalyticsRow('Sharpe Ratio', sharpe, {
    'Observations (periods)': periodReturns.length,
    'Periods per year assumed': PERIODS_PER_YEAR,
    'Annualized mean return': (annualizedReturn * 100).toFixed(2) + '%',
    'Annualized std dev': (annualizedStd * 100).toFixed(2) + '%',
    'Risk-free rate used': (RISK_FREE_RATE_ANNUAL * 100).toFixed(2) + '%'
  });

  Logger.log('Sharpe Ratio: ' + sharpe.toFixed(3));
  return sharpe;
}

/** Writes a metric + its assumptions to the Analytics tab, timestamped. */
function writeAnalyticsRow(metricName, value, assumptions) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(ANALYTICS_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(ANALYTICS_SHEET_NAME);
    sheet.getRange(1, 1, 1, 4)
      .setValues([['Timestamp', 'Metric', 'Value', 'Assumptions Used']])
      .setFontWeight('bold')
      .setBackground('#1c4587')
      .setFontColor('white');
    sheet.setFrozenRows(1);
  }
  const assumptionsText = Object.entries(assumptions).map(([k, v]) => k + ': ' + v).join(' | ');
  sheet.appendRow([new Date(), metricName, value, assumptionsText]);
}

// ======================================================================
// STEP 3: METRIC #2 — MAX DRAWDOWN (fully built — "the one other metric")
// ======================================================================
/**
 * Max Drawdown = largest peak-to-trough % decline in the value series.
 * WInS/StockTrak does not report this natively, so this is genuinely new
 * information Sharpe alone doesn't give you: Sharpe tells you risk-adjusted
 * return overall, drawdown tells you the worst pain you'd have actually sat
 * through to get it.
 */
function calculateMaxDrawdown() {
  const series = getPortfolioValueSeries();
  if (series.length < 2) {
    Logger.log('Need at least 2 snapshots to compute a drawdown. Currently have ' +
               series.length + '.');
    return null;
  }

  let runningPeak = series[0].value;
  let maxDrawdown = 0; // will end up negative or zero
  let peakDate = series[0].date;
  let troughDate = series[0].date;
  let worstPeakDate = series[0].date;
  let worstTroughDate = series[0].date;

  for (let i = 0; i < series.length; i++) {
    const v = series[i].value;
    if (v > runningPeak) {
      runningPeak = v;
      peakDate = series[i].date;
    }
    const drawdown = (v - runningPeak) / runningPeak;
    if (drawdown < maxDrawdown) {
      maxDrawdown = drawdown;
      worstPeakDate = peakDate;
      worstTroughDate = series[i].date;
    }
  }

  writeAnalyticsRow('Max Drawdown', maxDrawdown, {
    'Observations (snapshots)': series.length,
    'Peak date': Utilities.formatDate(worstPeakDate, Session.getScriptTimeZone(), 'yyyy-MM-dd'),
    'Trough date': Utilities.formatDate(worstTroughDate, Session.getScriptTimeZone(), 'yyyy-MM-dd')
  });

  Logger.log('Max Drawdown: ' + (maxDrawdown * 100).toFixed(2) + '%');
  return maxDrawdown;
}

// ======================================================================
// STEP 4: MONTE CARLO SIMULATION (stub)
// ======================================================================
/**
 * TODO:
 * 1. Fit a return distribution (mean/std) from getPeriodReturns() — this
 *    is your actual trading data, not the assumed inputs from the case-study
 *    model you built earlier in Excel.
 * 2. Simulate N random paths forward using that distribution.
 * 3. Report percentile outcomes (5th/25th/50th/75th/95th), same structure
 *    as the Excel model's Dashboard tab.
 * Reuses getPortfolioValueSeries() / getPeriodReturns() as its only inputs.
 */
function runMonteCarloSimulation() {
  Logger.log('Not yet implemented — needs real snapshot data first.');
}

// ======================================================================
// STEP 5: MARKOV REGIME-SWITCHING MODEL (stub)
// ======================================================================
/**
 * TODO:
 * 1. Label each historical period as "Bull" or "Bear" (e.g., return > 0 vs < 0,
 *    or vs. a benchmark).
 * 2. Estimate transition probabilities P(Bull->Bull), P(Bear->Bear) by
 *    counting actual transitions in your labeled history.
 * 3. Estimate mean/std of returns conditional on each state.
 * 4. Feed those FITTED parameters into runMonteCarloSimulation() instead of
 *    flat assumptions — this is the "Markov prediction model."
 * THIS is the piece that needs validation (see below) — the transition
 * probabilities and regime stats are fitted to data and can overfit if you
 * calibrate and test on the same stretch of history.
 */
function runMarkovRegimeModel() {
  Logger.log('Not yet implemented — needs real snapshot data first.');
}

// ======================================================================
// STEP 6: WALK-FORWARD VALIDATION (stub — applies to the Markov model only)
// ======================================================================
/**
 * TODO, once runMarkovRegimeModel() exists:
 * 1. Sort all snapshots by date (never shuffle — no look-ahead bias).
 * 2. Pick a rolling window size (e.g., fit on weeks 1-4, test on week 5).
 * 3. Fit transition probabilities + regime stats using ONLY data up to the
 *    cutoff date (the "train" window).
 * 4. Predict the next period's regime/return using those fitted parameters.
 * 5. Compare the prediction to what actually happened (the "test" period —
 *    data the model never saw while fitting).
 * 6. Slide the window forward by one period and repeat.
 * 7. Aggregate: how often did the model's predicted regime match reality?
 *    Was the predicted return in the right ballpark?
 * This is the actual "cross-validation without look-ahead bias" — it's a
 * rolling train/test split by date, never a random shuffle.
 */
function walkForwardValidateMarkov() {
  Logger.log('Not yet implemented — needs real snapshot data first, ' +
             'and enough periods to support multiple rolling windows.');
}
