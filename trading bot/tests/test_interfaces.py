"""Watchers: event bus, Telegram, dashboard state, MT5 overlay.

The recurring theme: **a watcher must never be able to stop the bot trading.**
Every test here that looks defensive is defensive on purpose — a Telegram
outage, a wedged HTTP client or a full queue should cost you visibility, never
a managed stop.

Nothing here touches the network. The Telegram transport is exercised through a
fake client; the real one is a thin urllib wrapper over a documented API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tbot.engine.events import CLOSED, ERROR, EXIT, ORDER, SIGNAL, Event, EventBus
from tbot.interfaces.dashboard import DashboardState
from tbot.interfaces.overlay import OverlayWriter
from tbot.interfaces.telegram import (
    ControlState,
    TelegramCommands,
    TelegramNotifier,
    format_event,
    format_status,
)

TS = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


class FakeClient:
    """Stands in for TelegramClient; records sends, can be made to fail."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail
        self.updates: list[dict] = []

    def send_message(self, chat_id, text):
        if self.fail:
            from tbot.interfaces.telegram import TelegramError

            raise TelegramError("network down")
        self.sent.append(text)
        return {}

    def get_updates(self, offset=None, timeout=25):
        out, self.updates = self.updates, []
        return out


def status_dict(**overrides):
    base = {
        "started": True,
        "mode": "paper",
        "broker": "paper",
        "paused": False,
        "balance": 10_000.0,
        "equity": 10_120.0,
        "day_pnl": 120.0,
        "day_trades": 2,
        "positions": [
            {
                "symbol": "EURUSD", "side": "LONG", "volume": 0.5, "entry": 1.1000,
                "sl": 1.0980, "tp": 1.1060, "pnl": 45.0, "ticket": 1,
                "opened_at": TS.isoformat(),
            }
        ],
        "phases": {
            "EURUSD": {"phase": "ARMED", "last_reject": "", "snapshot": {"available": True}}
        },
        "symbols": ["EURUSD"],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Event bus
# --------------------------------------------------------------------------- #


def test_events_reach_every_subscriber():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(seen.append, "a")
    bus.subscribe(seen.append, "b")
    bus.publish(ORDER, "EURUSD", side="LONG")
    assert len(seen) == 2
    assert seen[0].symbol == "EURUSD" and seen[0].data["side"] == "LONG"


def test_a_broken_subscriber_cannot_stop_the_others():
    """The whole point of the bus: a failing watcher is a log line, not an outage."""
    bus = EventBus()
    survived: list[Event] = []

    def explode(event):
        raise RuntimeError("telegram is on fire")

    bus.subscribe(explode, "broken")
    bus.subscribe(survived.append, "good")
    bus.publish(CLOSED, "EURUSD", pnl=10.0)
    assert len(survived) == 1


def test_event_serialises_flatly():
    event = Event(kind=ORDER, symbol="XAUUSD", ts=TS, data={"side": "LONG", "volume": 0.2})
    d = event.to_dict()
    assert d["kind"] == "order" and d["symbol"] == "XAUUSD" and d["volume"] == 0.2
    assert d["ts"].startswith("2026-01-05T10:00")


# --------------------------------------------------------------------------- #
# Telegram formatting
# --------------------------------------------------------------------------- #


def test_order_event_reads_like_a_trade_ticket():
    text = format_event(
        Event(ORDER, "EURUSD", TS, {"ok": True, "side": "LONG", "volume": 0.42,
                                    "price": 1.1005, "sl": 1.098, "tp": 1.106,
                                    "risk_money": 100.0, "reason": "order block"})
    )
    assert "EURUSD" in text and "LONG" in text and "0.42" in text and "100.00" in text


def test_rejected_order_is_flagged_loudly():
    text = format_event(Event(ORDER, "EURUSD", TS, {"ok": False, "message": "retcode 10030"}))
    assert "REJECTED" in text and "10030" in text


def test_closed_event_shows_the_sign():
    win = format_event(Event(CLOSED, "EURUSD", TS, {"pnl": 50.0, "side": "LONG",
                                                    "volume": 0.5, "reason": "TP"}))
    loss = format_event(Event(CLOSED, "EURUSD", TS, {"pnl": -30.0, "side": "LONG",
                                                     "volume": 0.5, "reason": "SL"}))
    assert "+50.00" in win and "-30.00" in loss


def test_failed_exit_is_not_announced():
    """Retryable plumbing noise does not belong on someone's phone."""
    assert format_event(Event(EXIT, "EURUSD", TS, {"ok": False, "kind": "modify"})) is None


def test_unknown_event_kinds_are_ignored():
    assert format_event(Event("quantum_flux", "EURUSD", TS, {})) is None


def test_status_renders_positions_and_phases():
    text = format_status(status_dict())
    assert "EURUSD LONG 0.5" in text
    assert "+120.00" in text
    assert "ARMED" in text


def test_status_says_when_there_is_nothing_open():
    text = format_status(status_dict(positions=[]))
    assert "no open positions" in text


def test_status_shows_a_pause():
    assert "PAUSED" in format_status(status_dict(paused=True))


# --------------------------------------------------------------------------- #
# Notifier
# --------------------------------------------------------------------------- #


def test_notifier_queues_only_subscribed_kinds():
    notifier = TelegramNotifier(FakeClient(), chat_id=1, kinds=[ORDER])
    notifier.on_event(Event(ORDER, "EURUSD", TS, {"ok": True, "side": "LONG",
                                                  "volume": 1, "price": 1.1}))
    notifier.on_event(Event(SIGNAL, "EURUSD", TS, {"side": "LONG"}))
    assert notifier.queue.qsize() == 1


def test_notifier_drops_rather_than_blocking_when_full():
    """A backlog must cost alerts, never a delayed stop-loss."""
    notifier = TelegramNotifier(FakeClient(), chat_id=1, kinds=[ERROR], max_queue=2)
    for _ in range(5):
        notifier.send("boom")
    assert notifier.queue.qsize() == 2
    assert notifier.dropped == 3


def test_notifier_sends_from_its_thread_and_drains_on_stop():
    client = FakeClient()
    notifier = TelegramNotifier(client, chat_id=1, kinds=[ERROR])
    notifier.send("one")
    notifier.send("two")
    notifier.start()
    notifier.stop(drain_seconds=5.0)
    assert client.sent == ["one", "two"]


def test_a_send_failure_is_swallowed():
    client = FakeClient(fail=True)
    notifier = TelegramNotifier(client, chat_id=1, kinds=[ERROR])
    notifier.send("will fail")
    notifier.start()
    notifier.stop(drain_seconds=5.0)
    assert client.sent == []  # and no exception escaped


# --------------------------------------------------------------------------- #
# Commands and control flags
# --------------------------------------------------------------------------- #


@pytest.fixture
def commands():
    control = ControlState()
    client = FakeClient()
    notifier = TelegramNotifier(client, chat_id="42", kinds=[])
    return TelegramCommands(client, "42", control, notifier), control, client


def test_pause_and_resume_set_the_flag(commands):
    cmd, control, _ = commands
    cmd.handle("/pause", "42")
    assert control.paused is True
    cmd.handle("/resume", "42")
    assert control.paused is False


def test_closeall_and_stop_are_one_shot_flags(commands):
    cmd, control, _ = commands
    cmd.handle("/closeall", "42")
    cmd.handle("/stop", "42")
    assert control.take("close_all_requested") is True
    assert control.take("close_all_requested") is False  # cleared by the taker
    assert control.take("stop_requested") is True


def test_status_defers_to_the_trading_thread(commands):
    cmd, control, _ = commands
    assert cmd.handle("/status", "42") is None  # no immediate reply
    assert control.take("status_requested") is True
    assert control.take("status_reply_pending") is True


def test_messages_from_other_chats_are_ignored_silently(commands):
    """No reply at all: confirming the bot exists to a stranger is worse than
    being unhelpful to them."""
    cmd, control, _ = commands
    assert cmd.handle("/closeall", "999") is None
    assert control.paused is False
    assert control.take("close_all_requested") is False
    assert cmd.ignored == 1


def test_unknown_command_gets_the_help_text(commands):
    cmd, _, _ = commands
    assert "unknown command" in cmd.handle("/moon", "42")


def test_command_suffix_for_group_chats_is_stripped(commands):
    cmd, control, _ = commands
    cmd.handle("/pause@my_tbot_bot", "42")
    assert control.paused is True


def test_control_take_is_atomic_enough_for_flags():
    control = ControlState()
    control.set(close_all_requested=True)
    assert control.take("close_all_requested") is True
    assert control.close_all_requested is False


# --------------------------------------------------------------------------- #
# Dashboard state
# --------------------------------------------------------------------------- #


def test_dashboard_payload_carries_status_events_and_equity():
    state = DashboardState()
    state.update_status(status_dict())
    state.on_event(Event(ORDER, "EURUSD", TS, {"ok": True}))
    payload = state.payload()
    assert payload["status"]["balance"] == 10_000.0
    assert payload["events"][0]["kind"] == "order"
    assert payload["equity"][-1]["equity"] == 10_120.0


def test_dashboard_keeps_newest_events_first_and_bounded():
    state = DashboardState(max_events=3)
    for i in range(6):
        state.on_event(Event(SIGNAL, f"S{i}", TS, {}))
    events = state.payload()["events"]
    assert len(events) == 3
    assert events[0]["symbol"] == "S5"


def test_dashboard_payload_is_json_serialisable():
    state = DashboardState()
    state.update_status(status_dict())
    state.on_event(Event(CLOSED, "EURUSD", TS, {"pnl": 10.0}))
    json.dumps(state.payload())  # must not raise


def test_dashboard_starts_empty():
    assert DashboardState().payload()["status"] == {"started": False}


# --------------------------------------------------------------------------- #
# MT5 overlay
# --------------------------------------------------------------------------- #


def test_overlay_writes_a_readable_state_file(tmp_path):
    writer = OverlayWriter(tmp_path, broker_utc_offset_hours=0.0)
    assert writer.write(status_dict())
    data = json.loads(writer.path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["positions"][0]["symbol"] == "EURUSD"
    assert data["phases"]["EURUSD"]["phase"] == "ARMED"


def test_overlay_converts_utc_back_to_broker_time(tmp_path):
    """MQL5 draws on the terminal's clock. Handing it UTC would offset every
    marker by the server's offset -- the mirror image of the snapshot reader."""
    writer = OverlayWriter(tmp_path, broker_utc_offset_hours=3.0)
    data = writer.build(status_dict())
    assert data["positions"][0]["opened_at"] == "2026.01.05 13:00:00"
    assert data["time_basis"] == "broker"


def test_overlay_write_is_atomic_leaving_no_temp_file(tmp_path):
    writer = OverlayWriter(tmp_path)
    writer.write(status_dict())
    writer.write(status_dict())
    assert [p.name for p in tmp_path.iterdir()] == ["tbot_state.json"]


def test_overlay_failure_is_reported_not_raised(tmp_path):
    blocked = tmp_path / "file_not_dir"
    blocked.write_text("i am a file", encoding="utf-8")
    writer = OverlayWriter(blocked / "sub")
    assert writer.write(status_dict()) is False  # no exception


def test_overlay_handles_a_missing_timestamp(tmp_path):
    writer = OverlayWriter(tmp_path)
    status = status_dict()
    status["positions"][0]["opened_at"] = None
    assert writer.write(status)
    data = json.loads(writer.path.read_text(encoding="utf-8"))
    assert data["positions"][0]["opened_at"] is None


def test_overlay_truncates_long_rejection_text(tmp_path):
    writer = OverlayWriter(tmp_path)
    status = status_dict(phases={"EURUSD": {"phase": "SCANNING", "last_reject": "x" * 500}})
    data = writer.build(status)
    assert len(data["phases"]["EURUSD"]["last_reject"]) == 120


# --------------------------------------------------------------------------- #
# Bundle wiring
# --------------------------------------------------------------------------- #


def test_bundle_with_nothing_enabled_is_inert(bot_cfg):
    from tbot.interfaces import build as build_interfaces

    bundle = build_interfaces(bot_cfg)
    assert bundle.enabled == []
    assert bundle.status_sinks == []
    bundle.start()
    bundle.stop()  # must be safe with nothing configured


def test_bundle_enables_the_dashboard(bot_cfg, monkeypatch):
    import dataclasses

    from tbot.config.models import DashboardConfig
    from tbot.interfaces import build as build_interfaces

    cfg = dataclasses.replace(
        bot_cfg, dashboard=DashboardConfig(enabled=True, port=8799)
    )
    bundle = build_interfaces(cfg)
    assert bundle.dashboard is not None
    assert "8799" in bundle.enabled[0]
    assert len(bundle.status_sinks) == 1


def test_bundle_skips_telegram_without_a_token(bot_cfg):
    import dataclasses

    from tbot.config.models import TelegramConfig
    from tbot.interfaces import build as build_interfaces

    cfg = dataclasses.replace(
        bot_cfg, telegram=TelegramConfig(enabled=True, chat_id="1", token="")
    )
    bundle = build_interfaces(cfg)
    assert bundle.notifier is None  # reported and skipped, never fatal
    assert bundle.enabled == []
