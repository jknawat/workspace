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


def test_brokers_own_figure_overrides_the_tick_value_derivation():
    """Measured on MetaQuotes-Demo, and worth a test of its own.

    XAUUSD reports tick_value 0.1 with tick_size 0.01, deriving $10 per dollar
    of gold. The terminal's order_calc_profit says $100 -- the real number.
    Since lot size is risk / this figure, the derivation would have sized every
    gold position ten times too large.
    """
    derived_only = SymbolSpec("XAUUSD", 2, 0.01, 0.01, 0.1, 0.01, 0.01, 100.0, 100.0)
    assert derived_only.value_per_price_unit == pytest.approx(10.0)  # the trap

    from_broker = SymbolSpec(
        "XAUUSD", 2, 0.01, 0.01, 0.1, 0.01, 0.01, 100.0, 100.0,
        money_per_price_unit=100.0,
    )
    assert from_broker.value_per_price_unit == pytest.approx(100.0)

    # $100 risk with a $5 stop: 0.2 lots on the truth, 2.0 on the derivation.
    assert lot_for_risk(from_broker, 100.0, 5.00).volume == pytest.approx(0.2)
    assert lot_for_risk(derived_only, 100.0, 5.00).volume == pytest.approx(2.0)


class _CentRoundingTerminal:
    """Stands in for MetaTrader 5: prices profit, then rounds it to the cent."""

    ORDER_TYPE_BUY = 0

    def __init__(self, per_lot_per_unit: float) -> None:
        self.per_lot_per_unit = per_lot_per_unit

    def symbol_info_tick(self, symbol):
        from types import SimpleNamespace

        return SimpleNamespace(bid=69650.5)

    def order_calc_profit(self, order_type, symbol, lots, price_open, price_close):
        return round(self.per_lot_per_unit * lots * (price_close - price_open), 2)


def _per_price_unit(per_lot_per_unit: float, volume_max: float) -> float | None:
    from types import SimpleNamespace

    from tbot.broker.mt5 import MT5Broker

    broker = MT5Broker()
    broker._mt5 = _CentRoundingTerminal(per_lot_per_unit)  # noqa: SLF001 - no terminal in tests
    info = SimpleNamespace(
        trade_tick_value=per_lot_per_unit * 0.1, trade_tick_size=0.1, point=0.1,
        volume_max=volume_max,
    )
    return broker._money_per_price_unit("JP225m", info)  # noqa: SLF001


def test_cent_rounding_does_not_set_the_value_of_a_cheap_contract():
    """Measured on Exness: one lot of JP225m earns $0.0063 per index point.

    The terminal rounds profit to the cent, so asking about one lot returned
    $0.01 -- 58% high. Lot size is risk divided by this number, so every
    position would have been 37% smaller than the budget intended.
    """
    assert _per_price_unit(0.006336, volume_max=5000.0) == pytest.approx(0.006336, rel=0.01)


def test_contracts_already_priced_in_dollars_are_left_alone():
    assert _per_price_unit(100.0, volume_max=200.0) == pytest.approx(100.0)   # gold
    assert _per_price_unit(1.1258, volume_max=300.0) == pytest.approx(1.1258, rel=0.001)  # DE30


def test_a_non_positive_broker_figure_is_rejected():
    spec = SymbolSpec(
        "BAD", 2, 0.01, 0.01, 1.0, 0.01, 0.01, 10.0, 100.0, money_per_price_unit=0.0
    )
    with pytest.raises(ValueError, match="money_per_price_unit"):
        _ = spec.value_per_price_unit
