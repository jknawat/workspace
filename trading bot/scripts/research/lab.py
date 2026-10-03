"""Experiment harness: config variants over fixed date windows, on real bars.

``tbot backtest`` answers "what does the config on disk do over this file?".
The questions that decide a change are different: what does *this variant* do
in *each period separately*, next to the current config, without editing a
file to find out. This builds each variant in memory from the TOML on disk plus
a dict of overrides, slices the trading timeframe to a date window, and runs
the ordinary ``run_backtest`` -- same engine, same simulator, same risk gate.

Data: the longest history the terminal will serve, in ``data/long``::

    .venv\\Scripts\\python.exe scripts/export_bars.py XAUUSDm US30m JP225m ^
        DE30m USTECm --days 690 --out data/long

Context timeframes are read whole and replayed point-in-time, so a window that
starts in May still has a warm daily trend on its first bar.

Nothing here writes to the config, the journal or the live log.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import math
import sys
import tomllib
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "data" / "long"
UTC = timezone.utc

#: H is the holdout: 2025-05-07 .. 2025-11-26, which no test before
#: 2026-10-03 had touched. A and B are the two halves every earlier result in
#: docs/BACKTEST_FINDINGS.md was split on.
T0 = datetime(2025, 5, 7, tzinfo=UTC)
T1 = datetime(2025, 11, 26, tzinfo=UTC)
T2 = datetime(2026, 5, 1, tzinfo=UTC)
T3 = datetime(2026, 10, 3, tzinfo=UTC)
PERIODS = {"H": (T0, T1), "A": (T1, T2), "B": (T2, T3)}

#: Spread charged per symbol, in points. Measured, then rounded up.
SPREADS = {"XAUUSDm": 240.0, "US30m": 13.0, "USTECm": 112.0, "DE30m": 10.0, "JP225m": 35.0}


def _deep_merge(base: dict, over: dict) -> dict:
    """Merge ``over`` into ``base``; a ``None`` value deletes the key."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def raw_symbol(name: str) -> dict:
    """The TOML table of the symbol file that configures ``name``."""
    for file in sorted((ROOT / "config" / "symbols").glob("*.toml")):
        with file.open("rb") as fh:
            raw = tomllib.load(fh)
        if str(raw.get("symbol", "")).strip() == name:
            return raw
    raise KeyError(f"no symbol file configures {name}")


def run_one(job: dict[str, Any]) -> dict[str, Any]:
    """Run one variant over one window.

    ``job`` keys: ``label``; ``period`` (a key of PERIODS or a (start, end)
    pair); ``symbols`` mapping a symbol name to ``{base, over, weight}`` where
    ``base`` names the symbol file to start from (default: its own) and
    ``over`` is one override dict or a list applied in order; optional
    ``risk`` / ``engine`` field overrides and a ``spreads`` map.
    """
    logging.disable(logging.CRITICAL)
    from tbot.cli import _load_specs
    from tbot.config import load_config
    from tbot.config.models import SymbolConfig
    from tbot.data.feed import BarFeed, CsvFeed
    from tbot.engine import run_backtest

    cfg = load_config(ROOT / "config" / "bot.toml")
    symbols = []
    for name, spec in job["symbols"].items():
        raw = raw_symbol(spec.get("base", name))
        overs = spec.get("over", {})
        for over in overs if isinstance(overs, list) else [overs]:
            raw = _deep_merge(raw, over)
        raw["symbol"] = name
        raw["enabled"] = True
        if "weight" in spec:
            raw["weight"] = spec["weight"]
        symbols.append(SymbolConfig.from_dict(raw, f"lab:{name}"))

    risk = dataclasses.replace(cfg.risk, **job["risk"]) if job.get("risk") else cfg.risk
    engine = dataclasses.replace(cfg.engine, **job["engine"]) if job.get("engine") else cfg.engine
    cfg = dataclasses.replace(cfg, symbols=tuple(symbols), risk=risk, engine=engine)

    period = job["period"]
    start, end = PERIODS[period] if isinstance(period, str) else period
    csv = CsvFeed(DATA)

    class Windowed(BarFeed):
        def history(self, symbol: str, timeframe: str, count: int):
            bars = csv.history(symbol, timeframe, 0)
            if timeframe.upper() == cfg.engine.timeframe.upper():
                bars = [b for b in bars if start <= b.ts < end]
            return bars[-count:] if count > 0 else bars

    spreads = job.get("spreads", SPREADS)
    report = run_backtest(
        cfg, Windowed(),
        specs=_load_specs(str(ROOT / "config" / "specs.toml")),
        spread_points={s.symbol: spreads[s.symbol] for s in symbols},
    )

    weekdays = max(1.0, (end - start).days * 5 / 7)
    pnls: dict[str, list[float]] = {}
    for trade in report.trades:
        pnls.setdefault(trade.symbol, []).append(trade.pnl)
    return {
        "label": job["label"],
        "period": period if isinstance(period, str) else "full",
        "trades": len(report.trades),
        "win": round(report.win_rate, 1),
        "net": round(report.net_pnl, 2),
        "pf": round(report.profit_factor, 2),
        "dd": round(report.max_drawdown_pct, 1),
        "per_day": round(len(report.trades) / weekdays, 2),
        "streak": report.longest_losing_streak,
        "pnls": pnls,
        "declined": sorted(report.declined_reasons.items(), key=lambda kv: -kv[1])[:3],
    }


def run_all(jobs: list[dict[str, Any]], workers: int = 10) -> list[dict[str, Any]]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_one, jobs))


def grid(variants: dict[str, dict], periods: tuple[str, ...] = ("H", "A", "B")) -> list[dict]:
    """One job per variant per period."""
    return [
        {**body, "label": label, "period": period}
        for label, body in variants.items()
        for period in periods
    ]


def show(results: list[dict[str, Any]], periods: tuple[str, ...] = ("H", "A", "B")) -> None:
    by: dict[str, dict[str, dict]] = {}
    for r in results:
        by.setdefault(r["label"], {})[r["period"]] = r
    head = f"{'variant':<32}" + "".join(
        f"| {p + ' trd':>6} {'net':>8} {'pf':>5} {'dd%':>5} " for p in periods
    )
    print(head)
    print("-" * len(head))
    for label, per in by.items():
        row = f"{label:<32}"
        for p in periods:
            r = per.get(p)
            row += (
                f"| {r['trades']:>6} {r['net']:>+8.0f} {r['pf']:>5.2f} {r['dd']:>5.1f} "
                if r else "| " + " " * 28
            )
        print(row)


def t_stat(values: list[float]) -> tuple[float, float]:
    """Mean and t-statistic of per-trade results: is the mean distinguishable from zero?"""
    n = len(values)
    if n < 2:
        return (values[0] if values else 0.0), 0.0
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    return mean, (mean / (sd / math.sqrt(n)) if sd else 0.0)
