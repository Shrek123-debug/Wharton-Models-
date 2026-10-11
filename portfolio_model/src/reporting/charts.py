"""Visualization suite (spec sections 102-105)."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update({"figure.dpi": 110, "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.3, "figure.autolayout": False})

NOTE = "Source: model output. Simulated results are scenarios, not guarantees."


def _save(fig, out_dir: Path, name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


def allocation_donut(holdings: pd.DataFrame, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.pie(holdings["weight"], labels=holdings["ticker"], autopct="%1.1f%%",
           wedgeprops=dict(width=0.45), startangle=90)
    ax.set_title("Portfolio Allocation by Holding")
    _save(fig, out_dir, "01_allocation_donut")
    return out_dir / "01_allocation_donut.png"


def sector_allocation(sector_df: pd.DataFrame, out_dir: Path) -> Path:
    d = sector_df[sector_df["weight"] > 0]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(d.index[::-1], d["weight"][::-1] * 100, color="steelblue")
    ax.set_xlabel("% of portfolio")
    ax.set_title("Sector Allocation")
    for i, v in enumerate(d["weight"][::-1]):
        ax.text(v * 100 + 0.3, i, f"{v * 100:.1f}%", va="center", fontsize=8)
    _save(fig, out_dir, "02_sector_allocation")
    return out_dir / "02_sector_allocation.png"


def cumulative_return(port_value: pd.Series, benchmarks: dict, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(port_value.index, port_value.values, label="Portfolio (current weights)", lw=1.6)
    for name, s in benchmarks.items():
        ax.plot(s.index, s.values, label=name, lw=1.0, alpha=0.8)
    ax.set_title("Historical Cumulative Growth ($1 rebalanced monthly)")
    ax.set_ylabel("Growth of $1")
    ax.legend(fontsize=8)
    _save(fig, out_dir, "03_cumulative_return")
    return out_dir / "03_cumulative_return.png"


def drawdown_chart(port_value: pd.Series, out_dir: Path) -> Path:
    dd = port_value / port_value.cummax() - 1
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.fill_between(dd.index, dd.values * 100, 0, color="firebrick", alpha=0.55)
    ax.set_title("Historical Portfolio Drawdown")
    ax.set_ylabel("Drawdown (%)")
    _save(fig, out_dir, "04_drawdown")
    return out_dir / "04_drawdown.png"


def correlation_heatmap(corr: pd.DataFrame, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(len(corr)), corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr)), corr.index)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, shrink=0.8)
    ax.set_title("Asset Correlation Matrix (historical monthly returns)")
    _save(fig, out_dir, "05_correlation_heatmap")
    return out_dir / "05_correlation_heatmap.png"


def terminal_distribution(terms: np.ndarray, label: str, out_dir: Path, name: str) -> Path:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(terms, bins=80, color="steelblue", edgecolor="none")
    med = np.median(terms)
    for p, c in [(5, "red"), (95, "green")]:
        v = np.percentile(terms, p)
        ax.axvline(v, color=c, ls="--", lw=1.2, label=f"{p}th pct: ${v:,.0f}")
    ax.axvline(med, color="black", lw=1.4, label=f"Median: ${med:,.0f}")
    ax.set_title(f"{label} — Terminal Value Distribution (start of 2033)")
    ax.set_xlabel("Portfolio value ($)")
    ax.set_ylabel("Simulations")
    ax.legend(fontsize=8)
    fig.text(0.01, 0.01, NOTE, fontsize=7, style="italic")
    _save(fig, out_dir, name)
    return out_dir / f"{name}.png"


def fan_chart(fan: dict[int, np.ndarray], start_year: int, end_year: int, label: str, out_dir: Path, name: str) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    months = len(fan[50])
    x = np.arange(months)
    ax.fill_between(x, fan[5], fan[95], color="steelblue", alpha=0.15, label="5th-95th")
    ax.fill_between(x, fan[10], fan[90], color="steelblue", alpha=0.25, label="10th-90th")
    ax.fill_between(x, fan[25], fan[75], color="steelblue", alpha=0.4, label="25th-75th")
    ax.plot(x, fan[50], color="black", lw=1.6, label="Median")
    ticks = list(range(0, months, 12))
    ax.set_xticks(ticks, [str(start_year + i) for i in range(len(ticks))])
    ax.set_title(f"{label} — Simulated Portfolio Value Fan ({start_year}-{end_year})")
    ax.set_ylabel("Portfolio value ($)")
    ax.legend(fontsize=8)
    fig.text(0.01, 0.01, NOTE, fontsize=7, style="italic")
    _save(fig, out_dir, name)
    return out_dir / f"{name}.png"


def model_comparison_table_image(rows: list[dict], out_dir: Path) -> Path:
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.axis("off")
    tbl = ax.table(cellText=df.values, colLabels=df.columns, cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7)
    tbl.scale(1, 1.25)
    ax.set_title("Model Comparison (simulated, not guaranteed)")
    _save(fig, out_dir, "09_model_comparison")
    return out_dir / "09_model_comparison.png"


def sensitivity_heatmap(grid: pd.DataFrame, value: str, title: str, out_dir: Path, name: str) -> Path:
    piv = grid.pivot(index="return_shift", columns="vol_multiplier", values=value)
    fig, ax = plt.subplots(figsize=(7.5, 5))
    im = ax.imshow(piv.values, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(piv.columns)), [f"{c:.1f}x" for c in piv.columns])
    ax.set_yticks(range(len(piv.index)), [f"{i:+.0%}" for i in piv.index])
    ax.set_xlabel("Volatility multiplier")
    ax.set_ylabel("Expected return shift")
    for i in range(len(piv.index)):
        for j in range(len(piv.columns)):
            ax.text(j, i, f"{piv.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, shrink=0.85)
    ax.set_title(title)
    _save(fig, out_dir, name)
    return out_dir / f"{name}.png"


def glide_path_chart(targets: pd.DataFrame, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7.5, 4))
    years = targets.index
    ax.stackplot(years, targets["equity"] * 100, targets["bond"] * 100, targets["cash"] * 100,
                 labels=["Equity", "Bonds", "Cash"], colors=["#4c72b0", "#dd8452", "#937860"], alpha=0.85)
    ax.set_xlim(years.min(), years.max())
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of portfolio")
    ax.set_title("2033 Glide Path (linear default)")
    ax.legend(loc="lower left", fontsize=8)
    _save(fig, out_dir, "11_glide_path")
    return out_dir / "11_glide_path.png"


def crisis_comparison(crises: list[dict], out_dir: Path) -> Path:
    if not crises:
        # every configured crisis window predates the available price history
        fig, ax = plt.subplots(figsize=(7.5, 4))
        ax.axis("off")
        ax.text(0.5, 0.5, "No configured crisis window overlaps the available price history.\n"
                          "See the Data Quality sheet for the skipped windows.",
                ha="center", va="center", fontsize=10)
        _save(fig, out_dir, "12_crisis_comparison")
        return out_dir / "12_crisis_comparison.png"
    names = [c["crisis"] for c in crises]
    pret = [c["portfolio_return"] * 100 for c in crises]
    mdd = [c["max_drawdown"] * 100 for c in crises]
    bench = [list(c["benchmarks"].values())[0] * 100 if c.get("benchmarks") else np.nan for c in crises]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.bar(x - 0.25, pret, 0.25, label="Portfolio", color="steelblue")
    ax.bar(x, mdd, 0.25, label="Max drawdown", color="firebrick")
    ax.bar(x + 0.25, bench, 0.25, label="S&P 500 benchmark", color="gray")
    ax.set_xticks(x, [n.replace(" Global Financial Crisis", " GFC") for n in names])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("%")
    ax.set_title("Historical Crisis Stress Tests (current weights)")
    ax.legend(fontsize=8)
    _save(fig, out_dir, "12_crisis_comparison")
    return out_dir / "12_crisis_comparison.png"


def contribution_chart(attr: pd.DataFrame, out_dir: Path, name: str, title: str) -> Path:
    d = attr.iloc[:15]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.bar(d.iloc[:, 0], d["contribution_12m"] * 100, color=["seagreen" if v >= 0 else "firebrick" for v in d["contribution_12m"]])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Contribution to 12m portfolio return (pp)")
    ax.set_title(title)
    _save(fig, out_dir, name)
    return out_dir / f"{name}.png"


def risk_concentration_chart(weights: pd.Series, out_dir: Path) -> Path:
    w = weights.sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(w.index, w.values * 100, color="slateblue")
    ax.axhline(25, color="red", ls="--", label="Max position cap (25%)")
    ax.set_ylabel("% of portfolio")
    ax.set_title("Holding Concentration")
    ax.legend(fontsize=8)
    _save(fig, out_dir, "15_risk_concentration")
    return out_dir / "15_risk_concentration.png"
