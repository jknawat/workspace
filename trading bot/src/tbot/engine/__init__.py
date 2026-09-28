"""Execution engine: one pipeline, three modes (backtest / paper / live)."""

from .backtest import BacktestReport, run_backtest
from .core import StepResult, SymbolRuntime, TradeEngine
from .exits import ExitAction, ExitManager, ExitPolicy
from .runner import Runner, RunnerStats

__all__ = [
    "BacktestReport",
    "ExitAction",
    "ExitManager",
    "ExitPolicy",
    "Runner",
    "RunnerStats",
    "StepResult",
    "SymbolRuntime",
    "TradeEngine",
    "run_backtest",
]
