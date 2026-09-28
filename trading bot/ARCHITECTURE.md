# Architecture

## 1. Layering

Dependencies point one way only. Each layer may import from the ones above it in
this list, never below.

| layer | package | knows about | knows nothing about |
|---|---|---|---|
| domain core | `core/` | numbers, bars, signals | files, brokers, config |
| configuration | `config/` | TOML, dataclasses | strategies, brokers |
| strategy | `strategy/` | bars, indicators, filters | orders, brokers, money |
| risk | `risk/` | specs, signals, account | strategies, data sources |
| broker port | `broker/base.py` | orders, positions, specs | which broker is in use |
| adapters | `broker/paper.py`, `broker/mt5.py` | one venue each | strategies, config |
| data | `data/` | bar sourcing | order routing |
| engine | `engine/` | all of the above | UI |
| persistence | `journal/`, `obs/` | rows and log lines | decisions |
| entry point | `cli.py` | wiring | trading rules |

`core/` has zero imports outside the standard library. That is what makes
indicator and state-machine tests instant and hermetic.

## 2. The pipeline

```
          ┌─ data/feed.py ────────────────┐
          │ CsvFeed | BrokerFeed | List   │
          └──────────────┬────────────────┘
                         │ list[Bar]
                 ┌───────▼─────────┐
                 │ SymbolRuntime   │  strategy.compute(bars) → named series
                 └───────┬─────────┘
                         │ BarContext(i)
                 ┌───────▼─────────┐
                 │ Strategy        │  FilterChain → Phase machine → Signal | None
                 └───────┬─────────┘
                         │ Signal
                 ┌───────▼─────────┐
                 │ RiskManager     │  budget · caps · min RR · daily stop → volume
                 └───────┬─────────┘
                         │ OrderRequest
                 ┌───────▼─────────┐
                 │ Broker (port)   │  PaperBroker | MT5Broker
                 └───────┬─────────┘
                         │ OrderResult / ClosedTrade
                 ┌───────▼─────────┐
                 │ Journal + logs  │  sqlite rows + JSONL events
                 └─────────────────┘
```

`engine/core.py::TradeEngine.step()` is the only implementation of that
sequence. `engine/backtest.py` drives it over a merged multi-symbol timeline;
`engine/runner.py` drives it once per newly closed bar per symbol. Neither
contains trading logic of its own.

## 3. Decisions worth defending

**Strategies are pure functions of bar history.** `on_bar(ctx) -> Signal | None`
returns a *proposal*. It cannot size a position, cannot place an order, and
cannot know the account balance. Position sizing and permission live entirely in
`risk/`, which means "why was this trade this size?" has exactly one answer.

**Config is declarative and validated.** Unknown keys raise `ConfigError` at
startup. A strategy declares its parameters in `defaults`; a filter declares its
options the same way. Nothing is inferred by parsing source code.

**One state machine, made explicit.** `Phase` (SCANNING → ARMED → WINDOW →
COOLDOWN) plus recorded transitions replace a scatter of boolean flags. Each
transition is appended to `strategy.transitions` with the bar index, timestamp
and reason, so a session can be explained after the fact.

**Filters are objects, not branches.** Each returns a `Decision` carrying the
numbers it judged on. `FilterChain.evaluate` stops at the first failure and
reports the full trace, which is written to the journal — so the tuning question
"what is actually rejecting my trades?" is a SQL query (`tbot report`), not a
log-grep session.

**Sizing comes from the broker.** `SymbolSpec.value_per_price_unit` is derived
from `tick_value / tick_size`. Hardcoded pip tables are wrong by 10x on JPY
crosses and by ~100x on silver; that class of bug only surfaces with real money
at stake. If the minimum volume exceeds the budget, sizing fails closed.

**Total risk is fixed, not per-symbol.** Weights are renormalised across enabled
symbols, so `risk_per_trade_pct` caps simultaneous exposure. Disabling a symbol
redistributes its budget instead of shrinking deployed risk.

**The simulator is pessimistic.** Fills take half the spread plus slippage; a
bar that touches both stop and target resolves as the **stop**, because OHLC
cannot reveal intrabar sequence. Optimistic simulators manufacture confidence.

