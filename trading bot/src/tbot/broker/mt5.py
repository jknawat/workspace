"""MetaTrader 5 adapter.

The ``MetaTrader5`` package is imported lazily inside :meth:`connect`, so the
rest of the system -- tests, backtests, config validation, CI -- runs on any
platform with nothing installed. This is the only module in the project that
knows MT5 exists.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.types import (
    AccountState,
    Bar,
    OrderRequest,
    OrderResult,
    Position,
    Side,
    SymbolSpec,
    round_to_step,
)
from ..obs import log as obs_log
from .base import Broker, BrokerError

#: Longest order comment the MetaTrader5 Python binding will accept.
#:
#: MQL5 documents 31, and the binding does not truncate: it refuses the whole
#: request with ``(-2, 'Invalid "comment" argument')`` and returns None, which
#: reads like a connection problem rather than a rejected string. Measured
#: against Exness build on 2026-10-06 with ``order_check``: 29 accepted, 30
#: refused, content irrelevant. Truncating at 31 meant every live order the bot
#: ever sent was rejected, while paper mode -- which ignores the field -- had
#: reported them all as filled.
MAX_COMMENT = 29

# The full ladder MT5 offers. Note the gaps that catch people out: there is no
# H5 and no H10, so "about five hours" means H4 or H6 and "about ten" means H8
# or H12. Anything missing here is silently unavailable as context, so keep it
# complete.
TIMEFRAMES = {
    name: f"TIMEFRAME_{name}"
    for name in (
        "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
        "H1", "H2", "H3", "H4", "H6", "H8", "H12",
        "D1", "W1", "MN1",
    )
}


class MT5Broker(Broker):
    name = "mt5"

    def __init__(
        self,
        credentials: dict[str, Any] | None = None,
        broker_utc_offset_hours: float = 0.0,
        magic: int = 770_001,
        deviation_points: int = 20,
    ) -> None:
        self.credentials = credentials or {}
        self.offset = timedelta(hours=broker_utc_offset_hours)
        self.magic = magic
        self.deviation_points = deviation_points
        self._mt5: Any = None
        self._spec_cache: dict[str, SymbolSpec] = {}

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    @property
    def mt5(self) -> Any:
        if self._mt5 is None:
            raise BrokerError("MT5Broker.connect() has not been called")
        return self._mt5

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5  # vendor's casing, not ours
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise BrokerError(
                "MetaTrader5 package is not installed (Windows only): pip install MetaTrader5"
            ) from exc

        kwargs: dict[str, Any] = {}
        if path := self.credentials.get("terminal_path"):
            kwargs["path"] = path
        if not mt5.initialize(**kwargs):
            raise BrokerError(f"mt5.initialize failed: {mt5.last_error()}")

        login = self.credentials.get("login")
        if login:
            ok = mt5.login(
                int(login),
                password=self.credentials.get("password", ""),
                server=self.credentials.get("server", ""),
            )
            if not ok:
                mt5.shutdown()
                raise BrokerError(f"mt5.login failed for {login}: {mt5.last_error()}")
        self._mt5 = mt5
        self._verify_account()

    def _verify_account(self) -> None:
        """Refuse to trade the wrong account.

        A terminal holding several saved logins can open a different one than
        expected, which changes the symbol names and the server's UTC offset.
        Without this check the first symptom is "symbol not available in Market
        Watch" -- which sounds like a config typo and is actually a $5,000 demo
        standing in for a $100,000 one, or worse, a live account standing in for
        a demo. Set expect_login / expect_server in credentials.toml.
        """
        want_login = self.credentials.get("expect_login")
        want_server = self.credentials.get("expect_server")
        if not want_login and not want_server:
            return
        info = self._mt5.account_info()
        if info is None:
            raise BrokerError(
                "no account is logged in to the terminal; expected "
                f"{want_login or ''}@{want_server or ''}"
            )
        if want_login and int(want_login) != int(info.login):
            raise BrokerError(
                f"terminal is on account {info.login}@{info.server}, expected "
                f"{want_login}@{want_server or info.server}. Launch MT5 with "
                f"mt5/start_gold.ini to pin it, or update credentials.toml."
            )
        if want_server and str(want_server) != str(info.server):
            raise BrokerError(
                f"terminal is on server {info.server}, expected {want_server}. "
                f"Symbol names and the UTC offset differ between servers."
            )

    def disconnect(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
            self._mt5 = None

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    def account(self) -> AccountState:
        info = self.mt5.account_info()
        if info is None:
            raise BrokerError(f"account_info unavailable: {self.mt5.last_error()}")
        return AccountState(
            balance=float(info.balance),
            equity=float(info.equity),
            currency=str(info.currency),
            leverage=int(info.leverage),
        )

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        sym = symbol.strip()
        if sym in self._spec_cache:
            return self._spec_cache[sym]
        if not self.mt5.symbol_select(sym, True):
            raise BrokerError(f"symbol {sym} not available in Market Watch")
        info = self.mt5.symbol_info(sym)
        if info is None:
            raise BrokerError(f"symbol_info({sym}) returned None")
        spec = SymbolSpec(
            name=sym,
            digits=int(info.digits),
            point=float(info.point),
            tick_size=float(info.trade_tick_size or info.point),
            tick_value=float(info.trade_tick_value),
            volume_min=float(info.volume_min),
            volume_step=float(info.volume_step),
            volume_max=float(info.volume_max),
            contract_size=float(info.trade_contract_size),
            money_per_price_unit=self._money_per_price_unit(sym, info),
        )
        if spec.tick_value <= 0 and spec.money_per_price_unit is None:
            raise BrokerError(
                f"{sym}: broker reported tick_value={spec.tick_value} and could not "
                f"calculate profit; refusing to size blind"
            )
        self._spec_cache[sym] = spec
        return spec

    def _money_per_price_unit(self, sym: str, info: Any) -> float | None:
        """Ask the terminal what 1.0 lot earns on a 1.0 move, in account currency.

        ``tick_value / tick_size`` is the obvious derivation and it is wrong on
        leveraged CFDs. Measured on MetaQuotes-Demo: XAUUSD reports
        ``tick_value 0.1`` and ``tick_size 0.01``, deriving $10 per dollar of
        gold, while ``order_calc_profit`` returns $100 -- the real figure. Since
        lot size is risk divided by this number, trusting the derivation would
        have sized gold ten times too large.

        Returns ``None`` when the terminal cannot price it (market closed, no
        quote); the caller then falls back to the derivation, which is correct
        for plain forex.
        """
        tick = self.mt5.symbol_info_tick(sym)
        price = float(getattr(tick, "bid", 0.0) or 0.0) if tick else 0.0
        if price <= 0:
            return None
        def calc(lots: float) -> float | None:
            value = self.mt5.order_calc_profit(
                self.mt5.ORDER_TYPE_BUY, sym, lots, price, price + 1.0
            )
            return float(value) if value is not None and value > 0 else None

        profit = calc(1.0)
        if profit is None:
            return None

        # The terminal rounds its answer to the account currency's cent. Where
        # one lot earns less than a few dollars per unit of price, that rounding
        # is most of the answer: JP225m at Exness earns $0.0063 and came back as
        # $0.01, 58% high, which sizes every position 37% too small. Ask again
        # with enough lots that the cent no longer matters, and divide.
        if profit < 10.0:
            lots = min(float(info.volume_max or 1.0), float(math.ceil(1000.0 / profit)))
            if lots > 1.0:
                scaled = calc(lots)
                if scaled is not None:
                    profit = scaled / lots

        derived = float(info.trade_tick_value) / float(info.trade_tick_size or info.point or 1)
        if derived > 0 and abs(profit - derived) / max(profit, derived) > 0.01:
            obs_log.get("broker").warning(
                "%s: broker profit calc says %.4f per price unit but tick_value "
                "implies %.4f (%.1fx) -- using the broker's figure",
                sym, profit, derived, profit / derived if derived else 0.0,
                extra={"symbol": sym, "event": "tick_value_mismatch",
                       "broker": profit, "derived": derived},
            )
        return float(profit)

    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        tf = self._timeframe(timeframe)
        # start_pos=1 skips the still-forming bar: strategies only see closed bars.
        rates = self.mt5.copy_rates_from_pos(symbol.strip(), tf, 1, count)
        if rates is None or len(rates) == 0:
            raise BrokerError(f"no rates for {symbol} {timeframe}: {self.mt5.last_error()}")
        out: list[Bar] = []
        for r in rates:
            ts = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc) - self.offset
            out.append(
                Bar(
                    ts=ts,
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                )
            )
        return out

    def spread_points(self, symbol: str) -> float:
        tick = self.mt5.symbol_info_tick(symbol.strip())
        if tick is None:
            return 0.0
        spec = self.symbol_spec(symbol)
        return (float(tick.ask) - float(tick.bid)) / spec.point

    def quote(self, symbol: str) -> tuple[float, float] | None:
        tick = self.mt5.symbol_info_tick(symbol.strip())
        if tick is None:
            return None
        bid, ask = float(tick.bid), float(tick.ask)
        # A terminal that is connected but has no fresh tick returns zeros
        # rather than None, and a zero price on the panel reads as a crash.
        if bid <= 0.0 or ask <= 0.0:
            return None
        return (bid, ask)

    def positions(self, symbol: str | None = None) -> list[Position]:
        raw = (
            self.mt5.positions_get(symbol=symbol.strip())
            if symbol
            else self.mt5.positions_get()
        )
        if raw is None:
            return []
        out: list[Position] = []
        for p in raw:
            if int(p.magic) != self.magic:
                continue  # never touch positions this bot did not open
            out.append(
                Position(
                    symbol=str(p.symbol),
                    side=Side.LONG if p.type == self.mt5.POSITION_TYPE_BUY else Side.SHORT,
                    volume=float(p.volume),
                    entry_price=float(p.price_open),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    opened_at=datetime.fromtimestamp(int(p.time), tz=timezone.utc) - self.offset,
                    ticket=int(p.ticket),
                    strategy=str(p.comment).split(":", 1)[0],
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    def market_order(self, req: OrderRequest) -> OrderResult:
        mt5 = self.mt5
        spec = self.symbol_spec(req.symbol)
        tick = mt5.symbol_info_tick(req.symbol.strip())
        if tick is None:
            return OrderResult(False, message=f"no tick for {req.symbol}")
        price = float(tick.ask) if req.side is Side.LONG else float(tick.bid)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": req.symbol.strip(),
            "volume": float(req.volume),
            "type": mt5.ORDER_TYPE_BUY if req.side is Side.LONG else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": round(req.sl, spec.digits),
            "tp": round(req.tp, spec.digits),
            "deviation": req.deviation_points or self.deviation_points,
            "magic": self.magic,
            "comment": req.comment[:MAX_COMMENT],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(req.symbol),
        }
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(False, message=f"order_send returned None: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                False, message=f"retcode {result.retcode}: {getattr(result, 'comment', '')}"
            )
        return OrderResult(
            True,
            ticket=int(result.order),
            price=float(result.price),
            volume=float(result.volume),
            message="filled",
        )

    def close_position(
        self, ticket: int, volume: float | None = None, reason: str = "manual"
    ) -> OrderResult:
        mt5 = self.mt5
        raw = mt5.positions_get(ticket=ticket)
        if not raw:
            return OrderResult(False, message=f"position {ticket} not found")
        p = raw[0]
        spec = self.symbol_spec(p.symbol)
        closing = float(p.volume) if volume is None else round_to_step(volume, spec)
        if closing < spec.volume_min:
            return OrderResult(
                False, message=f"close volume {closing} below minimum {spec.volume_min}"
            )
        if closing < float(p.volume):
            remainder = round_to_step(float(p.volume) - closing, spec)
            if remainder < spec.volume_min:
                return OrderResult(
                    False,
                    message=(
                        f"partial close would leave {remainder} below the "
                        f"{spec.volume_min} minimum"
                    ),
                )
        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(ticket),
            "symbol": p.symbol,
            "volume": closing,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if is_buy else tick.ask),
            "deviation": self.deviation_points,
            "magic": self.magic,
            "comment": f"close:{reason}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(p.symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = getattr(result, "retcode", "None")
            return OrderResult(False, message=f"close failed, retcode {code}")
        return OrderResult(
            True, ticket=ticket, price=float(result.price), volume=closing, message="closed"
        )

    def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        """Move a live stop or target with ``TRADE_ACTION_SLTP``.

        MT5 replaces both levels on every such request, so the current values
        are read back and any level not being changed is sent unchanged --
        omitting one would clear it.
        """
        mt5 = self.mt5
        raw = mt5.positions_get(ticket=ticket)
        if not raw:
            return OrderResult(False, message=f"position {ticket} not found")
        p = raw[0]
        spec = self.symbol_spec(p.symbol)
        new_sl = float(p.sl) if sl is None else round(sl, spec.digits)
        new_tp = float(p.tp) if tp is None else round(tp, spec.digits)
        if new_sl == float(p.sl) and new_tp == float(p.tp):
            return OrderResult(True, ticket=ticket, message="no change")

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": p.symbol,
            "sl": new_sl,
            "tp": new_tp,
            "magic": self.magic,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = getattr(result, "retcode", "None")
            comment = getattr(result, "comment", "")
            return OrderResult(False, message=f"modify failed, retcode {code}: {comment}")
        return OrderResult(True, ticket=ticket, volume=float(p.volume), message="modified")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _timeframe(self, name: str) -> Any:
        key = name.upper()
        if key not in TIMEFRAMES:
            raise BrokerError(f"unsupported timeframe '{name}'; known: {sorted(TIMEFRAMES)}")
        return getattr(self.mt5, TIMEFRAMES[key])

    def _filling_mode(self, symbol: str) -> Any:
        """Pick a filling mode the symbol actually accepts.

        Hardcoding ``ORDER_FILLING_FOK`` is a common source of retcode 10030
        ("unsupported filling mode") on brokers that only allow IOC.
        """
        mt5 = self.mt5
        info = mt5.symbol_info(symbol.strip())
        modes = int(getattr(info, "filling_mode", 0) or 0)
        if modes & 1:  # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        if modes & 2:  # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN
