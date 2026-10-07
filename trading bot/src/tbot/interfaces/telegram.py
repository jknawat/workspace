"""Telegram notifications and remote control, using only the standard library.

Telegram's Bot API is plain HTTPS and JSON, so ``urllib`` is enough — no
third-party client, nothing to keep updated, nothing new to audit.

Three separations matter here, and all three are about safety:

1. **Sending happens on its own thread.** Events are queued and drained by a
   background worker. A slow or unreachable Telegram must never delay a stop
   being moved, and a network exception must never surface in the trading loop.
2. **Commands set flags; they do not act.** The polling thread only writes to a
   :class:`ControlState`. The runner reads those flags at the top of its next
   cycle and acts on the trading thread, so there is still exactly one thread
   touching positions.
3. **Unknown senders are ignored silently.** The chat id is a whitelist. An
   unauthorised message gets no reply at all — replying would confirm the bot
   exists to whoever found it.

The bot token is a credential. It is read from config or environment, never
logged, and redacted from any error text.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..engine.events import CLOSED, DECLINED, ERROR, EXIT, ORDER, SIGNAL, STARTED, STOPPED, Event
from ..obs import log as obs_log

API = "https://api.telegram.org"
DEFAULT_EVENTS = [ORDER, CLOSED, ERROR, STARTED, STOPPED]


class TelegramError(RuntimeError):
    """A Telegram API call failed. The token is never included in the message."""


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #


class TelegramClient:
    """Thin synchronous wrapper over the Bot API."""

    def __init__(self, token: str, timeout: float = 20.0) -> None:
        if not token:
            raise TelegramError("no bot token configured")
        self._token = token
        self.timeout = timeout
        self.log = obs_log.get("telegram")

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "<token>")

    def call(
        self, method: str, _http_timeout: float | None = None, **params: Any
    ) -> dict[str, Any]:
        """Call the Bot API.

        ``_http_timeout`` overrides the socket timeout for this call. Long
        polling needs it: ``getUpdates`` asks Telegram to *hold* the connection
        open, so a socket timeout shorter than the hold is guaranteed to fire
        first and every poll fails.
        """
        url = f"{API}/bot{self._token}/{method}"
        payload = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=_http_timeout or self.timeout
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise TelegramError(f"{method} failed ({exc.code}): {self._redact(detail)}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TelegramError(f"{method} unreachable: {self._redact(str(exc))}") from None
        if not body.get("ok"):
            raise TelegramError(f"{method} rejected: {body.get('description', 'unknown')}")
        return body.get("result", {})

    def send_message(self, chat_id: int | str, text: str) -> dict[str, Any]:
        # Markdown is deliberately not used: an unescaped price or symbol can
        # make Telegram reject the whole message, and losing an alert to a
        # formatting error is a bad trade-off for bold text.
        return self.call(
            "sendMessage", chat_id=chat_id, text=text[:4000], disable_web_page_preview=True
        )

    #: Seconds of slack between Telegram's long-poll hold and our socket
    #: timeout. Without it the socket closes while Telegram is still holding
    #: the connection open, every poll raises, and no command ever arrives --
    #: which is exactly what happened: a 20s socket against a 25s hold meant
    #: /status had never once worked.
    POLL_SLACK = 15.0

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        result = self.call(
            "getUpdates",
            _http_timeout=max(self.timeout, timeout + self.POLL_SLACK),
            offset=offset,
            timeout=timeout,
        )
        return result if isinstance(result, list) else []

    def me(self) -> dict[str, Any]:
        return self.call("getMe")


# --------------------------------------------------------------------------- #
# Control flags
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ControlState:
    """Flags a remote operator can set; the runner acts on them, not Telegram."""

    paused: bool = False
    close_all_requested: bool = False
    stop_requested: bool = False
    status_requested: bool = False      # ask the runner to publish status now
    status_reply_pending: bool = False  # ...and send that status back to Telegram
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(self, **flags: bool) -> None:
        with self._lock:
            for key, value in flags.items():
                setattr(self, key, value)

    def take(self, name: str) -> bool:
        """Read a one-shot flag and clear it."""
        with self._lock:
            value = bool(getattr(self, name))
            setattr(self, name, False)
            return value


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #


def format_event(event: Event) -> str | None:
    """Render an event as a short mobile-friendly line, or None to stay quiet."""
    d = event.data
    sym = event.symbol

    if event.kind == ORDER:
        if not d.get("ok"):
            return f"⚠️ {sym} order REJECTED — {d.get('message', 'no reason given')}"
        risk = d.get("risk_money")
        risk_text = f", risk {risk:,.2f}" if isinstance(risk, (int, float)) else ""
        return (
            f"✅ {sym} {d.get('side')} {d.get('volume')} lots @ {d.get('price')}\n"
            f"SL {d.get('sl')}  TP {d.get('tp')}{risk_text}\n"
            f"{d.get('reason', '')}"
        )
    if event.kind == CLOSED:
        pnl = d.get("pnl", 0.0)
        mark = "🟢" if pnl > 0 else "🔴"
        return (
            f"{mark} {sym} closed {d.get('side')} {d.get('volume')} lots "
            f"{pnl:+,.2f} ({d.get('reason')})"
        )
    if event.kind == EXIT:
        if not d.get("ok"):
            return None
        if d.get("action") == "close":
            return f"✂️ {sym} partial close — {d.get('reason')}"
        return f"🛡️ {sym} stop moved to {d.get('sl')} — {d.get('reason')}"
    if event.kind == SIGNAL:
        return (
            f"📶 {sym} {d.get('side')} signal @ {d.get('price')} "
            f"(RR {d.get('rr')}) — {d.get('reason', '')}"
        )
    if event.kind == DECLINED:
        return f"🚫 {sym} {d.get('side')} declined — {d.get('reason')}"
    if event.kind == ERROR:
        return f"❗ {sym or 'bot'} error — {d.get('message')}"
    if event.kind == STARTED:
        return (
            f"🤖 tbot started — {d.get('mode')} on {d.get('broker')}, "
            f"{d.get('symbols')} symbol(s), balance {d.get('balance', 0):,.2f}"
        )
    if event.kind == STOPPED:
        return f"🛑 tbot stopped — {d.get('reason', 'shutdown')}"
    return None


def format_status(status: dict[str, Any]) -> str:
    """Render the runner's status dict as a readable /status reply."""
    # `or 0` rather than a dict default: a failed account read puts a real None
    # in the status, and formatting None would lose the whole reply.
    balance = status.get("balance") or 0.0
    equity = status.get("equity") or 0.0
    lines = [
        f"📊 {status.get('mode', '?')} on {status.get('broker', '?')} — "
        f"{'PAUSED' if status.get('paused') else 'running'}",
        f"balance {balance:,.2f}   equity {equity:,.2f}",
        f"today {status.get('day_pnl') or 0:+,.2f} over {status.get('day_trades', 0)} trade(s)",
    ]
    positions = status.get("positions") or []
    if positions:
        lines.append(f"\nopen ({len(positions)}):")
        for p in positions:
            lines.append(
                f"  {p['symbol']} {p['side']} {p['volume']} @ {p['entry']} "
                f"sl {p['sl']} tp {p['tp']}"
            )
    else:
        lines.append("\nno open positions")

    phases = status.get("phases") or {}
    if phases:
        lines.append("\nstrategy state:")
        for symbol, state in phases.items():
            phase = state.get("phase", "?")
            extra = state.get("last_reject") or ""
            lines.append(f"  {symbol}: {phase}" + (f" — {extra[:60]}" if extra else ""))
    return "\n".join(lines)


