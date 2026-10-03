"""The experiments behind docs/RESEARCH_2026-10-03.md, repeatable.

    .venv\\Scripts\\python.exe scripts/research/night_2026_10_03.py            # everything
    .venv\\Scripts\\python.exe scripts/research/night_2026_10_03.py portfolio  # one section

Sections: baseline, screen, hours, symbols, portfolio, stress, neighbours, donchian.

"Before" is pinned explicitly (gold 08:00-20:00, no JP225) rather than read
from the config, because the config on disk is now the "after".

Two rules, and which one applies depends on what a change does.

* A change to how trades are *chosen or managed* (a parameter, an exit policy)
  must beat the current profit factor in A, in B and in H. Of 62 tried, 2 did.
  Chance alone would pass about 8, so none was adopted.
* A change that *adds trades* without altering the existing ones (more hours,
  another symbol) is judged on the added trades alone: they must be profitable
  in A, in B and in H. Of 7 tried, 2 were, and both were adopted.

H was opened only for variants that had already passed A and B.
"""

from __future__ import annotations

import sys

from lab import SPREADS, T0, T1, T3, grid, run_all, show, t_stat

OPEN_SPREAD = {"filters": {"spread": {"max_points": 100000}}}


def session(start: str, end: str) -> dict:
    return {"session": {"start": start, "end": end}}


def gold(start: str = "08:00", end: str = "20:00", weight: float = 3.0, **over) -> dict:
    return {"weight": weight, "over": {**OPEN_SPREAD, **session(start, end), **over}}


def us30(weight: float = 1.0, **over) -> dict:
    return {"weight": weight, "over": {**OPEN_SPREAD, **over}}


def index(lo: float, hi: float, start: str = "08:00", end: str = "20:00",
          weight: float = 1.0) -> dict:
    """A new index symbol: US30's file (gold's parameters) with its own ATR band."""
    return {
        "base": "US30m", "weight": weight,
        "over": {**OPEN_SPREAD, **session(start, end),
                 "filters": {"atr_range": {"min": lo, "max": hi},
                             "spread": {"max_points": 100000}}},
    }


JP = (19.67, 145.54)     # p5, p95 of ATR(14) on M5
DE = (6.55, 35.09)
TEC = (6.88, 49.19)

BEFORE = {"XAUUSDm": gold(), "US30m": us30()}
AFTER = {"XAUUSDm": gold("01:00"), "US30m": us30(), "JP225m": index(*JP)}


def baseline() -> None:
    print("\n== the config as it stood, including the period nothing had seen ==")
    show(run_all(grid({
        "gold alone": {"symbols": {"XAUUSDm": gold()}},
        "US30 alone": {"symbols": {"US30m": us30()}},
        "gold 3 + US30 1": {"symbols": BEFORE},
    })))
    full = run_all([{"label": "gold", "period": (T1, T3), "symbols": {"XAUUSDm": gold()}}])[0]
    print(f"\ngold, 2025-11-26 on, one run: {full['trades']} trades, net {full['net']:+.2f}, "
          f"pf {full['pf']}   (findings doc: 125 trades, +1620.66, pf 1.19)")


SCREEN: dict[str, dict] = {
    "baseline": {},
    "session 07-20": session("07:00", "20:00"),
    "session 06-20": session("06:00", "20:00"),
    "session 08-21": session("08:00", "21:00"),
    "session 08-22": session("08:00", "22:00"),
    "session 06-22": session("06:00", "22:00"),
    "session 01-20": session("01:00", "20:00"),
    "session 00-24": session("00:00", "23:59"),
    "session 12-20": session("12:00", "20:00"),
    "session 08-17": session("08:00", "17:00"),
    "pullback_bars 1": {"params": {"pullback_bars": 1}},
    "pullback_bars 3": {"params": {"pullback_bars": 3}},
    "window_bars 5": {"params": {"window_bars": 5}},
    "window_bars 12": {"params": {"window_bars": 12}},
    "max_wait 15": {"params": {"pullback_max_wait": 15}},
    "offset 0.25": {"params": {"window_offset_atr": 0.25}},
    "offset 0.6": {"params": {"window_offset_atr": 0.6}},
    "no opposite-cross cancel": {"params": {"invalidate_on_opposite_cross": False}},
    "tp 6.0": {"params": {"tp_atr": 6.0}},
    "tp 9.0": {"params": {"tp_atr": 9.0}},
    "sl 2.5 tp 6.25": {"params": {"sl_atr": 2.5, "tp_atr": 6.25}},
    "sl 3.5 tp 8.75": {"params": {"sl_atr": 3.5, "tp_atr": 8.75}},
    "time_stop 48": {"exits": {"time_stop": {"max_bars": 48, "min_r": 0.5}}},
    "time_stop 96": {"exits": {"time_stop": {"max_bars": 96, "min_r": 0.5}}},
    "time_stop 144 r0": {"exits": {"time_stop": {"max_bars": 144, "min_r": 0.0}}},
    "break_even 1R": {"exits": {"break_even": {"trigger_r": 1.0}}},
    "break_even 1.5R": {"exits": {"break_even": {"trigger_r": 1.5}}},
    "trail 2atr from 1.5R": {"exits": {"trailing_atr": {"distance_atr": 2.0, "start_r": 1.5}}},
    "trail 3atr from 1R": {"exits": {"trailing_atr": {"distance_atr": 3.0, "start_r": 1.0}}},
    "partial 50% at 1R": {"exits": {"partial_tp": {"trigger_r": 1.0, "percent": 50.0}}},
    "partial 50% at 1.5R": {"exits": {"partial_tp": {"trigger_r": 1.5, "percent": 50.0}}},
}


