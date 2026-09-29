"""Strategy package.

Importing this package registers every built-in strategy and filter, so
``base.create()`` and ``filters.build_chain()`` can resolve names straight from
config.
"""

from . import (  # noqa: F401
    donchian_breakout,
    ema_pullback,
    ict_confluence,
    ict_filters,
)
from .base import BarContext, Strategy, available, create, get

__all__ = ["BarContext", "Strategy", "available", "create", "get"]
