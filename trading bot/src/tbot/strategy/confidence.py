"""Rating a signal, and sizing to the rating.

The filter chain answers "is this trade allowed?". That is not the same
question as "how much does it deserve?", and the second one decides money. A
signal that scrapes past every gate and one that has the daily trend, a wide
target and cheap costs behind it are both "allowed", and staking the same
amount on each throws away the difference.

**The score is not a win probability.** It is 0--100 points of evidence. The
distinction matters, and not pedantically: this strategy wins roughly 30% of
its trades and profits because the winners are bigger. A component labelled
"90% win rate" would be fiction, and a threshold set against that fiction would
never fire. What each band *actually* delivers is measured rather than
asserted -- ``scripts/score_report.py`` buckets real closed trades by score and
reports the win rate and expectancy of each.

Every component is clamped to 0..1 before weighting, so no single input can run
away with the total, and a component whose inputs are unavailable scores zero
rather than guessing. Scoring down for missing evidence is deliberate: an
unknown is not a point in the trade's favour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.models import ConfigError
from ..core.types import Side, Signal
from .base import BarContext

#: Points available per component. They sum to 100 so a score reads as a share
#: of the available evidence -- not as a probability of winning.
DEFAULT_WEIGHTS: dict[str, float] = {
    "mtf": 35.0,       # does the bigger picture back this side
    "reward": 25.0,    # how much the trade pays if it works
    "atr": 15.0,       # is volatility mid-band or at an awkward edge
    "pullback": 15.0,  # how tight the entry is against its moving average
    "cost": 10.0,      # spread as a share of what is being risked
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _other(side: Side) -> Side:
    return Side.SHORT if side == Side.LONG else Side.LONG


@dataclass(frozen=True, slots=True)
class Component:
    """One input's contribution, with the sentence that explains it."""

    name: str
    earned: float
    weight: float
    note: str

    @property
    def fraction(self) -> float:
        return self.earned / self.weight if self.weight else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "earned": round(self.earned, 1),
            "weight": round(self.weight, 1),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Score:
    """A rated signal: the number, the reasons, and what to stake."""

    points: float
    components: tuple[Component, ...] = ()
    risk_mult: float = 0.0
    tier: str = "below minimum"

    @property
    def tradeable(self) -> bool:
        return self.risk_mult > 0.0

    def explain(self) -> str:
        """One line for the decision panel and the journal."""
        parts = ", ".join(
            f"{c.name} {c.earned:.0f}/{c.weight:.0f}" for c in self.components
        )
        verdict = (
            f"{self.tier}, staking {self.risk_mult:.0%} of the risk budget"
            if self.tradeable
            else f"{self.tier} -- waiting"
        )
        return f"score {self.points:.0f}/100 ({parts}) -> {verdict}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": round(self.points, 1),
            "tier": self.tier,
            "risk_mult": self.risk_mult,
            "tradeable": self.tradeable,
            "components": [c.to_dict() for c in self.components],
        }


@dataclass(frozen=True, slots=True)
class Tier:
    """A score threshold and the share of the risk budget it unlocks."""

    min_score: float
    risk_mult: float
    label: str = ""

    def named(self) -> str:
        return self.label or f"score >= {self.min_score:.0f}"


