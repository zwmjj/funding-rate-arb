"""
Part 4 — Threshold sensitivity for the funding-rate arb strategy.

Scans (entry_bps, exit_bps) grid for BTC and ETH, reports Sharpe, annual return,
exposure, and max drawdown for each combination. Saves a heatmap per asset.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest import BacktestConfig, build_panel, run_backtest

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "results" / "figures"
RES = ROOT / "results"


def scan(asset: str, entries: np.ndarray, exits: np.ndarray) -> pd.DataFrame:
    panel = build_panel(asset)
    rows = []
    for e in entries:
        for x in exits:
            if x >= e:  # exit must be below entry
                continue
            cfg = BacktestConfig(entry_bps=float(e), exit_bps=float(x), taker_bps=4.0)
            _, m, _ = run_backtest(panel, cfg)
            rows.append({
                "entry_bps": e,
                "exit_bps": x,
                "ann_return_pct": m["ann_return_pct"],
                "sharpe": m["sharpe"],
                "max_dd_pct": m["max_dd_pct"],
                "n_trades": m["n_trades"],
                "exposure": m["exposure"],
            })
    return pd.DataFrame(rows)


def heatmap(df: pd.DataFrame, value: str, title: str, out: Path) -> None:
    pivot = df.pivot(index="entry_bps", columns="exit_bps", values=value)
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn", origin="lower")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{v:.1f}" for v in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{v:.1f}" for v in pivot.index])
    ax.set_xlabel("Exit threshold (bps / 8h)")
    ax.set_ylabel("Entry threshold (bps / 8h)")
    ax.set_title(title)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7, color="black")
    fig.colorbar(im, ax=ax, label=value)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def main() -> None:
    entries = np.arange(0.5, 5.1, 0.5)      # 0.5 bp → 5 bp per 8h
    exits = np.arange(0.0, 2.1, 0.5)        # 0 → 2 bp

    for asset in ("btc", "eth"):
        df = scan(asset, entries, exits)
        df.to_csv(RES / f"{asset}_sensitivity.csv", index=False)
        print(f"\n== {asset.upper()} top 5 by annual return ==")
        print(df.sort_values("ann_return_pct", ascending=False).head().to_string(index=False))
        heatmap(df, "ann_return_pct", f"{asset.upper()} annual return (%) by threshold",
                FIG / f"{asset}_heatmap_return.png")
        heatmap(df, "sharpe", f"{asset.upper()} Sharpe (8h-bar basis) by threshold",
                FIG / f"{asset}_heatmap_sharpe.png")

    print("\nHeatmaps saved to", FIG)


if __name__ == "__main__":
    main()
