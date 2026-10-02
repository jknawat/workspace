"""Multi-timeframe context: trade one timeframe, read many.

Entries still trigger on the trading timeframe (M5 by default). These views
only inform — they answer "does the bigger picture agree?" without ever
generating a signal themselves, so there is exactly one place a trade can be
born and the rest is evidence.

Each timeframe is reduced to a direction with a reason attached:

* price above or below its trend EMA, and
* the fast EMA above or below the slow one.

Both must agree, or the timeframe reads ``neutral``. That makes a disagreeing
timeframe honest rather than coin-flipping it: on a 1-minute chart inside a
daily uptrend, "neutral" is the correct answer most of the time.

**A timeframe without enough history is neutral, never bullish.** MT5 will hand
back 40 monthly bars where 200 are needed for a trend EMA; treating that as
agreement would let an unknowable timeframe vote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..core.indicators import atr as atr_of
from ..core.indicators import ema
from ..core.types import Bar

#: Ordered coarsest-last, so a rendered view reads the way a trader scans.
LADDER = [
    "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1",
]

BULLISH, BEARISH, NEUTRAL = "bullish", "bearish", "neutral"


def ladder_key(timeframe: str) -> int:
    """Sort order for a timeframe name; unknown names sort last."""
    try:
        return LADDER.index(timeframe.upper())
    except ValueError:
        return len(LADDER)


@dataclass(frozen=True, slots=True)
class TimeframeView:
    """One timeframe reduced to a direction, with the numbers behind it."""

    timeframe: str
    bars: int
    close: float
    direction: str
    reason: str
    ts: datetime | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    ema_trend: float | None = None
    atr: float | None = None
    ready: bool = True

    @property
    def is_bullish(self) -> bool:
        return self.direction == BULLISH

    @property
    def is_bearish(self) -> bool:
        return self.direction == BEARISH

    def agrees_with(self, side: str) -> bool:
        """``side`` is ``LONG``/``SHORT``. Neutral agrees with neither."""
        want = BULLISH if side.upper() == "LONG" else BEARISH
        return self.direction == want

    def to_dict(self) -> dict[str, object]:
        return {
            "timeframe": self.timeframe,
            "direction": self.direction,
            "reason": self.reason,
            "close": self.close,
            "bars": self.bars,
            "ready": self.ready,
            "atr": self.atr,
        }


def view_for(
    timeframe: str,
    bars: list[Bar],
    fast: int = 21,
    slow: int = 50,
    trend: int = 200,
    atr_period: int = 14,
) -> TimeframeView:
    """Reduce a timeframe's bars to a direction.

    Needs ``trend`` bars of history; with fewer it reports ``neutral`` and
    ``ready=False`` rather than guessing from a half-formed average.
    """
    if not bars:
        return TimeframeView(timeframe, 0, 0.0, NEUTRAL, "no bars", ready=False)

    last = bars[-1]
    closes = [b.close for b in bars]
    ef, es, et = (ema(closes, fast), ema(closes, slow), ema(closes, trend))
    a = atr_of(bars, atr_period)
    f, s, t, av = ef[-1], es[-1], et[-1], a[-1]

    if f is None or s is None or t is None:
        return TimeframeView(
            timeframe, len(bars), last.close, NEUTRAL,
            f"only {len(bars)} bars, needs {trend}", ts=last.ts, atr=av, ready=False,
        )

    above_trend = last.close > t
    stack_up = f > s
    if above_trend and stack_up:
        direction, why = BULLISH, "price above trend EMA and fast above slow"
    elif not above_trend and not stack_up:
        direction, why = BEARISH, "price below trend EMA and fast below slow"
    else:
        direction = NEUTRAL
        why = (
            "price above trend EMA but fast below slow"
            if above_trend
            else "price below trend EMA but fast above slow"
        )

    return TimeframeView(
        timeframe=timeframe, bars=len(bars), close=last.close, direction=direction,
        reason=why, ts=last.ts, ema_fast=f, ema_slow=s, ema_trend=t, atr=av, ready=True,
    )


@dataclass(slots=True)
class MultiTimeframe:
    """Every context timeframe for one symbol, at one moment."""

    views: dict[str, TimeframeView] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.views)

    def __iter__(self):
        """Coarsest last, so iteration reads M1 -> MN1."""
        return iter(sorted(self.views.values(), key=lambda v: ladder_key(v.timeframe)))

    def get(self, timeframe: str) -> TimeframeView | None:
        return self.views.get(timeframe.upper())

    def direction(self, timeframe: str) -> str:
        view = self.get(timeframe)
        return view.direction if view else NEUTRAL

    # -- agreement ------------------------------------------------------- #

    def agreeing(self, side: str, timeframes: list[str] | None = None) -> list[str]:
        wanted = [tf.upper() for tf in timeframes] if timeframes else list(self.views)
        return [tf for tf in wanted if (v := self.get(tf)) and v.agrees_with(side)]

    def disagreeing(self, side: str, timeframes: list[str] | None = None) -> list[str]:
        """Timeframes pointing the *other* way. Neutral is not disagreement."""
        opposite = "SHORT" if side.upper() == "LONG" else "LONG"
        return self.agreeing(opposite, timeframes)

    def not_ready(self, timeframes: list[str] | None = None) -> list[str]:
        wanted = [tf.upper() for tf in timeframes] if timeframes else list(self.views)
        return [tf for tf in wanted if not (v := self.get(tf)) or not v.ready]

    def tally(self) -> dict[str, int]:
        counts = {BULLISH: 0, BEARISH: 0, NEUTRAL: 0}
        for v in self.views.values():
            counts[v.direction] = counts.get(v.direction, 0) + 1
        return counts

    def summary(self) -> str:
        """One line, coarsest last: ``M1 bull | M15 flat | H1 bear | MN1 n/a``.

        A timeframe without enough history reads ``n/a``, not ``flat``. They are
        different statements -- "balanced" versus "unknown" -- and the decision
        panel exists to answer why the bot is waiting, so it must not present a
        missing answer as a neutral one.
        """
        short = {BULLISH: "bull", BEARISH: "bear", NEUTRAL: "flat"}
        return " | ".join(
            f"{v.timeframe} {short[v.direction] if v.ready else 'n/a'}" for v in self
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "tally": self.tally(),
            "summary": self.summary(),
            "views": [v.to_dict() for v in self],
        }


# --------------------------------------------------------------------------- #
# Point-in-time context, for replay
# --------------------------------------------------------------------------- #

#: Minutes per timeframe, used to work out when a context bar actually closed.
TIMEFRAME_MINUTES = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6, "M10": 10, "M12": 12,
    "M15": 15, "M20": 20, "M30": 30,
    "H1": 60, "H2": 120, "H3": 180, "H4": 240, "H6": 360, "H8": 480, "H12": 720,
    "D1": 1440, "W1": 10080, "MN1": 43200,
}


def _direction_of(close: float, fast, slow, trend) -> tuple[str, str]:
    """Shared by the live and historical paths, so they cannot disagree."""
    if fast is None or slow is None or trend is None:
        return NEUTRAL, "not enough history"
    above, stacked = close > trend, fast > slow
    if above and stacked:
        return BULLISH, "price above trend EMA and fast above slow"
    if not above and not stacked:
        return BEARISH, "price below trend EMA and fast below slow"
    return NEUTRAL, (
        "price above trend EMA but fast below slow" if above
        else "price below trend EMA but fast above slow"
    )


class HistoricalMtf:
    """Replays context timeframes without letting the future leak in.

    For a trading bar at time *T*, a higher-timeframe bar stamped *T* has only
    *opened* — it will not close for another hour, or day. Using it would hand
    the strategy information it could not have had, and multi-timeframe
    backtests flatter themselves exactly this way. So a context bar counts only
    once ``open time + duration <= T``.

    Indicators are computed once per timeframe and indexed, rather than
    recomputed per bar, which keeps a 60,000-bar replay across eight timeframes
    quick enough to iterate on.
    """

    def __init__(
        self,
        per_timeframe: dict[str, list[Bar]],
        fast: int = 21,
        slow: int = 50,
        trend: int = 200,
        atr_period: int = 14,
    ) -> None:
        self.trend = trend
        self._data: dict[str, dict[str, object]] = {}
        for tf, bars in per_timeframe.items():
            if not bars:
                continue
            closes = [b.close for b in bars]
            minutes = TIMEFRAME_MINUTES.get(tf.upper(), 1)
            self._data[tf.upper()] = {
                "bars": bars,
                # The moment each bar is safe to read: when it closed.
                "closed_at": [b.ts.timestamp() + minutes * 60 for b in bars],
                "fast": ema(closes, fast),
                "slow": ema(closes, slow),
                "trend": ema(closes, trend),
                "atr": atr_of(bars, atr_period),
            }

    @property
    def timeframes(self) -> list[str]:
        return sorted(self._data, key=ladder_key)

    def at(self, moment: datetime) -> MultiTimeframe:
        """The context as it stood at ``moment``, and no later."""
        import bisect

        cutoff = moment.timestamp()
        views: dict[str, TimeframeView] = {}
        for tf, d in self._data.items():
            closed_at: list[float] = d["closed_at"]  # type: ignore[assignment]
            i = bisect.bisect_right(closed_at, cutoff) - 1
            if i < 0:
                views[tf] = TimeframeView(tf, 0, 0.0, NEUTRAL, "no closed bars yet",
                                          ready=False)
                continue
            bars: list[Bar] = d["bars"]  # type: ignore[assignment]
            bar = bars[i]
            f, s, t = d["fast"][i], d["slow"][i], d["trend"][i]  # type: ignore[index]
            a = d["atr"][i]  # type: ignore[index]
            direction, why = _direction_of(bar.close, f, s, t)
            ready = None not in (f, s, t)
            views[tf] = TimeframeView(
                timeframe=tf, bars=i + 1, close=bar.close, direction=direction,
                reason=why if ready else f"only {i + 1} bars, needs {self.trend}",
                ts=bar.ts, ema_fast=f, ema_slow=s, ema_trend=t, atr=a, ready=ready,
            )
        return MultiTimeframe(views)
