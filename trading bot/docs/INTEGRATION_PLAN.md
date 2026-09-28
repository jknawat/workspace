# Integration plan — combining six repositories into one local bot

**Status: planning. Nothing in this document is built yet.**
Last updated: 2026-09-28.

Working notes for the next phase of `tbot`: what was analysed, what was decided,
what is still open, and what blocks progress. `ARCHITECTURE.md` describes what
exists today; this file describes where it is going.

---

## 1. The goal, in the user's words

> "the local AI bot trading that and run with computer and use the live the MT5
> desktop to analyze"

Read as three requirements:

1. **Local** — runs on the user's own Windows PC, not a cloud service.
2. **Uses the live MT5 desktop for analysis** — MetaTrader 5 is the analysis
   engine and data source, not just an order gateway.
3. **AI** — clarified below; the decision is made.

---

## 2. Decisions

### Made

| decision | choice | date |
|---|---|---|
| What "AI" means | **Classical ML scoring, trained on the user's own trade journal.** scikit-learn / XGBoost, local. Rule-based signals get a 0–1 quality score; low scores are vetoed, high scores are sized up within the hard risk cap. Not an LLM, not a black-box trader. | 2026-09-28 |

### Open — these change what gets built

1. **Account type** — prop-firm challenge (FTMO/The5ers…) vs personal live vs
   demo-only. Prop firm means a much stricter guard set: hard daily drawdown,
   equity-based total drawdown, news blackout, restart-safe state, consistency
   rules. This is the single biggest branch in the plan.
2. **Strategy basis** — ICT/SMC confluence from the MQL5 library, or ICT plus
   the existing `ema_pullback`, or ICT as a *filter* on `ema_pullback`, or
   following external signal channels with own risk rules.
3. **Control surface** — Telegram bot, local web dashboard, CLI only, MT5 chart
   overlay, or some combination.

The user asked to clarify these rather than answer immediately. Discussion was
paused here.

---

## 3. What is in each repository

Analysed at the commits below. Line counts are actual.

### xxvw/ICT_Library_MQ5 — `2b78e7d`, 2026-09-20 · MIT

171 files, 40 `.mqh`/`.mq5`. An MQL5 library that detects SMC/ICT structures
**inside MT5, on closed candles, in broker time**, and exports them as a
versioned JSON snapshot.

- Concepts: swings, BOS, CHoCH, order blocks, FVG, breaker blocks, liquidity,
  premium/discount, OTE, killzones, displacement, MSS, IFVG, BPR,
  previous-day/week highs and lows, session highs/lows, daily/weekly opening
  gaps, SMT divergence, Power of Three.
- `Experts/SMC_Snapshot_Export.mq5` — attaches to a chart, **places no orders**,
  writes a snapshot to MT5's shared `Terminal/Common/Files/` on each bar close.
- `schemas/snapshot.schema.json` — JSON Schema draft 2020-12. Records carry
  `id`, `concept`, `source_time`, `confirmed_at`, `updated_at`, `direction`,
  `lower`, `upper`, `state`, `active`, `related_ids`, `period_start`,
  `period_end`, `reference_price`, `comparison_price`, `strength`, `reason`.
  Snapshot status is one of `READY|PARTIAL|NOT_READY|ERROR|DISABLED`, reported
  per module as well as overall.
- `time_basis` is `"broker"` — timestamps have **no UTC suffix**. Conversion is
  the consumer's job. `tbot` already centralises this in
  `engine.broker_utc_offset_hours`.
- Reference readers in Python, TypeScript, C#, Go, Java, Rust; docs for rules,
  data contract, architecture; ONNX wrapper; visualizer indicator.

**Verdict: the most valuable of the five, and the direct answer to "use the live
MT5 desktop to analyze".** MT5 does the pattern detection; Python reads the
result. No re-implementation of order-block logic in Python, and the bot trades
exactly what the chart draws.

### aleemshahad/nexus-auto-system — `37c1194`, 2026-08-24 · ⚠️ no license

21,894 lines of Python plus a Next.js dashboard and a Node/TypeScript gateway.

- Event-driven: EventBus → Redis pub/sub → Node WebSocket gateway → React UI.
- Six agents (trading, risk, strategy manager, market intelligence, monitoring,
  social media); five strategies including `smc_strategy.py` (638 lines).