@dataclass(slots=True)
class ConfidenceConfig:
    enabled: bool = False
    min_score: float = 45.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    tiers: tuple[Tier, ...] = ()
    #: An rr at or above this earns full reward points.
    reward_full_at: float = 3.0
    #: An entry this many ATRs from the fast EMA earns no pullback points.
    pullback_atr_span: float = 1.5
    #: A spread costing this share of the stop distance earns no cost points.
    cost_ceiling: float = 0.25

    ALLOWED = (
        "enabled", "min_score", "weights", "tiers",
        "reward_full_at", "pullback_atr_span", "cost_ceiling",
    )

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str) -> ConfidenceConfig:
        unknown = sorted(set(d) - set(cls.ALLOWED))
        if unknown:
            raise ConfigError(f"{where}: unknown option(s) {unknown}")

        weights = dict(DEFAULT_WEIGHTS)
        for name, value in (d.get("weights") or {}).items():
            if name not in DEFAULT_WEIGHTS:
                raise ConfigError(
                    f"{where}.weights: unknown component {name!r}; "
                    f"choose from {sorted(DEFAULT_WEIGHTS)}"
                )
            weights[name] = float(value)

        raw_tiers = tuple(
            Tier(
                min_score=float(t["min_score"]),
                risk_mult=float(t["risk_mult"]),
                label=str(t.get("label", "")),
            )
            for t in (d.get("tiers") or ())
        )
        # Sorted highest-first so the first match is the best tier that
        # applies, which lets the config file list them in any order.
        tiers = tuple(sorted(raw_tiers, key=lambda t: -t.min_score))
        for t in tiers:
            if t.risk_mult <= 0:
                raise ConfigError(
                    f"{where}.tiers: risk_mult must be > 0 for a tier that "
                    "trades; to stop trading below a score raise min_score"
                )
            if t.risk_mult > 1.0:
                raise ConfigError(
                    f"{where}.tiers: risk_mult {t.risk_mult} exceeds 1.0, which "
                    "would stake more than [risk].risk_per_trade_pct allows"
                )

        cfg = cls(
            enabled=bool(d.get("enabled", False)),
            min_score=float(d.get("min_score", 45.0)),
            weights=weights,
            tiers=tiers,
            reward_full_at=float(d.get("reward_full_at", 3.0)),
            pullback_atr_span=float(d.get("pullback_atr_span", 1.5)),
            cost_ceiling=float(d.get("cost_ceiling", 0.25)),
        )
        if cfg.enabled and not cfg.tiers:
            raise ConfigError(
                f"{where}: enabled with no tiers, so every signal would be "
                "refused; add at least one [[confidence.tiers]]"
            )
        return cfg

    def tier_for(self, points: float) -> Tier | None:
        if points < self.min_score:
            return None
        for t in self.tiers:  # highest first
            if points >= t.min_score:
                return t
        return None


