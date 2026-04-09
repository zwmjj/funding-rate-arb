"""
Part 5 — Basis Trade vs Funding Rate Arbitrage comparison.

Fetches BTC quarterly futures that have completed their lifecycle on Binance
delivery market (CURRENT/NEXT quarter historical), computes rolling basis
(futures - spot)/spot annualized to time-to-expiry, and compares the theoretical
carry against the funding-rate arb carry from Part 3.

Approach:
- For each listed dated futures contract, pull daily mark close from Binance
  delivery market, fetch matching spot prices, compute annualized basis.
- Also compute the cheaper spot-vs-perp "implied basis" which is the cumulative
  funding rate trajectory — this is the instrument we actually traded in Part 3.
"""
from __future__ import annotations

from pathlib import Path

import ccxt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RES = ROOT / "results"
FIG = ROOT / "results" / "figures"
RES.mkdir(parents=True, exist_ok=True)


def _load(name: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / name)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df.sort_values("timestamp").reset_index(drop=True)


def fetch_delivery_contracts() -> list[dict]:
    """List BTCUSDT dated futures from Binance COIN-M/USDT-M delivery markets."""
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "delivery"}})
    try:
        markets = ex.load_markets()
    except Exception as exc:
        print(f"[warn] delivery load failed: {exc}")
        return []
    out = []
    for sym, m in markets.items():
        if not m.get("future"):
            continue
        if m.get("base") != "BTC":
            continue
        if not m.get("expiry"):
            continue
        out.append({"symbol": sym, "expiry": m["expiry"], "id": m["id"]})
    return out


def fetch_futures_ohlcv(symbol: str, since_ms: int) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "delivery"}})
    rows = []
    cursor = since_ms
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe="1d", since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        latest = batch[-1][0]
        if latest <= cursor:
            break
        cursor = latest + 86_400_000
        if latest >= ex.milliseconds() - 86_400_000:
            break
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.drop_duplicates("timestamp").reset_index(drop=True)


def compute_implied_basis_from_funding(asset: str = "btc") -> pd.DataFrame:
    """Convert 8h funding rate series into an annualized carry proxy.
    A position earns `sum(funding)` over holding period, so annualized rate
    is mean(funding) * 3 * 365.
    """
    fr = _load(f"{asset}_funding_rate.csv").set_index("timestamp")["fundingRate"].astype(float)
    # daily mean -> annualized carry
    daily = fr.resample("1D").mean()
    annualized = daily * 3 * 365  # funding-implied annual carry
    rolling30 = annualized.rolling(30).mean()
    df = pd.DataFrame({"annualized_carry": annualized, "rolling30d": rolling30})
    return df


def main() -> None:
    # Implied basis from funding (BTC & ETH)
    btc_implied = compute_implied_basis_from_funding("btc")
    eth_implied = compute_implied_basis_from_funding("eth")
    btc_implied.to_csv(RES / "btc_implied_basis_from_funding.csv")
    eth_implied.to_csv(RES / "eth_implied_basis_from_funding.csv")

    # Try to fetch BTC dated quarterly futures
    print("[info] fetching Binance BTC delivery futures list...")
    contracts = fetch_delivery_contracts()
    print(f"[info] found {len(contracts)} dated BTC futures contracts")
    spot = _load("btc_spot.csv").set_index("timestamp")["close"].astype(float)

    basis_rows: list[pd.DataFrame] = []
    for c in contracts[:8]:  # limit to 8 contracts for speed
        sym = c["symbol"]
        since = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
        try:
            fut = fetch_futures_ohlcv(sym, since)
        except Exception as exc:
            print(f"[warn] {sym}: {exc}")
            continue
        if fut.empty:
            continue
        fut = fut.set_index("timestamp")["close"].astype(float)
        df = pd.concat([fut.rename("fut"), spot.rename("spot")], axis=1).dropna()
        if df.empty:
            continue
        df["basis"] = df["fut"] / df["spot"] - 1
        expiry_ms = int(c["expiry"])
        expiry = pd.Timestamp(expiry_ms, unit="ms", tz="UTC")
        df["days_to_expiry"] = (expiry - df.index).days
        df = df[df["days_to_expiry"] > 0]
        if df.empty:
            continue
        df["annualized_basis"] = df["basis"] * 365 / df["days_to_expiry"]
        df["contract"] = sym
        basis_rows.append(df)

    if basis_rows:
        all_basis = pd.concat(basis_rows).reset_index()
        all_basis.to_csv(RES / "btc_quarterly_basis.csv", index=False)
        print("\n== BTC quarterly futures basis summary ==")
        print(
            all_basis.groupby("contract")["annualized_basis"]
            .agg(["mean", "std", "min", "max"])
            .round(4)
            .to_string()
        )

    # Plot: funding-implied carry vs dated-futures annualized basis
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(btc_implied.index, btc_implied["rolling30d"] * 100, label="BTC funding-implied carry (30d rolling ann. %)", color="C0", lw=1.2)
    ax.plot(eth_implied.index, eth_implied["rolling30d"] * 100, label="ETH funding-implied carry (30d rolling ann. %)", color="C1", lw=1.0, alpha=0.8)
    if basis_rows:
        for df in basis_rows:
            ax.plot(df.index, df["annualized_basis"] * 100, color="gray", alpha=0.4, lw=0.8)
        ax.plot([], [], color="gray", lw=0.8, label="BTC quarterly dated futures (ann. basis %)")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("Funding-implied carry vs quarterly-futures annualized basis (BTC)")
    ax.set_ylabel("Annualized %")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "basis_vs_funding.png", dpi=130)
    plt.close(fig)

    # Summary comparison table
    summary = {
        "BTC funding-arb mean ann carry (%)": round(btc_implied["annualized_carry"].mean() * 100, 3),
        "ETH funding-arb mean ann carry (%)": round(eth_implied["annualized_carry"].mean() * 100, 3),
    }
    if basis_rows:
        all_ab = pd.concat(basis_rows)["annualized_basis"]
        summary["BTC dated-futures mean ann basis (%)"] = round(all_ab.mean() * 100, 3)
        summary["BTC dated-futures std (%)"] = round(all_ab.std() * 100, 3)
    print("\n== Summary ==")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    pd.Series(summary).to_csv(RES / "basis_vs_funding_summary.csv")


if __name__ == "__main__":
    main()
