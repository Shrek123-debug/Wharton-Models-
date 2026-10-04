#!/usr/bin/env python
"""Portfolio modeling agent — CLI entry point.

Usage:
  python main.py                          # uses config input path
  python main.py --input path/to.xlsx    # override input spreadsheet
  python main.py --config path/to.yaml   # override configuration
  python main.py --sims 50000            # override simulation count
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.pipeline import run


def main() -> None:
    ap = argparse.ArgumentParser(description="Portfolio modeling, risk, simulation & reporting agent")
    ap.add_argument("--input", help="Path to portfolio spreadsheet (.xlsx)")
    ap.add_argument("--config", help="Path to model_config.yaml")
    ap.add_argument("--out", help="Output directory (default portfolio_model/outputs)")
    ap.add_argument("--sims", type=int, help="Override simulation count")
    ap.add_argument("--seed", type=int, help="Override random seed")
    args = ap.parse_args()

    overrides = {}
    if args.sims:
        overrides["sims"] = args.sims
    if args.seed:
        overrides["seed"] = args.seed
    results = run(input_path=args.input, config_path=args.config, out_dir=args.out, overrides=overrides or None)

    print("\n=== Portfolio Analysis Complete ===")
    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "outputs"
    print(f"Workbook: {out / 'spreadsheet' / 'portfolio_analysis.xlsx'}")
    print(f"Report:   {out / 'report' / 'portfolio_analysis_report.docx'}")
    print(f"Figures:  {out / 'figures'}/ ({len(results['figures'])} charts)")
    s = results["mc_sum"]
    b = results["bs_sum"]
    print(f"\nMonte Carlo  : median 2033 ${s['median_terminal']:,.0f} | success {s['prob_terminal_gt_start']:.1%} | reserve funded {s['prob_all_payments_funded']:.1%}")
    print(f"Bootstrap    : median 2033 ${b['median_terminal']:,.0f} | success {b['prob_terminal_gt_start']:.1%} | reserve funded {b['prob_all_payments_funded']:.1%}")
    print(f"Markov       : median 2033 ${results['mk_sum']['median_terminal']:,.0f} | P(bear ever 2027-32) {results['mk_sum']['bear_ever_prob']:.1%}")


if __name__ == "__main__":
    main()
