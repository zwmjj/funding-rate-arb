"""
Part 3 — Funding Rate Arbitrage backtest.

Strategy: long 1 unit spot + short 1 unit perpetual when 8h funding rate
         exceeds an entry threshold; exit when it falls back below an exit
         threshold (or optional hard holding cap).

PnL components per 8h step while in a position:
  + funding income       = notional * fundingRate   (shorts receive positive funding)
  + spot mark PnL        = notional * spot_return   (long leg)
  - perp mark PnL        = notional * perp_return   (short leg, so the sign flips)
  => net price PnL       = notional * (spot_return - perp_return)   (basis drift)

(This block previously stated the price-PnL sign backwards on both the spot
line and the net line. The implementation below was always correct; the
docstring disagreed with it on the most basic identity in the strategy.)
     (in practice spot_return ≈ perp_return, so this is near zero)

Costs:
  open  = 2 * taker_bps * notional  (one leg spot, one leg perp)
  close = 2 * taker_bps * notional

The notional is normalized to 1.0 at entry for clean unit reporting.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RES = ROOT / "results"
RES.mkdir(parents=True, exist_ok=True)


@dataclass
class BacktestConfig:
    entry_bps: float = 1.0      # enter when funding rate > entry_bps per 8h (1bp = 0.01%)
    exit_bps: float = 0.5       # exit when funding rate falls below exit_bps per 8h
    taker_bps: float = 4.0      # 0.04% per side per leg
    max_hold_periods: int = 0   # 0 = no cap; otherwise force exit after N 8h periods
    notional: float = 1.0


def _load(name: str, tcol: str = "timestamp") -> pd.DataFrame:
    df = pd.read_csv(RAW / name)
    df[tcol] = pd.to_datetime(df[tcol], utc=True, format="ISO8601")
    return df.sort_values(tcol).reset_index(drop=True)


def build_panel(asset: str) -> pd.DataFrame:
    """Align 8h funding-rate timestamps with 8h-resampled spot & perp prices.

    We resample daily OHLCV to an 8h forward-fill so every funding timestamp
    has a mark price from both spot and perp. This is a simplification — true
    8h marks would require 8h bars — but is sufficient for the directional
    analysis since spot/perp tracks are near-identical.
    """
    fr = _load(f"{asset}_funding_rate.csv")
    spot = _load(f"{asset}_spot.csv")
    perp = _load(f"{asset}_perp.csv")

    # Binance stamps funding settlements a few milliseconds off the hour
    # (e.g. 2026-04-09 08:00:00.010+00:00). The spot/perp series are resampled
    # onto an exact 8h grid, so an as-is concat aligns only the settlements that
    # happen to land on the grid and .dropna() silently discards the rest --
    # 3,051 of 6,872 BTC rows, 44% of the funding history, with no warning.
    # Floor the settlement timestamps onto the same grid before joining.
    fr = fr.set_index("timestamp")["fundingRate"].astype(float)
    fr.index = fr.index.floor("8h")
    fr = fr[~fr.index.duplicated(keep="last")]

    spot_c = spot.set_index("timestamp")["close"].astype(float).resample("8h").ffill()
    perp_c = perp.set_index("timestamp")["close"].astype(float).resample("8h").ffill()

    df = pd.concat(
        [fr.rename("funding"), spot_c.rename("spot"), perp_c.rename("perp")],
        axis=1,
    ).dropna()

    # Fail loudly rather than backtesting on a fraction of the sample. A
    # silent join loss is exactly the failure this guard exists to catch.
    kept, total = len(df), len(fr)
    if kept < 0.95 * total:
        raise ValueError(
            f"{asset}: joined panel keeps only {kept}/{total} funding settlements "
            f"({kept / total:.1%}). Check timestamp alignment before trusting results."
        )
    df["spot_ret"] = df["spot"].pct_change().fillna(0.0)
    df["perp_ret"] = df["perp"].pct_change().fillna(0.0)
    return df


def run_backtest(panel: pd.DataFrame, cfg: BacktestConfig) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    entry_rate = cfg.entry_bps / 1e4
    exit_rate = cfg.exit_bps / 1e4
    fee = cfg.taker_bps / 1e4
    N = cfg.notional

    in_pos = False
    hold = 0
    trades: list[dict] = []
    pnl_steps: list[float] = []
    position_flag: list[int] = []
    entry_ts: pd.Timestamp | None = None
    entry_spot = entry_perp = None
    trade_pnl_accum = 0.0
    funding_accum = 0.0

    for ts, row in panel.iterrows():
        step_pnl = 0.0

        # Decide action BEFORE earning funding this step (funding is paid at timestamp t
        # based on positions held from t-1 to t). To keep semantics simple, we treat a
        # position opened at time t as starting to earn from the NEXT funding timestamp.
        if not in_pos:
            if row["funding"] > entry_rate:
                # open at this timestamp — pay open cost, no funding yet
                step_pnl -= 2 * fee * N
                in_pos = True
                hold = 0
                entry_ts = ts
                entry_spot = row["spot"]
                entry_perp = row["perp"]
                trade_pnl_accum = -2 * fee * N
                funding_accum = 0.0
        else:
            # holding — earn funding on short perp leg
            funding_pnl = N * row["funding"]
            # basis drift PnL (long spot, short perp)
            price_pnl = N * (row["spot_ret"] - row["perp_ret"])
            step_pnl += funding_pnl + price_pnl
            trade_pnl_accum += funding_pnl + price_pnl
            funding_accum += funding_pnl
            hold += 1

            force_exit = cfg.max_hold_periods > 0 and hold >= cfg.max_hold_periods
            if row["funding"] < exit_rate or force_exit:
                step_pnl -= 2 * fee * N
                trade_pnl_accum -= 2 * fee * N
                trades.append({
                    "entry_ts": entry_ts,
                    "exit_ts": ts,
                    "hold_periods": hold,
                    "hold_days": hold / 3,
                    "funding_pnl": funding_accum,
                    "total_pnl": trade_pnl_accum,
                    "reason": "forced" if force_exit else "signal",
                })
                in_pos = False
                hold = 0

        pnl_steps.append(step_pnl)
        position_flag.append(int(in_pos))

    result = panel.copy()
    result["pnl"] = pnl_steps
    result["in_pos"] = position_flag
    result["cum_pnl"] = result["pnl"].cumsum()
    result["equity"] = 1.0 + result["cum_pnl"]

    trades_df = pd.DataFrame(trades)

    # metrics — 8h bar frequency
    step_returns = result["pnl"]  # absolute PnL per step on notional=1
    periods_per_year = 3 * 365  # 1095 8h bars
    mean = step_returns.mean()
    std = step_returns.std()
    sharpe = mean / std * np.sqrt(periods_per_year) if std > 0 else float("nan")
    ann_return = mean * periods_per_year
    cum = result["cum_pnl"]
    drawdown = (cum - cum.cummax())
    max_dd = drawdown.min()

    n_trades = len(trades_df)
    win_rate = (trades_df["total_pnl"] > 0).mean() if n_trades else float("nan")
    avg_hold = trades_df["hold_days"].mean() if n_trades else float("nan")
    exposure = result["in_pos"].mean()

    metrics = {
        "entry_bps": cfg.entry_bps,
        "exit_bps": cfg.exit_bps,
        "taker_bps": cfg.taker_bps,
        "n_steps": len(result),
        "n_trades": int(n_trades),
        "exposure": round(exposure, 4),
        "ann_return_pct": round(ann_return * 100, 3),
        "ann_vol_pct": round(std * np.sqrt(periods_per_year) * 100, 3),
        "sharpe": round(sharpe, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "win_rate": round(win_rate, 3) if n_trades else None,
        "avg_hold_days": round(avg_hold, 2) if n_trades else None,
        "total_pnl_pct": round(cum.iloc[-1] * 100, 3),
    }
    return result, metrics, trades_df


def main() -> None:
    import matplotlib.pyplot as plt

    FIG = ROOT / "results" / "figures"

    all_metrics = []
    curves: dict[str, pd.Series] = {}

    for asset in ("btc", "eth"):
        panel = build_panel(asset)
        cfg = BacktestConfig(entry_bps=1.0, exit_bps=0.5, taker_bps=4.0)
        result, metrics, trades = run_backtest(panel, cfg)
        metrics["asset"] = asset.upper()
        all_metrics.append(metrics)
        curves[asset.upper()] = result["cum_pnl"]
        trades.to_csv(RES / f"{asset}_trades_default.csv", index=False)
        print(f"\n== {asset.upper()} (entry=1bp, exit=0.5bp, taker=4bp) ==")
        for k, v in metrics.items():
            print(f"  {k:16s} {v}")

    pd.DataFrame(all_metrics).to_csv(RES / "backtest_default_metrics.csv", index=False)

    # equity curves
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for label, cum in curves.items():
        ax.plot(cum.index, cum * 100, label=label, lw=1.2)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_ylabel("Cumulative PnL (% of notional)")
    ax.set_title("Funding-rate arbitrage — cumulative PnL (entry=1bp, exit=0.5bp, taker=4bp)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "backtest_equity.png", dpi=130)
    plt.close(fig)

    # rolling 30d Sharpe on BTC
    btc_panel = build_panel("btc")
    result, _, _ = run_backtest(btc_panel, BacktestConfig(entry_bps=1.0, exit_bps=0.5))
    pnl = result["pnl"]
    win = 90  # 30 days * 3 (8h bars/day)
    rolling_sharpe = pnl.rolling(win).mean() / pnl.rolling(win).std() * np.sqrt(3 * 365)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(rolling_sharpe.index, rolling_sharpe, color="C0", lw=0.9)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("BTC funding-arb — rolling 30d Sharpe")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "backtest_rolling_sharpe.png", dpi=130)
    plt.close(fig)

    # drawdown
    cum = result["cum_pnl"]
    dd = (cum - cum.cummax()) * 100
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.fill_between(dd.index, dd, 0, color="crimson", alpha=0.5)
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("BTC funding-arb — drawdown")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "backtest_drawdown.png", dpi=130)
    plt.close(fig)

    print("\nFigures saved to", FIG)


if __name__ == "__main__":
    main()
