# tbot

A modular, broker-agnostic trading bot for MetaTrader 5 โ€” built so that the
strategy logic, the risk rules and the execution path can each be tested on
their own, on any machine, with no terminal running and no market open.

The core has **no third-party dependencies**: Python 3.11+ standard library
only. `MetaTrader5` is needed just for live data and live orders, and is
imported lazily in exactly one file.

```
bars โ’ indicators โ’ strategy โ’ risk gate โ’ broker โ’ journal
```

One pipeline, three modes: `backtest`, `paper`, `live`. They share the same
strategy objects, the same risk manager and the same fill logic, so a backtest
is a statement about the code that will actually trade.

---

## Quick start

```bash
# 0. check the environment first -- nothing here has ever been run
python -m tbot.cli doctor -c config/bot.toml

# 1. (optional) synthetic data so you can try the backtester straight away
python scripts/gen_sample_data.py --symbols EURUSD XAUUSD USDJPY --bars 6000

# 2. check the config and see the resolved risk budgets
python -m tbot.cli validate -c config/bot.toml

# 3. replay it
python -m tbot.cli backtest -c config/bot.toml --symbol EURUSD --trades

# 4. paper trade (simulated fills; CSV bars, or live MT5 bars if configured)
python -m tbot.cli paper -c config/bot.toml --data data
```

Installing the package (`pip install -e .`) adds a `tbot` entry point, so
`tbot validate` works in place of `python -m tbot.cli validate`.

### Going live

1. `pip install MetaTrader5`
2. Copy `config/credentials.example.toml` โ’ `config/credentials.toml`, or set
   `TBOT_MT5_LOGIN` / `TBOT_MT5_PASSWORD` / `TBOT_MT5_SERVER`.
3. Capture your broker's real contract specs and keep them for backtests:
   `tbot specs --save config/specs.toml`
4. Set `mode = "live"` and `broker = "mt5"` in `config/bot.toml`, and set
   `broker_utc_offset_hours` to your server's offset.
5. `tbot live -c config/bot.toml --yes` โ€” the `--yes` is mandatory; without it
   the command refuses to send real orders.

Use a demo account first. Then use it for longer than feels necessary.

---

## Commands

| command | purpose |
|---|---|
| `tbot validate` | validate config; print each symbol's risk budget and session |
| `tbot strategies` | list strategies and filters with every parameter and default |
| `tbot backtest` | replay CSV bars (`--symbol`, `--bars`, `--specs`, `--trades`, `--json`) |
| `tbot paper` | simulated fills on live or CSV bars |
| `tbot live` | real orders through MetaTrader 5 (requires `--yes`) |
| `tbot specs` | read contract specs from the broker, optionally save them as TOML |
| `tbot snapshot` | inspect the SMC/ICT structure snapshots MT5 is publishing |
| `tbot doctor` | check python, config, MT5, snapshots, journal and watchers |
| `tbot telegram-setup` | verify a Telegram bot token and find your chat id |
| `tbot report` | summarise a journal: trades, PnL, and why signals were declined |
| `tbot simspecs` | show the built-in simulated specs |

---

## Configuration

Strategy behaviour is **declared, not coded**. `config/bot.toml` holds engine
and risk settings; one file per symbol under `config/symbols/` holds the
strategy, its parameters, its filters and its session:

```toml
symbol = "EURUSD"
strategy = "ema_pullback"
weight = 3.0                   # relative risk weight
sides = ["LONG", "SHORT"]

[session]
start = "07:00"                # UTC, always
end   = "16:00"

[params]
ema_fast = 8
pullback_bars = 2
sl_atr = 2.5
tp_atr = 6.0

[filters.atr_range]
min = 0.0002
max = 0.0020

[filters.angle]
min_degrees = 15.0
```

Unknown keys are a **startup error**, not a silent no-op โ€” a typo in
`pullback_bars` can otherwise cost you a live session's worth of trades.
Run `tbot strategies` to see every legal parameter and filter option.

Deploy-time switches can come from the environment: `TBOT_MODE`,
`TBOT_BROKER`, `TBOT_TIMEFRAME`, `TBOT_BROKER_UTC_OFFSET_HOURS`.

### Risk model

`risk_per_trade_pct` is the **total** risk, split across symbols by weight and
renormalised over the enabled ones. Four symbols signalling on the same bar
still risk 1% between them, not 4%. Lot size always comes from the broker's own
`tick_value`/`tick_size`; if the minimum volume would exceed the budget, the
trade is **declined** rather than rounded up.

Other gates: `max_daily_loss_pct` (kill-switch for the UTC day),
`max_open_positions`, `max_positions_per_symbol`, and `min_rr`.

---

## Layout

```
src/tbot/
  core/        Bar, Signal, SymbolSpec, Decision + pure-python indicators
  config/      TOML โ’ validated dataclasses (rejects unknown keys)
  strategy/    Strategy base + registry, composable filters,
               ema_pullback (crossover โ’ pullback โ’ breakout window),
               ict_confluence (MT5 structure: zone entry, structural stop),
               ict_filters (bias, killzone, zone, liquidity, premium/discount),
               donchian (third strategy, proves the engine is generic)
  risk/        sizing from broker ticks, portfolio budgets and caps
  broker/      Broker port; paper simulator; MT5 adapter (lazy import)
  data/        bar feeds (CSV, broker, in-memory) and MT5 SMC/ICT snapshots
  engine/      the one pipeline (core.py), exits, events, replay, loop (runner.py)
  interfaces/  dashboard, Telegram, MT5 chart overlay -- all read-only watchers
  journal/     SQLite: every signal, trade, rejection reason, equity point
  obs/         JSONL structured logs + a readable console stream
  cli.py       entry points
config/        bot.toml + symbols/*.toml
tests/         pytest suite; no MT5, no network, no market needed
scripts/       synthetic data generator
```

