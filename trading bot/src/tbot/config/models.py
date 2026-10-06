"""Typed configuration objects.

Strategy behaviour lives in TOML, not in code. The reference systems this
replaces kept 3,000-line python files per symbol and scraped parameters back
out of the source text with regexes; here a symbol is ~30 lines of declarative
config validated on load, and one strategy implementation serves every symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any

from ..core.types import same_symbol

#: Timeframes MetaTrader 5 actually offers. Note the gaps: there is no H5 or
#: H10, so "about five hours" means H4 or H6 and "about ten" means H8 or H12.
TIMEFRAMES = frozenset(
    {
        "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
        "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1",
    }
)


class ConfigError(ValueError):
    """Raised for any malformed or unknown configuration key."""


def _require(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ConfigError(f"{where}: missing required key '{key}'")
    return d[key]


def _reject_unknown(d: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(d) - allowed
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}"
        )


def _parse_hhmm(value: str, where: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except Exception as exc:  # config errors are reported verbatim
        raise ConfigError(f"{where}: '{value}' is not HH:MM") from exc


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Trading window, always expressed in UTC.

    Broker server time is never trusted directly; the broker's UTC offset is a
    single engine-level setting (``engine.broker_utc_offset``) applied once when
    bars are ingested, so DST changes are a one-line config edit.
    """

    start: time = time(0, 0)
    end: time = time(23, 59)
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday=0

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str) -> SessionConfig:
        _reject_unknown(d, {"start", "end", "weekdays"}, where)
        return cls(
            start=_parse_hhmm(d.get("start", "00:00"), f"{where}.start"),
            end=_parse_hhmm(d.get("end", "23:59"), f"{where}.end"),
            weekdays=tuple(d.get("weekdays", [0, 1, 2, 3, 4])),
        )

    def contains(self, dt) -> bool:
        if dt.weekday() not in self.weekdays:
            return False
        t = dt.time()
        if self.start <= self.end:
            return self.start <= t <= self.end
        return t >= self.start or t <= self.end  # window wraps midnight


@dataclass(frozen=True, slots=True)
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_open_positions: int = 4
    max_positions_per_symbol: int = 1
    min_rr: float = 1.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RiskConfig:
        _reject_unknown(
            d,
            {
                "risk_per_trade_pct",
                "max_daily_loss_pct",
                "max_open_positions",
                "max_positions_per_symbol",
                "min_rr",
            },
            "[risk]",
        )
        cfg = cls(**d)
        if not 0 < cfg.risk_per_trade_pct <= 5:
            raise ConfigError("[risk].risk_per_trade_pct must be in (0, 5]")
        if cfg.max_open_positions < 1:
            raise ConfigError("[risk].max_open_positions must be >= 1")
        return cfg


