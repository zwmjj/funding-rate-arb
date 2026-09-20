# Crypto Funding Rate Arbitrage

Independent research project on carry harvesting in crypto perpetual-swap markets.

**Question.** How profitable is a delta-neutral `long spot + short perpetual` carry trade across BTC and ETH once realistic execution costs are applied, and how does it compare to a dated quarterly-futures basis trade?

**Data.** Binance spot, perpetual swap, funding-rate (8h), and USDT-margined quarterly futures, 2020-01-01 → 2026-04-09, pulled via `ccxt`. All raw CSVs live in `data/raw/`.

---

## Summary of Findings

![Funding rates — BTC vs ETH](results/figures/funding_timeseries.png)

### 1. Funding rates are strongly right-skewed carry instruments

On an 8-hour bar (bps):

| Asset | Mean | Std | Annualized | Negative obs | Kurtosis |
|-------|-----:|----:|----------:|------------:|--------:|
| BTC   | 1.13 | 2.15 | **12.3 %** | 13.5 % | 30.1 |
| ETH   | 1.34 | 2.80 | **14.7 %** | 13.1 % | 37.9 |

- Distribution is heavily right-skewed (skew ≈ 3.3) with fat tails. Most of the gross carry concentrates in a small number of high-funding periods.
- ETH carries a persistent premium over BTC (≈2.3 %/yr on average) — shorts are compensated more for taking the basis side on ETH.

### 2. Regime matters — 2021 was exceptional, 2025 is weak

| Period | BTC ann. | ETH ann. |
|--------|---------:|---------:|
| 2020 COVID / recovery | 17.2 % | 27.4 % |
| 2021 bull | **30.6 %** | **37.5 %** |
| 2022 bear | 4.2 % | 0.8 % |
| 2023 chop | 7.9 % | 8.3 % |
| 2024 ETF bull | 11.9 % | 13.0 % |
| 2025+ | 4.3 % | 3.9 % |

The strategy is heavily regime-dependent, and the 2025+ row is the reason it
stopped trading. That row's 4.3 %/yr is an average of 0.39 bp per 8h — **below
the 1 bp entry threshold**, so the rule simply never fired: zero trades were
entered in 2025 or 2026 in either asset.

(An earlier version of this line said the 2025 carry was "only marginally above
the 16bp round-trip fee cost." That comparison was unit-inconsistent — an
annualized rate against a one-off round-trip charge. Over the actual ~38-day
average hold, 4.3 %/yr is roughly 45 bp of gross carry against 16 bp of fees,
about 3× cover, not marginal. The conclusion was right for the wrong reason:
what killed 2025 was the entry threshold, not the fee.)

### 3. No reversal signal from funding level

BTC forward returns by funding quintile:

| Quintile | r₁ (%) | r₃ (%) | r₇ (%) |
|----------|-------:|-------:|-------:|
| Q1 low | 0.47 | 1.09 | 2.19 |
| Q2 | 0.00 | 0.42 | 0.67 |
| Q3 | 0.15 | −0.13 | −0.21 |
| Q4 | 0.12 | 0.46 | 1.70 |
| **Q5 high** | 0.02 | 0.38 | 0.88 |

High funding does **not** predict price reversal — the carry trade can be exited on funding decay without needing a directional overlay.

### 4. Funding-rate arbitrage strategy (Part 3)

Rule: enter long-spot + short-perp when 8h funding > `entry_bps`, exit when it falls below `exit_bps`. Taker fees 4 bps per side per leg (16 bps round-trip).

Default config (entry = 1 bp, exit = 0.5 bp, taker = 4 bps):

| Metric | BTC | ETH |
|--------|----:|----:|
| # trades | 18 | 14 |
| Exposure | 30.0 % | 35.3 % |
| **Annual return (gross of funding cost)** | **9.0 %** | **11.4 %** |
| Annual vol (8h-bar) | 0.89 % | 1.34 % |
| Max drawdown | −0.28 % | −1.80 % |
| Win rate | 100 % | 100 % |
| Avg hold (days) | 38 | 58 |
| Cumulative PnL over 6.27 yr | 56.4 % | 71.8 % |