HELP = (
    "tbot commands:\n"
    "/status — balance, open positions, strategy state\n"
    "/positions — open positions only\n"
    "/pause — stop taking new entries (open trades keep being managed)\n"
    "/resume — allow new entries again\n"
    "/closeall — close every open position now\n"
    "/stop — shut the bot down after the current cycle\n"
    "/help — this message"
)


# --------------------------------------------------------------------------- #
# Notifier
# --------------------------------------------------------------------------- #


class TelegramNotifier:
    """Queues events and sends them from a background thread."""

    def __init__(
        self,
        client: TelegramClient,
        chat_id: int | str,
        kinds: list[str] | None = None,
        max_queue: int = 500,
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.kinds = set(kinds or DEFAULT_EVENTS)
        self.queue: queue.Queue[str] = queue.Queue(maxsize=max_queue)
        self.log = obs_log.get("telegram")
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.dropped = 0
        self.sent = 0

    # -- event side (trading thread; must never block) -------------------- #

    def on_event(self, event: Event) -> None:
        if event.kind not in self.kinds:
            return
        text = format_event(event)
        if text is None:
            return
        self.send(text)

    def send(self, text: str) -> None:
        try:
            self.queue.put_nowait(text)
        except queue.Full:
            # Better to lose an alert than to block the trading loop on a
            # backlog. The journal remains the complete record either way.
            self.dropped += 1

    # -- sender side (background thread) ---------------------------------- #

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="telegram-send", daemon=True)
        self._thread.start()

    def stop(self, drain_seconds: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=drain_seconds)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set() or not self.queue.empty():
            try:
                text = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.client.send_message(self.chat_id, text)
                self.sent += 1
            except TelegramError as exc:
                self.log.warning("telegram send failed: %s", exc)
            time.sleep(0.05)  # stay well inside Telegram's rate limits


