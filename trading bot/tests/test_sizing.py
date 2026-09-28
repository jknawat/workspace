"""Position sizing -- the layer where a silent bug costs real money."""

from __future__ import annotations

import pytest

from tbot.core.types import SymbolSpec
from tbot.risk.sizing import lot_for_risk, risk_of_volume, round_volume


def test_value_per_price_unit_is_derived_from_broker_ticks(spec_eurusd, spec_xauusd):
    # 1 lot EURUSD: 0.00001 of price = $1 -> $100,000 per 1.0 of price
    assert spec_eurusd.value_per_price_unit == pytest.approx(100_000.0)
    # 1 lot XAUUSD (100 oz): 0.01 of price = $1 -> $100 per 1.0 of price
    assert spec_xauusd.value_per_price_unit == pytest.approx(100.0)


def test_lot_for_risk_hits_the_budget_exactly(spec_eurusd):
    result = lot_for_risk(spec_eurusd, risk_money=100.0, sl_distance=0.0010)
    assert result.ok
    assert result.volume == pytest.approx(1.0)
    assert result.risk_money == pytest.approx(100.0)


def test_same_budget_gives_a_very_different_lot_on_metals(spec_xauusd):
    """The bug hardcoded pip tables cause: gold is not forex.

    $100 risk with a $5 stop is 0.2 lots on gold. A forex-shaped calculation
    would have produced a wildly different number for the same dollar risk.
    """
    result = lot_for_risk(spec_xauusd, risk_money=100.0, sl_distance=5.00)
    assert result.ok
    assert result.volume == pytest.approx(0.2)
    assert result.risk_money == pytest.approx(100.0)


def test_rounding_is_always_downward(spec_eurusd):
    assert round_volume(spec_eurusd, 0.1234) == pytest.approx(0.12)
    assert round_volume(spec_eurusd, 0.999) == pytest.approx(0.99)


def test_volume_is_capped_at_the_broker_maximum(spec_eurusd):
    assert round_volume(spec_eurusd, 500.0) == pytest.approx(spec_eurusd.volume_max)


def test_sizing_refuses_rather_than_exceeding_the_budget(spec_eurusd):
    """Minimum volume risking more than allowed must fail, not round up."""
    result = lot_for_risk(spec_eurusd, risk_money=0.50, sl_distance=0.0010)
    assert not result.ok
    assert result.volume == 0.0
    assert "min volume" in result.reason


def test_sizing_rejects_a_zero_stop(spec_eurusd):
    assert not lot_for_risk(spec_eurusd, 100.0, 0.0).ok


def test_sizing_rejects_a_zero_budget(spec_eurusd):
    assert not lot_for_risk(spec_eurusd, 0.0, 0.0010).ok


def test_risk_of_volume_is_the_inverse_of_sizing(spec_eurusd):
    sized = lot_for_risk(spec_eurusd, 250.0, 0.0025)
    assert sized.ok
    assert risk_of_volume(spec_eurusd, sized.volume, 0.0025) == pytest.approx(sized.risk_money)


def test_spec_with_zero_tick_size_is_rejected():
    bad = SymbolSpec("BAD", 5, 0.00001, 0.0, 1.0, 0.01, 0.01, 10.0)
    with pytest.raises(ValueError):
        _ = bad.value_per_price_unit