> **These numbers changed on 2026-08-24 and the old ones were wrong.** The panel
> join dropped 44 % of the funding history without warning — Binance stamps
> settlements a few milliseconds off the hour, the price series were resampled
> onto an exact 8h grid, and `.dropna()` quietly discarded every settlement that
> did not line up (3,051 of 6,872 BTC rows). The previously published "16 trades,
> 25-day average hold" and "12 trades, 39-day hold" were computed on 3,821 of
> 6,871 steps. The annual return barely moved (9.02 → 8.99 %) purely by
> coincidence: the same defect halved both the numerator and the effective
> calendar, so the two errors cancelled to within 0.03pp. Trade counts, hold
> periods, cumulative PnL, win rate and Sharpe did not cancel. `build_panel` now
> floors the settlement timestamps onto the grid and raises if a join ever keeps
> less than 95 % of the funding series.

> **A 100 % win rate is a warning label, not a selling point.** With 18 and 14
> trades over six years, every one profitable, the strategy is not being tested
> — it is describing a period in which perpetual funding was persistently
> positive. The entry rule fires rarely and holds for weeks; there is no sense in
> which 18 observations establish an edge.

![Cumulative PnL](results/figures/backtest_equity.png)

> **Sharpe caveat.** Raw Sharpe from 8-hour bars looks very high (8–10) because the strategy is flat ~65 % of the time, which compresses the denominator. This is *not* a fair risk-adjusted number. The honest statement is **"9–11 % gross annual carry at <2 % drawdown with ~30–35 % capital utilization"**, not an inflated Sharpe.

> **The carry is gross, and the trade is not self-financing.** Long spot / short
> perp ties up 100 % of notional in cash on the spot leg; the backtest accrues
> funding and basis drift but charges nothing for that capital and pays nothing
> on idle balances. Against a USD cash rate of roughly 4–5 % through 2023–2025,
> a 9 % gross carry is an excess return of about half that — and the 2025 regime
> below, at 4.3 % annualized, is approximately **zero** excess return. Any
> comparison of these figures against a benchmark has to net the cash rate off
> first.

> **The strategy has not traded since December 2024.** Last exits are 2024-12-21
> (BTC) and 2024-12-24 (ETH), and no trade was entered in 2025 or 2026 in either
> asset — funding never crossed the 1bp entry threshold. Trades entered before
> 2022 account for **79 %** of BTC's cumulative PnL and **82 %** of ETH's. The
> headline annual return spreads six years of income over a book that earned
> most of it in the first two and none of it in the last twenty months.

### 5. Threshold sensitivity (Part 4)

Scanned entry ∈ {0.5, 1, …, 5} bps × exit ∈ {0, 0.5, 1, 1.5, 2} bps.

Top BTC configurations by annual return:

| Entry | Exit | Ann % | # trades |
|------:|-----:|------:|---------:|
| 1.0 | 0.0 | 9.50 | 14 |
| 1.5 | 0.0 | 9.24 | 14 |
| 2.0 | 0.0 | 9.01 | 13 |
| 1.0 | 0.5 | 8.99 | 18 |

Top ETH configurations:

| Entry | Exit | Ann % | # trades |
|------:|-----:|------:|---------:|
| 1.0 | 0.0 | 11.90 | 13 |
| 1.5 | 0.0 | 11.71 | 11 |
| 2.0 | 0.0 | 11.65 | 11 |
| 2.5 | 0.0 | 11.63 | 11 |

**Key insight, and the reason for it.** Results are flat in entry-threshold
space between 1 and 3 bp — but this is not evidence that there is no threshold
to overfit to. `results/eda_summary.csv` reports a median 8h funding of exactly
**1.0 bp** for both assets, which is Binance's default funding rate: the
distribution has an enormous point mass sitting precisely at the entry
threshold. Every entry threshold from 1.0 to 3.0 therefore selects almost the
same tail, and the flatness is an artifact of that clustering rather than a
property of the carry.

The same clustering makes the strategy fragile rather than robust. Dropping the
entry to 0.5 bp — below the mode — takes BTC from 9.50 % on 14 trades to
**5.06 % on 297 trades with a −11.9 % drawdown**, and ETH from 11.90 % to
7.14 % with −16.6 %. Moving the *exit* across 1 bp does the same thing in
reverse. What looks like a plateau is a narrow shelf with cliffs on both
sides, and the shelf is positioned by an exchange parameter that Binance can
change.

Holding through minor funding dips (`exit = 0`) does outperform early exits,
and that part stands.

![BTC threshold heatmap](results/figures/btc_heatmap_return.png)
![ETH threshold heatmap](results/figures/eth_heatmap_return.png)

### 6. Funding arb vs quarterly basis trade (Part 5)

