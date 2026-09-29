"""Reading SMC/ICT snapshots off disk from MetaTrader 5's shared folder.

The export EA writes to MT5's *common* data folder — shared by every terminal
installation on the machine — under a configurable subfolder:

    <common>/Files/<folder>/<sanitised symbol>_<timeframe>.json

On Windows ``<common>`` is ``%APPDATA%\\MetaQuotes\\Terminal\\Common``. The EA
publishes atomically (temp file, then ``FileMove`` with rewrite), so a reader
never sees a half-written file under normal operation — but this store retries
once on a decode error anyway, because "normal operation" is not a guarantee
worth betting an order on.

It also holds an empty ``<name>.json.lock`` beside each snapshot to claim sole
ownership of that destination. Those are ignored here.

Caching is by (mtime, size): the file is only re-parsed when the terminal has
actually republished, so polling every second costs almost nothing.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..obs import log as obs_log
from .snapshot import Snapshot, SnapshotError

#: Minutes per timeframe token, used to judge snapshot staleness.
TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440,
}

SAFE_SYMBOL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-."
)


def sanitise_symbol(symbol: str) -> str:
    """Mirror the export EA's filename encoding.

    Brokers put ``/``, ``:``, ``#`` and spaces in symbol names, any of which
    would turn a filename into a path. The EA encodes every character outside
    ``[A-Za-z0-9.-]`` as ``_xxxx`` (lower-case hex of the UTF-16 code unit);
    this must match exactly or the file is simply not found.
    """
    if not symbol:
        return "symbol"
    out = "".join(c if c in SAFE_SYMBOL_CHARS else f"_{ord(c):04x}" for c in symbol)
    return out or "symbol"


def default_common_files_dir() -> Path | None:
    """Best guess at MT5's shared ``Common/Files`` folder.

    Returns ``None`` rather than a wrong path when it cannot be determined —
    a misconfigured path should be an explicit error, not a silent empty read.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
        if candidate.is_dir():
            return candidate
    # Wine / non-standard layouts occasionally used for MT5 on Linux and macOS.
    for guess in (
        Path.home() / ".wine/drive_c/users" / os.environ.get("USER", "")
        / "AppData/Roaming/MetaQuotes/Terminal/Common/Files",
        Path.home() / "Library/Application Support/MetaQuotes/Terminal/Common/Files",
    ):
        if guess.is_dir():
            return guess
    return None


@dataclass(slots=True)
class CacheEntry:
    snapshot: Snapshot
    mtime_ns: int
    size: int
    read_at: datetime


