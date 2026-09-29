# Trading ICT/SMC structure

Stage 2 made MetaTrader 5's structure detection readable. This stage makes it
tradable, in two independent pieces:

1. **ICT filters** — gates you can bolt onto *any* strategy.
2. **`ict_confluence`** — a strategy whose entire entry model is structure.

They are separate on purpose. Whether you want to *trade* ICT or merely *filter*
with it stays a config decision rather than a rewrite.

---

## The one rule: every gate fails closed

No snapshot, a stale one, a `DISABLED` concept, a missing record — all reject.

A structure gate that passes when it has no data silently turns "I don't know"
into "go ahead". That is how a bot keeps trading confidently after the terminal
quietly stopped exporting. If `[snapshot].enabled = false`, every ICT gate
rejects and `ict_confluence` takes no trades at all. That is working as
intended, not a bug.

---

## Option A — ICT as a filter on an existing strategy

Keep your mechanical entries; only take them when structure agrees:

```toml
symbol = "EURUSD"
strategy = "ema_pullback"

[filters.ict_snapshot]          # require a usable export first

[filters.ict_bias]              # only trade with the newest BOS / CHoCH / MSS
concepts = ["BOS", "CHOCH", "MSS"]

[filters.ict_killzone]          # only during London / New York
names = ["london", "new york"]
```

The EMA crossover still decides *when*; structure decides *whether*.

## Option B — trade the structure itself

```toml
symbol = "GBPUSD"
strategy = "ict_confluence"
sides = ["LONG", "SHORT"]

[params]
zone_concepts = ["ORDER_BLOCK", "FVG", "BREAKER"]
confirmation = "candle"
sl_buffer_atr = 0.5
target = "rr"
tp_rr = 2.0
```

A complete, commented example ships as `config/symbols/gbpusd.toml` (disabled by
default until your export is running).

Both can run at once — different symbols, one shared risk budget. That answers
the "ICT, or my existing strategy, or both?" question without committing to it.

---

## How `ict_confluence` decides

> Structure picks the direction, a zone gives the entry and the stop, liquidity
> gives the target.

```
SCANNING   price trades into a directional zone (order block / FVG / breaker)
           that agrees with the published structural bias
   ↓
ARMED      wait for confirmation: a directional close, or a fresh BOS/MSS
   ↓  ✗ close through the zone, or the window expires → back to SCANNING
ENTRY      stop just beyond the zone's far edge, target R multiple or liquidity
   ↓
COOLDOWN   n bars
```

### The stop comes from structure, not volatility

This is the real difference from `ema_pullback`. The stop sits just beyond the
zone's far edge, plus a buffer of `sl_buffer_atr` ATR:

```
LONG :  sl = zone.lower − sl_buffer_atr × ATR
SHORT:  sl = zone.upper + sl_buffer_atr × ATR
```

If the zone was wrong, price closes through it and the trade is over. That is
both tighter and more meaningful than a fixed ATR distance — but it also means
the stop distance varies with zone height, which is why the bounds below exist.

### Two safeguards you should not remove

**One entry per zone.** An order block stays `active` for many bars. Without
remembering which zones have been traded, the bot re-enters the same setup on
*every* bar until the zone finally breaks. `one_entry_per_zone = true` keeps the
ids of zones already traded.

**Stop-distance bounds.** A zone a fraction of an ATR tall produces a tiny stop
— and since lot size is `risk ÷ stop distance`, a tiny stop means an enormous
position. Stops outside `[min_sl_atr, max_sl_atr]` are refused, with the reason
recorded in the journal.

### Targets

| `target` | behaviour |
|---|---|
| `rr` | `tp_rr` multiples of the stop distance |
| `liquidity` | the nearest published liquidity level beyond entry, falling back to `rr` when nothing is ahead or the pool is closer than `liquidity_min_rr` |

Liquidity targets use **geometry, not direction labels** — the nearest level
above entry for a long, below for a short. Which side of the book a library
labels "bullish" is a convention that can change between versions; "above the
entry price" cannot.

---

## Filter reference

Run `tbot strategies` for the authoritative list with every default. In summary:

| filter | rejects when |
|---|---|
| `ict_snapshot` | no usable snapshot, or a named concept is not ready |
| `ict_bias` | newest structural event disagrees with the trade (neutral rejected unless `allow_neutral`) |
| `ict_killzone` | the bar is outside every matching killzone window |
| `ict_zone` | price is not trading inside a directional zone |
| `ict_liquidity_swept` | no opposite-side pool was taken recently |
| `ict_premium_discount` | longs above equilibrium, shorts below it |
| `ict_no_opposing_zone` | an opposing zone blocks the path to target |

