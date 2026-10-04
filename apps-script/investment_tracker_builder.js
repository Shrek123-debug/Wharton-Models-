/**
 * INVESTMENT TRACKER BUILDER
 * ---------------------------------------------------------------
 * Creates a brand-new Google Sheet with 4 tabs:
 *   1. Transactions      - log every deposit, withdrawal, buy, sell
 *   2. Holdings Summary   - current quantity/value per ticker
 *   3. Yearly Summary     - 16-year snapshot of portfolio value
 *   4. Dashboard          - pie + area charts of your allocation
 *
 * HOW TO RUN THIS:
 *   1. Go to https://script.google.com -> New project
 *   2. Delete the placeholder code, paste this whole file in
 *   3. Click "Run" on createInvestmentTracker
 *   4. Authorize when prompted
 *   5. Check View > Logs (or Executions) for the link to your new sheet
 * ---------------------------------------------------------------
 */

function createInvestmentTracker() {
  const ss = SpreadsheetApp.create('My Investment Tracker');

  buildTransactionsSheet(ss);
  buildHoldingsSheet(ss);
  buildYearlySummarySheet(ss);
  buildDashboardSheet(ss);

  // Remove the default empty "Sheet1" that SpreadsheetApp.create() leaves behind
  const leftover = ss.getSheetByName('Sheet1');
  if (leftover) ss.deleteSheet(leftover);

  Logger.log('Your investment tracker is ready: ' + ss.getUrl());
}

// ---------------------------------------------------------------------
// 1. TRANSACTIONS — the master ledger. Add a row every time you buy,
//    sell, deposit, or withdraw. Everything else is calculated from this.
// ---------------------------------------------------------------------
function buildTransactionsSheet(ss) {
  const sheet = ss.insertSheet('Transactions', 0);

  const headers = [
    'Date', 'Type', 'Asset Class', 'Ticker / Description',
    'Quantity', 'Price per Unit', 'Deposit/Withdrawal Amount',
    'Cash Impact', 'Running Cash Balance', 'Notes'
  ];
  sheet.getRange(1, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#1c4587')
    .setFontColor('white');
  sheet.setFrozenRows(1);

  // Dropdowns
  const typeRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Deposit', 'Withdrawal', 'Buy', 'Sell'], true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange('B2:B1000').setDataValidation(typeRule);

  const assetRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Cash', 'Stocks', 'Bonds', 'ETF'], true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange('C2:C1000').setDataValidation(assetRule);

  // Cash Impact: money IN is positive, money OUT is negative
  // Deposit -> +Amount | Withdrawal -> -Amount | Sell -> +Qty*Price | Buy -> -Qty*Price
  sheet.getRange('H2:H1000').setFormulaR1C1(
    '=IF(RC1="","",IF(RC2="Deposit",RC7,IF(RC2="Withdrawal",-RC7,' +
    'IF(RC2="Sell",RC5*RC6,IF(RC2="Buy",-RC5*RC6,0)))))'
  );

  // Running cash balance = cumulative sum of Cash Impact so far
  sheet.getRange('I2:I1000').setFormulaR1C1(
    '=IF(RC1="","",SUM(R2C8:RC8))'
  );

  sheet.getRange('D:D').setNumberFormat('@');
  sheet.getRange('A:A').setNumberFormat('yyyy-mm-dd');
  sheet.getRange('F2:G1000').setNumberFormat('$#,##0.00');
  sheet.getRange('H2:I1000').setNumberFormat('$#,##0.00');
  sheet.autoResizeColumns(1, headers.length);

  // One example row so the format/logic is obvious
  sheet.getRange('A2:J2').setValues([[
    new Date(), 'Deposit', 'Cash', 'Initial funding', '', '', 1000, '', '', 'Example row - delete me'
  ]]);
}

// ---------------------------------------------------------------------
// 2. HOLDINGS SUMMARY — type each ticker you own once in columns A/B.
//    Quantity, cost basis, and gain/loss pull automatically from
//    Transactions. Fill in Current Price yourself whenever you check it.
// ---------------------------------------------------------------------
function buildHoldingsSheet(ss) {
  const sheet = ss.insertSheet('Holdings Summary', 1);

  const headers = [
    'Asset Class', 'Ticker / Description', 'Quantity Held',
    'Current Price', 'Market Value', 'Cost Basis', 'Unrealized Gain/Loss'
  ];
  sheet.getRange(1, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#1c4587')
    .setFontColor('white');
  sheet.setFrozenRows(1);

  const assetRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Cash', 'Stocks', 'Bonds', 'ETF'], true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange('A2:A50').setDataValidation(assetRule);

  // Quantity held = total bought - total sold for that Asset Class + Ticker
  sheet.getRange('C2:C50').setFormulaR1C1(
    '=IF(RC2="","",' +
    'SUMIFS(Transactions!R2C5:R1000C5,Transactions!R2C3:R1000C3,RC1,Transactions!R2C4:R1000C4,RC2,Transactions!R2C2:R1000C2,"Buy")' +
    '-SUMIFS(Transactions!R2C5:R1000C5,Transactions!R2C3:R1000C3,RC1,Transactions!R2C4:R1000C4,RC2,Transactions!R2C2:R1000C2,"Sell"))'
  );

  sheet.getRange('E2:E50').setFormulaR1C1('=IF(RC2="","",RC3*RC4)');

  // Cost basis = total $ spent buying that ticker minus total $ received selling it
  sheet.getRange('F2:F50').setFormulaR1C1(
    '=IF(RC2="","",' +
    'SUMPRODUCT((Transactions!R2C3:R1000C3=RC1)*(Transactions!R2C4:R1000C4=RC2)*(Transactions!R2C2:R1000C2="Buy")*Transactions!R2C5:R1000C5*Transactions!R2C6:R1000C6)' +
    '-SUMPRODUCT((Transactions!R2C3:R1000C3=RC1)*(Transactions!R2C4:R1000C4=RC2)*(Transactions!R2C2:R1000C2="Sell")*Transactions!R2C5:R1000C5*Transactions!R2C6:R1000C6))'
  );

  sheet.getRange('G2:G50').setFormulaR1C1('=IF(RC2="","",RC5-RC6)');

  sheet.getRange('D2:D50').setNumberFormat('$#,##0.00');
  sheet.getRange('E2:G50').setNumberFormat('$#,##0.00');
  sheet.autoResizeColumns(1, headers.length);
}

// ---------------------------------------------------------------------
// 3. YEARLY SUMMARY — one row per year of your 16-year horizon.
//    Edit the Year column to real calendar years, then once a year
//    (or whenever you like) fill in the four value columns as a snapshot.
// ---------------------------------------------------------------------
function buildYearlySummarySheet(ss) {
  const sheet = ss.insertSheet('Yearly Summary', 2);

  const headers = ['Year', 'Cash Value', 'Stocks Value', 'Bonds Value', 'ETF Value', 'Total Portfolio Value', 'Change vs Prior Year'];
  sheet.getRange(1, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#1c4587')
    .setFontColor('white');
  sheet.setFrozenRows(1);

  const startYear = new Date().getFullYear();
  const yearLabels = [];
  for (let i = 0; i < 16; i++) yearLabels.push(['Year ' + (i + 1) + ' (' + (startYear + i) + ')']);
  sheet.getRange(2, 1, 16, 1).setValues(yearLabels);

  sheet.getRange('F2:F17').setFormulaR1C1('=IF(RC1="","",SUM(RC2:RC5))');
  sheet.getRange('G3:G17').setFormulaR1C1('=IF(OR(RC1="",R[-1]C1=""),"",RC6-R[-1]C6)');

  sheet.getRange('B2:F17').setNumberFormat('$#,##0.00');
  sheet.autoResizeColumns(1, headers.length);
}

// ---------------------------------------------------------------------
// 4. DASHBOARD — current allocation pie chart + 16-year growth chart
// ---------------------------------------------------------------------
function buildDashboardSheet(ss) {
  const sheet = ss.insertSheet('Dashboard', 3);
  const holdings = ss.getSheetByName('Holdings Summary');
  const yearly = ss.getSheetByName('Yearly Summary');
  const transactions = ss.getSheetByName('Transactions');

  sheet.getRange('A1').setValue('Current Allocation').setFontWeight('bold');
  sheet.getRange('A2:B2').setValues([['Asset Class', 'Value']]).setFontWeight('bold');
  sheet.getRange('A3:A6').setValues([['Cash'], ['Stocks'], ['Bonds'], ['ETF']]);

  sheet.getRange('B3').setFormula(
    '=IFERROR(INDEX(Transactions!I2:I1000,MAX(FILTER(ROW(Transactions!I2:I1000),Transactions!A2:A1000<>""))-1),0)'
  );
  sheet.getRange('B4').setFormula('=SUMIF(\'Holdings Summary\'!A2:A50,"Stocks",\'Holdings Summary\'!E2:E50)');
  sheet.getRange('B5').setFormula('=SUMIF(\'Holdings Summary\'!A2:A50,"Bonds",\'Holdings Summary\'!E2:E50)');
  sheet.getRange('B6').setFormula('=SUMIF(\'Holdings Summary\'!A2:A50,"ETF",\'Holdings Summary\'!E2:E50)');
  sheet.getRange('B3:B6').setNumberFormat('$#,##0.00');

  const pie = sheet.newChart()
    .setChartType(Charts.ChartType.PIE)
    .addRange(sheet.getRange('A2:B6'))
    .setPosition(8, 1, 0, 0)
    .setOption('title', 'Current Allocation')
    .build();
  sheet.insertChart(pie);

  const growth = yearly.newChart()
    .setChartType(Charts.ChartType.AREA)
    .addRange(yearly.getRange('A1:E17'))
    .setPosition(28, 1, 0, 0)
    .setOption('title', 'Portfolio Growth by Asset Class Over 16 Years')
    .setOption('isStacked', true)
    .build();
  sheet.insertChart(growth);

  sheet.autoResizeColumns(1, 2);
}
