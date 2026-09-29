"""Bar feeds.

Data sourcing is separated from order routing on purpose: a backtest reads CSV
and routes to the simulator, while paper mode reads *live* MT5 bars and still
routes to the simulator. Those combinations are only possible because the two
concerns are different objects.
"""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from pathlib import Path

from ..core.types import Bar

TS_COLUMNS = ("ts", "time", "datetime", "date", "timestamp")


class BarFeed(ABC):
    @abstractmethod
    def history(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        """Most recent ``count`` *closed* bars, oldest first."""


class CsvFeed(BarFeed):
    """Reads ``<dir>/<SYMBOL>_<TIMEFRAME>.csv`` (or an explicit path per symbol).

    Accepts any of ``ts``/``time``/``datetime``/``date``/``timestamp`` as the
    timestamp column. Naive timestamps are treated as UTC.
    """

    def __init__(
        self, directory: str | Path = "data", paths: dict[str, str | Path] | None = None
    ) -> None:
        self.directory = Path(directory)
        self.paths = {k.strip(): Path(v) for k, v in (paths or {}).items()}
        self._cache: dict[tuple[str, str], list[Bar]] = {}

    def path_for(self, symbol: str, timeframe: str) -> Path:
        sym = symbol.strip()
        if sym in self.paths:
            return self.paths[sym]
        return self.directory / f"{sym}_{timeframe.upper()}.csv"

    def load(self, symbol: str, timeframe: str) -> list[Bar]:
        key = (symbol.upper(), timeframe.upper())
        if key in self._cache:
            return self._cache[key]
        path = self.path_for(symbol, timeframe)
        if not path.is_file():
            raise FileNotFoundError(f"no CSV data for {symbol} {timeframe}: {path}")
        bars: list[Bar] = []
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError(f"{path}: empty file")
            lower = {name.lower().strip(): name for name in reader.fieldnames}
            ts_col = next((lower[c] for c in TS_COLUMNS if c in lower), None)
            if ts_col is None:
                raise ValueError(
                    f"{path}: no timestamp column (looked for {', '.join(TS_COLUMNS)})"
                )
            for line, row in enumerate(reader, start=2):
                try:
                    bars.append(
                        Bar.from_row(
                            {
                                "ts": row[ts_col],
                                "open": row[lower["open"]],
                                "high": row[lower["high"]],
                                "low": row[lower["low"]],
                                "close": row[lower["close"]],
                                "volume": row.get(lower.get("volume", ""), 0) or 0,
                            }
                        )
                    )
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"{path}:{line}: {exc}") from exc
        bars.sort(key=lambda b: b.ts)
        self._cache[key] = bars
        return bars

    def history(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        bars = self.load(symbol, timeframe)
        return bars[-count:] if count > 0 else bars


class BrokerFeed(BarFeed):
    """Live bars pulled through whatever broker adapter is connected."""

    def __init__(self, broker) -> None:  # untyped: avoids an import cycle
        self.broker = broker

    def history(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        return self.broker.bars(symbol, timeframe, count)


class ListFeed(BarFeed):
    """In-memory feed, used by tests and by the backtester's replay loop."""

    def __init__(self, bars: dict[str, list[Bar]]) -> None:
        self.bars = {k.strip(): v for k, v in bars.items()}

    def history(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        series = self.bars.get(symbol.strip(), [])
        return series[-count:] if count > 0 else list(series)
