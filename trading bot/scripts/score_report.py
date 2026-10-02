"""What each confidence band is actually worth.

The scorer hands out points. This answers the only question that matters about
them: do higher-scoring trades make more money than lower-scoring ones? If the
bands all perform the same, the score is decoration and the tiers should be
deleted rather than tuned.

Method: replay with scoring switched *off*, so every signal that passes the
gates becomes a trade, while recording what the score would have been. Then
bucket the closed trades by that score and report each bucket's real win rate
and expectancy. Gating first and measuring second would only ever show the
bands that were already allowed to trade.

    .venv\\Scripts\\python.exe scripts/score_report.py

Read the result with the dataset's history in mind: these are the same 310 days
every other decision has already been taken on, so a band that looks good here
has not been validated, only described. docs/BACKTEST_FINDINGS.md keeps the
count of how often this data has been asked.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tbot.cli import _load_specs  # noqa: E402
from tbot.config import load_config  # noqa: E402
from tbot.data.feed import CsvFeed  # noqa: E402
from tbot.engine import run_backtest  # noqa: E402
from tbot.engine.core import TradeEngine  # noqa: E402
from tbot.strategy.confidence import Tier  # noqa: E402

#: Score bands to report. Edges are inclusive-low, exclusive-high.
BANDS = [(0, 30), (30, 45), (45, 60), (60, 75), (75, 88), (88, 101)]

SPREAD_POINTS = 240.0


def main() -> int:
    cfg = load_config(str(ROOT / "config" / "bot.toml"))
    scfg = cfg.active_symbols[0]
    specs = _load_specs(str(ROOT / "config" / "specs.toml"))

    # Score every signal, gate none of them: min_score 0 with one all-in tier.
    scoring = dataclasses.replace(
        scfg.confidence, enabled=True, min_score=0.0,
    )
    scoring.tiers = (Tier(min_score=0.0, risk_mult=1.0, label="measuring"),)
    measured = dataclasses.replace(scfg, confidence=scoring)
    run_cfg = dataclasses.replace(cfg, symbols=(measured,))

    # Capture each entry's score as it happens. The engine publishes a SCORED
    # event per rated signal; pairing it with the trade that follows is what
    # ties a score to an outcome.
    scores: dict[tuple[str, str], float] = {}
    original = TradeEngine.step

    def recording_step(self, symbol, i=None):
        result = original(self, symbol, i)
        if result.score is not None and result.entered and result.bar is not None:
            scores[(result.symbol, result.bar.ts.isoformat())] = result.score.points
        return result

    TradeEngine.step = recording_step  # type: ignore[method-assign]
    try:
        feed = CsvFeed(str(ROOT / "data"))
        report = run_backtest(
            run_cfg, feed, specs=specs,
            spread_points={scfg.symbol: SPREAD_POINTS},
        )
    finally:
        TradeEngine.step = original  # type: ignore[method-assign]

    print(f"\n{len(report.trades)} trades, {len(scores)} scored entries")
    print(f"overall: {report.win_rate:.1f}% win, {report.net_pnl:+.2f}, "
          f"pf {report.profit_factor:.2f}\n")

    rated: list[tuple[float, float]] = []
    unmatched = 0
    for t in report.trades:
        key = (t.symbol, t.opened_at.isoformat())
        points = scores.get(key)
        if points is None:
            unmatched += 1
            continue
        rated.append((points, t.pnl))

    if unmatched:
        print(f"note: {unmatched} trades could not be matched to a score "
              "(entry bar timestamps differ); they are excluded\n")
    if not rated:
        print("no trades could be tied to a score -- nothing to report")
        return 1

    header = (f"{'band':>10} {'trades':>7} {'win%':>7} {'net':>11} "
              f"{'per trade':>10} {'pf':>6}")
    print(header)
    print("-" * len(header))
    for lo, hi in BANDS:
        bucket = [pnl for pts, pnl in rated if lo <= pts < hi]
        if not bucket:
            print(f"{f'{lo}-{hi - 1}':>10} {0:>7} {'-':>7} {'-':>11} {'-':>10} {'-':>6}")
            continue
        wins = [p for p in bucket if p > 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(p for p in bucket if p <= 0))
        pf = gross_win / gross_loss if gross_loss else float("inf")
        print(
            f"{f'{lo}-{hi - 1}':>10} {len(bucket):>7} "
            f"{len(wins) / len(bucket) * 100:>6.1f}% {sum(bucket):>+11.2f} "
            f"{sum(bucket) / len(bucket):>+10.2f} {pf:>6.2f}"
        )

    print("\nWhat to look for: expectancy per trade rising with the band. If it")
    print("does not, the score is not measuring anything and the tiers should")
    print("go, not be retuned. A band under ~20 trades says nothing either way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
