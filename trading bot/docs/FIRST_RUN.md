# First run

**Nothing in this repository has ever been executed.** It was built on a machine
with no Python interpreter, so roughly 400 tests exist and none have run. That
is not a disclaimer to skim past — it is the single most important fact about
the current state, and working through this page is how it stops being true.

Expect the first `pytest` run to fail somewhere. Every failure is a real
finding: either the code is wrong or a test's expectation is. Both are worth
knowing, and both are cheap to fix now.

---

## 1. Install Python

**Python 3.11 or 3.12, 64-bit, from [python.org](https://www.python.org/downloads/).**

* Not 3.13+ — the `MetaTrader5` package lags new releases.
* Not the Microsoft Store build — that is the stub currently on this machine.
* Tick **"Add python.exe to PATH"** in the installer.

```powershell
python --version      # expect 3.11.x or 3.12.x
```

## 2. Set the project up

```powershell
cd "C:\workspace\jk\trading bot"
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

That installs pytest, ruff and mypy. The bot itself needs nothing.

## 3. Check the environment

```powershell
tbot doctor
```

It reports on the interpreter, config, strategies, exit policies, the
MetaTrader5 package, snapshot folder, journal and watchers — and names what is
missing. Fix anything marked `FAIL` before going further.

## 4. Run the tests

```powershell
pytest
```

Work through the failures. Useful flags:

```powershell
pytest -x                    # stop at the first failure
pytest tests/test_sizing.py  # one file
pytest -k trailing -vv       # one topic, verbose
ruff check src tests         # lint
```

Suggested order if many fail at once: `test_indicators` → `test_sizing` →
`test_config` → `test_snapshot` → everything else. The first three have no
dependencies on the rest, so a failure there is almost certainly a genuine bug
rather than a knock-on effect.

## 5. Try a backtest

```powershell
python scripts\gen_sample_data.py --symbols EURUSD --bars 6000
tbot validate
tbot backtest --symbol EURUSD --trades
```

The data is synthetic and seeded — good for proving the plumbing works, useless
as evidence about a strategy. A profitable result here means nothing.

---

## 6. Connect MetaTrader 5

1. Install MT5 and log in to a **demo** account.
2. `pip install MetaTrader5`
3. Copy `config/credentials.example.toml` → `config/credentials.toml` and fill in
   the login, password and server. (That file is gitignored.)
4. Set the broker's UTC offset in `config/bot.toml`:

```toml
[engine]
broker = "mt5"
broker_utc_offset_hours = 2.0   # compare MT5's Market Watch clock against UTC
```

That one setting governs bar timestamps, session filters, snapshot freshness and
the chart overlay. Getting it wrong shifts everything by that many hours.

5. Capture your broker's real contract specs:

```powershell
tbot specs --save config\specs.toml
```

Use them in backtests with `tbot backtest --specs config\specs.toml`, so
position sizing matches what the broker will actually do.

## 7. Turn on the structure feed

Install the SMC/ICT library and attach the export EA — see
[MT5_SNAPSHOT_SETUP.md](MT5_SNAPSHOT_SETUP.md). Then:

```toml
[snapshot]
enabled = true
```

```powershell
tbot snapshot --symbol EURUSD
```

**Look at the `state` strings it prints.** The ICT filters match on them
(`fresh`, `swept`, …) and the defaults in `config/symbols/gbpusd.toml` are
educated guesses until you have seen your own library version's vocabulary.

## 8. Paper trade

```toml
[engine]
mode = "paper"
broker = "mt5"     # live bars, simulated fills
```

```powershell
tbot paper
```

Real market data, no real orders. Leave it running for as long as you can stand
before considering anything else.

## 9. Turn on the watchers

```powershell
tbot telegram-setup --token <from @BotFather>
```

See [WATCHING_THE_BOT.md](WATCHING_THE_BOT.md) for the dashboard, Telegram and
the chart overlay.

---

## Before live trading

Not a checklist to rush. Each line is there because skipping it is how accounts
are lost.

- [ ] `pytest` passes.
- [ ] A backtest on **real** exported data, not the synthetic generator.
- [ ] Weeks of paper trading on the same config you intend to run.
- [ ] Journal reviewed with `tbot report` — especially *why signals were
      declined*. If one gate rejects almost everything, it is miscalibrated.
- [ ] `broker_utc_offset_hours` verified against the broker's clock, and again
      after any daylight-saving change.
- [ ] Risk settings deliberately chosen, not left at the defaults.
- [ ] A demo account first. Then a small live account. Then, maybe, a real one.

```powershell
tbot live --yes
```

The `--yes` is mandatory. It exists so that sending real orders is never
something that happens by accident.
