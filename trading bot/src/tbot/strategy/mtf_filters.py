"""Gates that read the multi-timeframe context.

These are what make "trade M5 but look at everything" a config decision rather
than a strategy rewrite. They work on any strategy, in either direction, so the
same rules that keep you out of a bad long keep you out of a bad short.

As with the ICT gates, they **fail closed**: without context they reject. A
timeframe filter that passes when it has no data is worse than no filter, since
it looks like confirmation and is silence.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.types import Decision, Side
from .base import BarContext
from .filters import Filter, register


def _context(ctx: BarContext):
    if ctx.mtf is None or not len(ctx.mtf):
        return None, Decision.no("no multi-timeframe context available")
    return ctx.mtf, Decision.ok("context present")


@register
class MtfAlignFilter(Filter):
    """Require higher timeframes to agree with the trade.

    ``timeframes`` lists which to consult (empty means every configured one),
    and ``min_agree`` how many must point the same way. ``max_disagree`` caps
    how many may point the *other* way -- separate from agreement because
    neutral is neither, and two timeframes actively against a trade matters
    more than four being undecided.
    """

    name = "mtf_align"
    defaults: ClassVar[dict[str, Any]] = {
        "timeframes": [],
        "min_agree": 1,
        "max_disagree": 99,
        "allow_not_ready": False,
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        mtf, why = _context(ctx)
        if mtf is None:
            return why
        wanted = list(self.opt["timeframes"]) or None

        missing = mtf.not_ready(wanted)
        if missing and not self.opt["allow_not_ready"]:
            return Decision.no(
                f"timeframe(s) without enough history: {', '.join(missing)}",
                not_ready=missing,
            )

        agree = mtf.agreeing(side.value, wanted)
        against = mtf.disagreeing(side.value, wanted)
        detail = {"agree": agree, "disagree": against, "summary": mtf.summary()}

        if len(agree) < int(self.opt["min_agree"]):
            return Decision.no(
                f"only {len(agree)} timeframe(s) agree with {side.value}, "
                f"need {self.opt['min_agree']} ({mtf.summary()})",
                **detail,
            )
        if len(against) > int(self.opt["max_disagree"]):
            return Decision.no(
                f"{len(against)} timeframe(s) against {side.value}: "
                f"{', '.join(against)}",
                **detail,
            )
        return Decision.ok(
            f"{len(agree)} timeframe(s) agree with {side.value}", **detail
        )


@register
class MtfRequiredFilter(Filter):
    """Require *specific* timeframes to agree, all of them.

    Use when a particular horizon is non-negotiable -- "never fight the daily"
    -- rather than counting votes. Listing nothing makes this a no-op, which is
    reported rather than silently passing.
    """

    name = "mtf_required"
    defaults: ClassVar[dict[str, Any]] = {"timeframes": [], "allow_neutral": False}

    def _objection(self, view, timeframe: str, side: Side) -> str | None:
        """Why this timeframe blocks the trade, or ``None`` if it does not."""
        if view is None:
            return f"{timeframe} missing"
        if not view.ready:
            return f"{timeframe} not ready"
        if view.agrees_with(side.value):
            return None
        if view.direction == "neutral" and self.opt["allow_neutral"]:
            return None
        return f"{timeframe} {view.direction}"

    def check(self, ctx: BarContext, side: Side) -> Decision:
        mtf, why = _context(ctx)
        if mtf is None:
            return why
        wanted = [tf.upper() for tf in self.opt["timeframes"]]
        if not wanted:
            return Decision.ok("no timeframes required (filter is a no-op)")

        blocking = [
            objection
            for tf in wanted
            if (objection := self._objection(mtf.get(tf), tf, side)) is not None
        ]

        if blocking:
            return Decision.no(
                f"required timeframe(s) do not back {side.value}: "
                f"{', '.join(blocking)}",
                summary=mtf.summary(),
            )
        return Decision.ok(
            f"{', '.join(wanted)} back {side.value}", summary=mtf.summary()
        )