def screen() -> None:
    """31 single changes per symbol. All three periods are printed here for the
    record; on the night, H was opened only for the rows that beat baseline in
    both A and B."""
    for name, make in (("XAUUSDm", gold), ("US30m", us30)):
        variants = {}
        for label, over in SCREEN.items():
            body = make()
            body["over"] = {**body["over"], **over}
            if name == "XAUUSDm" and "session" not in over:
                body["over"]["session"] = {"start": "08:00", "end": "20:00"}
            variants[label] = {"symbols": {name: {k: v for k, v in body.items() if k != "weight"}}}
        variants["2 positions per symbol"] = {
            "symbols": {name: {"over": make()["over"]}}, "risk": {"max_positions_per_symbol": 2},
        }
        print(f"\n== {name} alone ==")
        show(run_all(grid(variants)))


def hours() -> None:
    print("\n== extra hours, each judged on its own ==")
    show(run_all(grid({
        "gold 08-20 (before)": {"symbols": {"XAUUSDm": gold()}},
        "gold 01-08 only": {"symbols": {"XAUUSDm": gold("01:00", "07:59")}},
        "gold 00-08 only": {"symbols": {"XAUUSDm": gold("00:00", "07:59")}},
        "gold 20-24 only": {"symbols": {"XAUUSDm": gold("20:01", "23:59")}},
        "US30 08-20 (current)": {"symbols": {"US30m": us30()}},
        "US30 00-08 only": {"symbols": {"US30m": us30(**session("00:00", "07:59"))}},
        "US30 20-24 only": {"symbols": {"US30m": us30(**session("20:01", "23:59"))}},
    })))


def symbols() -> None:
    print("\n== new symbols, gold's parameters unchanged, each alone ==")
    show(run_all(grid({
        "DE30 08-20": {"symbols": {"DE30m": index(*DE)}},
        "DE30 06-20": {"symbols": {"DE30m": index(*DE, start="06:00")}},
        "USTEC 08-20": {"symbols": {"USTECm": index(*TEC)}},
        "JP225 08-20": {"symbols": {"JP225m": index(*JP)}},
        "JP225 00-20": {"symbols": {"JP225m": index(*JP, start="00:00")}},
    })))


PORTFOLIOS = {
    "P0 before": {"symbols": BEFORE},
    "P1 gold 01-20": {"symbols": {"XAUUSDm": gold("01:00"), "US30m": us30()}},
    "P2 + JP225": {"symbols": {**BEFORE, "JP225m": index(*JP)}},
    "P3 both (adopted)": {"symbols": AFTER},
    "P4 both, JP225 00-20": {"symbols": {**AFTER, "JP225m": index(*JP, start="00:00")}},
    "P3 at 0.8% risk": {"symbols": AFTER, "risk": {"risk_per_trade_pct": 0.8}},
}


