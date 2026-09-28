"""Strategy package.

Importing this package registers every built-in strategy, so ``base.create()``
can resolve a name straight from config.
"""

from . import donchian_breakout, ema_pullback  # noqa: F401  (import for side effects)
from .base import BarContext, Strategy, available, create, get

__all__ = ["BarContext", "Strategy", "available", "create", "get"]