@dataclass(frozen=True, slots=True)
class EngineConfig:
    mode: str = "paper"  # paper | live | backtest
    broker: str = "paper"
    timeframe: str = "M5"
    poll_seconds: float = 5.0
    warmup_bars: int = 400
    broker_utc_offset_hours: float = 0.0
    start_balance: float = 10_000.0
    journal_path: str = "data/journal.sqlite"
    #: Higher and lower timeframes read for context on every decision. The
    #: trading timeframe above stays the one that triggers entries; these only
    #: inform. MT5 has no 5h or 10h -- its ladder is M1..M30, H1..H4, H6, H8,
    #: H12, D1, W1, MN1 -- so H4 and H12 stand in for those.
    context_timeframes: tuple[str, ...] = ()
    #: Bars fetched per context timeframe. Must comfortably exceed the 200-bar
    #: trend EMA, not merely reach it: that EMA is seeded with the SMA of its
    #: first 200 bars, and after only 60 further bars ~55% of the value is
    #: still the seed -- a "trend EMA" that is really a stale average, which is
    #: how a gate ends up vetoing trades for the wrong reason. 1200 leaves the
    #: seed's weight at ~1e-4. Timeframes with less history available (MN1)
    #: simply return what exists and stay "not ready" until they have 200.
    context_bars: int = 1200
    #: Bars replayed through each strategy on the first poll, so a restart
    #: resumes a setup in progress instead of discarding it. Needs to cover a
    #: whole setup: pullback_max_wait + window_bars + cooldown_bars, with room
    #: to spare. 0 disables the replay.
    replay_bars: int = 60
    #: Touch this file to stop the bot after its current cycle. stop.bat
    #: writes it; run.bat clears it on start.
    stop_file: str = "data/STOP"
    #: In paper mode on a live feed, start the simulated account at the real
    #: account's balance instead of start_balance. On by default because
    #: position size is derived from the balance: simulating $10,000 against a
    #: $5,000 account sizes every trade twice too large, and nothing about the
    #: paper results would then carry over to live.
    mirror_account_balance: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EngineConfig:
        _reject_unknown(
            d,
            {
                "mode",
                "broker",
                "timeframe",
                "poll_seconds",
                "warmup_bars",
                "broker_utc_offset_hours",
                "start_balance",
                "journal_path",
                "context_timeframes",
                "context_bars",
                "replay_bars",
                "stop_file",
                "mirror_account_balance",
            },
            "[engine]",
        )
        if "context_timeframes" in d:
            d = {**d, "context_timeframes": tuple(str(x).upper() for x in
                                                  d["context_timeframes"])}
        cfg = cls(**d)
        unknown_tf = [tf for tf in cfg.context_timeframes if tf not in TIMEFRAMES]
        if unknown_tf:
            raise ConfigError(
                f"[engine].context_timeframes: {unknown_tf} not supported by MT5; "
                f"choose from {sorted(TIMEFRAMES)}"
            )
        if cfg.context_bars < 250:
            raise ConfigError(
                f"[engine].context_bars = {cfg.context_bars} is too few for a "
                "200-bar trend EMA to converge; use at least 250, 1200 preferred"
            )
        if cfg.timeframe.upper() not in TIMEFRAMES:
            raise ConfigError(
                f"[engine].timeframe {cfg.timeframe!r} not supported; "
                f"choose from {sorted(TIMEFRAMES)}"
            )
        if cfg.mode not in {"paper", "live", "backtest"}:
            raise ConfigError(f"[engine].mode '{cfg.mode}' not in paper|live|backtest")
        if cfg.broker not in {"paper", "mt5"}:
            raise ConfigError(f"[engine].broker '{cfg.broker}' not in paper|mt5")
        if cfg.mode == "live" and cfg.broker == "paper":
            raise ConfigError("[engine]: mode='live' requires a real broker, not 'paper'")
        return cfg


@dataclass(frozen=True, slots=True)
class SnapshotConfig:
    """Where to read MT5's SMC/ICT structure snapshots from.

    Detection runs inside MetaTrader 5 (the ``SMC_Snapshot_Export`` expert
    advisor); this only says where to find its output. Leaving ``common_path``
    empty auto-detects MT5's shared folder, which is right on a normal Windows
    install.
    """

    enabled: bool = False
    folder: str = "SMC_Export"
    common_path: str = ""
    timeframe: str = ""          # empty: follow [engine].timeframe
    max_age_minutes: float = 0.0  # 0: three bars of the snapshot timeframe
    require_fresh: bool = True    # no fresh snapshot -> ICT gates fail closed

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SnapshotConfig:
        _reject_unknown(
            d,
            {
                "enabled",
                "folder",
                "common_path",
                "timeframe",
                "max_age_minutes",
                "require_fresh",
            },
            "[snapshot]",
        )
        cfg = cls(**d)
        if cfg.max_age_minutes < 0:
            raise ConfigError("[snapshot].max_age_minutes must be >= 0")
        if cfg.enabled and not cfg.folder:
            raise ConfigError("[snapshot].folder must not be empty when enabled")
        return cfg


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    symbol: str
    strategy: str
    enabled: bool = True
    weight: float = 1.0
    sides: tuple[str, ...] = ("LONG",)
    params: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: How many *voting* filters (``veto = false``) must pass. 0 keeps the
    #: original rule that every filter must pass, which is what a config
    #: marking nothing as a voter means anyway.
    min_votes: int = 0
    exits: dict[str, dict[str, Any]] = field(default_factory=dict)
    session: SessionConfig = field(default_factory=SessionConfig)
    #: Signal rating and size tiering. Disabled by default, so an existing
    #: config keeps sizing every trade at the full risk budget.
    confidence: Any = None

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str) -> SymbolConfig:
        _reject_unknown(
            d,
            {
                "symbol",
                "strategy",
                "enabled",
                "weight",
                "sides",
                "params",
                "filters",
                "min_votes",
                "exits",
                "session",
                "confidence",
            },
            where,
        )
        # Exact, not uppercased: brokers use case-sensitive suffixes
        # (Exness EURUSDm, IC Markets EURUSD.a) and this string is sent
        # straight back to the terminal.
        symbol = str(_require(d, "symbol", where)).strip()
        sides = tuple(s.upper() for s in d.get("sides", ["LONG"]))
        for s in sides:
            if s not in {"LONG", "SHORT"}:
                raise ConfigError(f"{where}.sides: '{s}' not in LONG|SHORT")
        return cls(
            symbol=symbol,
            strategy=str(_require(d, "strategy", where)),
            enabled=bool(d.get("enabled", True)),
            weight=float(d.get("weight", 1.0)),
            sides=sides,
            params=dict(d.get("params", {})),
            filters={k: dict(v) for k, v in d.get("filters", {}).items()},
            min_votes=int(d.get("min_votes", 0)),
            exits={k: dict(v) for k, v in d.get("exits", {}).items()},
            session=SessionConfig.from_dict(d.get("session", {}), f"{where}.session"),
            confidence=_confidence_from(d.get("confidence", {}), f"{where}.confidence"),
        )