Pulled active Binance USDT-M quarterly futures (3 contracts: 2026-03, 2026-06, 2026-09). Computed `(futures / spot − 1) × 365 / days_to_expiry`:

| Instrument | Mean ann. carry | Comment |
|------------|---------------:|---------|
| BTC funding-implied (2020–2026 avg) | **12.3 %** | Perp carry, full sample |
| BTC dated-futures basis (2026 contracts, current) | **4.3 %** | Observable only on active contracts |

**Why they differ in this snapshot.** We could only pull currently-active contracts; dated-futures basis in 2021–2022 was historically much higher (frequently 15–25 % annualized) but those contracts have expired and are not in the current Binance delivery history. The 4.3 % reading reflects the 2025 low-carry regime, not the long-run average.

**Structural comparison:**
- **Funding arb** = continuous carry, variable daily, exit any time, no settlement risk.
- **Basis trade** = fixed carry locked at entry, forced roll at expiry, settlement risk, usually less competitive than funding arb when funding > 0.

![Basis vs funding carry](results/figures/basis_vs_funding.png)

---

## Limitations

- **8h bar approximation.** Spot/perp marks are daily closes forward-filled to 8h. Intraday basis noise is hidden; real-time execution would add bps-level slippage.
- **Perfect delta hedge assumed.** Spot and perp are treated as 1:1 hedges at entry; actual leg-up slippage is ignored.
- **Single venue.** Binance only. Cross-venue funding spreads (Bybit / OKX / Deribit) are not considered and are where much of the institutional flow actually trades.
- **Historical quarterly-futures depth is limited** by Binance's delivery API — only active contracts retrievable, so the 2021–2022 basis-trade boom is not represented in the dated-futures comparison.
- **Sharpe is not reported as a headline** because 8h-bar Sharpe on a sparse-position strategy is mechanically inflated.
- **Eighteen trades is not a sample.** BTC trades 18 times and ETH 14 times over
  six years, all profitable. Nothing here is powered to distinguish an edge from
  a six-year run of positive funding.
- **The returns are gross of the cash rate**, and the spot leg consumes 100 % of
  notional. Netting a 4–5 % USD cash rate off the 2023–2025 years roughly halves
  the excess return and takes 2025 to approximately zero.
- **Most of the PnL is old.** 79 % of BTC's and 82 % of ETH's cumulative PnL
  comes from trades entered before 2022; nothing has been entered since
  December 2024.
- **The entry threshold sits exactly on Binance's default funding rate** (1 bp,
  the median of the series), so threshold "robustness" is an artifact of that
  point mass and the strategy is fragile to Binance changing it.
- **Marks are daily closes indexed at the bar open.** ccxt stamps daily klines at
  the open, and the code uses `close[t]` at timestamp `t`, so the price series is
  shifted one day relative to its index. The effect on results is small (BTC
  annual return 8.99 % → 8.85 %, ETH 11.43 % → 11.71 % when corrected) because
  both legs shift together and the entry rule uses no prices at all — but it is a
  genuine look-ahead and it misdates `results/btc_quarterly_basis.csv`.
- **The committed results are not reproducible as-is.** `src/data_fetcher.py`
  fetches to "now" with no date pinning, so re-running it extends the sample and
  changes every number here; and `src/basis_trade.py` refetches the *active*
  contract list, so `BTC/USDT:USDT-260327` has expired and the dated-futures
  comparison can no longer be regenerated. The raw CSVs under `data/raw/` are
  committed, so the EDA, backtest and sensitivity results *can* be reproduced
  from them without refetching.

---

## Repository Structure

```
funding_rate_arb/
├── data/raw/               spot / perp / funding CSVs
├── src/
│   ├── data_fetcher.py     Part 1 — Binance pull via ccxt
│   ├── eda.py              Part 2 — descriptive stats, plots
│   ├── backtest.py         Part 3 — long spot / short perp carry
│   ├── sensitivity.py      Part 4 — threshold grid scan
│   └── basis_trade.py      Part 5 — dated-futures basis comparison
├── results/                metrics CSVs
│   └── figures/            13 plots
├── requirements.txt
└── README.md
```

## Reproduction

```
pip install -r requirements.txt
python src/data_fetcher.py     # ~2 min — Binance API
python src/eda.py
python src/backtest.py
python src/sensitivity.py      # ~1 min — grid scan
python src/basis_trade.py
```

## Disclaimer

Research and educational use only. Not investment advice. Past carry does not imply future carry — the 2025 regime shows just how thin the edge can get.
