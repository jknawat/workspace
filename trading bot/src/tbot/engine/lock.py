"""One bot at a time.

Two instances running at once is the kind of mistake that looks harmless in
paper mode -- two simulated accounts, one shared journal, mildly confusing
numbers -- and is genuinely dangerous live. Each instance reads positions from
the broker, sizes against the account balance, and enforces ``max_open_positions``
on what *it* can see. Two of them will happily open two sets of positions and
each believe the risk cap was respected, so the account carries double what was
configured, and the daily-loss kill-switch counts half the damage.

The lock is an OS file lock held open for the process's lifetime, not a PID file
written and checked. That distinction matters: if the bot is killed, crashes, or
the machine loses power, the operating system releases the lock. A PID file
would be left behind, and the next start would either refuse for no reason or
need a "is that PID still alive?" check that is racy and, on Windows, awkward to
do without terminating something by accident.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from types import TracebackType

from ..obs import log as obs_log


class AlreadyRunning(RuntimeError):
    """Another instance holds the lock."""


class InstanceLock:
    """Exclusive, OS-level, released automatically if the process dies."""

    def __init__(self, path: str | Path = "data/tbot.lock") -> None:
        self.path = Path(path)
        self._fd: int | None = None

    #: Windows locks a byte *range*, and a locked byte cannot be read even by
    #: the owner. So the claim is staked on a byte far past the text, leaving
    #: the pid readable -- including by the instance that gets refused, which is
    #: the one that needs it for its error message.
    LOCK_OFFSET = 4096

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            self._lock(fd)
        except OSError as exc:
            held_by = self._read_holder(fd)
            os.close(fd)
            raise AlreadyRunning(
                f"another tbot instance is already running{held_by} "
                f"(lock: {self.path}). Stop it first -- stop.bat, or close its "
                f"window -- then start this one."
            ) from exc

        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"pid={os.getpid()}\n".encode().ljust(64, b" "))
        os.fsync(fd)
        self._fd = fd
        obs_log.get("lock").info(
            "instance lock held: %s", self.path, extra={"event": "lock_acquired"}
        )

    @classmethod
    def _lock(cls, fd: int) -> None:
        """Take an exclusive non-blocking lock, however this platform does it."""
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, cls.LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @classmethod
    def _unlock(cls, fd: int) -> None:
        if os.name == "nt":
            import msvcrt

            # Unlocking a region that is not locked raises; closing the handle
            # releases it anyway, so this is belt and braces.
            with contextlib.suppress(OSError):
                os.lseek(fd, cls.LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)

    def _read_holder(self, fd: int) -> str:
        """Best-effort "(pid NNNN)" for the error message; never fatal."""
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            text = os.read(fd, 64).decode("utf-8", "replace").strip()
        except OSError:
            return ""
        if text.startswith("pid="):
            return f" ({text})"
        return ""

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            self._unlock(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None
            # The file is left in place deliberately: deleting it races with
            # another instance that may already have opened it.

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