def _confidence_from(d: dict[str, Any], where: str):
    """Build the confidence config without a circular import.

    ``strategy.confidence`` needs ``ConfigError`` from this module, so the
    import has to happen inside the call rather than at module level.
    """
    from ..strategy.confidence import ConfidenceConfig

    return ConfidenceConfig.from_dict(dict(d or {}), where)


@dataclass(frozen=True, slots=True)
class BotConfig:
    engine: EngineConfig
    risk: RiskConfig
    symbols: tuple[SymbolConfig, ...]
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    telegram: TelegramConfig = field(default_factory=lambda: TelegramConfig())
    dashboard: DashboardConfig = field(default_factory=lambda: DashboardConfig())
    overlay: OverlayConfig = field(default_factory=lambda: OverlayConfig())
    log_level: str = "INFO"
    log_file: str | None = "logs/tbot.jsonl"

    @property
    def active_symbols(self) -> tuple[SymbolConfig, ...]:
        return tuple(s for s in self.symbols if s.enabled)

    def symbol(self, name: str) -> SymbolConfig:
        for s in self.symbols:
            if same_symbol(s.symbol, name):
                return s
        raise ConfigError(f"symbol '{name}' is not configured")

    @property
    def normalised_weights(self) -> dict[str, float]:
        """Weights across enabled symbols, renormalised to sum to 1.0.

        Renormalising (instead of trusting the file to add up) means disabling a
        symbol cannot silently shrink total deployed risk.
        """
        active = self.active_symbols
        total = sum(s.weight for s in active)
        if total <= 0:
            raise ConfigError("sum of symbol weights must be > 0")
        return {s.symbol: s.weight / total for s in active}


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Phone notifications and remote control.

    The token is a credential: prefer ``TBOT_TELEGRAM_TOKEN`` in the
    environment, or a ``[telegram]`` table in the gitignored
    ``config/credentials.toml``. Putting it in ``bot.toml`` works but that file
    is usually committed.
    """

    enabled: bool = False
    token: str = ""
    chat_id: str = ""
    events: tuple[str, ...] = ("order", "closed", "error", "started", "stopped")
    accept_commands: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TelegramConfig:
        _reject_unknown(
            d, {"enabled", "token", "chat_id", "events", "accept_commands"}, "[telegram]"
        )
        data = dict(d)
        if "events" in data:
            data["events"] = tuple(str(e).lower() for e in data["events"])
        if "chat_id" in data:
            data["chat_id"] = str(data["chat_id"])
        cfg = cls(**data)
        if cfg.enabled and not cfg.chat_id:
            raise ConfigError(
                "[telegram].chat_id is required when enabled; run `tbot telegram-setup`"
            )
        return cfg


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """Local read-only web view.

    Binds to loopback by default. Changing ``host`` exposes account balance and
    open positions to anything that can reach the machine -- only do it behind a
    network you control.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8787

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DashboardConfig:
        _reject_unknown(d, {"enabled", "host", "port"}, "[dashboard]")
        cfg = cls(**d)
        if not 1 <= cfg.port <= 65535:
            raise ConfigError(f"[dashboard].port {cfg.port} is out of range")
        return cfg


@dataclass(frozen=True, slots=True)
class OverlayConfig:
    """Publishes the bot's own state back to MT5 for the chart indicator."""

    enabled: bool = False
    folder: str = ""  # empty: reuse [snapshot].folder
    filename: str = "tbot_state.json"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OverlayConfig:
        _reject_unknown(d, {"enabled", "folder", "filename"}, "[overlay]")
        cfg = cls(**d)
        if cfg.enabled and not cfg.filename:
            raise ConfigError("[overlay].filename must not be empty")
        return cfg
