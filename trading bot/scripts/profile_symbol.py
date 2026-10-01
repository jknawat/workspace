#!/usr/bin/env python3
"""Measure a symbol's live behaviour, so filter bounds are data not guesses.

    python scripts/profile_symbol.py XAUUSDm
    python scripts/profile_symbol.py EURUSDm --bars 3000 --timeframe M15

Prints the distributions a symbol config needs: ATR percentiles for
``[filters.atr_range]``, slope percentiles under both scalings for
``[filters.angle]``, spread for ``[filters.spread]``, and the lot size a given
risk buys at median volatility.

Why this exists: gold shipped with ``atr_range min 0.8 max 12.0`` while its
actual ATR(14) ranges 2.4-8.0, so the filter admitted every bar -- a filter
that never rejects is not a filter. And ``[filters.angle] min_degrees = 10``
was meaningless because point-scaled slope pins gold at ~89.9 degrees on every
bar. Both were caught by running this kind of measurement, not by reading code.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tbot.broker.base import BrokerError
from tbot.broker.mt5 import MT5Broker
from tbot.core.indicators import atr, ema, slope_degrees

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbol", help="exact broker symbol, e.g. XAUUSDm")
    ap.add_argument("--bars", type=int, default=1500)
    ap.add_argument("--timeframe", default="M5")
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--ema", type=int, default=21, help="EMA the slope is measured on")
    ap.add_argument("--lookback", type=int, default=5, help="slope lookback in bars")
    ap.add_argument("--risk", type=float, default=100.0, help="risk budget for the sizing line")
    ap.add_argument("--sl-atr", type=float, default=3.0)
    ap.add_argument("--terminal", default=TERMINAL)
    args = ap.parse_args()

    broker = MT5Broker(credentials={"terminal_path": args.terminal})
    try:
        broker.connect()
        spec = broker.symbol_spec(args.symbol)
        bars = broker.bars(args.symbol, args.timeframe, args.bars)
        spread = broker.spread_points(args.symbol)
    except BrokerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"{spec.name} {args.timeframe}  {len(bars)} bars  "
          f"{bars[0].ts:%Y-%m-%d %H:%M} -> {bars[-1].ts:%Y-%m-%d %H:%M} UTC")
    print(f"  price {bars[-1].close:,.{spec.digits}f}   digits {spec.digits}   "
          f"point {spec.point}   volume {spec.volume_min}/{spec.volume_step}")
    print(f"  ${spec.value_per_price_unit:,.2f} per 1.0 of price, per lot"
          + ("  (from the broker's own calculation)" if spec.money_per_price_unit
             else "  (derived from tick_value -- verify on CFDs)"))
    print(f"  spread now: {spread:.0f} points")

    series = atr(bars, args.atr_period)
    values = [v for v in series if v is not None]
    if not values:
        print("not enough history for ATR", file=sys.stderr)
        return 1
    median = statistics.median(values)
    print(f"\nATR({args.atr_period}):")
    print(f"  min {min(values):.3f}   p5 {pct(values, 0.05):.3f}   "
          f"median {median:.3f}   p95 {pct(values, 0.95):.3f}   max {max(values):.3f}")
    print(f"  suggested [filters.atr_range]  min = {pct(values, 0.05):.2f}  "
          f"max = {pct(values, 0.95):.2f}")

    closes = [b.close for b in bars]
    trend = ema(closes, args.ema)
    for label, scale in (("point", spec.point), ("atr", series)):
        slopes = [abs(v) for v in slope_degrees(trend, args.lookback, scale) if v is not None]
        if not slopes:
            continue
        print(f"\n|slope| of EMA{args.ema} over {args.lookback} bars, scale={label}:")
        print(f"  median {pct(slopes, 0.5):.1f}   p75 {pct(slopes, 0.75):.1f}   "
              f"p90 {pct(slopes, 0.90):.1f}   max {max(slopes):.1f}")
        if pct(slopes, 0.5) > 80:
            print("  WARNING: saturated near 90 degrees -- this scaling cannot "
                  "discriminate on this symbol, so an angle filter using it "
                  "would pass everything")

    stop = args.sl_atr * median
    lots = args.risk / (stop * spec.value_per_price_unit)
    print(f"\nsizing at median ATR: {args.sl_atr}xATR stop = {stop:.2f} -> "
          f"{lots:.2f} lots for {args.risk:,.0f} risk (broker minimum {spec.volume_min})")
    if lots < spec.volume_min:
        print("  WARNING: below the broker minimum -- the risk gate will decline "
              "every trade on this symbol at this budget")

    broker.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
