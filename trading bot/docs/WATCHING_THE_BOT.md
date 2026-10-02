# Watching and controlling the bot

Three ways to see what tbot is doing, and one way to tell it what to do.

| surface | purpose | can it send orders? |
|---|---|---|
| **Local dashboard** | live view at your desk | no — read-only |
| **MT5 chart overlay** | the bot's trades drawn on your chart | no — read-only |
| **Telegram** | alerts on your phone, and remote control | commands only, via flags |
| CLI + journal | the complete record, after the fact | no |

None of them can bypass the risk gate. The dashboard cannot place a trade at
all; Telegram commands set flags that the trading thread reads and acts on
itself, so there is still exactly one thread touching positions.

All of it uses the standard library. No FastAPI, no Redis, no Node, no
`pip install`.

---

## Local dashboard

```toml
[dashboard]
enabled = true
host = "127.0.0.1"    # loopback only
port = 8787
```

Run `tbot paper` or `tbot live` and open <http://127.0.0.1:8787/>. It shows
balance and equity, today's P/L, open positions with live P/L, each symbol's
strategy phase and structure status, an equity sparkline, and a feed of recent
activity. It refreshes every two seconds and adapts to your system's light or
dark theme.

**`host` is loopback for a reason.** Changing it to `0.0.0.0` exposes your
account balance and open positions to anything that can reach the machine.
There is no login. If you need it remotely, put it behind a VPN or an SSH
tunnel rather than opening the port.

---

## MT5 chart overlay

Stage 2 reads structure *from* MT5. This writes tbot's decisions back *to* it,
so one chart shows both the zones the library detected and what the bot did
about them.

```toml
[overlay]
enabled = true
folder = ""                     # blank reuses [snapshot].folder
filename = "tbot_state.json"
```

Then install the indicator:

1. In MT5: **File → Open Data Folder**, and copy `mql5/Indicators/TbotOverlay.mq5` into
   `MQL5/Indicators/`.
2. Compile it in MetaEditor (F7).
3. Drag it onto a chart. Set `InpFolder` to the same folder as `[overlay]`
   (default `SMC_Export`).

It draws the entry, stop and target of any open position on that symbol, and a
small status panel: mode, equity, today's P/L, and the strategy phase. It places
no orders and changes nothing.

Timestamps in the state file are written in **broker time**, because MQL5 draws
on the terminal's clock — the mirror image of the snapshot reader, which
converts broker time to UTC on the way in.

---

## Telegram

### Setting it up

1. On Telegram, message **@BotFather** → `/newbot` → follow the prompts. It
   gives you a token like `123456789:AA...`.
2. Run the helper, then send your new bot any message:

```bash
tbot telegram-setup --token 123456789:AA...
```

It prints your chat id and the exact config to paste.

3. Put the secrets in `config/credentials.toml` (gitignored):

```toml
[telegram]
token = "123456789:AA..."
chat_id = "987654321"
```

Or use `TBOT_TELEGRAM_TOKEN` and `TBOT_TELEGRAM_CHAT_ID` — environment wins over
the file, and both beat anything in `bot.toml`. **Do not put the token in
`bot.toml`**: that file is normally committed.

4. Enable it:

```toml
[telegram]
enabled = true
events = ["order", "closed", "error", "started", "stopped"]
accept_commands = true
```

### What it sends

```
✅ GBPUSD LONG 0.42 lots @ 1.26311
SL 1.25980  TP 1.26971, risk 100.00
ORDER_BLOCK ob-4412: directional close inside the zone

🟢 GBPUSD closed LONG 0.42 lots +184.30 (TP)
```

Add `"signal"`, `"declined"` or `"exit"` to `events` for more detail. `declined`
in particular is a firehose — useful for a day of tuning, painful as a
permanent setting.

### Commands

| command | effect |
|---|---|
| `/status` | balance, open positions, strategy state |
| `/positions` | the same, positions only |
| `/pause` | **stop new entries.** Open trades keep being managed |
| `/resume` | allow entries again |
| `/closeall` | close every open position now |
| `/stop` | shut the bot down after the current cycle |
| `/help` | the list |

Only your chat id is accepted. Messages from anyone else get **no reply at
all** — answering would confirm the bot exists to whoever found it.

`/pause` is worth understanding: strategies keep advancing their state machines
and exit policies keep managing open trades. A pause that froze everything would
leave the state machines stale and confused on resume.

---

## How it stays out of the way

A watcher that can break trading is worse than no watcher. Three mechanisms:

**Subscriber exceptions are caught.** The event bus wraps every callback. A
watcher that throws produces a log line, not an outage.

**Telegram sends from its own thread.** Events go into a bounded queue drained
by a background worker. If Telegram is slow or unreachable, the trading loop
never waits on it. If the queue fills, alerts are **dropped** rather than
blocking — losing an alert is acceptable, delaying a stop-loss is not. The
journal remains the complete record either way.

**Commands never act directly.** The poller only sets flags. The runner reads
them at the top of its next cycle and does the work itself.

If a watcher cannot even be constructed — bad token, port already in use — it
is reported and skipped. The bot still trades.

---

## Troubleshooting

| symptom | cause |
|---|---|
| dashboard shows "disconnected" | the bot is not running, or a different port |
| "address already in use" at start | another process on that port; change `[dashboard].port` |
| no Telegram messages | `enabled = false`, wrong chat id, or the event kind is not in `events` |
| Telegram commands ignored | `accept_commands = false`, or you are messaging from a different account than the configured `chat_id` |
| overlay panel says "no state file" | `[overlay].enabled = false`, the bot is not running, or `InpFolder` does not match the config |
| overlay markers at the wrong times | `broker_utc_offset_hours` is wrong — the same setting that governs bars and snapshots |

## The decision log

The dashboard's **Decision log** card is the full record: every order, and
every time the bot changed its mind. Columns are when, action (buy / sell /
wait / closed), the confidence score, the share of the account actually risked,
lots, price, and the reasoning in words.

Filter it with the buttons. `Buy`/`Sell` are the orders; `Waiting` is why it
held off; `Closed` is how each trade ended.

A repeated "still waiting" is **not** written again until the reason changes,
and two reasons that differ only by a number -- a session gate naming the
bar's own clock time, a cap naming the current count -- count as the same
reason. Without that the log was ~1,600 rows per 41 days of replay, nearly all
of them identical; with it, 725, and consecutive rows actually say different
things. The row that does get written keeps its exact wording.

It is read from `data/journal.sqlite` over a **read-only** connection, so the
page cannot alter the record it is showing, and it survives restarts.

## Reviewing what the bot learned

    .venv\Scripts\python.exe -m tbot.cli review

This reads the journal and reports what each band of the confidence score
actually earned -- win rate, net, and expectancy per trade. Every signal, taken
or declined, is recorded with its score and its component breakdown, and the
outcome is attached when the position settles.

**It will refuse to give you a verdict under 60 settled trades**, and say so.
That is the point of it. The strategy wins about 30% of its trades, so twenty
of them can say almost anything; a tool that printed a confident conclusion on
twenty would be worse than no tool. It also checks whether expectancy *rises*
with the score rather than just looking at the best band, because a score that
reads good, then bad, then good is not ranking anything.

Once the bands do line up on enough trades, the tiers in
`config/symbols/xauusd.toml` are how you act on it.
