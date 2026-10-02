"""Does an LLM rate these signals better than the arithmetic scorer does?

The same question that was asked of the angle gate, the multi-timeframe gates
and price_vs_ema, asked the same way: score every signal in the 310-day set,
bucket the trades by that score, and check whether expectancy rises with it --
in **both halves** separately, because a full-period number has now failed that
check four times running.

**This script does not spend money unless you pass --spend.** The default run
replays the data, builds every prompt, counts the tokens exactly through the
free count_tokens endpoint, prints what the real calls would cost, and stops.
Nothing is charged for finding out the price.

    .venv\\Scripts\\python.exe scripts/llm_score_test.py            # free: price it
    .venv\\Scripts\\python.exe scripts/llm_score_test.py --spend    # runs it

Submitted through the Batch API, which is half price and asynchronous -- there
is no latency requirement here, the data is 310 days old.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tbot.cli import _load_specs  # noqa: E402
from tbot.config import load_config  # noqa: E402
from tbot.data.feed import CsvFeed  # noqa: E402
from tbot.engine import run_backtest  # noqa: E402
from tbot.engine.core import TradeEngine  # noqa: E402

SPREAD_POINTS = 240.0

#: Published rates, $ per million tokens. Batch halves both.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

#: Thinking tokens bill as output, and an analysis prompt thinks before it
#: answers. Counting only the visible answer is how an estimate ends up a third
#: of the real bill, so assume this much reasoning per call.
ASSUMED_THINKING_TOKENS = 700
ASSUMED_ANSWER_TOKENS = 150

BANDS = ((0, 30), (30, 45), (45, 60), (60, 75), (75, 88), (88, 101))

SYSTEM = """You rate proposed gold (XAUUSD) trades on a 5-minute chart.

You are scoring a setup that has already passed every mechanical filter. Your
job is to judge how good it looks, 0-100, where 50 means "no opinion either
way". Be willing to use the whole range: a score that is always near 50 ranks
nothing and is worthless.

This strategy wins about 30% of its trades and makes money because the winners
are larger than the losers. So do NOT score on "will this win?" -- score on
whether the setup is worth risking money on given that most trades lose.

You cannot see the future and are not being asked to predict the price. Judge
only the quality of the setup from the evidence given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": {"type": "string", "maxLength": 200},
    },
    "required": ["score", "reason"],
    "additionalProperties": False,
}


def collect_signals(limit: int = 0) -> list[dict[str, Any]]:
    """Replay the data and capture every signal with its point-in-time context.

    No lookahead: everything recorded here is read from the bar the signal was
    generated on, through the same replay the backtest uses.
    """
    cfg = load_config(str(ROOT / "config" / "bot.toml"))
    scfg = cfg.active_symbols[0]
    specs = _load_specs(str(ROOT / "config" / "specs.toml"))

    captured: list[dict[str, Any]] = []
    original = TradeEngine.step

    def recording_step(self, symbol, i=None):
        result = original(self, symbol, i)
        if result.signal is not None and result.entered and result.bar is not None:
            rt = self.runtimes[result.symbol]
            idx = len(rt.bars) - 1 if i is None else i
            s = result.signal
            closes = [round(b.close, 2) for b in rt.bars[max(0, idx - 19):idx + 1]]
            atr = rt.ind.get("atr", [None])[idx]
            band = (rt.cfg.filters or {}).get("atr_range") or {}
            captured.append({
                "key": (result.symbol, result.bar.ts.isoformat()),
                "ts": result.bar.ts.isoformat(),
                "side": s.side.value,
                "entry": round(s.price, 2),
                "sl": round(s.sl, 2),
                "tp": round(s.tp, 2),
                "rr": round(s.rr, 2),
                "atr": round(atr, 2) if atr else None,
                "atr_band": [band.get("min"), band.get("max")],
                "closes": closes,
                "mtf": rt.mtf.summary() if len(rt.mtf) else "",
                "reason": s.reason,
                "arithmetic_score": result.score.points if result.score else None,
            })
        return result

    TradeEngine.step = recording_step  # type: ignore[method-assign]
    try:
        report = run_backtest(
            cfg, CsvFeed(str(ROOT / "data")), specs=specs,
            spread_points={scfg.symbol: SPREAD_POINTS},
        )
    finally:
        TradeEngine.step = original  # type: ignore[method-assign]

    outcomes = {(t.symbol, t.opened_at.isoformat()): t.pnl for t in report.trades}
    for c in captured:
        c["pnl"] = outcomes.get(c["key"])
    kept = [c for c in captured if c["pnl"] is not None]
    if limit:
        kept = kept[:limit]
    return kept


