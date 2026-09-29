"""Command line interface (argparse, stdlib only).

    tbot validate     check config and print the resolved risk budgets
    tbot strategies   list strategies, filters and their parameters
    tbot backtest     replay CSV bars through the real pipeline
    tbot paper        live/replay bars, simulated fills
    tbot live         real orders (requires an explicit acknowledgement flag)
    tbot specs        capture broker contract specs into a TOML file
    tbot snapshot     inspect the SMC/ICT structure snapshots MT5 is publishing
    tbot telegram-setup  verify a bot token and find your chat id
    tbot doctor       check python, config, MT5, snapshots, journal and watchers
    tbot report       summarise a journal database

Design choice: the CLI is the only entry point, and a GUI -- if one is ever
added -- is a *reader* of the journal and of ``TradeEngine.state()``. Making the
UI the application, as MT5 monitor bots typically do, is what makes those bots
untestable and unrunnable headless.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .broker import DEFAULT_SPECS, PaperBroker
from .broker import build as build_broker
from .broker.base import Broker, BrokerError
from .config import ConfigError, load_config, load_credentials
from .config.models import BotConfig
from .core.types import SymbolSpec
from .data.feed import BarFeed, BrokerFeed, CsvFeed
from .data.snapshot import SnapshotError
from .data.snapshot_store import SnapshotStore
from .engine import Runner, run_backtest
from .engine.exits import ExitManager
from .interfaces import build as build_interfaces
from .interfaces.telegram import TelegramClient, TelegramError, discover_chat_id
from .journal import Journal
from .obs import log as obs_log
from .strategy import available as available_strategies
from .strategy import create
from .strategy import get as get_strategy
from .strategy.filters import available as available_filters

DEFAULT_CONFIG = "config/bot.toml"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _load(args: argparse.Namespace) -> BotConfig:
    cfg = load_config(args.config)
    obs_log.setup(cfg.log_level, cfg.log_file)
    return cfg


def _load_specs(path: str | None) -> dict[str, SymbolSpec] | None:
    if not path:
        return None
    import tomllib

    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)
    return {k.upper(): SymbolSpec(name=k.upper(), **v) for k, v in raw.get("symbols", {}).items()}


def _build_snapshots(cfg: BotConfig) -> SnapshotStore | None:
    """Build the MT5 structure-snapshot store, or ``None`` when disabled."""
    if not cfg.snapshot.enabled:
        return None
    return SnapshotStore.from_settings(
        folder=cfg.snapshot.folder,
        common_path=cfg.snapshot.common_path,
        timeframe=cfg.snapshot.timeframe or cfg.engine.timeframe,
        max_age_minutes=cfg.snapshot.max_age_minutes,
        broker_utc_offset_hours=cfg.engine.broker_utc_offset_hours,
    )


def _build_runtime(
    cfg: BotConfig, config_path: str, data_dir: str | None
) -> tuple[Broker, BarFeed, Broker | None]:
    """Return (execution broker, data feed, extra broker needing shutdown)."""
    creds = load_credentials(Path(config_path).parent / "credentials.toml")

    if cfg.engine.mode == "live":
        broker = build_broker(
            "mt5", credentials=creds, broker_utc_offset_hours=cfg.engine.broker_utc_offset_hours
        )
        broker.connect()
        return broker, BrokerFeed(broker), None

    exec_broker = PaperBroker(balance=cfg.engine.start_balance)
    exec_broker.connect()
    if cfg.engine.broker == "mt5":
        data_broker = build_broker(
            "mt5", credentials=creds, broker_utc_offset_hours=cfg.engine.broker_utc_offset_hours
        )
        data_broker.connect()
        for scfg in cfg.active_symbols:  # trade the broker's real contract specs
            exec_broker.specs[scfg.symbol] = data_broker.symbol_spec(scfg.symbol)
        return exec_broker, BrokerFeed(data_broker), data_broker
    return exec_broker, CsvFeed(data_dir or "data"), None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_validate(args: argparse.Namespace) -> int:
    cfg = _load(args)
    weights = cfg.normalised_weights
    balance = cfg.engine.start_balance
    print(f"config      {args.config}")
    print(f"mode        {cfg.engine.mode} on {cfg.engine.broker} ({cfg.engine.timeframe})")
    print(
        f"risk        {cfg.risk.risk_per_trade_pct:.2f}% per trade, "
        f"daily stop {cfg.risk.max_daily_loss_pct:.2f}%, "
        f"max {cfg.risk.max_open_positions} open"
    )
    print(f"symbols     {len(cfg.active_symbols)} enabled of {len(cfg.symbols)}")
    print()
    print(f"{'symbol':<10} {'strategy':<16} {'sides':<12} {'weight':>7} {'budget':>10}  session")
    for scfg in cfg.active_symbols:
        w = weights[scfg.symbol]
        budget = balance * cfg.risk.risk_per_trade_pct / 100.0 * w
        session = f"{scfg.session.start:%H:%M}-{scfg.session.end:%H:%M}"
        print(
            f"{scfg.symbol:<10} {scfg.strategy:<16} {'/'.join(scfg.sides):<12} "
            f"{w:>6.1%} {budget:>10.2f}  {session} UTC"
        )
    print()
    print(
        f"total deployed risk at {balance:,.0f} balance: "
        f"{balance * cfg.risk.risk_per_trade_pct / 100.0:,.2f} "
        f"({cfg.risk.risk_per_trade_pct:.2f}%) across all symbols simultaneously"
    )
    return 0


def _summary(cls: type) -> str:
    """First line of the class docstring, falling back to its module's.

    Strategies put their explanation in the module docstring, where it belongs;
    without this fallback they listed with no description at all.
    """
    doc = cls.__doc__
    if not doc or not doc.strip():
        doc = getattr(sys.modules.get(cls.__module__), "__doc__", "") or ""
    lines = doc.strip().splitlines()
    return lines[0].strip() if lines else ""


def _describe(name: str, cls: type, module: bool = False) -> None:
    print(f"\n  {name}" + (f"  ({cls.__module__})" if module else ""))
    summary = _summary(cls)
    if summary:
        print(f"    {summary}")
    for key, value in cls.defaults.items():  # type: ignore[attr-defined]
        print(f"      {key:<26} = {value!r}")


def cmd_strategies(args: argparse.Namespace) -> int:
    print("strategies:")
    for name in available_strategies():
        _describe(name, get_strategy(name), module=True)

    print("\nexit policies (declare under [exits.<name>] in a symbol file):")
    from .engine import exits as ex

    for name in ex.available():
        _describe(name, ex._REGISTRY[name])  # noqa: SLF001 - introspection for help output

    print("\nfilters (declare under [filters.<name>] in a symbol file):")
    from .strategy import filters as f

    for name in available_filters():
        _describe(name, f._REGISTRY[name])  # noqa: SLF001 - introspection for help output
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = _load(args)
    feed = CsvFeed(args.data)
    journal = Journal(args.journal) if args.journal else None
    if journal:
        journal.start_run("backtest", "paper", note=f"cli backtest {args.symbol or 'all'}")
    try:
        report = run_backtest(
            cfg,
            feed,
            symbols=[args.symbol] if args.symbol else None,
            specs=_load_specs(args.specs),
            journal=journal,
            max_bars=args.bars,
        )
    finally:
        if journal:
            journal.close()

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"\nbacktest: {args.symbol or 'all enabled symbols'} ({cfg.engine.timeframe})")
        print(report.render())
        if args.trades:
            print("\n  trades:")
            for t in report.trades:
                print(
                    f"    {t.closed_at:%Y-%m-%d %H:%M} {t.symbol:<8} {t.side:<5} "
                    f"{t.volume:>6.2f} {t.entry_price:>10.5f} -> {t.exit_price:>10.5f} "
                    f"{t.pnl:>+10.2f}  {t.reason}"
                )
    return 0


def _run_session(args, cfg, mode: str) -> int:
    """Start the broker, watchers and runner for a paper or live session."""
    broker, feed, extra = _build_runtime(cfg, args.config, getattr(args, "data", None))
    snapshots = _build_snapshots(cfg)
    interfaces = build_interfaces(
        cfg, snapshot_dir=str(snapshots.directory) if snapshots else None
    )
    journal = Journal(cfg.engine.journal_path)
    journal.start_run(mode, broker.name)

    runner = Runner(
        cfg, broker, feed,
        journal=journal,
        snapshots=snapshots,
        control=interfaces.control,
        status_sinks=interfaces.status_sinks,
        max_iterations=args.iterations,
    )
    interfaces.attach(runner.engine)
    runner.install_signal_handlers()

    if interfaces.enabled:
        print("watching via: " + ", ".join(interfaces.enabled))
    try:
        interfaces.start()
        runner.run()
    finally:
        # Watchers stop first so the final "stopped" alert is still delivered.
        interfaces.stop()
        journal.close()
        broker.disconnect()
        if extra:
            extra.disconnect()
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if cfg.engine.mode == "live":
        print("config says mode='live'; use `tbot live` for that", file=sys.stderr)
        return 2
    return _run_session(args, cfg, "paper")


def cmd_live(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if cfg.engine.mode != "live":
        print(f"config mode is '{cfg.engine.mode}', not 'live'", file=sys.stderr)
        return 2
    if not args.yes:
        print(
            "live trading sends real orders. Re-run with --yes to confirm.\n"
            "Recommended first: `tbot backtest`, then `tbot paper` on the same config.",
            file=sys.stderr,
        )
        return 2
    return _run_session(args, cfg, "live")


def cmd_telegram_setup(args: argparse.Namespace) -> int:
    """Verify a bot token and discover the chat id to put in the config."""
    token = args.token or os.environ.get("TBOT_TELEGRAM_TOKEN", "")
    if not token:
        print(
            "No token. Create a bot by messaging @BotFather on Telegram (/newbot),\n"
            "then pass it here:  tbot telegram-setup --token 123456:ABC-DEF...",
            file=sys.stderr,
        )
        return 2
    client = TelegramClient(token, timeout=15.0)
    me = client.me()
    print(f"bot: @{me.get('username', '?')} ({me.get('first_name', '')})")
    print(f"\nNow send any message to @{me.get('username', '?')} from Telegram.")
    print(f"Waiting up to {args.wait:.0f}s...")

    chat_id = discover_chat_id(token, wait_seconds=args.wait)
    if chat_id is None:
        print("\nNo message received. Run it again and send the bot a message.",
              file=sys.stderr)
        return 1

    print(f"\nchat id: {chat_id}")
    print("\nPut this in config/credentials.toml (gitignored):\n")
    print("[telegram]")
    print(f'token = "{token}"')
    print(f'chat_id = "{chat_id}"')
    print("\nand enable it in config/bot.toml:\n")
    print("[telegram]\nenabled = true")
    return 0

def cmd_specs(args: argparse.Namespace) -> int:
    cfg = _load(args)
    symbols = args.symbols or [s.symbol for s in cfg.active_symbols]
    broker = build_broker("mt5", credentials=load_credentials(args.credentials))
    broker.connect()
    lines = ["# captured from the live broker -- do not hand-edit", ""]
    try:
        for sym in symbols:
            spec = broker.symbol_spec(sym)
            derived = spec.tick_value / spec.tick_size if spec.tick_size else 0.0
            flag = ""
            if spec.money_per_price_unit and derived:
                ratio = spec.money_per_price_unit / derived
                if abs(ratio - 1.0) > 0.01:
                    flag = f"  <- broker says {ratio:.0f}x the tick_value derivation"
            print(
                f"{spec.name:<10} digits={spec.digits} point={spec.point} "
                f"tick_size={spec.tick_size} tick_value={spec.tick_value} "
                f"vol={spec.volume_min}/{spec.volume_step}/{spec.volume_max} "
                f"contract={spec.contract_size} "
                f"per_price_unit={spec.value_per_price_unit:,.2f}{flag}"
            )
            lines += [
                f"[symbols.{spec.name}]",
                f"digits = {spec.digits}",
                f"point = {spec.point}",
                f"tick_size = {spec.tick_size}",
                f"tick_value = {spec.tick_value}",
                f"volume_min = {spec.volume_min}",
                f"volume_step = {spec.volume_step}",
                f"volume_max = {spec.volume_max}",
                f"contract_size = {spec.contract_size}",
            ]
            if spec.money_per_price_unit is not None:
                lines += [
                    "# What 1.0 lot earns per 1.0 of price movement, as the broker",
                    "# itself calculates it. Authoritative: tick_value/tick_size is",
                    "# wrong by 10x on this server's gold.",
                    f"money_per_price_unit = {spec.money_per_price_unit}",
                ]
            lines.append("")
    finally:
        broker.disconnect()
    if args.save:
        Path(args.save).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {args.save}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Inspect what MetaTrader 5 is currently publishing about market structure."""
    cfg = _load(args)
    if not cfg.snapshot.enabled and not args.force:
        print(
            "[snapshot].enabled is false in the config. Set it to true, or pass "
            "--force to inspect anyway.",
            file=sys.stderr,
        )
        return 2

    store = SnapshotStore.from_settings(
        folder=cfg.snapshot.folder,
        common_path=cfg.snapshot.common_path,
        timeframe=cfg.snapshot.timeframe or cfg.engine.timeframe,
        max_age_minutes=cfg.snapshot.max_age_minutes,
        broker_utc_offset_hours=cfg.engine.broker_utc_offset_hours,
    )
    now = datetime.now(timezone.utc)
    print(f"folder      {store.directory}")
    print(f"timeframe   {store.timeframe}")
    print(f"max age     {store.max_age}")
    print(f"broker UTC  {cfg.engine.broker_utc_offset_hours:+.1f}h")
    if not store.directory.is_dir():
        print(
            "\nfolder does not exist. In MT5: File -> Open Data Folder is the *terminal* "
            "folder;\nthe export writes to the shared Common folder instead. Attach "
            "SMC_Snapshot_Export.mq5\nto a chart and check its Experts log for the path "
            "it prints.",
            file=sys.stderr,
        )
        return 1

    found = store.discover()
    print(f"files       {len(found)} snapshot(s) present")
    print()

    for scfg in cfg.active_symbols:
        print(store.status_line(scfg.symbol, now))

    if not args.symbol:
        if found:
            print("\npublished files:")
            for p in found:
                print(f"  {p.name}")
        return 0

    # Detailed view of one symbol.
    snapshot = store.get(args.symbol)
    if snapshot is None:
        print(f"\nno readable snapshot for {args.symbol}", file=sys.stderr)
        return 1

    print(f"\n{snapshot.symbol} {snapshot.timeframe} -- {snapshot.status}")
    print(f"  library     {snapshot.library_version} (schema {snapshot.schema_version})")
    print(f"  as of       {snapshot.as_of_broker} broker = {snapshot.as_of} UTC")
    print(f"  bias        {snapshot.bias()}")
    for problem in snapshot.problems():
        print(f"  ! {problem}")

    print("\n  modules:")
    for module in snapshot.modules:
        flag = " truncated" if module.truncated else ""
        note = f"  {module.message}" if module.message else ""
        print(f"    {module.concept:<20} {module.status:<10}{flag}{note}")

    records = snapshot.records
    if args.concept:
        wanted = args.concept.upper()
        records = tuple(r for r in records if r.concept == wanted)
    if args.active:
        records = tuple(r for r in records if r.active)

    print(f"\n  records ({len(records)} shown of {len(snapshot.records)}):")
    print(f"    {'id':<22} {'concept':<18} {'dir':<8} {'state':<12} "
          f"{'lower':>12} {'upper':>12}  act")
    for r in sorted(records, key=lambda r: (r.concept, r.id))[: args.limit]:
        print(
            f"    {r.id[:22]:<22} {r.concept:<18} {r.direction:<8} {r.state[:12]:<12} "
            f"{r.lower:>12.5f} {r.upper:>12.5f}  {'y' if r.active else 'n'}"
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check the environment end to end and say exactly what is missing.

    Written for a first run: this project has been developed without a Python
    interpreter available, so the first thing anyone does with it should be to
    find out what actually works here.
    """
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    # --- interpreter -------------------------------------------------- #
    v = sys.version_info
    check(
        "python >= 3.11",
        v >= (3, 11),
        f"{v.major}.{v.minor}.{v.micro} ({'64-bit' if sys.maxsize > 2**32 else '32-bit'})",
    )
    if v >= (3, 13):
        check(
            "python <= 3.12 for MetaTrader5",
            False,
            "MetaTrader5 lags new releases; 3.11 or 3.12 is the safe choice",
        )

    # --- config -------------------------------------------------------- #
    cfg = None
    try:
        cfg = load_config(args.config)
        check("config loads", True, f"{args.config}: {len(cfg.active_symbols)} symbol(s) enabled")
    except (ConfigError, FileNotFoundError) as exc:
        check("config loads", False, str(exc))

    if cfg is not None:
        try:
            for scfg in cfg.active_symbols:
                create(scfg, DEFAULT_SPECS.get(scfg.symbol) or next(iter(DEFAULT_SPECS.values())))
            check("strategies build", True, ", ".join(s.strategy for s in cfg.active_symbols))
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            check("strategies build", False, str(exc))

        try:
            for scfg in cfg.active_symbols:
                ExitManager.from_config(scfg.exits)
            check("exit policies build", True, "")
        except ConfigError as exc:
            check("exit policies build", False, str(exc))

    # --- MetaTrader 5 -------------------------------------------------- #
    try:
        import MetaTrader5  # noqa: F401

        check("MetaTrader5 package", True, "installed")
    except ImportError:
        needed = cfg is not None and (cfg.engine.mode == "live" or cfg.engine.broker == "mt5")
        check(
            "MetaTrader5 package",
            not needed,
            "not installed -- required for live data/orders (pip install MetaTrader5)",
        )

    # --- structure snapshots ------------------------------------------- #
    if cfg is not None and cfg.snapshot.enabled:
        try:
            store = _build_snapshots(cfg)
            assert store is not None
            found = store.discover()
            check(
                "MT5 snapshot folder",
                store.directory.is_dir(),
                f"{store.directory} ({len(found)} file(s))",
            )
            for scfg in cfg.active_symbols:
                snap = store.get(scfg.symbol)
                check(
                    f"snapshot {scfg.symbol}",
                    snap is not None,
                    f"{snap.status}, {sum(snap.counts().values())} active records"
                    if snap
                    else f"missing: {store.path_for(scfg.symbol)}",
                )
        except SnapshotError as exc:
            check("MT5 snapshot folder", False, str(exc))
    elif cfg is not None:
        check("MT5 snapshots", True, "disabled in config (ICT gates will reject)")

    # --- journal -------------------------------------------------------- #
    if cfg is not None:
        try:
            journal = Journal(cfg.engine.journal_path)
            journal.conn.execute("SELECT 1")
            journal.conn.close()
            check("journal writable", True, cfg.engine.journal_path)
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            check("journal writable", False, str(exc))

    # --- watchers -------------------------------------------------------- #
    if cfg is not None and cfg.dashboard.enabled:
        import socket

        with socket.socket() as probe:
            free = probe.connect_ex((cfg.dashboard.host, cfg.dashboard.port)) != 0
        check(
            f"dashboard port {cfg.dashboard.port}",
            free,
            "available" if free else "already in use -- change [dashboard].port",
        )

    if cfg is not None and cfg.telegram.enabled:
        if not cfg.telegram.token:
            check("telegram token", False, "missing -- run `tbot telegram-setup`")
        else:
            try:
                me = TelegramClient(cfg.telegram.token, timeout=10.0).me()
                check("telegram bot", True, f"@{me.get('username', '?')}")
            except TelegramError as exc:
                check("telegram bot", False, str(exc))

    # --- report ---------------------------------------------------------- #
    width = max(len(name) for name, _, _ in checks)
    failures = 0
    for name, ok, detail in checks:
        mark = "ok  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{mark}] {name.ljust(width)}  {detail}")

    print()
    if failures:
        print(f"{failures} check(s) need attention before running.")
    else:
        print("All checks passed. Next: `pytest`, then `tbot backtest`.")
    return 1 if failures else 0

def cmd_report(args: argparse.Namespace) -> int:
    journal = Journal(args.journal)
    stats = journal.stats(args.run)
    print(f"journal     {args.journal}")
    print(f"trades      {stats['trades']} ({stats['wins']} wins, {stats['win_rate']:.1f}%)")
    print(f"net pnl     {stats['net_pnl']:+,.2f}")
    rejections = journal.rejection_counts(args.run)
    if rejections:
        print("\nwhy signals were declined:")
        for symbol, reason, n in rejections[:15]:
            print(f"  {n:>5}x  {symbol:<8} {reason[:90]}")
    journal.close()
    return 0


def cmd_defaults(args: argparse.Namespace) -> int:
    print("built-in simulated specs (used when no --specs file is given):")
    for name, s in DEFAULT_SPECS.items():
        print(
            f"  {name:<8} digits={s.digits} point={s.point} tick_value={s.tick_value} "
            f"value/price-unit={s.value_per_price_unit:,.2f}"
        )
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tbot", description="Modular trading bot")
    p.add_argument("--version", action="version", version=f"tbot {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def with_config(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="path to bot.toml")
        return sp

    with_config(sub.add_parser("validate", help="validate config, show risk budgets")).set_defaults(
        func=cmd_validate
    )
    sub.add_parser("strategies", help="list strategies and filters").set_defaults(
        func=cmd_strategies
    )

    bt = with_config(sub.add_parser("backtest", help="replay CSV bars"))
    bt.add_argument("--data", default="data", help="directory of SYMBOL_TF.csv files")
    bt.add_argument("--symbol", help="restrict to one symbol")
    bt.add_argument("--bars", type=int, default=0, help="use only the last N bars (0 = all)")
    bt.add_argument("--specs", help="TOML of real broker specs (see `tbot specs --save`)")
    bt.add_argument("--journal", help="write signals/trades to this sqlite file")
    bt.add_argument("--trades", action="store_true", help="print every closed trade")
    bt.add_argument("--json", action="store_true", help="machine-readable metrics")
    bt.set_defaults(func=cmd_backtest)

    pa = with_config(sub.add_parser("paper", help="simulated fills on live or CSV bars"))
    pa.add_argument("--data", help="CSV directory when no MT5 data source is configured")
    pa.add_argument("--iterations", type=int, default=0, help="stop after N polls (0 = forever)")
    pa.set_defaults(func=cmd_paper)

    lv = with_config(sub.add_parser("live", help="REAL orders through MetaTrader 5"))
    lv.add_argument("--yes", action="store_true", help="acknowledge that orders are real")
    lv.add_argument("--iterations", type=int, default=0)
    lv.set_defaults(func=cmd_live)

    sp = with_config(sub.add_parser("specs", help="capture broker contract specs"))
    sp.add_argument("--symbols", nargs="*", help="symbols (default: enabled ones)")
    sp.add_argument("--credentials", help="TOML file with an [mt5] table")
    sp.add_argument("--save", help="write the specs to this TOML file")
    sp.set_defaults(func=cmd_specs)

    sn = with_config(sub.add_parser("snapshot", help="inspect MT5's SMC/ICT snapshots"))
    sn.add_argument("--symbol", help="show full detail for one symbol")
    sn.add_argument("--concept", help="restrict detail to one concept, e.g. ORDER_BLOCK")
    sn.add_argument("--active", action="store_true", help="only active records")
    sn.add_argument("--limit", type=int, default=40, help="max records to print")
    sn.add_argument("--force", action="store_true", help="inspect even when disabled")
    sn.set_defaults(func=cmd_snapshot)

    with_config(sub.add_parser("doctor", help="check the environment end to end")).set_defaults(
        func=cmd_doctor
    )

    ts = sub.add_parser("telegram-setup", help="verify a bot token, find your chat id")
    ts.add_argument("--token", help="bot token from @BotFather (or TBOT_TELEGRAM_TOKEN)")
    ts.add_argument("--wait", type=float, default=60.0, help="seconds to wait for a message")
    ts.set_defaults(func=cmd_telegram_setup)

    rp = sub.add_parser("report", help="summarise a journal database")
    rp.add_argument("--journal", default="data/journal.sqlite")
    rp.add_argument("--run", type=int, help="restrict to one run id")
    rp.set_defaults(func=cmd_report)

    sub.add_parser("simspecs", help="show the built-in simulated specs").set_defaults(
        func=cmd_defaults
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (
        ConfigError, BrokerError, SnapshotError, TelegramError, FileNotFoundError, ValueError
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
