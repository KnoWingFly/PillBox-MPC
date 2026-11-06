"""Device WebSocket (/ws/device/{code}) against a real database."""

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.services.connection_manager import WS_CLOSE_AUTH_FAILED, connection_manager
from tests.constants import TEST_PROVISIONING_TOKEN
from tests.helpers import API

ADMIN = {"X-Provisioning-Token": TEST_PROVISIONING_TOKEN}


@pytest.fixture
def tc() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def _next_reply(ws: WebSocketTestSession) -> dict[str, Any]:
    """Skips the commands the server pushes on its own (e.g. schedule_updated on connect)."""
    while True:
        message: dict[str, Any] = ws.receive_json()
        if message.get("type") != "command":
            return message


def test_rotating_the_secret_closes_the_open_socket(tc: TestClient, db) -> None:  # noqa: ANN001 (db truncates)
    dev = tc.post(f"{API}/admin/devices", json={}, headers=ADMIN).json()
    with tc.websocket_connect(f"/ws/device/{dev['device_code']}", headers={"X-Device-Key": dev["device_secret"]}) as ws:
        assert _next_reply(ws)["type"] == "welcome"
        res = tc.post(f"{API}/admin/devices/{dev['device_code']}/rotate-secret", json={}, headers=ADMIN)
        assert res.status_code == 200

        with pytest.raises(WebSocketDisconnect) as closed:
            ws.send_json({"type": "heartbeat", "battery_percent": 33})
            _next_reply(ws)
        assert closed.value.code == WS_CLOSE_AUTH_FAILED
    assert connection_manager._connections == {}

    new_key = {"X-Device-Key": res.json()["device_secret"]}
    hb = tc.post(f"{API}/devices/{dev['device_code']}/heartbeat", json={"battery_percent": 33}, headers=new_key)
    assert hb.status_code == 200


def test_invalid_heartbeat_error_does_not_echo_the_values(tc: TestClient, db) -> None:  # noqa: ANN001 (db truncates)
    dev = tc.post(f"{API}/admin/devices", json={}, headers=ADMIN).json()
    with tc.websocket_connect(f"/ws/device/{dev['device_code']}", headers={"X-Device-Key": dev["device_secret"]}) as ws:
        assert _next_reply(ws)["type"] == "welcome"
        ws.send_json({"type": "heartbeat", "battery_percent": "secret-looking-value"})
        error = _next_reply(ws)
    assert error["type"] == "error" and error["details"][0]["loc"] == ["battery_percent"]
    assert "secret-looking-value" not in str(error)