def build_prompt(sig: dict[str, Any]) -> str:
    lo, hi = sig["atr_band"]
    return f"""Proposed trade: {sig['side']} XAUUSD on the 5-minute chart.

Time (broker, UTC+0): {sig['ts']}
Entry {sig['entry']}, stop {sig['sl']}, target {sig['tp']}
Reward/risk: {sig['rr']}
Why the strategy fired: {sig['reason']}

ATR(14) now: {sig['atr']}   (its configured healthy band is {lo} to {hi})
Spread charged: 240 points, i.e. $0.24

Higher timeframes right now:
{sig['mtf']}

Last 20 five-minute closes, oldest first:
{sig['closes']}

Score this setup 0-100 and give a one-line reason."""


def _estimate_tokens(text: str) -> int:
    """Rough token count without contacting anybody.

    About four characters per token for English prose with numbers in it. This
    is only used to show a price before an API key exists -- with a key the
    exact count is measured instead.
    """
    return max(1, len(text) // 4)


def price_it(
    prompts: list[str], model: str, use_batch: bool, exact: bool = True
) -> dict[str, Any]:
    """Price the run. ``exact`` measures tokens; otherwise they are estimated.

    Finding out what something costs must not itself require an account, so
    this works with no API key at all -- it just says which of the two numbers
    it is showing.
    """
    if not exact:
        avg_in = sum(
            _estimate_tokens(SYSTEM) + _estimate_tokens(p) for p in prompts
        ) / len(prompts)
    else:
        import anthropic

        client = anthropic.Anthropic()
        # A sample, not every prompt: they share a shape, and count_tokens is
        # free but not instant.
        counts = []
        for p in prompts[: min(5, len(prompts))]:
            r = client.messages.count_tokens(
                model=model,
                system=SYSTEM,
                messages=[{"role": "user", "content": p}],
            )
            counts.append(r.input_tokens)
        avg_in = sum(counts) / len(counts)
    avg_out = ASSUMED_THINKING_TOKENS + ASSUMED_ANSWER_TOKENS
    in_rate, out_rate = PRICES[model]
    n = len(prompts)
    cost = n * (avg_in * in_rate + avg_out * out_rate) / 1_000_000
    if use_batch:
        cost /= 2
    return {
        "calls": n,
        "avg_input_tokens": avg_in,
        "assumed_output_tokens": avg_out,
        "total_usd": cost,
        "exact": exact,
    }


def run_batch(prompts: list[str], model: str, effort: str) -> dict[int, dict]:
    import anthropic

    client = anthropic.Anthropic()
    requests = [
        {
            "custom_id": f"sig-{i}",
            "params": {
                "model": model,
                "max_tokens": 2000,
                "system": SYSTEM,
                "output_config": {
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                "messages": [{"role": "user", "content": p}],
            },
        }
        for i, p in enumerate(prompts)
    ]
    batch = client.messages.batches.create(requests=requests)
    print(f"  batch {batch.id} submitted, waiting...")
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        print(f"    {batch.processing_status}... ({batch.request_counts})")
        time.sleep(20)

    out: dict[int, dict] = {}
    for result in client.messages.batches.results(batch.id):
        i = int(result.custom_id.split("-")[1])
        if result.result.type != "succeeded":
            print(f"    signal {i}: {result.result.type}")
            continue
        text = "".join(
            b.text for b in result.result.message.content if b.type == "text"
        )
        try:
            out[i] = json.loads(text)
        except json.JSONDecodeError:
            print(f"    signal {i}: unparseable answer")
    return out


def report_bands(rows: list[tuple[float, float]], title: str) -> None:
    print(f"\n  {title}")
    header = (f"    {'band':>8} {'trades':>7} {'win%':>7} {'net':>10} "
              f"{'per trade':>10} {'pf':>6}")
    print(header)
    print("    " + "-" * (len(header) - 4))
    for lo, hi in BANDS:
        bucket = [pnl for s, pnl in rows if lo <= s < hi]
        if not bucket:
            print(f"    {f'{lo}-{hi - 1}':>8} {0:>7} {'-':>7} {'-':>10} "
                  f"{'-':>10} {'-':>6}")
            continue
        wins = [p for p in bucket if p > 0]
        loss = abs(sum(p for p in bucket if p <= 0))
        pf = (sum(wins) / loss) if loss else float("inf")
        print(f"    {f'{lo}-{hi - 1}':>8} {len(bucket):>7} "
              f"{len(wins) / len(bucket) * 100:>6.1f}% {sum(bucket):>+10.2f} "
              f"{sum(bucket) / len(bucket):>+10.2f} {pf:>6.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spend", action="store_true",
                    help="actually call the API (costs money; without this the "
                         "script only prices the run)")
    ap.add_argument("--model", default="claude-opus-5-5", choices=sorted(PRICES))
    ap.add_argument("--effort", default="low",
                    choices=["low", "medium", "high", "xhigh", "max"],
                    help="low is right for bulk scoring: 125 short judgements, "
                         "not one hard problem")
    ap.add_argument("--limit", type=int, default=0,
                    help="score only the first N signals (0 = all)")
    ap.add_argument("--no-batch", action="store_true",
                    help="send one at a time instead of the half-price batch")
    args = ap.parse_args()

    print("Replaying 310 days to collect the signals...")
    signals = collect_signals(args.limit)
    if not signals:
        print("No signals captured - nothing to score.")
        return 1
    print(f"  {len(signals)} signals with known outcomes")

    prompts = [build_prompt(s) for s in signals]
    print("\nExample prompt:")
    print("  " + "\n  ".join(prompts[0].splitlines()[:6]) + "\n  ...")

    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    print(f"\nPricing {len(prompts)} calls on {args.model}"
          f"{'' if args.no_batch else ' (batch, half price)'}...")
    est = price_it(prompts, args.model, not args.no_batch, exact=have_key)
    how = "measured" if est["exact"] else "estimated, no API key needed"
    print(f"  input  ~{est['avg_input_tokens']:.0f} tokens/call ({how})")
    print(f"  output ~{est['assumed_output_tokens']:.0f} tokens/call (assumed, "
          f"includes thinking)")
    print(f"\n  ESTIMATED TOTAL: ${est['total_usd']:.2f}")
    if not est["exact"]:
        print("  (rough: set ANTHROPIC_API_KEY for the measured figure, which")
        print("   is still free to check)")

    if not args.spend:
        print("\nNothing has been charged. This was a dry run.")
        print("To actually run it, add --spend")
        return 0

    if not have_key:
        print("\nNo ANTHROPIC_API_KEY set, so nothing can be sent.")
        return 1

    print("\nSending...")
    if args.no_batch:
        print("  --no-batch is not implemented; use the batch path.")
        return 1
    scored = run_batch(prompts, args.model, args.effort)
    if not scored:
        print("Nothing came back.")
        return 1

    rows, first_half, second_half, paired = [], [], [], []
    half = len(signals) // 2
    for i, sig in enumerate(signals):
        got = scored.get(i)
        if not got:
            continue
        pair = (float(got["score"]), float(sig["pnl"]))
        rows.append(pair)
        (first_half if i < half else second_half).append(pair)
        # Paired here, inside the same loop, so the two scores always belong
        # to the same signal. Zipping two separately-filtered lists afterwards
        # silently misaligns them the moment one call fails.
        if sig.get("arithmetic_score") is not None:
            paired.append((float(got["score"]), float(sig["arithmetic_score"])))

    print(f"\n{len(rows)} signals scored and settled.")
    report_bands(rows, "full period")
    report_bands(first_half, "first half")
    report_bands(second_half, "second half")

    if len(paired) > 2:
        n = len(paired)
        mean_llm = sum(a for a, _ in paired) / n
        mean_ari = sum(b for _, b in paired) / n
        cov = sum((a - mean_llm) * (b - mean_ari) for a, b in paired)
        va = sum((a - mean_llm) ** 2 for a, _ in paired) ** 0.5
        vb = sum((b - mean_ari) ** 2 for _, b in paired) ** 0.5
        if va and vb:
            print(f"\n  correlation with the arithmetic score: "
                  f"{cov / (va * vb):+.2f}")
            print("  (near +1 means it is agreeing with the scorer you already")
            print("   have, so it would add cost without adding information)")

    out = ROOT / "data" / "llm_scores.json"
    out.write_text(json.dumps(
        [{"ts": s["ts"], "side": s["side"], "pnl": s["pnl"],
          "llm": scored.get(i), "arithmetic": s["arithmetic_score"]}
         for i, s in enumerate(signals)], indent=2), encoding="utf-8")
    print(f"\n  raw scores written to {out}")
    print("\n  What to look for: expectancy rising with the band, in BOTH")
    print("  halves. Four changes have now failed that test; this is the")
    print("  same bar, not a lower one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
