"""Watchers and the operator surface: dashboard, Telegram, MT5 chart overlay.

Everything in this package is a *reader* of the engine, plus one narrowly
defined write path: Telegram commands, which set flags the runner acts on
itself. Nothing here decides a trade, sizes a position, or bypasses the risk
gate, and nothing here is allowed to break trading when it fails.

:class:`InterfaceBundle` owns the lifecycle so the CLI has one thing to start
and one thing to stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.models import BotConfig
from ..obs import log as obs_log
from .dashboard import DashboardServer, DashboardState
from .overlay import OverlayWriter
from .telegram import (
    ControlState,
    TelegramClient,
    TelegramCommands,
    TelegramError,
    TelegramNotifier,
    format_status,
)

__all__ = [
    "ControlState",
    "DashboardServer",
    "DashboardState",
    "InterfaceBundle",
    "OverlayWriter",
    "TelegramClient",
    "TelegramCommands",
    "TelegramError",
    "TelegramNotifier",
    "build",
]


@dataclass(slots=True)
class InterfaceBundle:
    """Whatever watchers are enabled, with a single start/stop."""

    control: ControlState = field(default_factory=ControlState)
    notifier: TelegramNotifier | None = None
    commands: TelegramCommands | None = None
    dashboard: DashboardServer | None = None
    dashboard_state: DashboardState | None = None
    overlay: OverlayWriter | None = None
    enabled: list[str] = field(default_factory=list)

    # -- wiring ---------------------------------------------------------- #

    @property
    def chart_sinks(self) -> list[Any]:
        sinks: list[Any] = []
        if self.dashboard_state is not None:
            sinks.append(self.dashboard_state.update_chart)
        return sinks

    @property
    def status_sinks(self) -> list[Any]:
        """Callables the runner feeds its status dict to, once per cycle."""
        sinks: list[Any] = []
        if self.dashboard_state is not None:
            sinks.append(self.dashboard_state.update_status)
        if self.overlay is not None:
            sinks.append(self.overlay.on_status)
        if self.notifier is not None:
            sinks.append(self._maybe_report_status)
        return sinks

    def _maybe_report_status(self, status: dict[str, Any]) -> None:
        """Answer a pending /status from the trading thread, where the truth is."""
        if self.commands is None or self.notifier is None:
            return
        if self.control.take("status_reply_pending"):
            self.notifier.send(format_status(status))

    def attach(self, engine: Any) -> None:
        """Subscribe every watcher to the engine's event bus."""
        if self.notifier is not None:
            engine.events.subscribe(self.notifier.on_event, "telegram")
        if self.dashboard_state is not None:
            engine.events.subscribe(self.dashboard_state.on_event, "dashboard")

    # -- lifecycle ------------------------------------------------------- #

    def start(self) -> None:
        log = obs_log.get("interfaces")
        if self.notifier is not None:
            self.notifier.start()
        if self.commands is not None:
            self.commands.start()
        if self.dashboard is not None:
            self.dashboard.start()
        if self.enabled:
            log.info("interfaces: %s", ", ".join(self.enabled), extra={"event": "interfaces"})

    def stop(self) -> None:
        if self.commands is not None:
            self.commands.stop()
        if self.dashboard is not None:
            self.dashboard.stop()
        if self.notifier is not None:
            self.notifier.stop()  # drains the queue, so the last alert still lands


def build(cfg: BotConfig, snapshot_dir: str | None = None) -> InterfaceBundle:
    """Construct the bundle described by the config.

    A watcher that cannot be constructed (bad Telegram token, port already in
    use) is reported and skipped -- never fatal. Losing the dashboard is an
    inconvenience; refusing to trade because of it would be a bug.
    """
    log = obs_log.get("interfaces")
    bundle = InterfaceBundle()

    if cfg.telegram.enabled:
        try:
            client = TelegramClient(cfg.telegram.token)
            bundle.notifier = TelegramNotifier(
                client, cfg.telegram.chat_id, kinds=list(cfg.telegram.events)
            )
            if cfg.telegram.accept_commands:
                bundle.commands = TelegramCommands(
                    client, cfg.telegram.chat_id, bundle.control, bundle.notifier
                )
            bundle.enabled.append("telegram")
        except TelegramError as exc:
            log.error("telegram disabled: %s", exc)

    if cfg.dashboard.enabled:
        try:
            bundle.dashboard_state = DashboardState(journal_path=cfg.engine.journal_path)
            bundle.dashboard = DashboardServer(
                bundle.dashboard_state, host=cfg.dashboard.host, port=cfg.dashboard.port
            )
            bundle.enabled.append(f"dashboard {bundle.dashboard.url}")
        except OSError as exc:
            log.error("dashboard disabled: %s", exc)
            bundle.dashboard = None
            bundle.dashboard_state = None

    if cfg.overlay.enabled:
        folder = cfg.overlay.folder or cfg.snapshot.folder
        if snapshot_dir is None:
            log.error("overlay disabled: MT5 shared folder could not be resolved")
        else:
            base = snapshot_dir
            if cfg.overlay.folder and cfg.overlay.folder != cfg.snapshot.folder:
                # An explicit overlay folder is relative to Common/Files, like
                # the snapshot one, so swap the last path segment.
                from pathlib import Path

                base = str(Path(snapshot_dir).parent / folder)
            bundle.overlay = OverlayWriter(
                base,
                broker_utc_offset_hours=cfg.engine.broker_utc_offset_hours,
                filename=cfg.overlay.filename,
            )
            bundle.enabled.append(f"overlay {bundle.overlay.path}")

    return bundle
