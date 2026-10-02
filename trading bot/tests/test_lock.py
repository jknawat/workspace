"""One bot at a time.

Two instances is the mistake that looks harmless in paper mode and doubles your
risk live: each reads positions from the broker, sizes against the balance, and
enforces max_open_positions on what *it* can see.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

from tbot.engine.lock import InstanceLock


def test_a_single_instance_acquires_cleanly(tmp_path):
    lock = InstanceLock(tmp_path / "tbot.lock")
    lock.acquire()
    try:
        assert lock.path.exists()
        # Readable despite the lock: the claim is staked past the text.
        assert f"pid={os.getpid()}" in lock.path.read_text(encoding="utf-8")
    finally:
        lock.release()


def test_a_second_instance_is_refused(tmp_path):
    """The real test has to be a separate process.

    A lock taken twice inside one process may be granted by the OS, since locks
    are usually per-handle or per-process. Spawning a child is the only honest
    check that a second *bot* cannot start.
    """
    path = tmp_path / "tbot.lock"
    held = InstanceLock(path)
    held.acquire()
    try:
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {repr(str(_src()))!s})
            from tbot.engine.lock import AlreadyRunning, InstanceLock
            try:
                InstanceLock({repr(str(path))!s}).acquire()
            except AlreadyRunning as exc:
                print("REFUSED", exc)
                raise SystemExit(0)
            print("ACQUIRED -- the lock did not hold")
            raise SystemExit(1)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" in result.stdout
        assert "already running" in result.stdout
    finally:
        held.release()


def test_the_lock_is_reusable_once_released(tmp_path):
    """Releasing must actually free it, or a clean restart would be refused."""
    path = tmp_path / "tbot.lock"
    first = InstanceLock(path)
    first.acquire()
    first.release()

    second = InstanceLock(path)
    second.acquire()  # must not raise
    second.release()


def test_release_without_acquire_is_harmless(tmp_path):
    InstanceLock(tmp_path / "tbot.lock").release()


def test_it_works_as_a_context_manager(tmp_path):
    path = tmp_path / "tbot.lock"
    with InstanceLock(path) as lock:
        assert lock.path.exists()
    InstanceLock(path).acquire()  # freed on exit
    InstanceLock(path).release()


def test_a_crashed_process_does_not_leave_the_lock_held(tmp_path):
    """The point of an OS lock rather than a PID file.

    A killed process leaves no usable claim behind: the kernel drops the lock
    when the handle closes, so the next start succeeds without anyone having to
    reason about whether a stale PID is still alive.
    """
    path = tmp_path / "tbot.lock"
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {repr(str(_src()))!s})
        from tbot.engine.lock import InstanceLock
        InstanceLock({repr(str(path))!s}).acquire()
        print("HELD", flush=True)
        import os
        os._exit(1)          # die without unwinding, like a kill -9
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert "HELD" in result.stdout

    survivor = InstanceLock(path)
    survivor.acquire()  # must not raise
    survivor.release()


def _src():
    """Path to ``src`` so a spawned interpreter can import tbot."""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "src"