- `trading/risk/` — `risk_engine.py` (872 lines) plus `daily_loss_guard`,
  `drawdown_guard`, `correlation_checker`. States the rule that matters: *no
  strategy, model, browser agent or dashboard command may bypass the risk
  engine.*
- `ai/` — `feature_engine`, `meta_labeling`, `signal_model` (heuristic now,
  sklearn/xgboost "Phase 2"), `reinforcement/strategy_selector`.
- Browser scrapers via DrissionPage: ForexFactory, Investing, TradingView,
  social media, WhatsApp.

**Verdict: the best blueprint of the five, and the closest match to the user's
ambition — but no license file means all rights reserved. Take the architecture
and the guard taxonomy; do not copy the code.** Also note the stack cost: Redis
+ Node + Next.js + FastAPI is a lot of moving parts for a single-user desktop
bot.

### usmanch96/mt5-telegram-trade-assistant — `b8a5f88`, 2026-07-27 · MIT

5,914 lines. Telegram front end for manual MT5 trading.

- `mt5/executor.py` — `get_filling_mode()`, `translate_error_code()`,
  `send_market_order`, `close_position` (supports partial volume),
  `modify_position_stops`, `send_pending_order`, `cancel_pending_order`.
- `mt5/risk_calculator.py` — five sizing functions including
  `calculate_layer_risk_stack` for layered entries.
- `services/trail_service.py` — trailing stops. `bot/handlers/positions.py`
  (842 lines) and `batch.py` (547) — per-position and bulk operations:
  partial close, move to break-even, edit SL/TP, trailing, close-all,
  close-profit-only, cancel pendings.
- Whitelist-only auth, including a guard on inline callback replay.

**Verdict: the best position-lifecycle and operator code, and MIT-licensed.**
`tbot` currently only opens positions and lets SL/TP resolve them; this is the
missing half.

### KAPKEPOT/tonpo-bot — `dac1a20`, 2026-06-19 · MIT

7,260 lines. A Telegram signal-executor product.

- `core/parser.py` (628 lines) — multi-format signal parser: JSON, standard,
  compact, MT4, TradingView.
- `core/risk_engine.py` (544), `core/validators.py` (385), `core/models.py` (689).
- PostgreSQL + Alembic (9 migrations), Redis, Docker, subscription tiers,
  crypto payment verification, admin panel.
- **Trades through a remote "Tonpo Gateway", not a local MT5 terminal** — the
  opposite of this project's premise.

**Verdict: useful if external signal-following is wanted (the parser is the
reusable part). The SaaS plumbing — payments, tiers, Postgres — is product
scaffolding this project does not need.**

### HDAVEEE/MT5-Bot-Audit — `be4efe4`, 2025-07-29 · ⚠️ no license

11 files. **The bot itself is not published.** `phase1_trader_shell.py` is a
47-line stub with the strategy deliberately commented out.

Value is the documented prop-firm checklist:

- daily drawdown cap, total drawdown cap, session/symbol trade limits;
- spread checker; dynamic symbol watchlist with delisting of offline symbols;
- restart-safe checkpointing; CSV audit log of trades *and skipped reasons*;
- explicit handling of MT5 retcodes 10027, 10030, 10019;
- Windows Task Scheduler + `.bat` orchestration.

**Verdict: ideas only, no usable code. The checklist is genuinely useful if the
target is a prop-firm challenge.**

---

## 4. Licensing position

| repo | license | what may be taken |
|---|---|---|
| ICT_Library_MQ5 | MIT | code, with attribution |
| mt5-telegram-trade-assistant | MIT | code, with attribution |
| tonpo-bot | MIT | code, with attribution |
| nexus-auto-system | **none** | ideas and architecture only — **not code** |
| MT5-Bot-Audit | **none** | ideas and checklist only — **not code** |

A repository with no license is "all rights reserved" by default. Architecture,
taxonomies and approaches are not copyrightable; source text is. Any MIT code
adopted needs its copyright notice preserved — plan for a `THIRD_PARTY.md`.

---

## 5. Target architecture