**Every signal is persisted, including rejected ones.** After a bad month, the
question that matters is what the bot *declined* to do and why.

**Single-threaded.** One thread owns all strategy state. Any UI reads
`TradeEngine.state()`; it never mutates.

## 4. Failure modes and how they are handled

| failure | behaviour |
|---|---|
| indicator not warmed up | filters fail closed; `on_bar` returns `None` before `warmup` |
| feed error mid-session | logged, counted, that symbol is skipped this poll, loop continues |
| same bar polled twice | timestamp check in `Runner`; no double entry |
| broker rejects order | `OrderResult.ok = False`, logged with retcode, no state corruption |
| unsupported filling mode | `_filling_mode` picks from the symbol's advertised modes |
| stop on the wrong side of the fill | order rejected before it is sent |
| broker closed a position | `reconcile_live_positions` diffs tickets, attributes balance delta |
| daily loss breached | `RiskManager` halts for the rest of the UTC day; clears on day roll |
| DST / server-time drift | one setting, `broker_utc_offset_hours`, applied at ingest; sessions are UTC |

## 5. Where to extend

* **New strategy** — subclass `Strategy`, `@register`, import in
  `strategy/__init__.py`, point a symbol TOML at it.
* **New filter** — subclass `Filter`, `@register`, use it as `[filters.<name>]`.
* **New venue** — implement the eight methods of `Broker`; nothing above the port
  changes.
* **Richer exits** — add an exit-policy object consulted per bar for open
  positions in `TradeEngine.step()`; keep it out of the entry state machine.
* **Read-only UI** — poll `TradeEngine.state()` and the journal; do not move
  decisions into it.

---

# Appendix: the reference system this was designed against

Source: `github.com/ilahuerta-IA/mt5_live_trading_bot` (analysed at commit
`30ad91b`, 2025-12-21: 30,778 lines of Python across 36 files, plus 86 markdown
documents).

## What is in that repository

**Entry point — `advanced_mt5_monitor_gui.py`, 4,611 lines, one class
(`AdvancedMT5TradingMonitorGUI`) with 72 methods.** It is simultaneously the
Tkinter UI, the MT5 connection manager, the indicator engine, the six filter
validators (`_validate_atr_filter`, `_validate_angle_filter`,
`_validate_price_filter`, `_validate_candle_direction`, `_validate_ema_ordering`,
`_validate_time_filter`), the four-phase state machine
(`determine_strategy_phase` at ~690 lines, `_phase3_open_breakout_window`,
`_phase4_monitor_window`), the position sizer, the order router
(`execute_trade`), the chart renderer, the log viewer and the state persister.

**`strategies/` — eight files, 1,748–3,321 lines each, ~22,100 lines total.**
One per symbol (EURUSD, GBPUSD, XAUUSD, AUDUSD, XAGUSD, USDCHF, EURJPY, USDJPY),
each a near-duplicate `SunriseOgle(bt.Strategy)` Backtrader class differing
mainly in the numbers inside `params = dict(...)`. The repository's own
`STRATEGY_FILES_POLICY.md` marks them READ-ONLY to protect backtest fidelity.

**`src/` — a second, parallel implementation.** `mt5_live_trading_connector.py`
(693 lines: `TradingLogger`, `MT5Connection`, `PositionManager`,
`SunriseMT5Trader`) and `sunrise_signal_adapter.py` (495 lines:
`TradingSignal`, `SunriseSignalGenerator`, `MultiSymbolSignalManager`,
`MT5DataProvider`) form a headless pipeline the GUI does not use — the GUI
reimplements all of it.

**`testing/` — ten standalone scripts** (`test_setup.py`, `test_mt5_order.py`,
`check_broker_specs.py`, `test_position_sizing.py`, `verify_all_symbols.py`, …)
run by hand; most require a connected terminal and one places live orders.
There is no pytest suite and no assertion-based CI.

