"""
Data fetcher for crypto funding-rate arbitrage research.

Pulls from Binance via ccxt:
- Perpetual swap funding-rate history for BTC/USDT:USDT and ETH/USDT:USDT
- Daily spot OHLCV for BTC/USDT and ETH/USDT

Designed to be resumable: each fetch paginates until it reaches `until` and
writes a single CSV per (symbol, dataset) pair under data/raw/.
"""
from __future__ import annotations

import time
from pathlib import Path

import ccxt
import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

START_MS = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)


def _binance_swap() -> ccxt.binance:
    return ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })


def _binance_spot() -> ccxt.binance:
    return ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })


def fetch_funding_rate_history(symbol: str, since_ms: int = START_MS) -> pd.DataFrame:
    """Fetch 8h funding-rate history for a perpetual swap symbol.

    Paginates with `since` cursor; Binance returns up to 1000 rows per call.
    """
    ex = _binance_swap()
    rows: list[dict] = []
    cursor = since_ms
    last_ts = -1
    while True:
        batch = ex.fetch_funding_rate_history(symbol, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        latest = batch[-1]["timestamp"]
        if latest <= last_ts:  # no forward progress — stop
            break
        last_ts = latest
        cursor = latest + 1
        if latest >= ex.milliseconds() - 8 * 3600 * 1000:
            break
        time.sleep(ex.rateLimit / 1000)

    df = pd.DataFrame([
        {
            "timestamp": pd.Timestamp(r["timestamp"], unit="ms", tz="UTC"),
            "symbol": r["symbol"],
            "fundingRate": float(r["fundingRate"]) if r.get("fundingRate") is not None else None,
        }
        for r in rows
    ])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_daily_ohlcv(symbol: str, market: str = "spot", since_ms: int = START_MS) -> pd.DataFrame:
    """Fetch daily OHLCV bars for a spot or swap symbol."""
    ex = _binance_spot() if market == "spot" else _binance_swap()
    rows: list[list] = []
    cursor = since_ms
    last_ts = -1
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe="1d", since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        latest = batch[-1][0]
        if latest <= last_ts:
            break
        last_ts = latest
        cursor = latest + 86_400_000
        if latest >= ex.milliseconds() - 86_400_000:
            break
        time.sleep(ex.rateLimit / 1000)

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def summarize(name: str, df: pd.DataFrame, time_col: str = "timestamp") -> dict:
    missing = int(df.isna().any(axis=1).sum())
    return {
        "dataset": name,
        "rows": len(df),
        "start": str(df[time_col].min()) if len(df) else None,
        "end": str(df[time_col].max()) if len(df) else None,
        "missing_rows": missing,
    }


def main() -> None:
    targets = [
        ("funding", "BTC/USDT:USDT", "btc_funding_rate.csv"),
        ("funding", "ETH/USDT:USDT", "eth_funding_rate.csv"),
        ("spot", "BTC/USDT", "btc_spot.csv"),
        ("spot", "ETH/USDT", "eth_spot.csv"),
        ("swap", "BTC/USDT:USDT", "btc_perp.csv"),
        ("swap", "ETH/USDT:USDT", "eth_perp.csv"),
    ]

    summaries = []
    for kind, symbol, fname in targets:
        out = RAW_DIR / fname
        print(f"[fetch] {kind:7s} {symbol:18s} -> {out.name}")
        if kind == "funding":
            df = fetch_funding_rate_history(symbol)
        else:
            df = fetch_daily_ohlcv(symbol, market=kind)
        df.to_csv(out, index=False)
        summaries.append(summarize(fname, df))
        print(f"        rows={len(df):>6}  range={summaries[-1]['start']} .. {summaries[-1]['end']}")

    print("\n== summary ==")
    for s in summaries:
        print(s)


if __name__ == "__main__":
    main()
