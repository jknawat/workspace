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

## Signal rating: built, measured, and not yet trusted with money

The scorer rates each passing signal 0--100 on five weighted components (MTF
support 35, reward/risk 25, ATR band position 15, entry tightness 15, spread
cost 10). The question it has to answer before it can size anything: **do
higher-scoring trades actually earn more?**

Measured with gating off, so every signal traded and every one was scored
(`scripts/score_report.py`):

| band | trades | win% | net | per trade | pf |
|---|---|---|---|---|---|
| 30--44 | 9 | 22.2% | -218.11 | -24.23 | 0.70 |
| 45--59 | 40 | 35.0% | +1021.47 | +25.54 | **1.40** |
| 60--74 | 54 | 27.8% | +166.79 | +3.09 | **1.04** |
| 75--87 | 22 | 36.4% | +650.51 | +29.57 | **1.51** |

**Expectancy does not rise with the score.** The 60s band is the weakest of the
three that trade, sitting between two strong ones. A ranking that is not
monotonic is not a ranking, and sizing to it would stake money on a pattern
that is not in the data.

No trade has ever scored above 87, so any tier at 90 or 95 would never fire.

Gating at 45 was tried, since the lowest band does lose:

| variant | full period | half A | half B |
|---|---|---|---|
| scoring off | +1620.66, pf 1.19 | +652.32, pf 1.20 | +1784.34, pf 1.40 |
| floor at 45 | +1897.90, pf 1.25 | **+380.64, pf 1.12** | +1865.35, pf 1.43 |
| floor 45 + size tiers | +950.89, pf 1.20 | -7.64, pf 1.00 | +973.32, pf 1.44 |

Better over the full period, worse in the first half. The same signature as
`mtf_required`: one favourable stretch carrying a full-period number. The size
tiers are worse everywhere, which is what should be expected -- scaling risk
down scales returns down, and that only pays if the bands really differ.

**Acted on: scoring runs in measure-only mode.** `min_score = 0` with a single
full-size tier, so behaviour is byte-identical to having no scorer (verified:
both report +1620.66), while the score is computed, shown in the decision panel
and written to the journal. That accumulates the forward record needed to judge
the bands on data nobody has optimised against.

The components could no doubt be reweighted until the bands line up on these
310 days. That is the definition of curve fitting, and the angle gate already
demonstrated what it costs. The weights stay as first written.

## price_vs_ema at the cross: the timing is right, the hypothesis was wrong

Watching it live on 2026-10-02 raised a fair suspicion. Six short crossovers
that day: three refused for being outside the session, then 08:20, 09:40 and
10:00 all refused by `price_vs_ema` because price sat above the trend EMA at
the instant of the cross. Price then fell about $13 with the bot flat.

The hypothesis: the gate asks its question at the wrong moment. A pullback
entry triggers many bars after the setup arms, at a materially different price,
so a move that *begins* above the trend EMA is refused at its start and only
becomes permissible once the cross is spent.

Filters gained a `when` option (`both` by default, or `arm` / `entry`) so the
question could be measured rather than argued:

| variant | full period | half A | half B |
|---|---|---|---|
| both (current) | 125 trades, +1620.66, pf 1.19 | +652.32, pf 1.20 | +1784.34, pf **1.40** |
| entry only | 151 trades, +1840.43, pf 1.18 | **-41.83, pf 0.99** | +623.20, pf 1.12 |
| arm only | 125 trades, +1620.66, pf 1.19 | +652.32, pf 1.20 | +1784.34, pf 1.40 |
| removed | 218 trades, **-622.30, pf 0.96** | +367.10, pf 1.10 | -214.65, pf 0.96 |

**Acted on: nothing. The hypothesis was wrong.** Checking only at the breakout
makes more money over the full period and *loses* in the first half, while the
current setting is the strongest variant in both halves independently. Removing
the gate entirely turns the strategy into a loser, which settles how much work
it is doing.

Two things worth keeping from this:

