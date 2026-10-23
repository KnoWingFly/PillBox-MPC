"""Device WebSocket: the backend -> device command channel.

Contract: docs/DEVICE_CONTRACT.md §3. Connects to /ws/device/{device_code}
with the X-Device-Key header and turns {"type": "command"} messages into a Qt
signal; the window handles the command and answers with send_ack(). Runs on
the Qt event loop (QtWebSockets ships with PySide6), so no extra thread and no
extra dependency.

Without this socket the app's "Bunyikan alarm" / "Test" fail with 409 and a
schedule change waits for the next heartbeat.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from smart_pillbox import config

logger = logging.getLogger(__name__)


class DeviceSocket(QObject):
    command_received = Signal(str, str, dict)  # command_id, command, payload
    connected_changed = Signal(bool)
    welcome_received = Signal(dict)  # carries server_time + timezone (clock sync)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ws = QWebSocket(parent=self)
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_lost)
        self._ws.errorOccurred.connect(self._on_lost)
        self._ws.textMessageReceived.connect(self._on_message)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._open)
        self._delay_ms = config.WS_RECONNECT_MIN_MS
        self._identity: tuple[str, str] | None = None
        self._wanted = False
        self.is_connected = False

    def start(self, device_code: str, device_key: str) -> None:
        """Connects (or keeps the current connection if the identity is unchanged)."""
        if self._wanted and self._identity == (device_code, device_key):
            return
        self._identity = (device_code, device_key)
        self._wanted = True
        self._delay_ms = config.WS_RECONNECT_MIN_MS
        self._retry.stop()
        self._ws.abort()
        self._open()

    def stop(self) -> None:
        self._wanted = False
        self._retry.stop()
        self._ws.close()

    def send_ack(self, command_id: str, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        ack: dict[str, Any] = {"type": "ack", "command_id": command_id, "ok": ok}
        if ok and result is not None:
            ack["result"] = result
        if not ok:
            ack["error"] = error or "command failed"
        self._ws.sendTextMessage(json.dumps(ack))

    # -- internals ---------------------------------------------------------------
    def _open(self) -> None:
        if not self._wanted or self._identity is None:
            return
        code, key = self._identity
        request = QNetworkRequest(QUrl(config.device_ws_url(code)))
        request.setRawHeader(b"X-Device-Key", key.encode("utf-8"))
        self._ws.open(request)

    def _on_connected(self) -> None:
        self._delay_ms = config.WS_RECONNECT_MIN_MS
        self.is_connected = True
        logger.info("Command channel connected.")
        self.connected_changed.emit(True)

    def _on_lost(self, *_: object) -> None:
        # A failed connect emits errorOccurred (and maybe disconnected): retry once.
        if self.is_connected:
            self.is_connected = False
            logger.info("Command channel disconnected.")
            self.connected_changed.emit(False)
        if self._wanted and not self._retry.isActive():
            self._retry.start(self._delay_ms)
            self._delay_ms = min(self._delay_ms * 2, config.WS_RECONNECT_MAX_MS)

    def _on_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if message.get("type") == "welcome":
            self.welcome_received.emit(message)
            return
        if message.get("type") != "command":
            return  # heartbeat_ack, pong, error: nothing to do
        payload = message.get("payload")
        self.command_received.emit(
            str(message.get("command_id", "")),
            str(message.get("command", "")),
            payload if isinstance(payload, dict) else {},
        )
