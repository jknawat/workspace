# What the backtests actually showed

Every filter bound in `config/symbols/xauusd.toml` is here because of a number
below, not because it sounded prudent. This file exists so the reasoning
survives, and so the next person to "improve" a filter can see whether it was
already tried.

**Dataset:** XAUUSDm, 60,000 M5 bars, 2025-11-26 .. 2026-10-02 (310 days), real
broker specs captured with `tbot specs`, 240-point spread (the real one), both
directions enabled. Context timeframes replayed point-in-time via
`HistoricalMtf`, which holds a higher-timeframe bar back until it has closed.

> **One dataset, many questions.** As of 2026-10-02 this data has been queried
> with roughly a dozen variants. That is enough for the best-looking result to
> look good by luck alone, which is why nothing here is adopted on a single
> full-period number -- only if it survives both halves separately. Forward
> paper trading is the only uncontaminated evidence left.

## The filter stack was destroying the edge

The first honest run, and the most important result in the project:

| variant | trades | win | net | pf |
|---|---|---|---|---|
| all filters on | 8 | -- | -354 | 0.39 |
| without the angle gate | 117 | -- | +902 | 1.13 |

The angle gate was rejecting almost everything. Cause: `slope_degrees`
normalised the price slope by `point`, which on gold saturates the angle at
~89.9 degrees, so any threshold either passed everything or nothing. Positive in
both halves of a walk-forward split once removed.

**Acted on:** `[filters.angle] enabled = false`, and `slope_scale = "atr"` added
for anything that does want a slope.

Two further bounds were wrong against real data in the same way:

* `spread` max 60 against a real spread of ~240 -- rejected 100% of signals.
* `atr_range` 0.8--12 against a real range of 1.9--7.8 -- rejected 0%, i.e. it
  was decoration. Tightened to 2.9--7.2.

## The multi-timeframe gates: one earns its place, one looked like it didn't

Full period, varying only the two MTF gates:

| variant | trades | win | net | pf | dd |
|---|---|---|---|---|---|
| both gates (current) | 125 | 31.2% | +1620.66 | 1.19 | 8.6% |
| without `mtf_align` | 151 | 27.8% | +217.93 | 1.02 | 11.9% |
| without `mtf_required` | 151 | 32.5% | +2666.27 | **1.27** | 10.5% |
| no MTF gate at all | 214 | 29.4% | +1487.78 | 1.10 | 11.0% |
| `mtf_align min_agree=1` | 139 | 29.5% | +1057.61 | 1.12 | 8.8% |

`mtf_align` plainly earns its place: removing it collapses the profit factor
from 1.19 to 1.02, which is the difference between an edge and a coin flip that
pays commission.

Removing `mtf_required` (never trade against the daily) looked like free money
-- pf 1.19 to 1.27, net +1620 to +2666. **It did not survive the split:**

| half | period | both gates | `mtf_align` only |
|---|---|---|---|
| A | 2025-11-26 .. 2026-05-01 | +652.32, pf 1.20 | +1204.89, pf 1.24 |
| B | 2026-05-01 .. 2026-10-02 | +1784.34, pf **1.40** | +626.68, pf **1.08** |

The entire gain came from the first half; in the second half dropping the gate
roughly halves the profit factor. A change that helps in one period and hurts in
the next is a period, not an improvement.

**Acted on: nothing. The config stands.** Both gates stay. This is the result --
an ablation that tells you to leave something alone has done its job.

Worth noting what *was* stable: both gates together beat no gates in both halves
(1.20 vs 1.12, 1.40 vs 1.09). The pair is sound even though the full-period
ranking of the individual gates is not.

## Both directions pull their weight

With the MTF gates off, to isolate direction:

| side | trades | win | net | pf |
|---|---|---|---|---|
| LONG only | 117 | 29.9% | +1048.49 | 1.15 |
| SHORT only | 113 | 29.2% | +789.59 | 1.10 |

Independently profitable, and close to an even split of the trade count. Trading
both bear and bull markets is justified, not just symmetric-looking.

## The top blocker is the position cap, not a filter

"already has 1 position(s)" is the most frequent rejection in every variant
(27--51 occurrences). Signals are being dropped because an earlier trade is
still open, so `max_open_positions` is currently shaping returns more than any
filter bound. Untested, and the obvious next question.

## Standing caveats

* A profit factor of 1.13--1.19 is thin. It survives a 240-point spread, which
  is the real one, but not much more than that.
* Win rate sits near 30%: the strategy makes money from a few large winners, so
  expect long losing streaks and do not read one as a malfunction.
* `ict_confluence` **cannot be backtested here.** The MT5 snapshot describes
  structure as it stands *now*; there is no historical series of it to replay.
  Any claim about that strategy has to come from forward trading.