```
MT5 desktop (user's PC)
 ├─ SMC_Snapshot_Export.mq5   ──►  Common/Files/*.json   ICT/SMC structures
 └─ MetaTrader5 Python API    ──►  bars, ticks, specs, orders
                │
        ┌───────▼─────────────────────────────────────────┐
        │ tbot                                            │
        │  data/      bars + SnapshotFeed (ICT JSON)      │ ← ICT_Library
        │  strategy/  ema_pullback, donchian,             │
        │             ict_confluence + ICT filters        │ ← ICT_Library
        │  ai/        features → meta-labeling → score    │ ← nexus (ideas)
        │  risk/      budget + guard chain:               │ ← nexus + Audit
        │             daily DD, total DD, correlation,    │
        │             spread, news blackout, prop rules   │
        │  engine/    entries + exit policies:            │ ← telegram-assistant
        │             trailing, break-even, partials      │
        │  journal/   every signal, veto, fill, exit      │
        └───────┬─────────────────────────────────────────┘
                ├─ CLI (backtest / paper / live)
                └─ Telegram: alerts, /status, /closeall, kill-switch
```

Principles carried forward from the existing build:

- The risk layer is a **gatekeeper nothing bypasses** — not a strategy, not the
  ML model, not a Telegram command.
- Strategies stay pure functions of bar history plus snapshot; they propose,
  they never size or route.
- Any UI is a **reader** of `TradeEngine.state()` and the journal.
- One pipeline serves backtest, paper and live.

### Where the ML actually sits

```
ICT rule-based signal  →  feature vector  →  model score 0..1
                                              │
                        score < floor  ──────►  veto (journalled with reason)
                        score ≥ floor  ──────►  risk budget × f(score), capped
```

Trained offline from the journal using triple-barrier meta-labeling: for each
historical signal, did price hit the target, the stop, or time out first? That
is the label. **This requires journal history that does not exist yet** — so the
first phase is necessarily rules-only, with everything logged for later
training.

---

## 6. Staged build plan

Each stage is independently useful and independently testable.

| # | stage | delivers | depends on |
|---|---|---|---|
| 0 | **Bring-up** | Python 3.11/3.12 installed, `pytest` green, `tbot backtest` runs on synthetic data | — |
| 1 | **MT5 live link** | `tbot specs` captures real contract specs; paper mode on live MT5 bars | 0, MT5 installed |
| 2 | **ICT snapshot feed** | `SMC_Snapshot_Export` EA installed; `data/snapshot.py` reads and validates the JSON contract; snapshot visible in `tbot status` | 1 |
| 3 | **ICT strategy + filters** | `ict_confluence` strategy; filters for killzone, order-block containment, unfilled FVG, HTF bias, liquidity sweep | 2, strategy decision |
| 4 | **Guard chain** | composable risk guards: daily DD, total DD (equity-based), correlation, spread, news blackout, restart-safe state | 1, account decision |
| 5 | **Exit policies** | trailing stop, move-to-break-even, partial take-profit — simulated in backtest *and* executed live through the same interface | 1 |
| 6 | **Operator surface** | Telegram alerts + `/status` `/positions` `/closeall` + kill-switch; optional approve-before-entry | 5, control decision |
| 7 | **ML scoring** | feature engine, triple-barrier labeller over the journal, trained model, score-gated entries and score-scaled sizing | 3–5 plus real journal history |

Stages 3, 4 and 6 are gated on the three open decisions in §2.

---

## 7. Blockers

1. **No Python interpreter on this machine.** Only the Windows Store stub
   (`WindowsApps/python.exe`). Nothing can run — not the bot, not the test
   suite already written. Needs **Python 3.11 or 3.12, 64-bit, from
   python.org**; not 3.13+, because the `MetaTrader5` package lags new releases.
2. **The existing test suite has never been executed.** It was written without
   an interpreter available. Treat the first `pytest` run as part of stage 0.
3. **MT5 terminal presence unconfirmed** — stages 1+ need MetaTrader 5 installed
   and logged in on this PC, with algorithmic trading enabled.

---

## 8. Next actions

- [ ] User answers the three open decisions in §2.
- [ ] Install Python 3.11/3.12 (64-bit), then `pytest` and fix whatever the
      first run surfaces.
- [ ] Confirm MT5 is installed, which broker/server, and which symbols matter.
- [ ] Begin stage 2 — it is valuable regardless of how the open decisions land.
