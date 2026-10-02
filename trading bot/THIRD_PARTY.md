# Third-party components

## SMC/ICT Library for MetaTrader 5

- Source: <https://github.com/xxvw/ICT_Library_MQ5>
- License: MIT — Copyright (c) 2025-2026 SMC_ICT_Library Project
- Used for: the in-terminal detection of SMC/ICT structures and the JSON
  snapshot contract that `tbot.data.snapshot` reads.

Most of the MQL5 library is **not vendored**; it is installed into MetaTrader 5
separately (see `docs/MT5_SNAPSHOT_SETUP.md`). What this project contains is an
independent Python reader written against the library's published JSON Schema
and data contract, plus a test fixture authored here in that format.

**Three files are vendored**, under `mql5/`, and keep the MIT notice they
carry:

| file | why it is pinned here |
|---|---|
| `Experts/SMC_Snapshot_Export.mq5` | publishes the snapshot the bot reads |
| `Include/SMC/Core/SmcSnapshot.mqh` | defines the schema version and contract |
| `Include/SMC/Utils/SnapshotExporter.mqh` | writes the JSON the reader parses |

These three *are* the contract `tbot.data.snapshot` is written against, so an
upstream change to them silently changes what the bot reads. Pinning them means
a fresh clone on another machine compiles the same exporter this one runs,
rather than whatever upstream happens to hold that day. The rest of the library
is still installed from upstream.

MIT permits this; the copyright notice stays with the files.

## Repositories studied, not copied

The design of the risk guard chain, the position-lifecycle work planned for
stage 5, and the signal-parser option in stage 7 were informed by reading:

| project | license | use made of it |
|---|---|---|
| [usmanch96/mt5-telegram-trade-assistant](https://github.com/usmanch96/mt5-telegram-trade-assistant) | MIT | reference for MT5 filling modes, retcode handling, partial close, trailing stops. Any adapted code must carry its notice. |
| [KAPKEPOT/tonpo-bot](https://github.com/KAPKEPOT/tonpo-bot) | MIT | reference for multi-format signal parsing. Same condition. |
| [aleemshahad/nexus-auto-system](https://github.com/aleemshahad/nexus-auto-system) | **none** | architecture and risk-guard taxonomy only. No code taken, and none may be. |
| [HDAVEEE/MT5-Bot-Audit](https://github.com/HDAVEEE/MT5-Bot-Audit) | **none** | prop-firm audit checklist only. No code taken, and none may be. |
| [ilahuerta-IA/mt5_live_trading_bot](https://github.com/ilahuerta-IA/mt5_live_trading_bot) | MIT | the original reference system analysed in `ARCHITECTURE.md`. Ideas only; no code taken. |

A repository published without a license is "all rights reserved" by default.
Ideas, architecture and taxonomies are not copyrightable; source text is.