def portfolio() -> None:
    print("\n== portfolios, total risk 1% throughout, 10,000 start ==")
    show(run_all(grid(PORTFOLIOS)))
    print("\n== the same at 5,000, the real paper account ==")
    at5k = {k: {**v, "engine": {"start_balance": 5000.0}} for k, v in PORTFOLIOS.items()}
    show(run_all(grid({k: at5k[k] for k in ("P0 before", "P3 both (adopted)")})))
    print("\n== 17 months as one continuous run ==")
    jobs = [{**body, "label": label, "period": (T0, T3)} for label, body in PORTFOLIOS.items()]
    for r in run_all(jobs):
        print(f"{r['label']:<24} {r['trades']:>4} trades  {r['per_day']:.2f}/day  "
              f"net {r['net']:>+8.0f}  pf {r['pf']:.2f}  dd {r['dd']}%  "
              f"longest losing streak {r['streak']}")
    print("\n== the config on disk, with no overrides: must equal P3 ==")
    names = ("XAUUSDm", "US30m", "JP225m")
    show(run_all(grid({"config/symbols as committed": {"symbols": {n: {} for n in names}}})))


def stress() -> None:
    """The simulator charges half the spread at entry and nothing at exit. A
    real round trip pays all of it, so x2 is the honest figure and x3 a stress."""
    for mult in (2.0, 3.0):
        print(f"\n== spreads x{mult:g} ==")
        spreads = {k: v * mult for k, v in SPREADS.items()}
        show(run_all(grid({
            "P0 before": {"symbols": BEFORE, "spreads": spreads},
            "P3 both (adopted)": {"symbols": AFTER, "spreads": spreads},
        })))
    print("\n== each stream alone over 17 months: is its mean distinguishable from zero? ==")
    jobs = [
        {"label": "gold 08-20", "symbols": {"XAUUSDm": gold()}},
        {"label": "gold 01-08 only", "symbols": {"XAUUSDm": gold("01:00", "07:59")}},
        {"label": "US30 08-20", "symbols": {"US30m": us30()}},
        {"label": "JP225 08-20", "symbols": {"JP225m": index(*JP)}},
    ]
    for r in run_all([{**j, "period": (T0, T3)} for j in jobs]):
        values = next(iter(r["pnls"].values()))
        mean, t = t_stat(values)
        print(f"{r['label']:<18} {len(values):>4} trades  net {r['net']:>+8.0f}  pf {r['pf']:.2f}  "
              f"mean {mean:>+6.1f}/trade  t = {t:.2f}")


def neighbours() -> None:
    print("\n== gold: every start hour near the one chosen ==")
    show(run_all(grid({
        f"gold {h:02d}-20": {"symbols": {"XAUUSDm": gold(f"{h:02d}:00")}}
        for h in (0, 1, 2, 3, 4, 6, 8)
    })))
    print("\n== JP225: settings near the ones chosen ==")
    show(run_all(grid({
        "JP225 08-20 (adopted)": {"symbols": {"JP225m": index(*JP)}},
        "JP225 07-20": {"symbols": {"JP225m": index(*JP, start="07:00")}},
        "JP225 09-20": {"symbols": {"JP225m": index(*JP, start="09:00")}},
        "JP225 08-21": {"symbols": {"JP225m": index(*JP, end="21:00")}},
        "JP225 atr band p10-p90": {"symbols": {"JP225m": index(24.0, 115.0)}},
        "JP225 no atr band": {"symbols": {"JP225m": index(0.0, 100000.0)}},
    })))


def donchian() -> None:
    """A different entry under the same filters, stops and risk."""
    def breakout(name: str, period: int) -> dict:
        base = gold() if name == "XAUUSDm" else us30() if name == "US30m" else index(*JP)
        return {
            "base": base.get("base", name),
            "over": [
                base["over"],
                {"params": None, "strategy": "donchian"},
                {"params": {"channel_period": period, "sl_atr": 3.0, "tp_atr": 7.5,
                            "cooldown_bars": 6},
                 "filters": {"angle": None}},
            ],
        }

    print("\n== Donchian channel breakout in place of the EMA pullback ==")
    show(run_all(grid({
        f"{name} donchian {period}": {"symbols": {name: breakout(name, period)}}
        for name in ("XAUUSDm", "US30m", "JP225m")
        for period in (20, 48, 96)
    })))


SECTIONS = {
    "baseline": baseline, "screen": screen, "hours": hours, "symbols": symbols,
    "portfolio": portfolio, "stress": stress, "neighbours": neighbours, "donchian": donchian,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SECTIONS)
    unknown = [w for w in wanted if w not in SECTIONS]
    if unknown:
        raise SystemExit(f"unknown section(s) {unknown}; choose from {', '.join(SECTIONS)}")
    for name in wanted:
        SECTIONS[name]()