**`docs/` — ~90 markdown files**, the majority named for individual bugs
(`BUG_FIX_INDEX_VS_TIMESTAMP.md`, `CRITICAL_POSITION_SIZING_FIX.md`,
`PULLBACK_COUNT_BUG_FIX.md`, `GLOBAL_INVALIDATION_FIX.md`, …), plus
`DALIO_ALLOCATION_SYSTEM.md` describing an eight-asset weighting scheme
(XAUUSD 18%, USDCHF/AUDUSD 15%, GBPUSD 13%, EURUSD/XAGUSD 12%, USDJPY 8%,
EURJPY 7%) that caps total portfolio risk at 1%.

Plus Windows batch/PowerShell scaffolding (`setup.ps1`, `run_bot.bat`,
`build_exe.bat`, `setup_autostart.bat`), a `MetaTrader5 + pandas + numpy +
matplotlib + mplfinance + backtrader` dependency set, and leftovers
(`temp_fix.py`, `fix_encoding.py`, `docs/archive/temp_strategy_diff.txt`).

## The ideas worth keeping

Three, and they are genuinely good:

1. **Weighted portfolio allocation** so simultaneous signals share one risk
   budget instead of multiplying it. Kept here as `weight` + renormalisation in
   `RiskManager.budget_for`.
2. **Broker-derived position sizing** via MT5 `trade_tick_value` rather than a
   pip table — the fix its `POSITION_SIZING_FIX_V2.md` documents. Kept as
   `SymbolSpec.value_per_price_unit`, with the additional rule that sizing fails
   rather than rounding up.
3. **A filter cascade plus a pullback/breakout state machine** as the entry
   model. Kept as `FilterChain` + the `Phase` machine in `ema_pullback`.

## The structural problems, and what replaced them

| in the reference | consequence | here |
|---|---|---|
| 4,611-line God class mixing UI, data, filters, state machine, sizing, routing | almost nothing can be unit-tested; UI and logic share mutable state | nine packages, strict layering, `TradeEngine.step()` as the only pipeline |
| **Parameters recovered by text-parsing the strategy source** (`parse_strategy_config`, `_extract_value`, `extract_bool_value`, `validate_critical_params`, `check_config_retry_needed`, `retry_load_config`) | a config change means editing a file marked READ-ONLY; parsing can silently yield wrong values, hence the retry-and-validate scaffolding | TOML → validated dataclasses; unknown keys are startup errors |
| Eight ~3,000-line near-duplicate strategy files | a fix must be applied eight times; the archived bug logs show fixes that reached some symbols only | one strategy implementation, eight ~30-line config files |
| Two unconnected pipelines (`src/` vs the GUI) | the untested path rots; the tested path is the one nobody runs | one pipeline, three modes |
| `MetaTrader5` imported throughout | cannot run, test, or CI without Windows + a terminal | one adapter behind `Broker`; core suite runs anywhere |
| Backtrader strategies for backtests, hand-written logic for live | live/backtest divergence is unverifiable — the reason a 1,500-line "MT5 vs Backtrader verification" document exists | same objects in both; the simulator is shared |
| Hand-run scripts as tests, some placing live orders | no regression safety net | pytest suite, hermetic, no broker required |
| Plain-text logs; bug history in ~90 markdown files | post-hoc analysis is regex archaeology | JSONL events + SQLite journal of every signal, rejection and trade |
| UI thread owning strategy state | display and logic can disagree | single-threaded engine; UI would be a reader |
| Broker server time handled ad hoc (UTC offset dropdown, several DST fix documents) | recurring timezone bugs | offset applied once at ingest; every session expressed in UTC |

## Honest comparison

The reference system does things this one does not: a live candlestick GUI with
EMA overlays and per-symbol phase display, eight tuned symbol configurations
with real backtested parameters, a PyInstaller build, Windows autostart, and
strategy logic refined against a lot of live observation. The `params` blocks in
its eight files encode real work; the strategies here ship with plausible
defaults, not validated ones.

What this project offers instead is a shape that can absorb that tuning safely:
the parameters can be transcribed into `config/symbols/*.toml`, and each one then
has a single place to live, a validator, a hermetic test, and a backtest that
exercises the same code the live loop runs.
