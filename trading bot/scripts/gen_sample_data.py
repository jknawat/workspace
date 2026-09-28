#!/usr/bin/env python3
"""Generate synthetic OHLC CSVs so the backtester can be tried immediately.

    python scripts/gen_sample_data.py --symbols EURUSD XAUUSD --bars 5000

The walk is seeded, so the same arguments always produce the same file. This is
sample data for exercising the plumbing -- it is not a market, and a profitable
backtest on it means nothing.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# symbol -> (start price, digits, per-bar volatility, trend per bar)
PROFILES: dict[str, tuple[float, int, float, float]] = {
    "EURUSD": (1.0850, 5, 0.00035, 0.0000020),
    "GBPUSD": (1.2650, 5, 0.00045, -0.0000015),
    "USDJPY": (152.500, 3, 0.0450, 0.0000400),
    "XAUUSD": (2350.00, 2, 1.8000, 0.0040000),
    "XAGUSD": (28.500, 3, 0.0450, 0.0000300),
}

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def generate(symbol: str, bars: int, timeframe: str, seed: int) -> list[dict[str, object]]:
    price, digits, vol, drift = PROFILES[symbol.upper()]
    rng = random.Random(f"{seed}:{symbol}")
    minutes = TF_MINUTES[timeframe.upper()]
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    regime = 1.0
    while len(rows) < bars:
        if ts.weekday() >= 5:  # skip the weekend, as a real feed does
            ts += timedelta(minutes=minutes)
            continue
        if len(rows) % 240 == 0:  # flip trend regime a few times a day
            regime = rng.choice((1.0, 1.0, -1.0, 0.0))
        step = rng.gauss(drift * regime, vol)
        open_ = price
        close = max(price + step, price * 0.5)
        wick = abs(rng.gauss(0.0, vol * 0.6))
        rows.append(
            {
                "ts": ts.isoformat(),
                "open": round(open_, digits),
                "high": round(max(open_, close) + wick, digits),
                "low": round(min(open_, close) - wick, digits),
                "close": round(close, digits),
                "volume": rng.randint(50, 900),
            }
        )
        price = close
        ts += timedelta(minutes=minutes)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="*", default=["EURUSD", "XAUUSD", "USDJPY"])
    ap.add_argument("--bars", type=int, default=6000)
    ap.add_argument("--timeframe", default="M5")
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for symbol in args.symbols:
        if symbol.upper() not in PROFILES:
            print(f"skipping {symbol}: no profile (known: {', '.join(PROFILES)})")
            continue
        rows = generate(symbol, args.bars, args.timeframe, args.seed)
        path = out / f"{symbol.upper()}_{args.timeframe.upper()}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"{path}  {len(rows):,} bars  {rows[0]['ts']} -> {rows[-1]['ts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
