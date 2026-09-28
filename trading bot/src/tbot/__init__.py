"""tbot -- a modular, broker-agnostic trading bot.

Layering (each layer may only import from the ones above it)::

    core        value objects + indicators   (no I/O, no dependencies)
    config      declarative TOML -> validated objects
    strategy    pure decision logic over bars
    risk        sizing + portfolio permissions
    broker      ports and adapters (paper, mt5)
    data        bar feeds (csv, broker, in-memory)
    engine      the one pipeline that wires the above
    journal/obs persistence and structured logs
    cli         entry points
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
