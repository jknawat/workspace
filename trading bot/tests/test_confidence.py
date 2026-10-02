"""Rating signals, and sizing to the rating.

The properties that matter here are honesty ones. A score must not reward
missing evidence, must not exceed its own scale, and must never be mistaken for
a win probability -- the strategy wins ~30% of its trades, so a "90" that read
as "90% likely to win" would misprice every stake built on it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from conftest import bars_from_closes

from tbot.config.models import ConfigError
from tbot.core.types import Side, Signal
from tbot.data.mtf import MultiTimeframe, TimeframeView
from tbot.strategy.base import BarContext
from tbot.strategy.confidence import (
    DEFAULT_WEIGHTS,
    ConfidenceConfig,
    ConfidenceScorer,
    Tier,
)

TS = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def mtf_of(**directions) -> MultiTimeframe:
    return MultiTimeframe({
        tf: TimeframeView(tf, 300, 4000.0, d, "test", ready=True)
        for tf, d in directions.items()
    })


def ctx_for(symbol_cfg, spec, mtf=None, atr=4.0, ema_fast=4000.0, spread=0.0):
    bars = bars_from_closes([4000.0] * 30)
    return BarContext(
        cfg=symbol_cfg, spec=spec, bars=bars, i=len(bars) - 1,
        ind={"atr": [atr] * len(bars), "ema_fast": [ema_fast] * len(bars)},
        mtf=mtf, spread_points=spread,
    )


def signal_for(side=Side.LONG, price=4000.0, sl=3990.0, tp=4030.0) -> Signal:
    return Signal(
        symbol="XAUUSDm", side=side, ts=TS, price=price, sl=sl, tp=tp,
        strategy="ema_pullback", reason="test",
    )


def scorer(**over) -> ConfidenceScorer:
    cfg = ConfidenceConfig(
        enabled=True, min_score=float(over.pop("min_score", 0.0)),
        tiers=tuple(over.pop("tiers", (Tier(0.0, 1.0),))),
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return ConfidenceScorer(cfg)


# --------------------------------------------------------------------------- #
# The scale
# --------------------------------------------------------------------------- #


def test_the_weights_sum_to_one_hundred():
    """So a score reads as a share of available evidence."""
    assert sum(DEFAULT_WEIGHTS.values()) == 100.0


def test_a_score_never_exceeds_its_scale(symbol_cfg, spec_eurusd):
    """Every component is clamped, so even a perfect setup cannot overflow."""
    ctx = ctx_for(symbol_cfg, spec_eurusd,
                  mtf=mtf_of(M15="bullish", H1="bullish", D1="bullish"))
    # An absurdly generous signal: huge reward, entry exactly on the EMA.
    s = scorer().score(signal_for(tp=9999.0), ctx, Side.LONG)
    assert 0.0 <= s.points <= 100.0


def test_a_hopeless_setup_scores_at_the_floor(symbol_cfg, spec_eurusd):
    ctx = ctx_for(symbol_cfg, spec_eurusd,
                  mtf=mtf_of(M15="bearish", H1="bearish", D1="bearish"),
                  ema_fast=4100.0)
    s = scorer().score(signal_for(tp=4000.5), ctx, Side.LONG)
    assert s.points >= 0.0
    assert s.points < 40.0


# --------------------------------------------------------------------------- #
# Missing evidence must not pay
# --------------------------------------------------------------------------- #


def test_no_timeframe_context_earns_no_timeframe_points(symbol_cfg, spec_eurusd):
    """An unknown is not a point in the trade's favour."""
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=None)
    s = scorer().score(signal_for(), ctx, Side.LONG)
    mtf = next(c for c in s.components if c.name == "mtf")
    assert mtf.earned == 0.0
    assert "no timeframe context" in mtf.note


def test_a_timeframe_without_history_does_not_vote(symbol_cfg, spec_eurusd):
    views = {
        "D1": TimeframeView("D1", 300, 4000.0, "bullish", "ok", ready=True),
        "MN1": TimeframeView("MN1", 101, 4000.0, "neutral", "thin", ready=False),
    }
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=MultiTimeframe(views))
    s = scorer().score(signal_for(), ctx, Side.LONG)
    mtf = next(c for c in s.components if c.name == "mtf")
    # One ready timeframe, and it agrees: full marks, MN1 ignored entirely.
    assert mtf.earned == pytest.approx(mtf.weight)
    assert "1 of 1" in mtf.note


def test_disagreement_is_netted_not_ignored(symbol_cfg, spec_eurusd):
    """Four for and two against is a weaker case than four for and none."""
    clean = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(
        A="bullish", B="bullish", C="bullish", D="bullish"))
    mixed = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(
        A="bullish", B="bullish", C="bullish", D="bullish",
        E="bearish", F="bearish"))
    sc = scorer()
    a = next(c for c in sc.score(signal_for(), clean, Side.LONG).components
             if c.name == "mtf")
    b = next(c for c in sc.score(signal_for(), mixed, Side.LONG).components
             if c.name == "mtf")
    assert a.earned > b.earned


def test_shorts_are_scored_symmetrically(symbol_cfg, spec_eurusd):
    """Bidirectional trading is only honest if the rating is too."""
    bear = ctx_for(symbol_cfg, spec_eurusd,
                   mtf=mtf_of(M15="bearish", H1="bearish", D1="bearish"))
    bull = ctx_for(symbol_cfg, spec_eurusd,
                   mtf=mtf_of(M15="bullish", H1="bullish", D1="bullish"))
    sc = scorer()
    short = sc.score(signal_for(Side.SHORT, sl=4010.0, tp=3970.0), bear, Side.SHORT)
    long_ = sc.score(signal_for(Side.LONG), bull, Side.LONG)
    short_mtf = next(c for c in short.components if c.name == "mtf")
    long_mtf = next(c for c in long_.components if c.name == "mtf")
    assert short_mtf.earned == pytest.approx(long_mtf.earned)


