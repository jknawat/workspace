# Letting MetaTrader 5 do the analysis

`tbot` does not re-implement Smart Money Concepts in Python. MetaTrader 5
detects the structures on its own closed candles and publishes them as JSON;
`tbot` reads that file. The bot therefore trades exactly what your chart draws,
and there is no second implementation to drift out of agreement.

This document covers installing the exporter and confirming the link works.

---

## 1. Install the library into MetaTrader 5

Get the MIT-licensed SMC/ICT library:

```
https://github.com/xxvw/ICT_Library_MQ5
```

Then, in MetaTrader 5:

1. **File → Open Data Folder**. This opens the *terminal* folder, which contains
   `MQL5/`.
2. Copy the library's `Include/SMC/` into `MQL5/Include/SMC/`.
3. Copy `Experts/SMC_Snapshot_Export.mq5` into `MQL5/Experts/`.
4. Open MetaEditor (F4), open `SMC_Snapshot_Export.mq5`, press **Compile** (F7).
   It must compile with no errors.

> The export EA **places no orders**. It only reads candles and writes a file.
> Order routing stays in `tbot`, behind the risk gate.

## 2. Attach it to a chart per symbol

One chart per symbol you intend to trade, on the timeframe `tbot` is configured
for (`[engine].timeframe`, `M5` by default).

Inputs that matter:

| input | set it to | why |
|---|---|---|
| `InpSymbol` | blank | uses the chart symbol |
| `InpTimeframe` | `PERIOD_CURRENT` | uses the chart period |
| `InpFolder` | `SMC_Export` | must match `[snapshot].folder` in `bot.toml` |
| `InpSMTSymbol` | blank, or a correlated symbol | enables SMT divergence |

Enable **Algo Trading** in the toolbar, then check the **Experts** tab. On
attach it prints the exact path it writes to — something like:

```
Snapshot output: C:\Users\you\AppData\Roaming\MetaQuotes\Terminal\Common\Files\SMC_Export\EURUSD_M5.json
```

Note that this is the **Common** folder — shared by all terminals on the machine
— not the per-terminal folder that "Open Data Folder" showed you.

### One publisher per file

The EA takes a lock on its destination. Attaching a second EA to the same
symbol, timeframe and folder fails with *"already has a publisher"*. That is
deliberate: two writers would interleave. Use a different `InpFolder` for a
second terminal.

## 3. Point tbot at it

In `config/bot.toml`:

```toml
[snapshot]
enabled = true
folder = "SMC_Export"       # same as InpFolder
common_path = ""            # blank auto-detects the Common\Files folder
timeframe = ""              # blank follows [engine].timeframe
max_age_minutes = 0.0       # 0 = three bars of that timeframe
require_fresh = true
```

Set `common_path` explicitly only if auto-detection fails — paste the path the
EA printed, up to and including `Files`.

## 4. Check the link

```bash
tbot snapshot -c config/bot.toml
```

```
folder      C:\Users\you\AppData\Roaming\MetaQuotes\Terminal\Common\Files\SMC_Export
timeframe   M5
max age     0:15:00
broker UTC  +2.0h
files       3 snapshot(s) present

EURUSD     READY     tf=M5 age=41s active_records=18 bias=bullish
XAUUSD     READY     tf=M5 age=39s active_records=22 bias=bearish
USDJPY     MISSING   ...\SMC_Export\USDJPY_M5.json
```

For detail on one symbol, including per-concept readiness and every record:

```bash
tbot snapshot -c config/bot.toml --symbol EURUSD
tbot snapshot -c config/bot.toml --symbol EURUSD --concept ORDER_BLOCK --active
```

---

## Reading the output

**Statuses.** `READY` is fully evaluated; `PARTIAL` means some concepts are
usable and others are not; `NOT_READY` means insufficient history — normal for
the first minutes after attaching; `ERROR` is a failure; `DISABLED` means the
concept was switched off in the EA's config.

`tbot` treats `READY` and `PARTIAL` as usable. It never treats `DISABLED` as
agreement — a concept that was switched off is *absent evidence*, not a pass.

**Freshness.** A snapshot older than `max_age_minutes` is ignored entirely and a
warning is logged. A stale structure file is worse than none: it looks
authoritative while describing a market that has moved on. If you see staleness
warnings, MT5 has stopped, the chart lost its EA, or the market is closed.

**Truncation.** `truncated` on a module means the record cap was hit and older
structures were dropped. Raise `max_records_per_concept` in the EA if a concept
you rely on is truncating.

---

## Time zones — the part that bites

Snapshot timestamps are **broker wall-clock with no timezone suffix**. A broker
on UTC+2 writes `2026-09-18T12:00:00` for what is really 10:00 UTC.

`tbot` converts every snapshot timestamp to real UTC using one setting:

```toml
[engine]
broker_utc_offset_hours = 2.0   # your MT5 server's offset, including DST
```

That is the same setting used for bar timestamps, so bars and structures always
land on the same clock. Get it wrong and every session filter and every
freshness check is off by that many hours. Check your broker's server time in
MT5 (the Market Watch clock) against UTC, and remember it usually shifts with
daylight saving.

---

## Troubleshooting

| symptom | cause |
|---|---|
| `folder does not exist` | wrong `common_path`, or the EA has never run. Use the path from the Experts log. |
| `MISSING` for one symbol | no EA attached to that symbol's chart, or a different `InpFolder`, or the broker's symbol name differs (`EURUSD.pro` is not `EURUSD` — configure the exact broker name). |
| `INVALID` | the file is not the expected contract. The error names the field. A major schema bump (`2.x`) needs a reader update, and is refused rather than guessed at. |
| status stuck `NOT_READY` | not enough history loaded. Scroll the chart back, or lower `lookback_bars` in the EA. |
| stale warnings during quiet hours | expected when the market is closed. |
| `already has a publisher` | a second EA is targeting the same file. Give it its own `InpFolder`. |

---

## What this does not do yet

Stage 2 makes the structure data available and visible: `tbot snapshot` shows
it, and every strategy receives it on `ctx.snapshot`. **No strategy trades on it
yet** — the ICT entry model and its filters are stage 3. Until then the snapshot
is observable, journalled context, which is the right order: prove the data is
correct before betting on it.
