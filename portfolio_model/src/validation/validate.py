"""Input validation and weight normalization (spec section 4)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

CASH_TICKERS = {"CASH", "USD", "MMF", "BIL", "SGOV", "USDA"}
BOND_TICKERS = {"IEF", "SHY", "AGG", "BND", "TLT", "LQD", "MUB", "VEU"}
EQUITY_ETF = {"VOO", "SPY", "VTI", "QQQ", "IWM", "SCHB"}


@dataclass
class ValidationResult:
    holdings: pd.DataFrame
    weights_source: str
    warnings: list[str] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _flag(flags: list[dict], severity: str, ticker: str, issue: str, detail: str = ""):
    flags.append({"severity": severity, "ticker": ticker, "issue": issue, "detail": detail})


def classify_asset_class(ticker: str, raw_bucket: str | None) -> str:
    t = ticker.upper()
    if t in CASH_TICKERS:
        return "Cash"
    if raw_bucket:
        b = str(raw_bucket).lower()
        if "cash" in b:
            return "Cash"
        if "bond" in b or "treasury" in b or "fixed" in b:
            return "Treasury" if t in {"IEF", "SHY", "TLT"} else "Corporate Bond"
        if "stock" in b or "equity" in b:
            return "ETF" if t in EQUITY_ETF else "US Equity"
    if t in BOND_TICKERS:
        return "Treasury" if t in {"IEF", "SHY", "TLT"} else "Corporate Bond"
    if t in EQUITY_ETF:
        return "ETF"
    return "US Equity"


def validate(holdings: pd.DataFrame, config: dict) -> ValidationResult:
    warnings: list[str] = []
    flags: list[dict] = []
    errors: list[str] = []
    df = holdings.copy()

    # --- required information -------------------------------------------------
    if "ticker" not in df.columns or df["ticker"].isna().all():
        errors.append("No ticker/security identifier found.")
        return ValidationResult(df, "none", warnings, flags, errors)

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()

    dupes = df["ticker"][df["ticker"].duplicated()].tolist()
    if dupes:
        flags.append({"severity": "high", "ticker": ",".join(dupes), "issue": "Duplicate tickers", "detail": "Merged by summing weights/quantities."})
        num_cols = df.select_dtypes(include=[np.number]).columns
        df = df.groupby("ticker", as_index=False)[num_cols].sum() if len(num_cols) else df.groupby("ticker", as_index=False).first()

    blank = df["ticker"].isin({"", "NAN", "NONE"})
    if blank.any():
        flags.append({"severity": "high", "ticker": "(blank)", "issue": "Missing tickers", "detail": f"{int(blank.sum())} rows dropped."})
        df = df[~blank]

    # --- numeric sanity --------------------------------------------------------
    for col in ("quantity", "market_value", "portfolio_weight", "price"):
        if col in df.columns:
            neg = df[df[col].fillna(0) < 0]
            if len(neg):
                flags.append({"severity": "high", "ticker": ",".join(neg["ticker"]), "issue": f"Negative {col}", "detail": "Positions with negative values are not modeled."})
            zero = df[(df[col].fillna(0) == 0) & df[col].notna()]
            if len(zero) and col in ("quantity", "market_value"):
                flags.append({"severity": "medium", "ticker": ",".join(zero["ticker"]), "issue": f"Zero {col}", "detail": "Position excluded from modeling."})

    df = df[~(df.get("quantity", pd.Series(1, index=df.index)).fillna(1) == 0)]
    df = df[~(df.get("market_value", pd.Series(1, index=df.index)).fillna(1) == 0)]

    # --- weights ---------------------------------------------------------------
    weights_source = "none"
    if "portfolio_weight" in df.columns and df["portfolio_weight"].notna().sum() >= max(1, len(df) - 1):
        w = df["portfolio_weight"].astype(float)
        total = w.sum()
        if total <= 0:
            errors.append("Supplied weights sum to <= 0.")
        else:
            if abs(total - 1.0) > 0.02:
                warnings.append(f"Supplied weights sum to {total:.4f}; normalized to 1.0.")
            df["weight"] = w / total
            weights_source = "supplied"
    elif {"quantity", "price"} <= set(df.columns) and df["quantity"].notna().all() and df["price"].notna().all():
        df["market_value"] = df["quantity"] * df["price"]
        df["weight"] = df["market_value"] / df["market_value"].sum()
        weights_source = "calculated (quantity x price)"
    elif "market_value" in df.columns and df["market_value"].notna().all():
        df["weight"] = df["market_value"] / df["market_value"].sum()
        weights_source = "calculated (market value)"
    else:
        errors.append("Insufficient data: need weights, market values, or quantity+price for every holding.")

    if errors:
        return ValidationResult(df, weights_source, warnings, flags, errors)

    # --- classification ---------------------------------------------------------
    df["asset_class"] = [
        classify_asset_class(t, df.loc[i, "asset_class"] if "asset_class" in df.columns else None)
        for i, t in enumerate(df["ticker"])
    ]
    if "sector" not in df.columns:
        df["sector"] = np.nan
    for t in df["ticker"][df["ticker"].isin(CASH_TICKERS)]:
        df.loc[df["ticker"] == t, "asset_class"] = "Cash"

    missing_sector = df[df["sector"].isna() & ~df["asset_class"].isin(["Cash", "Treasury", "Corporate Bond"])]
    if len(missing_sector):
        flags.append({"severity": "medium", "ticker": ",".join(missing_sector["ticker"]), "issue": "Missing sector", "detail": "Sector will be assigned via classification lookup."})

    # --- config caps ------------------------------------------------------------
    max_w = config.get("risk", {}).get("max_position_weight", 0.10)
    over = df[df["weight"] > max_w + 1e-9]
    for _, row in over.iterrows():
        _flag(flags, "high", row["ticker"], "HIGH CONCENTRATION", f"Weight {row['weight']:.1%} exceeds configured max {max_w:.0%}.")

    if "correlation_group" in df.columns:
        grp_cap = config.get("risk", {}).get("max_correlated_group_weight", 0.30)
        grp = df[df["correlation_group"].notna()].groupby("correlation_group")["weight"].sum()
        for g, s in grp.items():
            if s > grp_cap + 1e-9:
                _flag(flags, "high", str(g), "CORRELATED-GROUP OVERWEIGHT", f"Group '{g}' totals {s:.1%} > cap {grp_cap:.0%}.")

    if abs(df["weight"].sum() - 1.0) > 1e-6:
        errors.append("Internal error: normalized weights do not sum to 1.")

    return ValidationResult(df.reset_index(drop=True), weights_source, warnings, flags, errors)