@dataclass(slots=True)
class SnapshotStore:
    """Loads and caches snapshots for many symbols from one export folder."""

    directory: Path
    broker_utc_offset_hours: float = 0.0
    timeframe: str = "M5"
    max_age: timedelta | None = None
    _cache: dict[str, CacheEntry] = field(default_factory=dict, init=False)
    _misses: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)
        if self.max_age is None:
            minutes = TIMEFRAME_MINUTES.get(self.timeframe.upper(), 5)
            # Three bars: tolerates one missed publish and a slow terminal,
            # without letting yesterday's structure look current.
            self.max_age = timedelta(minutes=minutes * 3)

    @classmethod
    def from_settings(
        cls,
        *,
        folder: str = "SMC_Export",
        common_path: str = "",
        timeframe: str = "M5",
        max_age_minutes: float = 0.0,
        broker_utc_offset_hours: float = 0.0,
    ) -> SnapshotStore:
        """Build a store from plain settings, resolving MT5's shared folder.

        Takes primitives rather than a config object so the data layer keeps no
        dependency on the config layer.
        """
        if common_path:
            base = Path(common_path)
            if base.name.lower() != "files" and (base / "Files").is_dir():
                base = base / "Files"  # accept either Common or Common/Files
        else:
            found = default_common_files_dir()
            if found is None:
                raise SnapshotError(
                    "could not locate MetaTrader 5's shared Common/Files folder; set "
                    "[snapshot].common_path explicitly (MT5: File -> Open Data Folder)"
                )
            base = found
        return cls(
            directory=base / folder if folder else base,
            broker_utc_offset_hours=broker_utc_offset_hours,
            timeframe=timeframe,
            max_age=timedelta(minutes=max_age_minutes) if max_age_minutes > 0 else None,
        )

    # ------------------------------------------------------------------ #
    # Paths
    # ------------------------------------------------------------------ #

    def path_for(self, symbol: str, timeframe: str | None = None) -> Path:
        tf = (timeframe or self.timeframe).upper()
        return self.directory / f"{sanitise_symbol(symbol)}_{tf}.json"

    def exists(self, symbol: str, timeframe: str | None = None) -> bool:
        return self.path_for(symbol, timeframe).is_file()

    def discover(self) -> list[Path]:
        """Every snapshot file in the folder, ignoring lock files."""
        if not self.directory.is_dir():
            return []
        return sorted(
            p for p in self.directory.glob("*.json") if not p.name.endswith(".lock")
        )

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    def load(self, symbol: str, timeframe: str | None = None) -> Snapshot:
        """Parse the snapshot for a symbol, using the cache when unchanged.

        Raises :class:`SnapshotError` if the file is missing or malformed.
        """
        path = self.path_for(symbol, timeframe)
        try:
            stat = path.stat()
        except OSError as exc:
            raise SnapshotError(
                f"no snapshot for {symbol} {timeframe or self.timeframe} at {path} -- "
                f"is SMC_Snapshot_Export attached to that chart?"
            ) from exc

        key = str(path)
        cached = self._cache.get(key)
        if cached and cached.mtime_ns == stat.st_mtime_ns and cached.size == stat.st_size:
            return cached.snapshot

        snapshot = self._read(path)
        self._cache[key] = CacheEntry(
            snapshot=snapshot,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            read_at=datetime.now(timezone.utc),
        )
        self._misses.pop(symbol.upper(), None)
        return snapshot

    def _read(self, path: Path) -> Snapshot:
        last: SnapshotError | None = None
        for attempt in (0, 1):
            try:
                text = path.read_text(encoding="utf-8")
                return Snapshot.from_json(
                    text,
                    broker_utc_offset_hours=self.broker_utc_offset_hours,
                    source_path=str(path),
                )
            except (SnapshotError, OSError, UnicodeError) as exc:
                last = exc if isinstance(exc, SnapshotError) else SnapshotError(str(exc))
                if attempt == 0:
                    time.sleep(0.05)  # a torn read during republish; try once more
        raise last  # type: ignore[misc]

    def get(self, symbol: str, timeframe: str | None = None) -> Snapshot | None:
        """Like :meth:`load` but returns ``None`` instead of raising.

        The failure reason is logged once per distinct message per symbol, so a
        permanently missing export does not fill the log on every poll.
        """
        try:
            return self.load(symbol, timeframe)
        except SnapshotError as exc:
            key = symbol.upper()
            message = str(exc)
            if self._misses.get(key) != message:
                self._misses[key] = message
                obs_log.get("snapshot").warning(
                    "snapshot unavailable for %s: %s",
                    symbol, message,
                    extra={"symbol": symbol, "event": "snapshot_unavailable"},
                )
            return None

    # ------------------------------------------------------------------ #
    # Freshness
    # ------------------------------------------------------------------ #

    def fresh(
        self, symbol: str, now: datetime | None = None, timeframe: str | None = None
    ) -> Snapshot | None:
        """A snapshot only if it is present, usable and not stale.

        This is what trading code should call. A stale snapshot is worse than
        none: it looks authoritative while describing a market that has moved.
        """
        snapshot = self.get(symbol, timeframe)
        if snapshot is None:
            return None
        moment = now or datetime.now(timezone.utc)
        assert self.max_age is not None
        if not snapshot.usable:
            obs_log.get("snapshot").warning(
                "snapshot for %s is %s, not usable: %s",
                symbol, snapshot.status, "; ".join(snapshot.problems()),
                extra={"symbol": symbol, "event": "snapshot_not_ready"},
            )
            return None
        if snapshot.is_stale(moment, self.max_age):
            age = snapshot.age(moment)
            obs_log.get("snapshot").warning(
                "snapshot for %s is stale (age %s, limit %s) -- is MT5 running?",
                symbol, age, self.max_age,
                extra={"symbol": symbol, "event": "snapshot_stale"},
            )
            return None
        return snapshot

    def status_line(self, symbol: str, now: datetime | None = None) -> str:
        """One-line human summary, used by ``tbot snapshot`` and diagnostics."""
        path = self.path_for(symbol)
        if not path.is_file():
            return f"{symbol:<10} MISSING   {path}"
        try:
            snapshot = self.load(symbol)
        except SnapshotError as exc:
            return f"{symbol:<10} INVALID   {exc}"
        moment = now or datetime.now(timezone.utc)
        age = snapshot.age(moment)
        age_text = "unknown" if age is None else f"{age.total_seconds():.0f}s"
        counts = snapshot.counts()
        total = sum(counts.values())
        return (
            f"{symbol:<10} {snapshot.status:<9} tf={snapshot.timeframe} "
            f"age={age_text} active_records={total} bias={snapshot.bias()}"
        )
