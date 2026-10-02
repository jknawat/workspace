"""Which instruments are even worth backtesting?

EURUSD and USDJPY were added, profiled, backtested and rejected -- and the
number that predicted it was visible before any of that work: how much the
spread costs relative to how far the instrument moves.

    gold      spread 240 against ATR 5128 points   4.7%
    USDJPY    spread  10 against ATR   47 points    21%
    EURUSD    spread   8 against ATR   28 points    29%

The strategy's edge on gold is thin (profit factor 1.19) while paying 4.7% of
each bar's range in costs. At six times that drag there is nothing left, which
is exactly what the backtests showed. So screen on the ratio first and spend
the hour of export-profile-backtest only on instruments that could plausibly
clear it.

This is a filter for *disqualifying* candidates, not a predictor of profit. A
good ratio means a symbol is worth testing; it does not mean the strategy works
on it.

    .venv\\Scripts\\python.exe scripts/screen_symbols.py
    .venv\\Scripts\\python.exe scripts/screen_symbols.py --pattern "XAU,XAG,BTC,US30"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tbot.core.indicators import atr as atr_of  # noqa: E402
from tbot.core.types import Bar  # noqa: E402

#: Gold's ratio, the one configuration known to work. Anything far above this
#: is paying proportionally more to trade than the only symbol that has ever
#: shown an edge here.
GOLD_RATIO = 0.047


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pattern", default="",
                    help="comma-separated substrings to match, e.g. 'XAU,BTC'")
    ap.add_argument("--bars", type=int, default=2000)
    ap.add_argument("--max-symbols", type=int, default=2000)
    args = ap.parse_args()

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print('MetaTrader5 is not installed: pip install -e ".[mt5]"')
        return 1

    if not mt5.initialize():
        print("could not reach MetaTrader 5:", mt5.last_error())
        return 1

    wanted = [p.strip().upper() for p in args.pattern.split(",") if p.strip()]
    rows = []
    try:
        symbols = mt5.symbols_get() or []
        for info in symbols[: args.max_symbols]:
            name = info.name
            if wanted and not any(w in name.upper() for w in wanted):
                continue
            # A symbol absent from Market Watch returns no rates. Select it
            # first, or the screen silently reports only what happens to be
            # on screen already.
            if not info.visible and not mt5.symbol_select(name, True):
                continue
            rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M5, 0, args.bars)
            if rates is None or len(rates) < 100:
                continue
            bars = [
                Bar(
                    ts=__import__("datetime").datetime.fromtimestamp(
                        int(r["time"]), tz=__import__("datetime").timezone.utc
                    ),
                    open=float(r["open"]), high=float(r["high"]),
                    low=float(r["low"]), close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                )
                for r in rates
            ]
            series = [v for v in atr_of(bars, 14) if v is not None]
            if not series:
                continue
            series.sort()
            median_atr = series[len(series) // 2]
            point = info.point or 0.0
            if point <= 0 or median_atr <= 0:
                continue
            atr_points = median_atr / point
            spread = float(info.spread)
            if spread <= 0:
                continue
            rows.append((spread / atr_points, name, spread, atr_points))
    finally:
        mt5.shutdown()

    if not rows:
        print("no symbols matched -- check the pattern, or that Market Watch "
              "has them visible")
        return 1

    rows.sort()
    print(f"{'symbol':<14} {'spread':>8} {'ATR pts':>10} {'cost ratio':>11}   verdict")
    print("-" * 64)
    for ratio, name, spread, atr_points in rows:
        if ratio <= GOLD_RATIO * 1.5:
            verdict = "worth testing"
        elif ratio <= GOLD_RATIO * 3:
            verdict = "marginal"
        else:
            verdict = "too expensive"
        star = " *" if name.upper().startswith("XAU") else ""
        print(f"{name:<14} {spread:>8.0f} {atr_points:>10,.0f} "
              f"{ratio:>10.1%}   {verdict}{star}")

    print()
    print(f"  * gold, the only symbol with a validated edge, sits at "
          f"{GOLD_RATIO:.1%}.")
    print("  A good ratio only means a symbol is worth the hour of testing.")
    print("  EURUSD and USDJPY were tested properly and both lost money.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
