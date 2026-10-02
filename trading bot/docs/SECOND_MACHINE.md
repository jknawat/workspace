# Running it on another computer

Everything the bot needs is in git except four things: Python, MetaTrader 5,
your broker login, and the market data CSVs. This is the order that works.

> **Read the warning at the bottom first if the other machine will run at the
> same time as this one.** Two bots on one trading account is the mistake that
> costs money, and the single-instance lock cannot catch it — it only guards
> one machine.

## 1. Push from the machine that has the work

On the current PC:

    cd "C:\workspace\jk"
    git push

If `git push` asks for credentials, use a GitHub personal access token as the
password, not your account password.

## 2. Install Python 3.12 on the new machine

    winget install Python.Python.3.12

**Not 3.13 or newer.** The `MetaTrader5` package lags behind the newest Python
by months, and a version it does not support fails at import with no useful
message.

Check it:

    py -3.12 --version

## 3. Clone and build the environment

    git clone https://github.com/jknawat/workspace.git C:\workspace\jk
    cd "C:\workspace\jk\trading bot"
    py -3.12 -m venv .venv
    .venv\Scripts\python.exe -m pip install -e ".[dev]"

Confirm it:

    .venv\Scripts\python.exe -m pytest -q

All tests should pass before you go near a broker. If they do not, stop here —
something in the install is wrong and nothing after this will behave.

## 4. Install MetaTrader 5 and log in

Install MT5, then log in to **the same Exness demo account** this machine uses.
File → Open an Account, or File → Login to Trade Account with the existing
credentials.

Then check the symbol. Exness names gold `XAUUSDm` on some account types and
`XAUUSD` on others. Market Watch → right-click → Symbols, and find what yours is
called. If it differs, change `symbol` in `config/symbols/xauusd.toml`.

## 5. Install the snapshot exporter

The three files the bot's reader depends on are in the repo, under `mql5/`.
The rest of the SMC library is not — install that from upstream first.

1. Clone <https://github.com/xxvw/ICT_Library_MQ5> and copy its `Include/SMC`
   folder into MT5's `MQL5/Include/` (MT5: **File → Open Data Folder**).
2. From this repo, copy over the top, replacing any file it asks about:
   - `mql5/Experts/SMC_Snapshot_Export.mq5` → `MQL5/Experts/`
   - `mql5/Include/SMC/Core/SmcSnapshot.mqh` → `MQL5/Include/SMC/Core/`
   - `mql5/Include/SMC/Utils/SnapshotExporter.mqh` → `MQL5/Include/SMC/Utils/`
   - `mql5/Indicators/TbotOverlay.mq5` → `MQL5/Indicators/` (optional)
3. Open MetaEditor (F4), open `SMC_Snapshot_Export.mq5`, press **Compile** (F7).
4. Drag the compiled EA onto a **XAUUSDm M5** chart and enable **Algo Trading**.

Replacing those three deliberately: they define the JSON contract the Python
side parses, and the repo's copies are the ones this project was built and
tested against.

Full detail, including the common-files path and troubleshooting, is in
`docs/MT5_SNAPSHOT_SETUP.md`.

## 6. Capture that machine's contract specs

    .venv\Scripts\python.exe -m tbot.cli specs --save config\specs.toml

Do this on the new machine rather than trusting the committed file. Contract
size, tick value and minimum volume come from the broker and can differ between
account types even at the same broker. Position sizing is built on these
numbers, and a wrong one sizes every trade wrong.

## 7. Check the environment end to end

    .venv\Scripts\python.exe -m tbot.cli doctor

This checks the terminal connection, the symbol, the snapshot freshness and the
config together. Fix anything it reports before running.

## 8. The trade journal is shared automatically

`data/journal.sqlite` **is** in git, and the scripts keep it in step:

* `run.bat` fetches before starting and takes anything the other machine
  recorded.
* `stop.bat` waits for the bot to actually exit, then commits and pushes it.

You never type a git command. Stop properly on one machine, start on the other,
and the history follows.

The waiting in `stop.bat` is not politeness. Committing or copying a SQLite
file while the process is still writing to it is how a database gets corrupted,
so it polls for the bot to exit and refuses to save if it is still alive after
a minute.

**If `run.bat` refuses to start**, it will be this:

    STOP - both computers have history the other does not have.

That means the bot ran in two places. Git cannot merge two SQLite files, so one
of the two records has to be chosen and the other is lost. Pick the journal
from the machine that actually placed the trades. It also means both bots were
trading the same account — see the warning at the bottom.

Market data (`data/*.csv`) is **not** shared: it is large and regenerable, and
you only need it to re-run backtests. Copy `data\` by hand if you want it, or
re-export on the new machine.

## 9. Run it

    run.bat

Same as here: MT5 open, double-click `run.bat`, dashboard at
<http://127.0.0.1:8787>, `stop.bat` to stop.

---

## The warning: do not run both at once on one account

The single-instance lock stops two bots on **one machine**. It cannot see
another computer.

Two machines on the same trading account is genuinely dangerous, and worse in
paper mode because it looks harmless:

* Each one reads positions from the broker and enforces `max_open_positions`
  on what *it* can see, so both open a position and each believes the cap was
  respected. The account carries double the configured risk.
* The daily loss kill-switch counts only the damage its own instance did, so
  the real loss can reach twice `max_daily_loss_pct` before either stops.
* Both write to their own journal, so neither has the full record and
  `tbot review` is wrong on both.

Pick one machine to be the live one. The other can safely run backtests,
`tbot review` and the dashboard against a copied journal — none of those place
orders.

If you want the bot running whether or not your work PC is on, run it at home
and leave this one for development.
