#!/usr/bin/env python
"""(Re)build the example input workbooks, including an in-workbook Instructions sheet.

Why a script instead of two committed binaries
---------------------------------------------
The example spreadsheets are documentation. Editing them by hand is how they drift from the
ingestion rules they are supposed to demonstrate. This script writes them from a spec, so
`data/input/example_portfolio_*.xlsx` can always be regenerated and reviewed as code.

Usage:
  python scripts/build_example_workbooks.py
  python scripts/build_example_workbooks.py --out /tmp/examples
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from src.config import PACKAGE_ROOT  # noqa: E402

HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E79")
NOTE_FONT = Font(italic=True, size=10, color="444444")

MINIMAL_ROWS = [
    ["VOO", 0.50],
    ["XOM", 0.20],
    ["IEF", 0.20],
    ["CASH", 0.10],
]

FULL_HEADERS = ["Ticker", "Name", "Shares", "Price", "Market Value", "Weight", "Target Weight",
                "Sector", "Asset Class", "Currency", "Cost Basis", "Purchase Date",
                "Expected Return", "Volatility", "Correlation Group", "Investment Thesis", "Notes"]

FULL_ROWS = [
    ["VOO", "Vanguard S&P 500 ETF", 120, 500, 60000, 0.300, 0.300, "Broad Market (ETF)", "ETF", "USD",
     420, "2024-03-15", 0.09, 0.15, "", "Core broad-market anchor", ""],
    ["ADBE", "Adobe Inc.", 60, 210, 12600, 0.063, 0.060, "Information Technology", "US Equity", "USD",
     180, "2024-05-02", 0.12, 0.28, "Growth/Consumer-Tech", "Creative software subscription", ""],
    ["DIS", "Walt Disney Co.", 80, 110, 8800, 0.044, 0.050, "Communication Services", "US Equity", "USD",
     95, "2024-06-11", 0.08, 0.30, "Growth/Consumer-Tech", "Media/IP", ""],
    ["DUOL", "Duolingo Inc.", 30, 200, 6000, 0.030, 0.030, "Information Technology", "US Equity", "USD",
     150, "2024-08-01", 0.14, 0.40, "Growth/Consumer-Tech", "Edtech growth", "Short history: low-confidence stats"],
    ["XOM", "Exxon Mobil", 70, 115, 8050, 0.040, 0.050, "Energy", "US Equity", "USD",
     100, "2024-04-20", 0.08, 0.22, "", "Energy / inflation hedge", ""],
    ["IEF", "iShares 7-10Y Treasury", 40, 95, 3800, 0.190, 0.200, "Bonds", "Treasury", "USD",
     90, "2024-02-10", 0.04, 0.07, "", "Duration ballast", ""],
    ["SHY", "iShares 1-3Y Treasury", 30, 82, 2460, 0.123, 0.120, "Bonds", "Treasury", "USD",
     80, "2024-02-10", 0.03, 0.03, "", "Near-term liquidity", ""],
    ["CASH", "Cash / money market", 1, 12340, 12340, 0.210, 0.200, "Cash", "Cash", "USD",
     12340, "2024-01-05", 0.041, 0.00, "", "Reserve buffer for the 2033 payments", ""],
]

INSTRUCTIONS: list[tuple[str, str]] = [
    ("title", "How to use this workbook"),
    ("note", "This is an EXAMPLE input file. Copy it, replace the rows with your own holdings, "
             "and run:  python main.py --input data/input/your_file.xlsx"),
    ("h", "1. The only required columns"),
    ("p", "Ticker, plus ONE of: Portfolio Weight | Market Value | Shares and Price. "
          "Everything else improves the analysis but is optional."),
    ("h", "2. Column reference"),
    ("table", ["Column", "Required", "What it does", "Accepted header names"]),
    ("table", ["Ticker", "YES", "Identifies the holding and its price series", "ticker, symbol, security, company, name"]),
    ("table", ["Weight", "one of three", "The allocation being analysed (must sum to 1.0)", "portfolio weight, weight, % of portfolio"]),
    ("table", ["Market Value", "one of three", "Weights derived as value / total", "market value, current value, value"]),
    ("table", ["Shares + Price", "one of three", "Weights derived from shares x price", "shares, quantity | current price, last price"]),
    ("table", ["Asset Class", "recommended", "Drives equity / bond / cash logic and stress mapping", "asset class, class, bucket, type"]),
    ("table", ["Sector", "recommended", "Sector caps and sector attribution", "sector, GICS sector, industry sector"]),
    ("table", ["Expected Return", "recommended", "The central simulation assumption", "expected return, exp return, mean return"]),
    ("table", ["Volatility", "recommended", "Dispersion used by every engine", "volatility, std dev, stdev, risk"]),
    ("table", ["Investment Thesis", "recommended", "Missing theses become governance flags", "investment thesis, thesis, why own"]),
    ("table", ["Target Weight", "optional", "Enables drift-vs-target flags", "target weight, target allocation"]),
    ("table", ["Correlation Group", "optional", "Enables correlated-group exposure caps", "correlation group, group, cluster"]),
    ("table", ["Cost Basis", "optional", "Enables dollar P&L", "cost basis, avg cost, average cost"]),
    ("table", ["Currency", "optional", "Non-USD rows are excluded and reported", "currency, ccy"]),
    ("h", "3. Formats the reader accepts"),
    ("p", "Weights: 0.15, 15%, 15 % and 0.1500 all mean 15%.  Money: $1,234.50 and 1,234.50 "
          "both work.  Negatives: (450) is read as -450.  Tickers must look like ADBE, BRK.B, 6752.T."),
    ("h", "4. Things that will make the run fail (deliberately included so you can see the messages)"),
    ("p", "A company name instead of a ticker is skipped and reported. Formulas with no cached "
          "values are reported with instructions to re-save the file in Excel/LibreOffice. "
          "Weights that do not sum to 1.0 are renormalised and the run says so."),
    ("h", "5. Try these three runs"),
    ("p", "python main.py --input data/input/example_portfolio_full.xlsx --offline"),
    ("p", "python main.py --input data/input/example_portfolio_full.xlsx --offline --glide-method none"),
    ("p", "python main.py --input data/input/example_portfolio_full.xlsx --offline --model student_t"),
    ("p", "Compare Probability reserve fully funded and CVaR 95% across the three runs. That "
          "comparison is the model explaining itself."),
    ("h", "6. Where every number is defined"),
    ("p", "docs/METRIC_DEFINITIONS.md, the Definitions sheet of the OUTPUT workbook, and the "
          "Definitions tab of the web UI - all generated from portfolio_model/src/metric_glossary.py."),
]


def _style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def _autosize(ws, max_w: int = 46) -> None:
    for col in ws.columns:
        length = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_w, max(10, length + 2))


def _write_instructions(ws) -> None:
    r = 1
    for kind, text in INSTRUCTIONS:
        if kind == "title":
            ws.cell(row=r, column=1, value=text).font = TITLE_FONT
            r += 2
        elif kind == "note":
            ws.cell(row=r, column=1, value=text).font = Font(bold=True, size=11, color="9C5700")
            r += 2
        elif kind == "h":
            ws.cell(row=r, column=1, value=text).font = Font(bold=True, size=12, color="1F4E79")
            r += 1
        elif kind == "p":
            ws.cell(row=r, column=1, value=text).font = NOTE_FONT
            r += 1
        elif kind == "table":
            cells = text if isinstance(text, list) else [text]
            for j, v in enumerate(cells, start=1):
                ws.cell(row=r, column=j, value=v)
            if cells[0] == "Column":
                _style_header(ws, r, len(cells))
            r += 1
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 52
    ws.column_dimensions["D"].width = 46


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # ---- minimal: ticker + weight only
    wb = Workbook()
    ws = wb.active
    ws.title = "Positions"
    ws.cell(row=1, column=1, value="Example portfolio — minimal (ticker + weight only)").font = TITLE_FONT
    ws.cell(row=2, column=1, value="Copy this file, replace the rows, run: python main.py --input data/input/your_file.xlsx").font = NOTE_FONT
    ws.append([])
    ws.append(["Ticker", "Weight"])
    _style_header(ws, 4, 2)
    for t, w in MINIMAL_ROWS:
        ws.append([t, w])
    for row in ws.iter_rows(min_row=5, min_col=2, max_col=2):
        row[0].number_format = "0.0%"
    _autosize(ws)
    _write_instructions(wb.create_sheet("Instructions"))
    p = out_dir / "example_portfolio_minimal.xlsx"
    wb.save(p)
    written.append(p)

    # ---- full: every supported column
    wb = Workbook()
    ws = wb.active
    ws.title = "Holdings"
    ws.cell(row=1, column=1, value="Example portfolio — full column set").font = TITLE_FONT
    ws.cell(row=2, column=1, value="Copy this file, replace the rows, run: python main.py --input data/input/your_file.xlsx").font = NOTE_FONT
    ws.append([])
    ws.append(FULL_HEADERS)
    _style_header(ws, 4, len(FULL_HEADERS))
    for row in FULL_ROWS:
        ws.append(row)
    pct_cols = {FULL_HEADERS.index("Weight") + 1, FULL_HEADERS.index("Target Weight") + 1,
                FULL_HEADERS.index("Expected Return") + 1, FULL_HEADERS.index("Volatility") + 1}
    money_cols = {FULL_HEADERS.index("Market Value") + 1, FULL_HEADERS.index("Price") + 1,
                  FULL_HEADERS.index("Cost Basis") + 1}
    for r in range(5, 5 + len(FULL_ROWS)):
        for c in range(1, len(FULL_HEADERS) + 1):
            cell = ws.cell(row=r, column=c)
            if c in pct_cols:
                cell.number_format = "0.0%"
            elif c in money_cols:
                cell.number_format = "#,##0.00"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    total_row = 5 + len(FULL_ROWS)
    ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
    ws.cell(row=total_row, column=6, value=f"=SUM(F5:F{total_row - 1})").number_format = "0.0%"
    ws.cell(row=total_row + 1, column=1,
            value="The TOTAL row is ignored by the reader (it is a total, not a holding).").font = NOTE_FONT
    _autosize(ws)
    _write_instructions(wb.create_sheet("Instructions"))
    p = out_dir / "example_portfolio_full.xlsx"
    wb.save(p)
    written.append(p)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the example input workbooks")
    ap.add_argument("--out", default=str(PACKAGE_ROOT / "data" / "input"))
    args = ap.parse_args()
    for path in build(Path(args.out)):
        print(f"Wrote {path}")
    print("Verify ingestion with:  python main.py --check --input <that file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