# --------------------------------------------------------------------------- #
# Command polling
# --------------------------------------------------------------------------- #


class TelegramCommands:
    """Polls for commands from the allowed chat and sets control flags."""

    def __init__(
        self,
        client: TelegramClient,
        chat_id: int | str,
        control: ControlState,
        notifier: TelegramNotifier | None = None,
        poll_timeout: int = 25,
    ) -> None:
        self.client = client
        self.chat_id = str(chat_id)
        self.control = control
        self.notifier = notifier
        self.poll_timeout = poll_timeout
        self.log = obs_log.get("telegram")
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._offset: int | None = None
        self.handled = 0
        self.ignored = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="telegram-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _reply(self, text: str) -> None:
        if self.notifier is not None:
            self.notifier.send(text)

    def handle(self, text: str, sender_chat: str) -> str | None:
        """Apply one command. Returns the reply, or None when ignored."""
        if sender_chat != self.chat_id:
            self.ignored += 1
            # No reply: confirming the bot exists to an unknown sender is worse
            # than being unhelpful to them.
            return None
        command = text.strip().split()[0].lower().split("@")[0]
        self.handled += 1

        if command in {"/start", "/help"}:
            return HELP
        if command in {"/status", "/positions"}:
            # Answered by the runner, on the trading thread: it is the only
            # place that can read positions without racing the engine.
            self.control.set(status_requested=True, status_reply_pending=True)
            return None
        if command == "/pause":
            self.control.set(paused=True)
            return "⏸️ paused — no new entries. Open positions are still managed."
        if command == "/resume":
            self.control.set(paused=False)
            return "▶️ resumed — new entries allowed."
        if command == "/closeall":
            self.control.set(close_all_requested=True)
            return "closing every open position…"
        if command == "/stop":
            self.control.set(stop_requested=True)
            return "🛑 stopping after the current cycle."
        return f"unknown command {command}\n\n{HELP}"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                updates = self.client.get_updates(self._offset, timeout=self.poll_timeout)
            except TelegramError as exc:
                self.log.warning("telegram poll failed: %s", exc)
                time.sleep(5.0)
                continue
            for update in updates:
                self._offset = int(update.get("update_id", 0)) + 1
                message = update.get("message") or update.get("edited_message") or {}
                text = message.get("text")
                chat = str((message.get("chat") or {}).get("id", ""))
                if not text:
                    continue
                reply = self.handle(text, chat)
                if reply:
                    self._reply(reply)


# --------------------------------------------------------------------------- #
# Setup helper
# --------------------------------------------------------------------------- #


def discover_chat_id(token: str, wait_seconds: float = 60.0) -> int | None:
    """Wait for a message to the bot and return the chat id that sent it.

    Saves the usual dance of finding your own numeric id: run it, send the bot
    any message, and it prints the id to put in the config.
    """
    client = TelegramClient(token, timeout=10.0)
    deadline = time.monotonic() + wait_seconds
    offset: int | None = None
    while time.monotonic() < deadline:
        try:
            updates = client.get_updates(offset, timeout=5)
        except TelegramError:
            time.sleep(2.0)
            continue
        for update in updates:
            offset = int(update.get("update_id", 0)) + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            if chat.get("id") is not None:
                return int(chat["id"])
    return None


def build(
    token: str,
    chat_id: int | str,
    kinds: list[str] | None = None,
    control: ControlState | None = None,
    accept_commands: bool = True,
) -> tuple[TelegramNotifier, TelegramCommands | None]:
    """Wire a notifier and, optionally, the command poller."""
    client = TelegramClient(token)
    notifier = TelegramNotifier(client, chat_id, kinds=kinds)
    commands = None
    if accept_commands:
        commands = TelegramCommands(client, chat_id, control or ControlState(), notifier)
    return notifier, commands
