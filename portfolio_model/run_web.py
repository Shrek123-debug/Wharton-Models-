#!/usr/bin/env python
"""Launch the local portfolio-analysis web UI.

Usage:
  python run_web.py                # http://127.0.0.1:8000
  python run_web.py --port 8080
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from web.app import app


def main() -> int:
    ap = argparse.ArgumentParser(description="Portfolio analysis local web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"\nPortfolio Analysis Web UI → http://{args.host}:{args.port}  (local only, no AI)\n")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except OSError as exc:
        # the common case is a previous run still holding the port
        print(f"\nCould not start the web UI on {args.host}:{args.port}: {exc}\n"
              f"Try a different port:  python run_web.py --port {args.port + 1}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
