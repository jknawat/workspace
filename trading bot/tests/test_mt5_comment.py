"""The order comment length MetaTrader's Python binding will accept.

This cost two live orders. MQL5 documents 31 characters and the code truncated
to exactly that; the binding refuses anything from 30 up, and refuses it by
returning None with ``Invalid "comment" argument`` -- which reads like a
connection fault rather than a rejected string. Paper mode ignores the field
entirely, so every simulated order had reported "filled" and nothing suggested
the live path was broken.

Measured with ``order_check`` against Exness on 2026-10-06: 29 accepted, 30
refused, content irrelevant.
"""

from __future__ import annotations

from tbot.broker.mt5 import MAX_COMMENT


def test_the_limit_is_below_the_documented_mql5_one():
    """MQL5 says 31. The Python binding disagrees, and it is the one actually
    sending the request."""
    assert MAX_COMMENT < 31
    assert MAX_COMMENT == 29


def test_the_comment_the_engine_builds_is_longer_than_the_limit():
    """So the truncation is not theoretical -- it runs on every order.

    'ema_pullback:breakout of pullback window' is 40 characters, and its
    31-character truncation is exactly what the broker refused twice.
    """
    comment = "ema_pullback:breakout of pullback window"
    assert len(comment) > 31
    assert len(comment[:31]) == 31          # what used to be sent
    assert len(comment[:MAX_COMMENT]) == MAX_COMMENT


def test_a_short_comment_is_left_alone():
    assert "tbot"[:MAX_COMMENT] == "tbot"
    assert ""[:MAX_COMMENT] == ""
