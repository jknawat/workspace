"""Core value objects shared by every layer.

Deliberately dependency-free: no pandas, no numpy, no broker SDK. Anything in
this module can be constructed in a unit test without a terminal, a network
connection, or a market being open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> Side:
        return Side.SHORT if self is Side.LONG else Side.LONG


class Phase(str, Enum):
    """Generic entry state machine phases (see strategy/state.py)."""

    SCANNING = "SCANNING"
    ARMED = "ARMED"
    WINDOW = "WINDOW"
    COOLDOWN = "COOLDOWN"


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Bar.ts must be timezone-aware (use UTC)")
        if self.high < self.low:
            raise ValueError(f"Bar high {self.high} < low {self.low} at {self.ts}")

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Bar:
        ts = row["ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return cls(
            ts=ts.astimezone(timezone.utc),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0) or 0.0),
        )


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    """Broker contract specification. Never hardcode pip values -- ask the broker."""

    name: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    volume_min: float
    volume_step: float
    volume_max: float
    contract_size: float = 100_000.0
    #: Account currency per 1.0 of price movement for 1.0 lot, as calculated by
    #: the broker itself. Set from ``order_calc_profit`` where available; it
    #: overrides the ``tick_value / tick_size`` derivation below.
    money_per_price_unit: float | None = None

    @property
    def value_per_price_unit(self) -> float:
        """Account currency gained per 1.0 of price movement, per 1.0 lot.

        Prefers the broker's own figure when we have it. The
        ``tick_value / tick_size`` derivation looks authoritative but is not:
        on a real MetaQuotes demo, XAUUSD reports ``tick_value 0.1`` with
        ``tick_size 0.01``, deriving $10 per dollar of gold -- while the
        terminal's own ``order_calc_profit`` says $100. Sizing off the
        derivation would have built every gold position **ten times too
        large**, because lot size is risk divided by this number.

        Forex agrees with the derivation; leveraged CFDs are where it breaks.
        So: ask the broker, and only fall back to arithmetic.
        """
        if self.money_per_price_unit is not None:
            if self.money_per_price_unit <= 0:
                raise ValueError(
                    f"{self.name}: money_per_price_unit must be > 0, "
                    f"got {self.money_per_price_unit}"
                )
            return self.money_per_price_unit
        if self.tick_size <= 0:
            raise ValueError(f"{self.name}: tick_size must be > 0")
        return self.tick_value / self.tick_size


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    side: Side
    ts: datetime
    price: float
    sl: float
    tp: float
    strategy: str
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def sl_distance(self) -> float:
        return abs(self.price - self.sl)

    @property
    def rr(self) -> float:
        risk = self.sl_distance
        return abs(self.tp - self.price) / risk if risk > 0 else 0.0


@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: str
    side: Side
    volume: float
    sl: float
    tp: float
    comment: str = ""
    deviation_points: int = 20


@dataclass(frozen=True, slots=True)
class OrderResult:
    ok: bool
    ticket: int | None = None
    price: float = 0.0
    volume: float = 0.0
    message: str = ""


@dataclass(slots=True)
class Position:
    symbol: str
    side: Side
    volume: float
    entry_price: float
    sl: float
    tp: float
    opened_at: datetime
    ticket: int = 0
    strategy: str = ""

    def unrealised(self, price: float, spec: SymbolSpec) -> float:
        move = (price - self.entry_price) * self.side.sign
        return move * spec.value_per_price_unit * self.volume


@dataclass(frozen=True, slots=True)
class AccountState:
    balance: float
    equity: float
    currency: str = "USD"
    leverage: int = 30


@dataclass(frozen=True, slots=True)
class Decision:
    """Result of a gate (filter / risk check). Carries the *why*, always."""

    passed: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.passed

    @classmethod
    def ok(cls, reason: str = "", **detail: Any) -> Decision:
        return cls(True, reason, detail)

    @classmethod
    def no(cls, reason: str, **detail: Any) -> Decision:
        return cls(False, reason, detail)


def same_symbol(a: str, b: str) -> bool:
    """Compare two symbol names.

    Case-insensitive because config and broker may disagree on casing, but
    never *normalising* either one: the broker's exact string is what must
    be sent back to it. Uppercasing EURUSDm to EURUSDM asks Exness for a
    symbol that does not exist.
    """
    return a.strip().casefold() == b.strip().casefold()


def round_to_step(volume: float, spec: SymbolSpec) -> float:
    """Floor a volume to the broker's step, then clamp to its maximum.

    Lives in ``core`` because both the risk layer (sizing a new order) and the
    broker adapters (slicing a partial close) need exactly the same arithmetic,
    and two implementations of it would eventually disagree.
    """
    import math

    if spec.volume_step <= 0:
        raise ValueError(f"{spec.name}: volume_step must be > 0")
    steps = math.floor(volume / spec.volume_step + 1e-9)
    stepped = steps * spec.volume_step
    decimals = max(0, -math.floor(math.log10(spec.volume_step)))
    return min(max(round(stepped, decimals + 2), 0.0), spec.volume_max)
