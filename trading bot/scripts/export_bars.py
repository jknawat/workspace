"""Export real bars from MetaTrader 5 into the CSV files the backtester reads.

Gold's data was exported by hand, which was fine once and useless the second
time -- the second machine needs the same files, and so does every symbol added
after the first. This is that step, repeatable.

    .venv\\Scripts\\python.exe scripts/export_bars.py XAUUSDm
    .venv\\Scripts\\python.exe scripts/export_bars.py EURUSDm USDJPYm --days 310

Timestamps are written as the broker sends them, converted once to UTC using
``[engine].broker_utc_offset_hours`` -- the same conversion the live path makes,
so a backtest and a live session read the same clock.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tbot.config import load_config  # noqa: E402

#: Bars per minute of each timeframe, used to size the request.
MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "H12": 720, "D1": 1440, "W1": 10080, "MN1": 43200,
}


def export(mt5, symbol: str, timeframe: str, days: int, offset_hours: float,
           out_dir: Path) -> int:
    tf = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
    if tf is None:
        print(f"  {timeframe:<4} not a MetaTrader timeframe, skipped")
        return 0

    minutes = MINUTES.get(timeframe, 5)
    # Ask for more than the window needs: the higher timeframes want enough
    # history for a 200-bar trend EMA to converge, not just enough to cover
    # the test period.
    wanted = max(int(days * 24 * 60 / minutes) + 50, 1500)
    wanted = min(wanted, 200_000)

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, wanted)
    if rates is None or len(rates) == 0:
        print(f"  {timeframe:<4} no data ({mt5.last_error()})")
        return 0

    path = out_dir / f"{symbol}_{timeframe}.csv"
    shift = timedelta(hours=offset_hours)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for r in rates:
            # Broker wall-clock -> UTC, once, here. Doing it later means two
            # places can disagree about what a timestamp means.
            ts = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc) - shift
            w.writerow([
                ts.isoformat(),
                f"{float(r['open']):.5f}".rstrip("0").rstrip("."),
                f"{float(r['high']):.5f}".rstrip("0").rstrip("."),
                f"{float(r['low']):.5f}".rstrip("0").rstrip("."),
                f"{float(r['close']):.5f}".rstrip("0").rstrip("."),
                float(r["tick_volume"]),
            ])
    first = datetime.fromtimestamp(int(rates[0]["time"]), tz=timezone.utc) - shift
    last = datetime.fromtimestamp(int(rates[-1]["time"]), tz=timezone.utc) - shift
    print(f"  {timeframe:<4} {len(rates):>7} bars  "
          f"{first:%Y-%m-%d} .. {last:%Y-%m-%d}  -> {path.name}")
    return len(rates)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="+", help="broker symbol names, e.g. EURUSDm")
    ap.add_argument("--days", type=int, default=310,
                    help="how much history to cover (default 310, matching the "
                         "gold set every other result is measured against)")
    ap.add_argument("--config", default=str(ROOT / "config" / "bot.toml"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    args = ap.parse_args()

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("MetaTrader5 is not installed: pip install -e \".[mt5]\"")
        return 1

    cfg = load_config(args.config)
    timeframes = [cfg.engine.timeframe, *cfg.engine.context_timeframes]
    seen: list[str] = []
    for tf in timeframes:
        if tf.upper() not in seen:
            seen.append(tf.upper())

    if not mt5.initialize():
        print("could not reach MetaTrader 5:", mt5.last_error())
        print("Open the terminal and log in, then run this again.")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    offset = cfg.engine.broker_utc_offset_hours

    try:
        for symbol in args.symbols:
            info = mt5.symbol_info(symbol)
            if info is None:
                print(f"{symbol}: not found at this broker, skipped")
                continue
            if not info.visible and not mt5.symbol_select(symbol, True):
                print(f"{symbol}: could not be added to Market Watch, skipped")
                continue
            print(f"{symbol} (spread now {info.spread} points):")
            for tf in seen:
                export(mt5, symbol, tf, args.days, offset, out_dir)
    finally:
        mt5.shutdown()

    print("\nNext: profile each symbol before trusting any filter bound --")
    print("  .venv\\Scripts\\python.exe scripts/profile_symbol.py <SYMBOL>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