def test_an_unquoted_spread_does_not_earn_full_cost_points(symbol_cfg, spec_eurusd):
    """A backtest with no spread must not collect points live trading cannot."""
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"), spread=0.0)
    cost = next(c for c in scorer().score(signal_for(), ctx, Side.LONG).components
                if c.name == "cost")
    assert cost.earned < cost.weight
    assert "no spread quoted" in cost.note


# --------------------------------------------------------------------------- #
# Components behave directionally
# --------------------------------------------------------------------------- #


def test_a_wider_target_scores_better(symbol_cfg, spec_eurusd):
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"))
    sc = scorer()
    thin = sc.score(signal_for(tp=4010.0), ctx, Side.LONG)
    fat = sc.score(signal_for(tp=4030.0), ctx, Side.LONG)
    assert fat.points > thin.points


def test_a_tighter_entry_scores_better(symbol_cfg, spec_eurusd):
    sc = scorer()
    near = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"), ema_fast=4000.0)
    far = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"), ema_fast=3990.0)
    assert sc.score(signal_for(), near, Side.LONG).points > \
        sc.score(signal_for(), far, Side.LONG).points


def test_a_cheaper_spread_scores_better(symbol_cfg, spec_eurusd):
    sc = scorer()
    cheap = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"), spread=10.0)
    dear = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"), spread=5000.0)
    assert sc.score(signal_for(), cheap, Side.LONG).points > \
        sc.score(signal_for(), dear, Side.LONG).points


# --------------------------------------------------------------------------- #
# Tiers
# --------------------------------------------------------------------------- #


def test_below_the_minimum_is_not_tradeable():
    cfg = ConfidenceConfig(enabled=True, min_score=50.0, tiers=(Tier(50.0, 1.0),))
    assert cfg.tier_for(49.9) is None
    assert cfg.tier_for(50.0) is not None


def test_the_best_applicable_tier_wins_whatever_the_file_order():
    cfg = ConfidenceConfig.from_dict({
        "enabled": True,
        "min_score": 45,
        "tiers": [
            {"min_score": 45, "risk_mult": 0.4, "label": "lean"},
            {"min_score": 80, "risk_mult": 1.0, "label": "strong"},
            {"min_score": 60, "risk_mult": 0.7, "label": "normal"},
        ],
    }, "[confidence]")
    assert cfg.tier_for(50).label == "lean"
    assert cfg.tier_for(65).label == "normal"
    assert cfg.tier_for(95).label == "strong"


def test_a_tier_may_not_stake_more_than_the_risk_budget():
    """risk_mult is a share of risk_per_trade_pct, so >1 would breach the cap."""
    with pytest.raises(ConfigError, match=r"exceeds 1\.0"):
        ConfidenceConfig.from_dict({
            "enabled": True,
            "tiers": [{"min_score": 50, "risk_mult": 1.5}],
        }, "[confidence]")


def test_enabled_with_no_tiers_is_refused():
    """Otherwise every signal is silently declined and the bot looks broken."""
    with pytest.raises(ConfigError, match="no tiers"):
        ConfidenceConfig.from_dict({"enabled": True}, "[confidence]")


def test_an_unknown_component_weight_is_refused():
    with pytest.raises(ConfigError, match="unknown component"):
        ConfidenceConfig.from_dict({
            "enabled": True,
            "weights": {"vibes": 50},
            "tiers": [{"min_score": 0, "risk_mult": 1.0}],
        }, "[confidence]")


def test_an_unknown_option_is_refused():
    with pytest.raises(ConfigError, match="unknown option"):
        ConfidenceConfig.from_dict({"enabled": True, "mni_score": 45}, "[confidence]")


def test_a_zero_weight_component_is_left_out_entirely(symbol_cfg, spec_eurusd):
    """Switching a component off should remove it, not score it zero."""
    sc = scorer(weights={**DEFAULT_WEIGHTS, "cost": 0.0})
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"))
    names = [c.name for c in sc.score(signal_for(), ctx, Side.LONG).components]
    assert "cost" not in names
    assert "mtf" in names


# --------------------------------------------------------------------------- #
# What it says
# --------------------------------------------------------------------------- #


def test_the_explanation_never_claims_a_win_rate(symbol_cfg, spec_eurusd):
    """The panel must not imply the score is a probability of winning."""
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"))
    text = scorer().score(signal_for(), ctx, Side.LONG).explain()
    assert "/100" in text
    assert "win" not in text.lower()


def test_the_explanation_names_every_component(symbol_cfg, spec_eurusd):
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"))
    s = scorer().score(signal_for(), ctx, Side.LONG)
    for c in s.components:
        assert c.name in s.explain()


def test_it_serialises_for_the_dashboard(symbol_cfg, spec_eurusd):
    ctx = ctx_for(symbol_cfg, spec_eurusd, mtf=mtf_of(D1="bullish"))
    d = scorer().score(signal_for(), ctx, Side.LONG).to_dict()
    assert set(d) == {"points", "tier", "risk_mult", "tradeable", "components"}
    assert d["components"] and all("note" in c for c in d["components"])
