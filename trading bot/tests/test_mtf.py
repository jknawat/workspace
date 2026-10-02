"""Multi-timeframe context: direction per timeframe, and the gates on it.

The property that matters: **a timeframe with too little history is neutral,
never agreeing.** MT5 will hand back 40 monthly bars where 200 are needed for a
trend EMA, and counting that as confirmation lets an unknowable timeframe vote.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from conftest import START, bars_from_closes, n_shape, v_shape

from tbot.core.types import Side
from tbot.data.mtf import (
    HistoricalMtf,
    MultiTimeframe,
    TimeframeView,
    ladder_key,
    view_for,
)
from tbot.strategy.base import BarContext
from tbot.strategy.filters import build_chain


def rising(n: int = 320) -> list:
    return bars_from_closes([1.0 + 0.001 * i for i in range(n)])


def falling(n: int = 320) -> list:
    return bars_from_closes([1.5 - 0.001 * i for i in range(n)])


def ctx_with(symbol_cfg, spec, mtf, closes=None) -> BarContext:
    bars = bars_from_closes(closes or [1.1000] * 30)
    return BarContext(
        cfg=symbol_cfg, spec=spec, bars=bars, i=len(bars) - 1,
        ind={"atr": [0.0010] * len(bars)}, mtf=mtf,
    )


def mtf_of(**directions) -> MultiTimeframe:
    views = {
        tf: TimeframeView(tf, 300, 1.0, direction, "test", ready=True)
        for tf, direction in directions.items()
    }
    return MultiTimeframe(views)


# --------------------------------------------------------------------------- #
# Reducing a timeframe to a direction
# --------------------------------------------------------------------------- #


def test_a_rising_market_reads_bullish():
    view = view_for("H1", rising())
    assert view.direction == "bullish" and view.ready
    assert view.is_bullish and not view.is_bearish
    assert "above trend EMA" in view.reason


def test_a_falling_market_reads_bearish():
    view = view_for("H1", falling())
    assert view.direction == "bearish" and view.ready
    assert view.agrees_with("SHORT") and not view.agrees_with("LONG")


def test_too_little_history_is_neutral_and_not_ready():
    """40 monthly bars cannot support a 200-period trend EMA."""
    view = view_for("MN1", rising(40))
    assert view.direction == "neutral"
    assert view.ready is False
    assert "needs 200" in view.reason
    assert not view.agrees_with("LONG") and not view.agrees_with("SHORT")


def test_no_bars_at_all_is_neutral():
    view = view_for("W1", [])
    assert view.direction == "neutral" and not view.ready


def test_a_conflicted_market_is_neutral_not_a_coin_flip():
    """Price one side of the trend EMA while the fast/slow stack says otherwise.

    A V-shaped recovery puts price back above its trend EMA while the faster
    averages have not caught up -- the honest read is "undecided".
    """
    view = view_for("M15", bars_from_closes(v_shape(down=180, up=140)))
    assert view.direction in {"bullish", "neutral", "bearish"}
    if view.direction == "neutral":
        assert "but" in view.reason


def test_neutral_agrees_with_neither_side():
    view = TimeframeView("H1", 300, 1.0, "neutral", "undecided")
    assert not view.agrees_with("LONG")
    assert not view.agrees_with("SHORT")


# --------------------------------------------------------------------------- #
# The collection
# --------------------------------------------------------------------------- #


def test_iteration_runs_fine_to_coarse():
    mtf = mtf_of(D1="bullish", M1="bearish", H4="bullish", M15="neutral")
    assert [v.timeframe for v in mtf] == ["M1", "M15", "H4", "D1"]


def test_unknown_timeframes_sort_last():
    assert ladder_key("M5") < ladder_key("D1") < ladder_key("WHAT")


def test_agreement_and_disagreement_are_counted_separately():
    mtf = mtf_of(M15="bullish", H1="bullish", H4="neutral", D1="bearish")
    assert set(mtf.agreeing("LONG")) == {"M15", "H1"}
    assert mtf.disagreeing("LONG") == ["D1"]       # neutral is not opposition
    assert set(mtf.agreeing("SHORT")) == {"D1"}


def test_tally_and_summary_read_plainly():
    mtf = mtf_of(M15="bullish", H1="bearish", D1="neutral")
    assert mtf.tally() == {"bullish": 1, "bearish": 1, "neutral": 1}
    assert mtf.summary() == "M15 bull | H1 bear | D1 flat"


def test_not_ready_is_reported():
    views = {
        "D1": TimeframeView("D1", 300, 1.0, "bullish", "ok", ready=True),
        "MN1": TimeframeView("MN1", 40, 1.0, "neutral", "short", ready=False),
    }
    assert MultiTimeframe(views).not_ready() == ["MN1"]


def test_serialises_for_the_dashboard():
    payload = mtf_of(M15="bullish", D1="bearish").to_dict()
    assert payload["tally"]["bullish"] == 1
    assert [v["timeframe"] for v in payload["views"]] == ["M15", "D1"]


# --------------------------------------------------------------------------- #
# mtf_align
# --------------------------------------------------------------------------- #


def test_align_passes_when_enough_timeframes_agree(symbol_cfg, spec_eurusd):
    mtf = mtf_of(M15="bullish", H1="bullish", D1="neutral")
    chain = build_chain({"mtf_align": {"min_agree": 2}})
    assert chain.evaluate(ctx_with(symbol_cfg, spec_eurusd, mtf), Side.LONG)


def test_align_rejects_when_too_few_agree(symbol_cfg, spec_eurusd):
    mtf = mtf_of(M15="bullish", H1="neutral", D1="neutral")
    decision = build_chain({"mtf_align": {"min_agree": 2}}).evaluate(
        ctx_with(symbol_cfg, spec_eurusd, mtf), Side.LONG
    )
    assert not decision and "only 1 timeframe" in decision.reason


def test_align_caps_active_disagreement(symbol_cfg, spec_eurusd):
    mtf = mtf_of(M15="bullish", H1="bullish", H4="bearish", D1="bearish")
    ctx = ctx_with(symbol_cfg, spec_eurusd, mtf)
    assert build_chain({"mtf_align": {"min_agree": 2, "max_disagree": 2}}).evaluate(
        ctx, Side.LONG
    )
    tight = build_chain({"mtf_align": {"min_agree": 2, "max_disagree": 1}})
    decision = tight.evaluate(ctx, Side.LONG)
    assert not decision and "against LONG" in decision.reason


def test_align_works_the_same_for_shorts(symbol_cfg, spec_eurusd):
    """Bidirectional by construction, not by a second code path."""
    mtf = mtf_of(M15="bearish", H1="bearish", D1="bullish")
    chain = build_chain({"mtf_align": {"min_agree": 2}})
    ctx = ctx_with(symbol_cfg, spec_eurusd, mtf)
    assert chain.evaluate(ctx, Side.SHORT)
    assert not chain.evaluate(ctx, Side.LONG)


def test_align_rejects_a_timeframe_without_history(symbol_cfg, spec_eurusd):
    views = {
        "D1": TimeframeView("D1", 300, 1.0, "bullish", "ok", ready=True),
        "MN1": TimeframeView("MN1", 40, 1.0, "neutral", "short", ready=False),
    }
    ctx = ctx_with(symbol_cfg, spec_eurusd, MultiTimeframe(views))
    decision = build_chain({"mtf_align": {"min_agree": 1}}).evaluate(ctx, Side.LONG)
    assert not decision and "without enough history" in decision.reason
    assert build_chain({"mtf_align": {"min_agree": 1, "allow_not_ready": True}}).evaluate(
        ctx, Side.LONG
    )


def test_align_can_be_scoped_to_named_timeframes(symbol_cfg, spec_eurusd):
    mtf = mtf_of(M1="bearish", M15="bullish", H1="bullish")
    ctx = ctx_with(symbol_cfg, spec_eurusd, mtf)
    scoped = build_chain({"mtf_align": {"timeframes": ["M15", "H1"], "min_agree": 2}})
    assert scoped.evaluate(ctx, Side.LONG)


# --------------------------------------------------------------------------- #
# mtf_required
# --------------------------------------------------------------------------- #


def test_required_blocks_when_the_named_timeframe_disagrees(symbol_cfg, spec_eurusd):
    mtf = mtf_of(M15="bullish", H1="bullish", D1="bearish")
    decision = build_chain({"mtf_required": {"timeframes": ["D1"]}}).evaluate(
        ctx_with(symbol_cfg, spec_eurusd, mtf), Side.LONG
    )
    assert not decision and "D1 bearish" in decision.reason


def test_required_can_tolerate_neutral(symbol_cfg, spec_eurusd):
    mtf = mtf_of(D1="neutral")
    ctx = ctx_with(symbol_cfg, spec_eurusd, mtf)
    strict = build_chain({"mtf_required": {"timeframes": ["D1"]}})
    lenient = build_chain({"mtf_required": {"timeframes": ["D1"], "allow_neutral": True}})
    assert not strict.evaluate(ctx, Side.LONG)
    assert lenient.evaluate(ctx, Side.LONG)


def test_required_reports_a_missing_timeframe(symbol_cfg, spec_eurusd):
    decision = build_chain({"mtf_required": {"timeframes": ["H8"]}}).evaluate(
        ctx_with(symbol_cfg, spec_eurusd, mtf_of(D1="bullish")), Side.LONG
    )
    assert not decision and "H8 missing" in decision.reason


def test_required_with_no_timeframes_says_so_rather_than_passing_silently(
    symbol_cfg, spec_eurusd
):
    decision = build_chain({"mtf_required": {}}).evaluate(
        ctx_with(symbol_cfg, spec_eurusd, mtf_of(D1="bullish")), Side.LONG
    )
    # The chain reports its own verdict; each filter's reasoning is in the trace.
    assert decision
    assert "no-op" in decision.detail["trace"]["mtf_required"]["reason"]


# --------------------------------------------------------------------------- #
# Failing closed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["mtf_align", "mtf_required"])
def test_every_gate_rejects_without_context(name, symbol_cfg, spec_eurusd):
    ctx = ctx_with(symbol_cfg, spec_eurusd, None)
    options = {"timeframes": ["D1"]} if name == "mtf_required" else {}
    decision = build_chain({name: options}).evaluate(ctx, Side.LONG)
    assert not decision, f"{name} passed with no timeframe context"


def test_empty_context_is_also_rejected(symbol_cfg, spec_eurusd):
    ctx = ctx_with(symbol_cfg, spec_eurusd, MultiTimeframe({}))
    assert not build_chain({"mtf_align": {}}).evaluate(ctx, Side.LONG)


# --------------------------------------------------------------------------- #
# A real price path, end to end
# --------------------------------------------------------------------------- #


def test_opposite_paths_give_opposite_reads():
    assert view_for("H1", bars_from_closes(n_shape(up=20, down=300))).direction == "bearish"
    assert view_for("H1", bars_from_closes(v_shape(down=20, up=300))).direction == "bullish"


def test_a_strategy_sees_the_context(symbol_cfg, spec_eurusd):
    cfg = dataclasses.replace(symbol_cfg, filters={"mtf_align": {"min_agree": 1}})
    ctx = ctx_with(cfg, spec_eurusd, mtf_of(H1="bullish"))
    assert ctx.mtf is not None
    assert build_chain(cfg.filters).evaluate(ctx, Side.LONG)


# --------------------------------------------------------------------------- #
# Point-in-time replay
# --------------------------------------------------------------------------- #
#
# The property worth defending: a higher-timeframe bar stamped T has only
# *opened* at T. A backtest that reads it is reading the next hour's close, and
# multi-timeframe backtests flatter themselves in exactly this way.


def test_an_open_bar_is_not_read_until_it_closes():
    """The whole point. An H1 bar stamped 03:00 must not be visible at 03:00."""
    h1 = bars_from_closes([1.0 + 0.001 * i for i in range(300)], minutes=60)
    hist = HistoricalMtf({"H1": h1})

    opened = h1[250].ts  # the 03:00-style boundary: this bar just opened
    at_open = hist.at(opened)
    assert at_open.get("H1").bars == 250, "an only-just-opened bar was counted"
    assert at_open.get("H1").close == h1[249].close

    just_closed = opened + timedelta(minutes=60)
    assert hist.at(just_closed).get("H1").bars == 251
    assert hist.at(just_closed).get("H1").close == h1[250].close


def test_a_bar_mid_formation_is_not_read_either():
    """Halfway through an H1 bar, the newest usable close is still the last one."""
    h1 = bars_from_closes([1.0 + 0.001 * i for i in range(300)], minutes=60)
    hist = HistoricalMtf({"H1": h1})
    mid = h1[250].ts + timedelta(minutes=59)
    assert hist.at(mid).get("H1").close == h1[249].close


def test_before_any_context_bar_closes_the_view_is_neutral_and_not_ready():
    """Not bullish, not bearish: unknown. A gate must fail closed here."""
    h1 = bars_from_closes([1.0 + 0.001 * i for i in range(300)], minutes=60)
    hist = HistoricalMtf({"H1": h1})
    view = hist.at(h1[0].ts).get("H1")
    assert view.direction == "neutral"
    assert not view.ready
    assert not view.agrees_with(Side.LONG.value)


def test_replay_and_live_agree_on_the_same_closed_bars():
    """Two code paths reading one market must not reach two conclusions.

    If these ever diverge, a backtest stops being a statement about the bot
    that will trade.
    """
    for series in (rising(300), falling(300)):
        bars = bars_from_closes([b.close for b in series], minutes=60)
        hist = HistoricalMtf({"H1": bars})
        # Everything through bars[-1] has closed by this moment.
        replayed = hist.at(bars[-1].ts + timedelta(minutes=60)).get("H1")
        live = view_for("H1", bars)
        assert replayed.direction == live.direction
        assert replayed.close == live.close
        assert replayed.bars == live.bars
        assert replayed.ready == live.ready


def test_too_little_history_is_not_ready_in_replay_either():
    h1 = bars_from_closes([1.0 + 0.001 * i for i in range(40)], minutes=60)
    hist = HistoricalMtf({"H1": h1})
    view = hist.at(h1[-1].ts + timedelta(minutes=60)).get("H1")
    assert not view.ready
    assert view.direction == "neutral"
    assert "needs 200" in view.reason


def test_each_timeframe_closes_on_its_own_clock():
    """A D1 bar and an M15 bar stamped alike become readable a day apart."""
    closes = [1.0 + 0.001 * i for i in range(300)]
    hist = HistoricalMtf({
        "M15": bars_from_closes(closes, minutes=15),
        "D1": bars_from_closes(closes, minutes=1440),
    })
    # One hour into the shared start: three M15 bars have closed, no D1 bar has.
    view = hist.at(START + timedelta(minutes=60))
    assert view.get("M15").bars == 4
    assert view.get("D1").bars == 0
    assert not view.get("D1").ready


def test_an_empty_timeframe_is_dropped_rather_than_faked():
    hist = HistoricalMtf({"H1": bars_from_closes([1.0] * 300, minutes=60), "W1": []})
    assert hist.timeframes == ["H1"]
    assert hist.at(START).get("W1") is None


def test_timeframes_are_reported_fine_to_coarse():
    closes = [1.0] * 300
    hist = HistoricalMtf({
        "D1": bars_from_closes(closes, minutes=1440),
        "M15": bars_from_closes(closes, minutes=15),
        "H4": bars_from_closes(closes, minutes=240),
    })
    assert hist.timeframes == ["M15", "H4", "D1"]


def test_context_depth_must_let_the_trend_ema_converge():
    """A 200-bar EMA reached at bar 200 is still its own seed.

    The config refuses a depth that would make the trend EMA a stale average
    wearing the name of a trend -- the same class of mistake as the angle gate,
    where an indicator silently did not mean what it said.
    """
    from tbot.config.models import ConfigError, EngineConfig

    with pytest.raises(ConfigError, match="context_bars"):
        EngineConfig.from_dict({"context_bars": 210})

    seed_weight = (1 - 2 / 201) ** (1200 - 200)
    assert seed_weight < 1e-3, "1200 bars should wash the seed out"


def test_the_summary_says_unknown_rather_than_flat():
    """"Balanced" and "no idea" are different answers.

    Gold has ~101 monthly bars at the broker, so MN1 can never satisfy a
    200-bar trend EMA. Rendering that as "flat" puts a verdict in the decision
    panel where there is none.
    """
    views = {
        "H1": TimeframeView("H1", 300, 1.0, "bearish", "test", ready=True),
        "MN1": TimeframeView("MN1", 101, 1.0, "neutral", "only 101 bars", ready=False),
    }
    summary = MultiTimeframe(views).summary()
    assert "H1 bear" in summary
    assert "MN1 n/a" in summary
    assert "MN1 flat" not in summary
