"""
Part 2 — EDA on BTC/ETH funding rates.

Outputs:
- results/eda_summary.csv            descriptive stats
- results/figures/funding_timeseries.png
- results/figures/funding_histogram.png
- results/figures/funding_acf.png
- results/figures/funding_rolling.png
- results/figures/funding_vs_price.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
FIG = ROOT / "results" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
RES = ROOT / "results"


def load() -> dict[str, pd.DataFrame]:
    def rd(name: str, tcol: str = "timestamp") -> pd.DataFrame:
        df = pd.read_csv(RAW / name)
        df[tcol] = pd.to_datetime(df[tcol], utc=True, format="ISO8601")
        return df.sort_values(tcol).reset_index(drop=True)

    return {
        "btc_fr": rd("btc_funding_rate.csv"),
        "eth_fr": rd("eth_funding_rate.csv"),
        "btc_spot": rd("btc_spot.csv"),
        "eth_spot": rd("eth_spot.csv"),
    }


def descriptive(frs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in frs.items():
        r = df["fundingRate"].astype(float)
        ann = r * 3 * 365
        rows.append({
            "symbol": name,
            "n_obs": len(r),
            "mean_8h_bps": r.mean() * 1e4,
            "median_8h_bps": r.median() * 1e4,
            "std_8h_bps": r.std() * 1e4,
            "skew": r.skew(),
            "kurt": r.kurt(),
            "mean_annualized_pct": ann.mean() * 100,
            "pct_above_1bp": (r > 0.0001).mean() * 100,
            "pct_above_10bp": (r > 0.001).mean() * 100,
            "pct_negative": (r < 0).mean() * 100,
            "max_8h_bps": r.max() * 1e4,
            "min_8h_bps": r.min() * 1e4,
        })
    return pd.DataFrame(rows).set_index("symbol").round(3)


def plot_timeseries(btc: pd.DataFrame, eth: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(btc["timestamp"], btc["fundingRate"] * 1e4, lw=0.5, alpha=0.8, label="BTC")
    ax.plot(eth["timestamp"], eth["fundingRate"] * 1e4, lw=0.5, alpha=0.8, label="ETH")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_ylabel("Funding rate (bps / 8h)")
    ax.set_title("Binance perpetual funding rates — BTC vs ETH (2020–2026)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "funding_timeseries.png", dpi=130)
    plt.close(fig)


def plot_histogram(btc: pd.DataFrame, eth: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, (label, df) in zip(axes, [("BTC", btc), ("ETH", eth)]):
        r = df["fundingRate"].astype(float) * 1e4
        clipped = r.clip(-20, 20)
        ax.hist(clipped, bins=80, color="steelblue", edgecolor="white", alpha=0.85)
        mu, sd = r.mean(), r.std()
        x = np.linspace(-20, 20, 400)
        # overlay normal with empirical mean/std for comparison
        from scipy.stats import norm
        ax.plot(x, norm.pdf(x, mu, sd) * len(r) * (40 / 80), color="crimson", lw=1.5, label=f"N(μ={mu:.2f}, σ={sd:.2f})")
        ax.set_title(f"{label} funding rate distribution (bps/8h, clipped ±20)")
        ax.set_xlabel("bps per 8h")
        ax.legend()
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "funding_histogram.png", dpi=130)
    plt.close(fig)


def plot_acf_pacf(btc: pd.DataFrame) -> None:
    r = btc["fundingRate"].astype(float).dropna()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    plot_acf(r, ax=axes[0], lags=60, title="BTC funding rate — ACF (60 lags ≈ 20 days)")
    plot_pacf(r, ax=axes[1], lags=60, title="BTC funding rate — PACF", method="ywm")
    fig.tight_layout()
    fig.savefig(FIG / "funding_acf.png", dpi=130)
    plt.close(fig)


def plot_rolling(btc: pd.DataFrame, eth: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for ax, (label, df) in zip(axes, [("BTC", btc), ("ETH", eth)]):
        r = df.set_index("timestamp")["fundingRate"].astype(float) * 1e4
        # 30-day rolling windows (30*3 = 90 8h obs)
        ax.plot(r.index, r.rolling(90).mean(), label="30d rolling mean", color="C0")
        ax.fill_between(
            r.index,
            r.rolling(90).mean() - r.rolling(90).std(),
            r.rolling(90).mean() + r.rolling(90).std(),
            alpha=0.25, color="C0", label="±1σ",
        )
        ax.axhline(0, color="k", lw=0.5)
        ax.set_ylabel(f"{label} (bps/8h)")
        ax.legend(loc="upper right")
        ax.grid(alpha=0.3)
    axes[0].set_title("Rolling 30-day mean and volatility of funding rate")
    fig.tight_layout()
    fig.savefig(FIG / "funding_rolling.png", dpi=130)
    plt.close(fig)


def regime_split(fr: pd.DataFrame, label: str) -> pd.DataFrame:
    r = fr.set_index("timestamp")["fundingRate"].astype(float)
    periods = {
        "2020 COVID / recovery": ("2020-01-01", "2020-12-31"),
        "2021 bull": ("2021-01-01", "2021-12-31"),
        "2022 bear": ("2022-01-01", "2022-12-31"),
        "2023 chop": ("2023-01-01", "2023-12-31"),
        "2024 ETF bull": ("2024-01-01", "2024-12-31"),
        "2025+": ("2025-01-01", "2026-12-31"),
    }
    rows = []
    for regime, (s, e) in periods.items():
        sub = r.loc[s:e]
        if len(sub) == 0:
            continue
        rows.append({
            "asset": label,
            "regime": regime,
            "n": len(sub),
            "mean_bps_8h": sub.mean() * 1e4,
            "annualized_pct": sub.mean() * 3 * 365 * 100,
            "std_bps_8h": sub.std() * 1e4,
            "pct_negative": (sub < 0).mean() * 100,
        })
    return pd.DataFrame(rows)


def plot_funding_vs_price(btc_fr: pd.DataFrame, btc_spot: pd.DataFrame) -> pd.DataFrame:
    """Check: does an elevated funding rate predict short-term price reversal?"""
    spot = btc_spot.set_index("timestamp")["close"].astype(float)
    # aggregate 8h funding to daily average
    fr_daily = (
        btc_fr.set_index("timestamp")["fundingRate"]
        .astype(float)
        .resample("1D")
        .mean()
        .dropna()
    )
    spot_daily = spot.resample("1D").last().dropna()
    fwd_ret_1d = spot_daily.pct_change().shift(-1)
    fwd_ret_3d = spot_daily.pct_change(3).shift(-3)
    fwd_ret_7d = spot_daily.pct_change(7).shift(-7)
    df = pd.concat(
        [fr_daily.rename("fr"), fwd_ret_1d.rename("r1"), fwd_ret_3d.rename("r3"), fwd_ret_7d.rename("r7")],
        axis=1,
    ).dropna()

    # bucket analysis
    df["bucket"] = pd.qcut(df["fr"].rank(method="first"), 5, labels=["Q1 low", "Q2", "Q3", "Q4", "Q5 high"])
    buckets = df.groupby("bucket", observed=True)[["r1", "r3", "r7"]].mean() * 100

    fig, ax = plt.subplots(figsize=(8, 4.5))
    buckets.plot(kind="bar", ax=ax)
    ax.set_ylabel("Mean forward return (%)")
    ax.set_title("BTC: forward return vs funding-rate quintile")
    ax.axhline(0, color="k", lw=0.5)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "funding_vs_price.png", dpi=130)
    plt.close(fig)
    return buckets


def main() -> None:
    data = load()
    btc_fr, eth_fr = data["btc_fr"], data["eth_fr"]

    desc = descriptive({"BTC": btc_fr, "ETH": eth_fr})
    desc.to_csv(RES / "eda_summary.csv")
    print("\n== Descriptive stats ==")
    print(desc.to_string())

    regimes = pd.concat([regime_split(btc_fr, "BTC"), regime_split(eth_fr, "ETH")], ignore_index=True)
    regimes.to_csv(RES / "eda_regimes.csv", index=False)
    print("\n== Regime split ==")
    print(regimes.round(3).to_string(index=False))

    plot_timeseries(btc_fr, eth_fr)
    plot_histogram(btc_fr, eth_fr)
    plot_acf_pacf(btc_fr)
    plot_rolling(btc_fr, eth_fr)
    buckets = plot_funding_vs_price(btc_fr, data["btc_spot"])
    print("\n== BTC forward return (%) by funding-rate quintile ==")
    print(buckets.round(3).to_string())

    print("\nFigures saved to", FIG)


if __name__ == "__main__":
    main()