Layers only import downward. `core/` imports nothing; `strategy/` never touches
a broker; only `broker/mt5.py` knows MetaTrader exists.

---

## Letting MetaTrader 5 do the analysis

`tbot` does not re-implement Smart Money Concepts in Python. The MIT-licensed
[SMC/ICT library](https://github.com/xxvw/ICT_Library_MQ5) runs *inside* MT5,
detects structure on closed candles โ€” order blocks, FVGs, BOS/CHoCH, liquidity,
killzones, displacement, MSS, SMT, PO3 โ€” and publishes a schema-versioned JSON
snapshot. `tbot` reads that file, so the bot trades exactly what your chart
draws, with no second implementation to drift out of agreement.

```toml
[snapshot]
enabled = true
folder = "SMC_Export"      # must match the export EA's InpFolder
```

```bash
tbot snapshot -c config/bot.toml                    # health of every symbol
tbot snapshot -c config/bot.toml --symbol EURUSD    # modules and every record
```

Snapshot timestamps are broker wall-clock with no timezone; they are converted
to UTC with the same `broker_utc_offset_hours` used for bars. A snapshot that is
missing, degraded or older than `max_age_minutes` is dropped with a warning โ€”
stale structure is worse than none, because it looks authoritative while
describing a market that has moved.

Setup, troubleshooting and the timezone trap: **[docs/MT5_SNAPSHOT_SETUP.md](docs/MT5_SNAPSHOT_SETUP.md)**.

Strategies receive it as `ctx.snapshot` (`None` when unavailable โ€” gates that
depend on it fail closed). The `ict_confluence` strategy and the `ict_*` filters
trade on it: see **[docs/ICT_STRATEGY.md](docs/ICT_STRATEGY.md)**.

---

## Watching and controlling it

Three read-only views plus one narrow control path, all on the standard library
โ€” no FastAPI, no Redis, no Node.

```toml
[dashboard]                     # http://127.0.0.1:8787 โ€” loopback only
enabled = true

[telegram]                      # alerts on your phone, plus remote commands
enabled = true                  # token/chat_id go in credentials.toml

[overlay]                       # draws the bot's trades on your MT5 chart
enabled = true
```

Telegram accepts `/status`, `/positions`, `/pause`, `/resume`, `/closeall` and
`/stop`, restricted to your chat id โ€” anyone else gets no reply at all. Commands
only set flags; the trading thread reads them and acts on them itself, so there
is still exactly one thread touching positions. A watcher that fails, hangs or
cannot be constructed is logged and skipped: losing the dashboard is an
inconvenience, refusing to trade because of it would be a bug.

Setup, including `tbot telegram-setup` and installing `mql5/Indicators/TbotOverlay.mq5`:
**[docs/WATCHING_THE_BOT.md](docs/WATCHING_THE_BOT.md)**.
- [Running it on another computer](docs/SECOND_MACHINE.md) - moving it to a second PC, and why not to run both at once

---

## Adding a strategy

```python
from tbot.strategy.base import Strategy, register

@register
class MyStrategy(Strategy):
    name = "my_strategy"
    defaults = {"lookback": 20, "sl_atr": 2.0}

    @property
    def warmup(self) -> int: ...
    def compute(self, bars): ...      # named indicator series
    def on_bar(self, ctx): ...        # return a Signal or None
```

Import it in `strategy/__init__.py`, then point a symbol file at it with
`strategy = "my_strategy"`. No engine, risk or broker code changes.

---

## Testing

```bash
pip install pytest
pytest
```

The suite covers indicator maths against hand-computed values, filter
pass/reject in both directions, state-machine properties (arm, pull back, break
out, invalidate, cool down), sizing (including the metals case that hardcoded
pip tables get wrong), the simulator's fill and stop/target rules, the risk
gate, and two end-to-end backtests through the journal. Nothing in it requires
MetaTrader 5, so it runs in CI on Linux.

**Status: 306 tests, all passing on Python 3.12.** `ruff check` is clean, and
`tbot backtest` runs the full pipeline end to end on synthetic data.

The suite was written before an interpreter was available; its first run found
nine failures, three of them real bugs (a sign error in `Record.distance_to`, a
rejection reason wiped the instant it was set, and a price path that could never
arm a short). A first live backtest then found a fourth: an event payload field
colliding with `EventBus.publish`'s own parameter.

New checkout? Start with **[docs/FIRST_RUN.md](docs/FIRST_RUN.md)** and
`tbot doctor`, which checks the interpreter, config, strategies, exit policies,
MetaTrader5, the snapshot folder, the journal and the watchers in one pass.

---

## Deliberate omissions

* **No trading logic in any UI.** The dashboard and the chart overlay are
  strictly read-only; Telegram commands set flags the trading thread acts on
  itself. Trading logic living inside a widget callback is untestable and
  cannot run headless.
* **No pending orders.** Entries are market orders at bar close. Resting a
  limit inside a zone -- how ICT setups are usually traded by hand -- needs
  order-state tracking the engine does not have yet.
* **Live PnL attribution is approximate.** Closed-position reconciliation diffs
  ticket sets between polls and attributes the balance delta, which keeps the
  daily kill-switch correct but does not read MT5 deal history per trade.
* **Single timeframe per symbol.** Multi-timeframe confirmation would need a
  second feed per symbol in `BarContext`.

## Risk warning

This software places real orders when you tell it to. Backtest results โ€” on
synthetic data especially โ€” say nothing about future performance. Run on a demo
account, understand every parameter you change, and never risk money you cannot
afford to lose.

MIT licensed.
