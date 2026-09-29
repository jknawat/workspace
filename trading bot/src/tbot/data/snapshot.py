"""SMC/ICT snapshot contract — parsing and validation.

MetaTrader 5 does the pattern detection. The ``SMC_Snapshot_Export`` expert
advisor from the SMC/ICT library (MIT, see THIRD_PARTY.md) evaluates closed
candles inside the terminal and writes a schema-versioned JSON snapshot; this
module turns that file into typed objects.

Why read MT5's output instead of recomputing in Python:

* the bot trades exactly what the chart draws — no second implementation to
  drift out of agreement;
* order blocks, FVGs, liquidity and displacement are fiddly to get right, and
  the library's rules are already documented and tested;
* detection runs on the terminal's own bar closes, so there is no
  "did my candle boundary match the broker's?" question.

**Time basis.** Snapshot timestamps are broker wall-clock with *no* timezone
suffix — the contract's ``time_basis`` is always ``"broker"``. Every timestamp
is converted here to real UTC using the engine's single
``broker_utc_offset_hours`` setting, and the original string is preserved for
display. Nothing downstream should ever see a naive datetime.

**Validation is strict and fails closed.** A malformed or unexpected snapshot
raises rather than yielding a half-populated object: trading on a
misunderstood structure file is worse than not trading.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_MAJOR = 1
SCHEMA_VERSION_RE = re.compile(r"^1\.[0-9]+$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

STATUSES = frozenset({"READY", "PARTIAL", "NOT_READY", "ERROR", "DISABLED"})
DIRECTIONS = frozenset({"bullish", "bearish", "neutral"})

CONCEPTS = frozenset(
    {
        "SWING_HIGH", "SWING_LOW", "BOS", "CHOCH", "ORDER_BLOCK", "FVG", "LIQUIDITY",
        "PREMIUM_DISCOUNT", "OTE", "KILL_ZONE", "BREAKER", "DISPLACEMENT", "MSS",
        "IFVG", "BPR", "PREVIOUS_DAY_HIGH", "PREVIOUS_DAY_LOW", "PREVIOUS_WEEK_HIGH",
        "PREVIOUS_WEEK_LOW", "SESSION_HIGH", "SESSION_LOW", "DAILY_GAP", "WEEKLY_GAP",
        "SMT", "PO3",
    }
)

#: Concepts that describe a price *zone* rather than a single level.
ZONE_CONCEPTS = frozenset(
    {"ORDER_BLOCK", "FVG", "IFVG", "BPR", "BREAKER", "PREMIUM_DISCOUNT", "OTE", "DAILY_GAP",
     "WEEKLY_GAP"}
)

#: Concepts whose direction expresses a directional bias worth trading with.
BIAS_CONCEPTS = frozenset({"BOS", "CHOCH", "MSS", "DISPLACEMENT", "SMT", "PO3"})


class SnapshotError(ValueError):
    """The file does not implement the supported snapshot contract."""


# --------------------------------------------------------------------------- #
# Primitive checks
# --------------------------------------------------------------------------- #


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def _obj(value: Any, path: str, required: tuple[str, ...] = ()) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{path} must be an object")
    missing = [name for name in required if name not in value]
    _require(not missing, f"{path} is missing required key(s): {', '.join(missing)}")
    return value


def _str(value: Any, path: str, *, allow_empty: bool = False) -> str:
    _require(isinstance(value, str), f"{path} must be a string")
    _require(allow_empty or value != "", f"{path} must not be empty")
    return value


def _bool(value: Any, path: str) -> bool:
    _require(type(value) is bool, f"{path} must be a boolean")
    return value


def _num(value: Any, path: str) -> float:
    _require(type(value) in (int, float), f"{path} must be a number")
    _require(math.isfinite(float(value)), f"{path} must be finite")
    return float(value)


def _enum(value: Any, allowed: frozenset[str], path: str) -> str:
    text = _str(value, path)
    _require(text in allowed, f"{path}: {text!r} is not one of {', '.join(sorted(allowed))}")
    return text


def _reject_constant(token: str) -> Any:
    raise SnapshotError(f"non-finite JSON value {token} is not supported")


def _broker_time(value: Any, path: str, offset: timedelta, *, nullable: bool = False):
    """Parse a broker wall-clock timestamp into an aware UTC datetime."""
    if value is None:
        _require(nullable, f"{path} must not be null")
        return None
    text = _str(value, path)
    _require(
        TIMESTAMP_RE.match(text) is not None,
        f"{path}: {text!r} is not a broker timestamp (YYYY-MM-DDTHH:MM:SS, no timezone)",
    )
    try:
        naive = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SnapshotError(f"{path}: {text!r} is not a valid date/time") from exc
    return (naive - offset).replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Typed objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Session:
    name: str
    start_minute: int
    end_minute: int


@dataclass(frozen=True, slots=True)
class Module:
    """Per-concept readiness. A concept can fail while the snapshot succeeds."""

    concept: str
    status: str
    as_of: datetime | None
    truncated: bool
    message: str

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    @property
    def usable(self) -> bool:
        """Deliberately excludes DISABLED: a disabled concept is not evidence."""
        return self.status in {"READY", "PARTIAL"}


@dataclass(frozen=True, slots=True)
class Record:
    """One detected structure: a zone, a level, or an event."""

    id: str
    concept: str
    direction: str
    state: str
    active: bool
    lower: float
    upper: float
    source_time: datetime
    confirmed_at: datetime
    updated_at: datetime
    period_start: datetime | None
    period_end: datetime | None
    reference_price: float
    comparison_price: float
    strength: float
    reason: str
    related_ids: tuple[str, ...] = ()
    broker_times: dict[str, str] = field(default_factory=dict, repr=False)

    # -- geometry ---------------------------------------------------------- #

    @property
    def is_zone(self) -> bool:
        return self.upper > self.lower

    @property
    def mid(self) -> float:
        return (self.lower + self.upper) / 2.0

    @property
    def height(self) -> float:
        return self.upper - self.lower

    def contains(self, price: float, tolerance: float = 0.0) -> bool:
        return self.lower - tolerance <= price <= self.upper + tolerance

    def distance_to(self, price: float) -> float:
        """Signed gap from the zone to ``price``; zero when price is inside.

        Positive means price sits **above** the zone, negative **below**, so the
        sign says which side of the structure price is on. Callers that only
        care about proximity take ``abs()``.
        """
        if self.contains(price):
            return 0.0
        return price - self.upper if price > self.upper else price - self.lower

    # -- direction --------------------------------------------------------- #

    @property
    def is_bullish(self) -> bool:
        return self.direction == "bullish"

    @property
    def is_bearish(self) -> bool:
        return self.direction == "bearish"

    def agrees_with(self, side: str) -> bool:
        """``side`` is ``LONG``/``SHORT``; neutral records agree with neither."""
        want = "bullish" if side.upper() == "LONG" else "bearish"
        return self.direction == want

    def age(self, now: datetime) -> timedelta:
        return now - self.updated_at

    @classmethod
    def parse(cls, raw: Any, path: str, offset: timedelta) -> Record:
        d = _obj(
            raw,
            path,
            (
                "id", "concept", "source_time", "confirmed_at", "updated_at", "direction",
                "lower", "upper", "state", "active", "related_ids", "period_start",
                "period_end", "reference_price", "comparison_price", "strength", "reason",
            ),
        )
        lower = _num(d["lower"], f"{path}.lower")
        upper = _num(d["upper"], f"{path}.upper")
        _require(lower <= upper, f"{path}: lower {lower} exceeds upper {upper}")

        related = d["related_ids"]
        _require(isinstance(related, list), f"{path}.related_ids must be an array")

        return cls(
            id=_str(d["id"], f"{path}.id"),
            concept=_enum(d["concept"], CONCEPTS, f"{path}.concept"),
            direction=_enum(d["direction"], DIRECTIONS, f"{path}.direction"),
            state=_str(d["state"], f"{path}.state"),
            active=_bool(d["active"], f"{path}.active"),
            lower=lower,
            upper=upper,
            source_time=_broker_time(d["source_time"], f"{path}.source_time", offset),
            confirmed_at=_broker_time(d["confirmed_at"], f"{path}.confirmed_at", offset),
            updated_at=_broker_time(d["updated_at"], f"{path}.updated_at", offset),
            period_start=_broker_time(
                d["period_start"], f"{path}.period_start", offset, nullable=True
            ),
            period_end=_broker_time(d["period_end"], f"{path}.period_end", offset, nullable=True),
            reference_price=_num(d["reference_price"], f"{path}.reference_price"),
            comparison_price=_num(d["comparison_price"], f"{path}.comparison_price"),
            strength=_num(d["strength"], f"{path}.strength"),
            reason=_str(d["reason"], f"{path}.reason", allow_empty=True),
            related_ids=tuple(
                _str(r, f"{path}.related_ids[{i}]") for i, r in enumerate(related)
            ),
            broker_times={
                "source_time": d["source_time"],
                "confirmed_at": d["confirmed_at"],
                "updated_at": d["updated_at"],
            },
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One evaluation of one symbol on one timeframe, at one bar close."""

    schema_version: str
    library_version: str
    symbol: str
    timeframe: str
    as_of: datetime | None
    status: str
    message: str
    records: tuple[Record, ...]
    modules: tuple[Module, ...]
    sessions: tuple[Session, ...]
    config: dict[str, Any] = field(default_factory=dict, repr=False)
    source_path: str = ""
    as_of_broker: str = ""

    # -- readiness --------------------------------------------------------- #

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    @property
    def usable(self) -> bool:
        return self.status in {"READY", "PARTIAL"}

    def module(self, concept: str) -> Module | None:
        for m in self.modules:
            if m.concept == concept.upper():
                return m
        return None

    def concept_ready(self, concept: str) -> bool:
        """A concept with no module entry is *not* assumed ready."""
        module = self.module(concept)
        return module is not None and module.usable

    def problems(self) -> list[str]:
        """Human-readable reasons the snapshot is not fully ready."""
        out: list[str] = []
        if not self.ready:
            detail = f": {self.message}" if self.message else ""
            out.append(f"snapshot status {self.status}{detail}")
        for m in self.modules:
            if m.status in {"ERROR", "NOT_READY"}:
                out.append(f"{m.concept} {m.status}" + (f": {m.message}" if m.message else ""))
            elif m.truncated:
                out.append(f"{m.concept} truncated (raise max_records_per_concept)")
        return out

    def age(self, now: datetime) -> timedelta | None:
        return None if self.as_of is None else now - self.as_of

    def is_stale(self, now: datetime, max_age: timedelta) -> bool:
        """No ``as_of`` counts as stale: unknown freshness is not freshness."""
        age = self.age(now)
        return age is None or age > max_age

    # -- queries ----------------------------------------------------------- #

    def by_concept(self, *concepts: str, active_only: bool = True) -> tuple[Record, ...]:
        wanted = {c.upper() for c in concepts}
        return tuple(
            r for r in self.records
            if r.concept in wanted and (r.active or not active_only)
        )

    def containing(
        self, price: float, *concepts: str, tolerance: float = 0.0, active_only: bool = True
    ) -> tuple[Record, ...]:
        """Zones whose range covers ``price``, nearest-midpoint first."""
        pool = self.by_concept(*concepts, active_only=active_only) if concepts else tuple(
            r for r in self.records if r.active or not active_only
        )
        hits = [r for r in pool if r.contains(price, tolerance)]
        hits.sort(key=lambda r: abs(r.mid - price))
        return tuple(hits)

    def nearest(
        self, price: float, *concepts: str, side: str | None = None, active_only: bool = True
    ) -> Record | None:
        pool = self.by_concept(*concepts, active_only=active_only)
        if side is not None:
            pool = tuple(r for r in pool if r.agrees_with(side))
        return min(pool, key=lambda r: abs(r.distance_to(price)), default=None)

    def latest(self, *concepts: str, active_only: bool = True) -> Record | None:
        """Most recently updated record, ties broken by id for determinism."""
        pool = self.by_concept(*concepts, active_only=active_only)
        return max(pool, key=lambda r: (r.updated_at, r.id), default=None)

    def bias(self, *concepts: str) -> str:
        """Directional bias from the most recent structural event.

        Returns ``bullish``, ``bearish`` or ``neutral``. Neutral is the honest
        answer when nothing structural has confirmed — never a coin flip.
        """
        record = self.latest(*(concepts or tuple(BIAS_CONCEPTS)))
        return record.direction if record is not None else "neutral"

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.records:
            if r.active:
                out[r.concept] = out.get(r.concept, 0) + 1
        return dict(sorted(out.items()))

    # -- parsing ----------------------------------------------------------- #

    @classmethod
    def parse(
        cls, raw: Any, *, broker_utc_offset_hours: float = 0.0, source_path: str = ""
    ) -> Snapshot:
        offset = timedelta(hours=broker_utc_offset_hours)
        d = _obj(
            raw,
            "snapshot",
            (
                "schema_version", "library_version", "symbol", "timeframe", "time_basis",
                "as_of", "status", "config", "modules", "records",
            ),
        )

        version = _str(d["schema_version"], "schema_version")
        _require(
            SCHEMA_VERSION_RE.match(version) is not None,
            f"schema_version {version!r} is not supported; this reader implements "
            f"major version {SCHEMA_MAJOR}",
        )
        _require(
            d["time_basis"] == "broker",
            f"time_basis must be 'broker', got {d['time_basis']!r}",
        )

        config = _obj(d["config"], "config")
        raw_sessions = config.get("sessions", [])
        _require(isinstance(raw_sessions, list), "config.sessions must be an array")
        sessions: list[Session] = []
        for i, raw_session in enumerate(raw_sessions):
            path = f"config.sessions[{i}]"
            s = _obj(raw_session, path, ("name", "start_minute", "end_minute"))
            sessions.append(
                Session(
                    name=_str(s["name"], f"{path}.name"),
                    start_minute=int(_num(s["start_minute"], f"{path}.start_minute")),
                    end_minute=int(_num(s["end_minute"], f"{path}.end_minute")),
                )
            )

        _require(isinstance(d["modules"], list), "modules must be an array")
        modules: list[Module] = []
        for i, raw_module in enumerate(d["modules"]):
            path = f"modules[{i}]"
            m = _obj(raw_module, path, ("concept", "status", "as_of", "truncated", "message"))
            modules.append(
                Module(
                    concept=_enum(m["concept"], CONCEPTS, f"{path}.concept"),
                    status=_enum(m["status"], STATUSES, f"{path}.status"),
                    as_of=_broker_time(m["as_of"], f"{path}.as_of", offset, nullable=True),
                    truncated=_bool(m["truncated"], f"{path}.truncated"),
                    message=_str(m["message"], f"{path}.message", allow_empty=True),
                )
            )

        _require(isinstance(d["records"], list), "records must be an array")
        records: list[Record] = []
        seen: set[str] = set()
        for i, raw_record in enumerate(d["records"]):
            record = Record.parse(raw_record, f"records[{i}]", offset)
            _require(record.id not in seen, f"records[{i}].id {record.id!r} is duplicated")
            seen.add(record.id)
            records.append(record)

        return cls(
            schema_version=version,
            library_version=_str(d["library_version"], "library_version"),
            symbol=_str(d["symbol"], "symbol"),
            timeframe=_str(d["timeframe"], "timeframe"),
            as_of=_broker_time(d["as_of"], "as_of", offset, nullable=True),
            as_of_broker=d["as_of"] or "",
            status=_enum(d["status"], STATUSES, "status"),
            message=_str(d.get("message", ""), "message", allow_empty=True),
            records=tuple(records),
            modules=tuple(modules),
            sessions=tuple(sessions),
            config=dict(config),
            source_path=source_path,
        )

    @classmethod
    def from_json(
        cls, text: str, *, broker_utc_offset_hours: float = 0.0, source_path: str = ""
    ) -> Snapshot:
        try:
            raw = json.loads(text, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"{source_path or '<snapshot>'}: invalid JSON — {exc}") from exc
        return cls.parse(
            raw, broker_utc_offset_hours=broker_utc_offset_hours, source_path=source_path
        )