class ConfidenceScorer:
    """Scores a signal that has already passed every gate."""

    def __init__(self, cfg: ConfidenceConfig) -> None:
        self.cfg = cfg

    def score(self, signal: Signal, ctx: BarContext, side: Side) -> Score:
        w = self.cfg.weights
        components = tuple(
            c
            for c in (
                self._mtf(ctx, side, w.get("mtf", 0.0)),
                self._reward(signal, w.get("reward", 0.0)),
                self._atr(ctx, w.get("atr", 0.0)),
                self._pullback(signal, ctx, w.get("pullback", 0.0)),
                self._cost(signal, ctx, w.get("cost", 0.0)),
            )
            if c.weight > 0
        )
        points = sum(c.earned for c in components)
        tier = self.cfg.tier_for(points)
        if tier is None:
            return Score(
                points=points,
                components=components,
                risk_mult=0.0,
                tier=f"below the {self.cfg.min_score:.0f} minimum",
            )
        return Score(
            points=points,
            components=components,
            risk_mult=tier.risk_mult,
            tier=tier.named(),
        )

    # -- components ------------------------------------------------------ #

    def _mtf(self, ctx: BarContext, side: Side, weight: float) -> Component:
        """Net support across the timeframes that have enough history.

        Net, not gross: four agreeing timeframes against two disagreeing is a
        weaker case than four against none, and counting only agreement would
        score them identically.
        """
        if weight <= 0:
            return Component("mtf", 0.0, 0.0, "not scored")
        mtf = ctx.mtf
        if mtf is None or not len(mtf):
            return Component("mtf", 0.0, weight, "no timeframe context")
        ready = [v for v in mtf if v.ready]
        if not ready:
            return Component("mtf", 0.0, weight, "no timeframe has enough history")
        agree = sum(1 for v in ready if v.agrees_with(side.value))
        against = sum(1 for v in ready if v.agrees_with(_other(side).value))
        frac = _clamp((agree - against) / len(ready))
        return Component(
            "mtf",
            weight * frac,
            weight,
            f"{agree} of {len(ready)} timeframes agree, {against} against",
        )

    def _reward(self, signal: Signal, weight: float) -> Component:
        """How much the trade pays if it works.

        At a ~30% win rate this is the component that decides whether the
        strategy makes money at all, which is why it carries real weight.
        """
        if weight <= 0:
            return Component("reward", 0.0, 0.0, "not scored")
        rr = signal.rr
        span = max(self.cfg.reward_full_at - 1.0, 1e-9)
        frac = _clamp((rr - 1.0) / span)
        return Component(
            "reward",
            weight * frac,
            weight,
            f"reward/risk {rr:.2f} (full at {self.cfg.reward_full_at:.1f})",
        )

    def _atr(self, ctx: BarContext, weight: float) -> Component:
        """Volatility mid-band scores best; both edges score badly.

        The band comes from the symbol's own ``atr_range`` filter, so this
        cannot drift away from the bounds real data established.
        """
        if weight <= 0:
            return Component("atr", 0.0, 0.0, "not scored")
        atr = ctx.value("atr")
        if atr is None:
            return Component("atr", 0.0, weight, "atr not ready")
        band = (ctx.cfg.filters or {}).get("atr_range") or {}
        lo, hi = float(band.get("min", 0.0)), float(band.get("max", 0.0))
        if not hi or hi <= lo:
            return Component(
                "atr",
                weight * 0.5,
                weight,
                f"atr {atr:.2f}, no configured band to judge it against",
            )
        pos = _clamp((atr - lo) / (hi - lo))
        frac = 1.0 - 2.0 * abs(pos - 0.5)  # 1.0 mid-band, 0.0 at either edge
        where = "mid-band" if frac > 0.6 else "near the edge of its band"
        return Component(
            "atr",
            weight * frac,
            weight,
            f"atr {atr:.2f} is {where} ({lo:.1f}-{hi:.1f})",
        )

    def _pullback(self, signal: Signal, ctx: BarContext, weight: float) -> Component:
        """A tight entry against the fast EMA beats a stretched one.

        Entering far from the average means paying for distance the trade has
        to give back before it is in profit.
        """
        if weight <= 0:
            return Component("pullback", 0.0, 0.0, "not scored")
        fast, atr = ctx.value("ema_fast"), ctx.value("atr")
        if fast is None or not atr:
            return Component("pullback", 0.0, weight, "ema or atr not ready")
        distance = abs(signal.price - fast) / atr
        span = max(self.cfg.pullback_atr_span, 1e-9)
        frac = _clamp(1.0 - distance / span)
        return Component(
            "pullback",
            weight * frac,
            weight,
            f"entry {distance:.2f} ATR from the fast EMA",
        )

    def _cost(self, signal: Signal, ctx: BarContext, weight: float) -> Component:
        """Spread as a share of the stop distance.

        A tight stop on a wide spread is an expensive trade however good it
        looks, and on gold the spread is ~$0.24 against stops of a few dollars.
        """
        if weight <= 0:
            return Component("cost", 0.0, 0.0, "not scored")
        stop = signal.sl_distance
        if stop <= 0:
            return Component("cost", 0.0, weight, "signal has no stop distance")
        spread_price = ctx.spread_points * ctx.spec.point
        if spread_price <= 0:
            # A backtest with no quoted spread must not collect free points
            # that live trading would never earn.
            return Component("cost", weight * 0.5, weight, "no spread quoted")
        share = spread_price / stop
        frac = _clamp(1.0 - share / max(self.cfg.cost_ceiling, 1e-9))
        return Component(
            "cost",
            weight * frac,
            weight,
            f"spread is {share:.1%} of the {stop:.2f} stop",
        )
