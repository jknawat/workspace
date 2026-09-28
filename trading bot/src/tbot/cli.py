"""Command line interface (argparse, stdlib only).

    tbot validate     check config and print the resolved risk budgets
    tbot strategies   list strategies, filters and their parameters
    tbot backtest     replay CSV bars through the real pipeline
    tbot paper        live/replay bars, simulated fills
    tbot live         real orders (requires an explicit acknowledgement flag)
    tbot specs        capture broker contract specs into a TOML file
    tbot report       summarise a journal database

Design choice: the CLI is the only entry point, and a GUI -- if one is ever
added -- is a *reader* of the journal and of ``TradeEngine.state()``. Making the
UI the application, as MT5 monitor bots typically do, is what makes those bots
untestable and unrunnable headless.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .broker import DEFAULT_SPECS, PaperBroker, build as build_broker
from .broker.base import Broker, BrokerError
from .config import ConfigError, load_config, load_credentials
from .config.models import BotConfig
from .core.types import SymbolSpec
from .data.feed import BarFeed, BrokerFeed, CsvFeed
from .engine import Runner, run_backtest
from .journal import Journal
from .obs import log as obs_log
from .strategy import available as available_strategies, get as get_strategy
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


def cmd_strategies(args: argparse.Namespace) -> int:
    print("strategies:")
    for name in available_strategies():
        cls = get_strategy(name)
        print(f"\n  {name}  ({cls.__module__})")
        doc = (cls.__doc__ or "").strip().splitlines()
        if doc:
            print(f"    {doc[0]}")
        for key, value in cls.defaults.items():
            print(f"      {key:<26} = {value!r}")
    print("\nfilters (declare under [filters.<name>] in a symbol file):")
    from .strategy import filters as f

    for name in available_filters():
        cls = f._REGISTRY[name]  # noqa: SLF001 - introspection for the help output
        print(f"\n  {name}")
        doc = (cls.__doc__ or "").strip().splitlines()
        if doc:
            print(f"    {doc[0]}")
        for key, value in cls.defaults.items():
            print(f"      {key:<26} = {value!r}")
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


def cmd_paper(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if cfg.engine.mode == "live":
        print("config says mode='live'; use `tbot live` for that", file=sys.stderr)
        return 2
    broker, feed, extra = _build_runtime(cfg, args.config, args.data)
    journal = Journal(cfg.engine.journal_path)
    journal.start_run("paper", broker.name)
    runner = Runner(cfg, broker, feed, journal=journal, max_iterations=args.iterations)
    runner.install_signal_handlers()
    try:
        runner.run()
    finally:
        journal.close()
        broker.disconnect()
        if extra:
            extra.disconnect()
    return 0


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
    broker, feed, extra = _build_runtime(cfg, args.config, None)
    journal = Journal(cfg.engine.journal_path)
    journal.start_run("live", broker.name)
    runner = Runner(cfg, broker, feed, journal=journal, max_iterations=args.iterations)
    runner.install_signal_handlers()
    try:
        runner.run()
    finally:
        journal.close()
        broker.disconnect()
        if extra:
            extra.disconnect()
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
            print(
                f"{spec.name:<10} digits={spec.digits} point={spec.point} "
                f"tick_size={spec.tick_size} tick_value={spec.tick_value} "
                f"vol={spec.volume_min}/{spec.volume_step}/{spec.volume_max} "
                f"contract={spec.contract_size}"
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
                "",
            ]
    finally:
        broker.disconnect()
    if args.save:
        Path(args.save).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {args.save}")
    return 0


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
    except (ConfigError, BrokerError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
