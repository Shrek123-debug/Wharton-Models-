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

from src.config import PACKAGE_ROOT, ConfigError  # noqa: E402
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
    ap.add_argument("--variant", action="append", metavar="KEY=VALUE",
                    help="Run a second scenario with these overrides and print a side-by-side "
                         "comparison (repeatable, e.g. --variant glide_end_equity=0.35 "
                         "--variant model=student_t)")
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
    except ConfigError as exc:
        print(f"\nCONFIG PROBLEM:\n{exc}", file=sys.stderr)
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

    if args.variant:
        return _run_comparison(args, overrides, results, out)
    return 0


def _parse_scalar(raw: str):
    """KEY=VALUE on the command line arrives as text; convert it the way the config would."""
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _run_comparison(args, overrides: dict, results: dict, out: Path) -> int:
    from src.compare import compare_runs, flag_deltas, format_comparison
    from src.pipeline import _ALLOWED_OVERRIDES

    variant_overrides = dict(overrides)
    for pair in args.variant:
        if "=" not in pair:
            print(f"\nBAD --variant: {pair!r} - expected KEY=VALUE", file=sys.stderr)
            return 2
        key, raw = pair.split("=", 1)
        key = key.strip()
        if key not in _ALLOWED_OVERRIDES:
            print(f"\nBAD --variant: {key!r} cannot be overridden from the CLI.\n"
                  f"Allowed: {', '.join(sorted(_ALLOWED_OVERRIDES))}", file=sys.stderr)
            return 2
        variant_overrides[key] = _parse_scalar(raw.strip())

    try:
        variant = run(input_path=args.input, config_path=args.config, out_dir=str(out / "variant"),
                      overrides=variant_overrides, render_charts=False)
    except (PipelineError, ConfigError, SystemExit) as exc:
        print(f"\nVARIANT RUN FAILED: {exc}", file=sys.stderr)
        return 2

    diff = compare_runs(results, variant, "baseline", "variant")
    print("\n=== Baseline versus variant ===")
    print(f"Variant overrides: {', '.join(f'{k}={v}' for k, v in sorted(variant_overrides.items()))}")
    print(format_comparison(diff, flag_deltas(results, variant), "baseline", "variant"))

    csv_path = out / "compare" / "run_comparison.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    diff.to_csv(csv_path, index=False)
    print(f"\nComparison written to {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
