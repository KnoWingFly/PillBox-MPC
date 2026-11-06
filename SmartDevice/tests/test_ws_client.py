"""Command-channel reconnect policy (Qt offscreen, no network)."""

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWebSockets import QWebSocketProtocol

from smart_pillbox import config
from smart_pillbox.core.ws_client import DeviceSocket


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _lost_with(code: int) -> tuple[DeviceSocket, list[bool]]:
    socket = DeviceSocket()
    socket._wanted = True
    socket._identity = ("PB-TEST0001", "test-secret-not-real")
    socket._ws.closeCode = lambda: QWebSocketProtocol.CloseCode(code)  # type: ignore[method-assign]
    rejected: list[bool] = []
    socket.auth_rejected.connect(lambda: rejected.append(True))
    socket._on_lost()
    return socket, rejected


def test_a_rejected_key_backs_off_to_the_longest_delay(qt_app) -> None:
    socket, rejected = _lost_with(config.WS_CLOSE_AUTH_FAILED)
    assert rejected == [True]
    assert socket._retry.interval() >= config.WS_RECONNECT_MAX_MS * (1 - config.WS_RECONNECT_JITTER)
    socket._retry.stop()


def test_being_replaced_does_not_reconnect_at_once(qt_app) -> None:
    socket, rejected = _lost_with(config.WS_CLOSE_REPLACED)
    assert rejected == []
    assert socket._retry.interval() >= config.WS_RECONNECT_MAX_MS * (1 - config.WS_RECONNECT_JITTER)
    socket._retry.stop()


def test_a_normal_drop_retries_soon_with_jitter(qt_app) -> None:
    socket, _ = _lost_with(1006)
    low = config.WS_RECONNECT_MIN_MS * (1 - config.WS_RECONNECT_JITTER)
    high = config.WS_RECONNECT_MIN_MS * (1 + config.WS_RECONNECT_JITTER)
    assert low <= socket._retry.interval() <= high
    socket._retry.stop()


def test_a_server_failure_close_backs_off_without_rejecting_the_key(qt_app) -> None:
    """1011 = server-side failure: the key is fine, so no 4401 handling, just the jittered backoff."""
    socket, rejected = _lost_with(config.WS_CLOSE_SERVER_ERROR)
    assert rejected == []
    assert socket._retry.interval() <= config.WS_RECONNECT_MIN_MS * (1 + config.WS_RECONNECT_JITTER)
    assert socket._delay_ms > config.WS_RECONNECT_MIN_MS  # the next drop waits longer
    socket._retry.stop()


def test_heartbeat_not_stored_is_reported(qt_app) -> None:
    import json

    socket = DeviceSocket()
    failed: list[bool] = []
    socket.heartbeat_failed.connect(lambda: failed.append(True))
    socket._on_message(json.dumps({"type": "error", "error": config.WS_HEARTBEAT_NOT_STORED}))
    socket._on_message(json.dumps({"type": "error", "error": "invalid message"}))
    assert failed == [True]
