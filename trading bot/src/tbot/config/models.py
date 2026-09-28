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
    except Exception as exc:  # noqa: BLE001 - config errors are reported verbatim
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
    def from_dict(cls, d: dict[str, Any], where: str) -> "SessionConfig":
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
    def from_dict(cls, d: dict[str, Any]) -> "RiskConfig":
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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EngineConfig":
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
            },
            "[engine]",
        )
        cfg = cls(**d)
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
    def from_dict(cls, d: dict[str, Any]) -> "SnapshotConfig":
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
    session: SessionConfig = field(default_factory=SessionConfig)

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str) -> "SymbolConfig":
        _reject_unknown(
            d,
            {"symbol", "strategy", "enabled", "weight", "sides", "params", "filters", "session"},
            where,
        )
        symbol = str(_require(d, "symbol", where)).upper()
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
            session=SessionConfig.from_dict(d.get("session", {}), f"{where}.session"),
        )


@dataclass(frozen=True, slots=True)
class BotConfig:
    engine: EngineConfig
    risk: RiskConfig
    symbols: tuple[SymbolConfig, ...]
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    log_level: str = "INFO"
    log_file: str | None = "logs/tbot.jsonl"

    @property
    def active_symbols(self) -> tuple[SymbolConfig, ...]:
        return tuple(s for s in self.symbols if s.enabled)

    def symbol(self, name: str) -> SymbolConfig:
        for s in self.symbols:
            if s.symbol == name.upper():
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
