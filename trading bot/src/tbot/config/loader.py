"""Load ``bot.toml`` plus one file per symbol into a validated :class:`BotConfig`.

Uses ``tomllib`` from the standard library (Python 3.11+), so configuration
needs no third-party dependency.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from .models import (
    BotConfig,
    ConfigError,
    DashboardConfig,
    EngineConfig,
    OverlayConfig,
    RiskConfig,
    SnapshotConfig,
    SymbolConfig,
    TelegramConfig,
    _reject_unknown,
)

ENV_PREFIX = "TBOT_"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as fh:
        try:
            return tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML -- {exc}") from exc


def _apply_env_overrides(engine: dict[str, Any]) -> dict[str, Any]:
    """Allow ``TBOT_MODE=live`` style overrides for deploy-time switches."""
    mapping = {
        f"{ENV_PREFIX}MODE": "mode",
        f"{ENV_PREFIX}BROKER": "broker",
        f"{ENV_PREFIX}TIMEFRAME": "timeframe",
        f"{ENV_PREFIX}BROKER_UTC_OFFSET_HOURS": "broker_utc_offset_hours",
    }
    out = dict(engine)
    for env_key, cfg_key in mapping.items():
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        out[cfg_key] = float(raw) if cfg_key.endswith("_hours") else raw
    return out


def load_config(path: str | Path) -> BotConfig:
    root = Path(path)
    raw = _read_toml(root)
    _reject_unknown(
        raw,
        {"engine", "risk", "log", "symbols", "snapshot", "telegram", "dashboard", "overlay"},
        str(root),
    )

    engine = EngineConfig.from_dict(_apply_env_overrides(raw.get("engine", {})))
    risk = RiskConfig.from_dict(raw.get("risk", {}))
    snapshot = SnapshotConfig.from_dict(raw.get("snapshot", {}))
    telegram = TelegramConfig.from_dict(_apply_telegram_env(raw.get("telegram", {}), root))
    dashboard = DashboardConfig.from_dict(raw.get("dashboard", {}))
    overlay = OverlayConfig.from_dict(raw.get("overlay", {}))

    log = raw.get("log", {})
    _reject_unknown(log, {"level", "file"}, "[log]")

    symbols_dir = root.parent / str(raw.get("symbols", {}).get("dir", "symbols"))
    symbols = load_symbol_configs(symbols_dir)
    if not symbols:
        raise ConfigError(f"no symbol configs found in {symbols_dir}")

    return BotConfig(
        engine=engine,
        risk=risk,
        symbols=symbols,
        snapshot=snapshot,
        telegram=telegram,
        dashboard=dashboard,
        overlay=overlay,
        log_level=str(log.get("level", "INFO")).upper(),
        log_file=log.get("file", "logs/tbot.jsonl"),
    )


def load_symbol_configs(directory: str | Path) -> tuple[SymbolConfig, ...]:
    d = Path(directory)
    if not d.is_dir():
        raise ConfigError(f"symbol config directory not found: {d}")
    out: list[SymbolConfig] = []
    seen: set[str] = set()
    for file in sorted(d.glob("*.toml")):
        cfg = SymbolConfig.from_dict(_read_toml(file), str(file))
        if cfg.symbol in seen:
            raise ConfigError(f"duplicate symbol config for {cfg.symbol} ({file})")
        seen.add(cfg.symbol)
        out.append(cfg)
    return tuple(out)


def load_credentials(path: str | Path | None = None) -> dict[str, Any]:
    """Broker credentials, environment first so secrets never need a file.

    Recognised: ``TBOT_MT5_LOGIN``, ``TBOT_MT5_PASSWORD``, ``TBOT_MT5_SERVER``,
    ``TBOT_MT5_TERMINAL_PATH``.
    """
    creds: dict[str, Any] = {}
    if path is not None and Path(path).is_file():
        creds.update(_read_toml(Path(path)).get("mt5", {}))
    for key in ("login", "password", "server", "terminal_path",
                "expect_login", "expect_server"):
        env = os.environ.get(f"{ENV_PREFIX}MT5_{key.upper()}")
        if env:
            creds[key] = env
    if "login" in creds:
        creds["login"] = int(creds["login"])
    return creds


def _apply_telegram_env(raw: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Fill the bot token and chat id from the safest source available.

    Precedence: environment, then ``credentials.toml`` beside the config, then
    whatever ``bot.toml`` says. A token in a committed config file is the worst
    of the three, so it loses to both others.
    """
    out = dict(raw)
    secrets = load_telegram_credentials(config_path.parent / "credentials.toml")
    for key in ("token", "chat_id"):
        if secrets.get(key):
            out[key] = secrets[key]
    for key, env_key in (("token", "TELEGRAM_TOKEN"), ("chat_id", "TELEGRAM_CHAT_ID")):
        value = os.environ.get(f"{ENV_PREFIX}{env_key}")
        if value:
            out[key] = value
    return out


def load_telegram_credentials(path: str | Path | None = None) -> dict[str, Any]:
    """Read a ``[telegram]`` table from a credentials file, if one exists."""
    if path is None or not Path(path).is_file():
        return {}
    table = _read_toml(Path(path)).get("telegram", {})
    out = {k: v for k, v in table.items() if k in {"token", "chat_id"}}
    if "chat_id" in out:
        out["chat_id"] = str(out["chat_id"])
    return out
