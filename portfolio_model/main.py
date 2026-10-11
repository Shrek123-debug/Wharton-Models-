#!/usr/bin/env python
"""Portfolio modeling agent — CLI entry point.

Usage:
  python main.py                            # uses config input path
  python main.py --input path/to.xlsx      # override input spreadsheet
  python main.py --config path/to.yaml     # override configuration
  python main.py --sims 50000              # override simulation count
  python main.py --offline                 # never touch the network (bundled + cached data only)
  python main.py --refresh                 # force a fresh download of market data
  python main.py --no-charts               # skip figure rendering (faster smoke run)
  python main.py --check                   # environment + data self-test, no simulation

Exit codes: 0 = ok, 2 = input/config problem you can fix, 3 = unexpected internal error.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import PACKAGE_ROOT  # noqa: E402
from src.pipeline import PipelineError, run  # noqa: E402
from src.runtime_env import configure_local_runtime  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="portfolio-model",
        description="Portfolio modeling, risk, simulation & reporting agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--input", help="Path to portfolio spreadsheet (.xlsx)")
    ap.add_argument("--config", help="Path to model_config.yaml")
    ap.add_argument("--out", help="Output directory (default portfolio_model/outputs)")
    ap.add_argument("--sims", type=int, help="Override simulation count")
    ap.add_argument("--seed", type=int, help="Override random seed")
    ap.add_argument("--model", choices=["gaussian", "lognormal", "student_t", "historical_residual"],
                    help="Return distribution used by the Monte Carlo engine")
    ap.add_argument("--glide-method", choices=["none", "linear", "accelerating", "stepwise", "custom"],
                    help="Glide-path de-risking shape")
    ap.add_argument("--start-date", help="Historical data start date (YYYY-MM-DD)")
    ap.add_argument("--end-date", help="Historical data end date (YYYY-MM-DD)")
    ap.add_argument("--offline", action="store_true",
                    help="Never use the network; resolve prices from data/cache and data/offline")
    ap.add_argument("--refresh", action="store_true",
                    help="Ignore cached market data and re-download it")
    ap.add_argument("--no-charts", action="store_true", help="Skip figure rendering")
    ap.add_argument("--quiet", action="store_true", help="Only print warnings and the summary")
    ap.add_argument("--check", action="store_true", help="Run the environment/data self-test and exit")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_local_runtime()

    if args.check:
        from src.selfcheck import run_selfcheck
        return 0 if run_selfcheck() else 1

    overrides: dict = {}
    for key in ("sims", "seed", "model", "glide_method"):
        val = getattr(args, key, None)
        if val is not None:
            overrides[key] = val
    if args.start_date:
        overrides["start_date"] = args.start_date
    if args.end_date:
        overrides["end_date"] = args.end_date
    if args.offline:
        overrides["offline"] = "always"
    if args.refresh:
        overrides["max_cache_age_days"] = 0

    import logging
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    try:
        results = run(input_path=args.input, config_path=args.config, out_dir=args.out,
                      overrides=overrides or None, render_charts=not args.no_charts)
    except PipelineError as exc:
        print(f"\nINPUT/CONFIG PROBLEM: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:  # validation failure raised inside the pipeline
        print(f"\nINPUT/CONFIG PROBLEM: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("\nUNEXPECTED ERROR:\n" + traceback.format_exc(), file=sys.stderr)
        return 3

    out = Path(args.out) if args.out else PACKAGE_ROOT / "outputs"
    print("\n=== Portfolio Analysis Complete ===")
    print(f"Workbook: {out / 'spreadsheet' / 'portfolio_analysis.xlsx'}")
    print(f"Report:   {out / 'report' / 'portfolio_analysis_report.docx'}")
    print(f"Figures:  {out / 'figures'}/ ({len(results['figures'])} charts)")
    s, b, mk = results["mc_sum"], results["bs_sum"], results["mk_sum"]
    print(f"\nMonte Carlo  : median 2033 ${s['median_terminal']:,.0f} | "
          f"success {s['prob_terminal_gt_start']:.1%} | reserve funded {s['prob_all_payments_funded']:.1%}")
    print(f"Bootstrap    : median 2033 ${b['median_terminal']:,.0f} | "
          f"success {b['prob_terminal_gt_start']:.1%} | reserve funded {b['prob_all_payments_funded']:.1%}")
    print(f"Markov       : median 2033 ${mk['median_terminal']:,.0f} | "
          f"P(bear ever 2027-32) {mk['bear_ever_prob']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
