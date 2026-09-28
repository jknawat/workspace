"""Position sizing from broker contract specs.

The rule this module exists to enforce: lot size is derived from the broker's
own ``tick_value``/``tick_size``, never from a hardcoded pip table. Hardcoded
pip values are the single most expensive bug class in retail bots -- they are
off by 100x on metals and by 10x on JPY crosses, and the error only shows up
once real money is on the line.

If the smallest tradable volume would risk more than allowed, sizing *fails*
instead of rounding up. Refusing a trade is always cheaper than silently
doubling risk.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.types import SymbolSpec, round_to_step


@dataclass(frozen=True, slots=True)
class SizingResult:
    ok: bool
    volume: float
    risk_money: float
    value_per_price_unit: float
    reason: str

    @property
    def detail(self) -> dict[str, float]:
        return {
            "volume": self.volume,
            "risk_money": self.risk_money,
            "value_per_price_unit": self.value_per_price_unit,
        }


def round_volume(spec: SymbolSpec, volume: float) -> float:
    """Floor to the broker's volume step, then clamp to its maximum."""
    return round_to_step(volume, spec)


def risk_of_volume(spec: SymbolSpec, volume: float, sl_distance: float) -> float:
    return volume * sl_distance * spec.value_per_price_unit


def lot_for_risk(
    spec: SymbolSpec, risk_money: float, sl_distance: float
) -> SizingResult:
    """Largest volume whose stop-out loss stays within ``risk_money``."""
    vppu = spec.value_per_price_unit
    if risk_money <= 0:
        return SizingResult(False, 0.0, 0.0, vppu, "risk budget is zero or negative")
    if sl_distance <= 0:
        return SizingResult(False, 0.0, 0.0, vppu, "stop distance is zero")

    raw = risk_money / (sl_distance * vppu)
    volume = round_volume(spec, raw)

    if volume < spec.volume_min:
        min_risk = risk_of_volume(spec, spec.volume_min, sl_distance)
        return SizingResult(
            False,
            0.0,
            min_risk,
            vppu,
            (
                f"min volume {spec.volume_min} would risk {min_risk:.2f} "
                f"> budget {risk_money:.2f}"
            ),
        )

    actual = risk_of_volume(spec, volume, sl_distance)
    if actual > risk_money * 1.0001:  # tolerance for float noise only
        return SizingResult(
            False, 0.0, actual, vppu, f"rounded volume risks {actual:.2f} > {risk_money:.2f}"
        )
    return SizingResult(True, volume, actual, vppu, "sized from broker tick value")