* `arm only` is **identical** to `both`, to the cent. The re-check at the
  breakout never once rejected a trade that had passed at the cross -- for this
  filter. Price that was on the right side of the trend EMA when the EMAs
  crossed is still on the right side when price breaks out in that direction.
  The re-check still earns its place for `session` and `spread`, which do change
  while a setup waits.
* Three refused shorts in one afternoon feels like a lot and is not evidence.
  The same gate refuses the entries that would have been taken into the teeth
  of a trend all year, and the full-period numbers are what that is worth.

The `when` option is kept, tested and currently unused by any shipped config.
It is how the same question gets asked of another filter without rebuilding
this scaffolding.

## Candlestick patterns, and "almost all passed"

Two proposals, tested together because they interact: add candlestick patterns
to the decision, and stop requiring *every* filter to pass -- let a setup
through when almost all of them do.

Filters gained `veto = true|false`. A veto fails the trade alone; a voter
contributes to a count, and `min_votes` of them must pass. `session`, `spread`,
`price_vs_ema` and `mtf_required` were kept as vetoes: the first two are safety
rather than edge, and removing the third turns +1621 into -622.

| variant | full period | half A | half B |
|---|---|---|---|
| current | +1620.66, pf 1.19 | **+652.32, pf 1.20** | **+1784.34, pf 1.40** |
| candles must support | 20 trades, +102.65, pf 1.08 | -83.22, pf 0.84 | +578.06, pf 2.53 |
| candles not against | +2050.56, pf **1.29** | +520.92, pf 1.19 | +1473.72, pf 1.38 |
| vote 2 of 3, with candles | +1466.92, pf 1.16 | +156.76, pf 1.04 | +1139.80, pf 1.24 |
| vote 1 of 3, with candles | **-1451.55, pf 0.89** | +541.43, pf 1.09 | +417.12, pf 1.07 |
| vote 1 of 2, no candles | **-1104.90, pf 0.91** | +499.61, pf 1.08 | +494.03, pf 1.09 |

**Acted on: nothing. Both ideas were rejected.**

### Loosening the gates loses money

This is the clearest result of the lot. Requiring only one of the soft filters
turns a +1621 strategy into a **-1452 one**, with drawdown going from 8.6% to
21.6%. Two of three is also worse than the current rule in both halves.

The filters are not too strict. They are load-bearing. The intuition that a
good setup is being blocked on a technicality is real -- it happens, visibly,
and it is the price of refusing the much larger number of bad ones.

### The candle result is a lesson in why halves matter

"Candles not against" looks like the best variant on the table: +2050 against
+1621, profit factor 1.29 against 1.19. **Both halves are worse than current**
(1.19 vs 1.20, and 1.38 vs 1.40).

The full-period figure is a path effect, not better selection. Fewer early
trades meant a different balance curve, which changed position sizes later; the
halves each restart flat and measure trade quality directly. Where the two
disagree, the halves are the honest answer -- which is the same rule that has
now rejected five changes, and the only reason this one did not slip through.

"Candles must support" took 20 trades in 310 days, eight of them in half A,
where it lost. A variant that trades once a fortnight cannot be judged on this
data at all.

### What is kept

`strategy/candles.py` and the veto/vote machinery stay: tested, default-inert,
and used by no shipped config. Every pattern is defined as a measurement
(`lower >= wick_ratio * body`) rather than a shape, because a pattern that
cannot be computed identically on every bar cannot be backtested. If forward
data ever suggests revisiting this, the scaffolding is here and does not need
rebuilding.

## Standing caveats

* A profit factor of 1.13--1.19 is thin. It survives a 240-point spread, which
  is the real one, but not much more than that.
* Win rate sits near 30%: the strategy makes money from a few large winners, so
  expect long losing streaks and do not read one as a malfunction.
* The confidence score is not a win probability, and nothing in the code or
  the panel calls it one. The strategy wins ~30% of its trades; a score of
  80 means "most of the evidence lines up", never "80% likely to win".
* `ict_confluence` **cannot be backtested here.** The MT5 snapshot describes
  structure as it stands *now*; there is no historical series of it to replay.
  Any claim about that strategy has to come from forward trading.
