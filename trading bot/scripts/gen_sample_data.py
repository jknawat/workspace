#!/usr/bin/env python3
"""Generate synthetic OHLC CSVs so the backtester can be tried immediately.

    python scripts/gen_sample_data.py --symbols EURUSD XAUUSDm --bars 5000

The walk is seeded, so the same arguments always produce the same file. This is
sample data for exercising the plumbing -- it is not a market, and a profitable
backtest on it means nothing.

Alongside ``SYMBOL_M5.csv`` it writes one file per context timeframe (M15 up to
MN1), aggregated from the same walk. Without those, every multi-timeframe gate
fails closed and the backtest reports zero trades -- which reads as a verdict
on the strategy and is really a missing feed. The context files also reach back
``--lead-days`` before the first trading bar, because a daily trend EMA needs
200 daily bars before it says anything at all.
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
    # Volatility chosen so ATR(14) sits near the 24.89 median measured on real
    # US30m M5 bars -- inside the atr_range band in config/symbols/us30.toml.
    "US30": (51000.0, 1, 14.0000, 0.0300000),
}

TF_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "H12": 720, "D1": 1440,
}
# Calendar buckets, not fixed lengths. Ordered after everything in TF_MINUTES.
CALENDAR_TFS = ("W1", "MN1")

# Matches context_timeframes in config/bot.toml.
DEFAULT_CONTEXT = ["M15", "H1", "H4", "H12", "D1", "W1", "MN1"]

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def resolve(symbol: str) -> tuple[str, str] | None:
    """Map a symbol to (profile key, file stem), or None if there is no profile.

    Brokers suffix their symbols (Exness: ``XAUUSDm``) and the config files use
    the suffixed name, so the CSV has to carry it too or the feed will not find
    it. The data is the same walk either way.
    """
    key = symbol.strip().upper()
    if key in PROFILES:
        return key, key
    if symbol.strip().endswith("m") and key[:-1] in PROFILES:
        return key[:-1], key[:-1] + "m"
    return None


def generate(symbol: str, bars: int, timeframe: str, seed: int) -> list[dict[str, object]]:
    price, digits, vol, drift = PROFILES[symbol.upper()]
    rng = random.Random(f"{seed}:{symbol}")
    minutes = TF_MINUTES[timeframe.upper()]
    ts = START
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


def generate_lead(symbol: str, bars: int, timeframe: str, seed: int) -> list[dict[str, object]]:
    """History *before* the first trading bar, walked backwards from its open.

    Its own generator, so adding or resizing the lead never changes a single
    value in the trading file -- the same arguments still give the same bars.
    """
    price, digits, vol, drift = PROFILES[symbol.upper()]
    rng = random.Random(f"{seed}:{symbol}:lead")
    minutes = TF_MINUTES[timeframe.upper()]
    ts = START
    rows: list[dict[str, object]] = []
    regime = 1.0
    while len(rows) < bars:
        ts -= timedelta(minutes=minutes)
        if ts.weekday() >= 5:
            continue
        if len(rows) % 240 == 0:
            regime = rng.choice((1.0, 1.0, -1.0, 0.0))
        step = rng.gauss(drift * regime, vol)
        close = price
        open_ = max(price - step, price * 0.5)
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
        price = open_
    rows.reverse()
    return rows


def _bucket(ts: datetime, timeframe: str) -> datetime:
    """Open time of the ``timeframe`` bar that ``ts`` falls in."""
    if timeframe == "MN1":
        return ts.replace(day=1, hour=0, minute=0)
    if timeframe == "W1":
        day = ts.replace(hour=0, minute=0)
        return day - timedelta(days=day.weekday())
    minutes = TF_MINUTES[timeframe]
    into_day = (ts.hour * 60 + ts.minute) // minutes * minutes
    return ts.replace(hour=into_day // 60, minute=into_day % 60)


def aggregate(rows: list[dict[str, object]], timeframe: str) -> list[dict[str, object]]:
    """Roll base bars up into a higher timeframe. ``rows`` must be oldest first."""
    out: dict[datetime, dict[str, object]] = {}
    for row in rows:
        key = _bucket(datetime.fromisoformat(str(row["ts"])), timeframe)
        bar = out.get(key)
        if bar is None:
            out[key] = {**row, "ts": key.isoformat()}
            continue
        bar["high"] = max(bar["high"], row["high"])  # type: ignore[type-var]
        bar["low"] = min(bar["low"], row["low"])  # type: ignore[type-var]
        bar["close"] = row["close"]
        bar["volume"] = bar["volume"] + row["volume"]  # type: ignore[operator]
    return list(out.values())


def _is_higher(timeframe: str, base: str) -> bool:
    if timeframe in CALENDAR_TFS:
        return True
    return TF_MINUTES[timeframe] > TF_MINUTES[base]


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="*", default=["EURUSD", "XAUUSD", "USDJPY"])
    ap.add_argument("--bars", type=int, default=6000)
    ap.add_argument("--timeframe", default="M5")
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--context",
        nargs="*",
        default=DEFAULT_CONTEXT,
        help="higher timeframes to write alongside (pass with no values for none)",
    )
    ap.add_argument(
        "--lead-days",
        type=int,
        default=300,
        help="trading days of history the context files get before the first bar",
    )
    args = ap.parse_args()

    base = args.timeframe.upper()
    context = [tf.upper() for tf in args.context]
    unknown = [tf for tf in context if tf not in TF_MINUTES and tf not in CALENDAR_TFS]
    if unknown:
        ap.error(f"unknown context timeframe(s): {', '.join(unknown)}")
    context = [tf for tf in context if _is_higher(tf, base)]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for symbol in args.symbols:
        resolved = resolve(symbol)
        if resolved is None:
            print(f"skipping {symbol}: no profile (known: {', '.join(PROFILES)})")
            continue
        key, stem = resolved
        rows = generate(key, args.bars, base, args.seed)
        path = out / f"{stem}_{base}.csv"
        _write(path, rows)
        print(f"{path}  {len(rows):,} bars  {rows[0]['ts']} -> {rows[-1]['ts']}")

        if not context:
            continue
        lead_bars = args.lead_days * 1440 // TF_MINUTES[base]
        full = generate_lead(key, lead_bars, base, args.seed) + rows
        counts = []
        for tf in context:
            higher = aggregate(full, tf)
            _write(out / f"{stem}_{tf}.csv", higher)
            counts.append(f"{tf} {len(higher):,}")
        print(f"  context from {full[0]['ts']}: {', '.join(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
