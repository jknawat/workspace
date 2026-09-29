"""Broker adapters. Resolved by name from ``[engine].broker``."""

from __future__ import annotations

from typing import Any

from .base import Broker, BrokerError, ClosedTrade
from .paper import DEFAULT_SPECS, PaperBroker

__all__ = ["DEFAULT_SPECS", "Broker", "BrokerError", "ClosedTrade", "PaperBroker", "build"]


def build(name: str, **kwargs: Any) -> Broker:
    key = name.lower()
    if key == "paper":
        allowed = {"balance", "currency", "slippage_points", "specs", "spread_points_map"}
        return PaperBroker(**{k: v for k, v in kwargs.items() if k in allowed})
    if key == "mt5":
        from .mt5 import MT5Broker  # imported here so non-Windows hosts stay clean

        allowed = {"credentials", "broker_utc_offset_hours", "magic", "deviation_points"}
        return MT5Broker(**{k: v for k, v in kwargs.items() if k in allowed})
    raise BrokerError(f"unknown broker '{name}'; available: paper, mt5")
