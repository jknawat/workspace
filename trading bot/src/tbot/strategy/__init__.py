"""Strategy package.

Importing this package registers every built-in strategy and filter, so
``base.create()`` and ``filters.build_chain()`` can resolve names straight from
config.
"""

from . import donchian_breakout, ema_pullback, ict_confluence  # noqa: F401
from . import ict_filters  # noqa: F401  (registers the ICT filters)
from .base import BarContext, Strategy, available, create, get

__all__ = ["BarContext", "Strategy", "available", "create", "get"]