### The vocabulary this library actually emits

Measured from a live EURUSD M5 export (library 1.1.0, schema 1.0, 462 records),
rather than read off the documentation:

| concept | states seen | active? |
|---|---|---|
| `ORDER_BLOCK` | `FRESH` `TESTED` `MITIGATED` `BROKEN` | only the first three |
| `BREAKER` | `FRESH` `TESTED` `MITIGATED` `BROKEN` | only the first three |
| `FVG` / `IFVG` | `FRESH` `TESTED` `MITIGATED` `BROKEN` | only the first three |
| `LIQUIDITY` | `SWEPT` `ACTIVE` | both |
| `KILL_ZONE` | `FORMING` `COMPLETE` | both |
| `PREMIUM_DISCOUNT`, `OTE` | `ACTIVE` | yes |
| `BOS`, `CHOCH` | `CONFIRMED` | **never active** |
| `MSS`, `DISPLACEMENT` | `CONFIRMED` | always active |
| `SWING_HIGH` / `SWING_LOW` | `CONFIRMED` `BROKEN` | confirmed only |
| `PO3` | `ACCUMULATION` `MANIPULATION` `INVALIDATED` | varies |

Two things follow, and both bit this project:

**`BOS` and `CHOCH` are never `active`.** They are point-in-time events, not
living zones. Anything that filters them on the active flag sees nothing at
all — which is why `Snapshot.bias()` deliberately ignores the flag. If you
write your own query over structural events, do the same.

**There is no `UNSWEPT`.** An untaken liquidity pool is `ACTIVE`; a taken one
is `SWEPT`. So `[filters.ict_liquidity_swept] states = ["swept"]` is right, and
`states = ["active"]` is how you ask for the opposite.

### Truncation is real, and the cap is inside the EA

That same export showed `ORDER_BLOCK truncated` and `BREAKER truncated`:
exactly 100 records each, of which 80 were `BROKEN`. The library's
`max_records_per_concept` defaults to 100, and dead blocks crowd out live ones.

`tbot snapshot` reports this under `!` markers — believe it. The cap is not an
EA input, so raising it means editing `SMC_Snapshot_Export.mq5` to set
`config.maxRecordsPerConcept` after `SetDefaults()`, then recompiling.

### State strings are yours to configure

The snapshot contract fixes the *concepts* but leaves each record's `state` as
free text (`FRESH`, `MITIGATED`, `SWEPT`, …) that a library version may extend.
Filters that care about state match whole lower-case **tokens** from config:

```toml
[filters.ict_zone]
states = ["fresh"]      # matches "FRESH" and "FRESH_UNTESTED", not "MITIGATED"
```

Token matching, not substring — because `"swept"` is a substring of `"UNSWEPT"`,
and a naive `in` test would let an untouched liquidity pool satisfy a "must have
been swept" gate. Exactly backwards, and silently so.

Check the strings your own library version emits before relying on one:

```bash
tbot snapshot --symbol EURUSD --concept LIQUIDITY
```

### Direction conventions

`ict_liquidity_swept` has a `direction` option (`agree` / `oppose` / `any`)
because libraries differ on whether an equal-lows pool is labelled by the side
it sits on or by the move that follows its sweep. The default assumes the
latter. Verify against your own data rather than trusting it.

---

## Tuning it

Everything is journalled, including rejections and their reason:

```bash
tbot report --journal data/journal.sqlite
```

```
why signals were declined:
   142x  GBPUSD   ict_zone: price 1.26311 is not in a LONG ORDER_BLOCK/FVG zone
    38x  GBPUSD   ict_killzone: outside killzone (london, new york) at Wed 04:15 UTC
    11x  GBPUSD   sizing: min volume 0.01 would risk 14.20 > budget 9.80
```

That top line is the tuning loop: if one gate rejects almost everything, either
it is miscalibrated or the setup genuinely is not there. The journal tells you
which, without guesswork.

---

## Honest limitations

* **Unvalidated parameters.** The defaults are plausible, not backtested. The
  ICT model has more knobs than the EMA one and each is a chance to overfit.
* **Backtesting needs recorded snapshots.** CSV replay has no structure data,
  so `ict_confluence` produces nothing in a plain backtest. Evaluating it
  properly means recording live snapshots over time and replaying them — worth
  building before trusting any number this strategy produces.
* **Bias is one event deep.** `bias()` reads the newest structural record, with
  no higher-timeframe confirmation. Multi-timeframe would need a second
  snapshot per symbol, which the store already supports but the strategy does
  not yet use.
* **Entry is at bar close.** No limit orders resting inside the zone, which is
  how this is usually traded manually. Pending-order support belongs with the
  stage-5 execution work.
