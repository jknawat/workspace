# Running the bot day to day

## The short version

1. Double-click **`run.bat`**
2. Open **<http://127.0.0.1:8787>** in a browser
3. When you want it to stop, double-click **`stop.bat`**

That's it. `run.bat` starts MetaTrader 5 for you if it isn't already running —
pinned to the right account, with the structure exporter on the gold chart —
then starts the bot.

---

## What the dashboard shows you

**Why it is doing that** — a plain sentence per symbol, updated every bar:

```
XAUUSDm  SCANNING
waiting for a setup; last one was turned down because mtf_align: only 1
timeframe agrees with LONG, need 2  [M1 bull | M15 bear | H1 bear | D1 bear]
```

So "why wait" is answered directly, not inferred from a log. When it does take
a trade, the same panel says why it bought or sold, and the activity feed keeps
the history.

**Timeframes** — every context timeframe as a coloured chip, finest on the left:

```
M1 bull   M15 bear   H1 bear   H4 bear   H12 bear   D1 bear   W1 bull   MN1 flat
```

Green is bullish, red bearish, grey undecided, faded means not enough history to
judge. Hover a chip for the reason.

**Plus** balance, today's P/L, open positions with live P/L, an equity
sparkline, and the recent activity feed.

The dashboard is **read-only** and bound to `127.0.0.1`, so nothing on your
network can reach it. Commands go through Telegram — see
[WATCHING_THE_BOT.md](WATCHING_THE_BOT.md).

---

## How stop.bat works

It writes a file (`data/STOP`). The bot checks for it once per cycle and then
shuts down cleanly.

It does **not** kill the process, because that could interrupt a journal write.
And it does **not** close your open positions — those stay open. Close them in
MT5 yourself, or send `/closeall` from Telegram, if you want to be flat.

`run.bat` deletes the file on startup, so a leftover stop signal can't make the
bot quit the moment it starts.

---

## Multi-timeframe: trade one, read many

Entries trigger on **M5**. These are read for context on every decision:

```toml
[engine]
timeframe = "M5"
context_timeframes = ["M1", "M15", "H1", "H4", "H12", "D1", "W1", "MN1"]
```

**MT5 has no 5h or 10h timeframe.** Its ladder is M1–M30, H1, H2, H3, H4, H6,
H8, H12, D1, W1, MN1 — so **H4** stands in for "about five hours" and **H12**
for "about ten".

A timeframe reads **bullish** only when price is above its trend EMA *and* its
fast EMA is above its slow one. Anything else is **neutral** — which is the
honest answer, not a coin flip. On a 1-minute chart inside a daily uptrend,
"undecided" is usually correct.

A timeframe without enough history (MN1 often has only tens of bars) reads
neutral and is marked **not ready**. It never counts as agreement: an
unknowable timeframe does not get a vote.

### Using it

```toml
# At least 2 must agree, no more than 3 may actively oppose.
[filters.mtf_align]
timeframes = ["M15", "H1", "H4", "H12", "D1"]
min_agree = 2
max_disagree = 3

# Never fight the daily. Neutral is tolerated; it is not opposition.
[filters.mtf_required]
timeframes = ["D1"]
allow_neutral = true
```

Agreement and disagreement are counted **separately** because neutral is
neither — two timeframes actively against a trade matters more than four being
undecided.

---

## Trading both directions

```toml
sides = ["LONG", "SHORT"]
```

Gold is set this way now, so it works in a falling market as well as a rising
one. The timeframe gates are symmetric by construction, not by a second code
path: in a bear market the same rules that would block a long permit a short.

---

## If something looks wrong

| symptom | cause |
|---|---|
| `symbol not available in Market Watch` | MT5 is on the wrong account. The terminal holds more than one saved login. Close it and let `run.bat` start it, or check `mt5/start_gold.ini`. |
| bot refuses to start, naming an account | the `expect_login` check in `config/credentials.toml` is doing its job — you are on a different account than configured |
| `context timeframe X unavailable` | that timeframe isn't in the MT5 ladder. See the list above. |
| timeframe chips all faded | not enough history downloaded. Open that timeframe's chart in MT5 once and scroll back. |
| dashboard says "disconnected" | the bot isn't running, or it's on a different port |
| bot stops immediately | a leftover `data/STOP`. `run.bat` clears it; delete it by hand if you started the bot another way. |

Run `tbot doctor` for a full check of interpreter, config, MT5, snapshots,
journal and watchers.
