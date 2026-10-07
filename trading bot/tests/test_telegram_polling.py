"""Long polling needs a socket timeout longer than the poll it is waiting on.

``getUpdates`` asks Telegram to *hold* the connection open until a message
arrives or the timeout expires. A socket timeout shorter than that hold is
guaranteed to fire first, so every poll raises and no command ever gets
through.

That is not hypothetical: a 20-second socket against a 25-second hold shipped,
and the log filled with "getUpdates unreachable: The read operation timed out"
every cycle. Alerts still went out -- sending is a short request -- so the link
looked half-alive while /status had never once worked.
"""

from __future__ import annotations

import pytest

from tbot.interfaces.telegram import TelegramClient, TelegramError


class _Recorder(TelegramClient):
    """Captures the socket timeout each call would use."""

    def __init__(self, timeout=20.0):
        super().__init__("123:fake", timeout=timeout)
        self.calls = []

    def call(self, method, _http_timeout=None, **params):
        self.calls.append((method, _http_timeout, params))
        return [] if method == "getUpdates" else {}


def test_the_socket_outlives_the_long_poll():
    """The property that was wrong."""
    c = _Recorder(timeout=20.0)
    c.get_updates(timeout=25)
    _, http_timeout, params = c.calls[0]
    assert params["timeout"] == 25
    assert http_timeout > 25, "the socket would close while Telegram still holds"


def test_the_slack_is_generous_enough_to_absorb_a_slow_network():
    c = _Recorder(timeout=20.0)
    c.get_updates(timeout=25)
    _, http_timeout, _ = c.calls[0]
    assert http_timeout >= 25 + 10


@pytest.mark.parametrize("poll", [0, 5, 25, 50])
def test_it_holds_for_any_poll_length(poll):
    c = _Recorder(timeout=20.0)
    c.get_updates(timeout=poll)
    _, http_timeout, params = c.calls[0]
    assert params["timeout"] == poll
    assert http_timeout > poll


def test_a_long_client_timeout_is_not_shortened():
    """Someone configuring a generous client timeout should keep it."""
    c = _Recorder(timeout=120.0)
    c.get_updates(timeout=25)
    _, http_timeout, _ = c.calls[0]
    assert http_timeout == 120.0


def test_ordinary_calls_still_use_the_client_timeout():
    """Only long polling needs the extension; sending a message does not."""
    sent = {}

    class _C(TelegramClient):
        def call(self, method, _http_timeout=None, **params):
            sent["timeout"] = _http_timeout
            return {}

    _C("123:fake", timeout=20.0).send_message(1, "hi")
    assert sent["timeout"] is None  # falls back to self.timeout inside call()


def test_a_missing_token_is_refused_up_front():
    with pytest.raises(TelegramError):
        TelegramClient("")
