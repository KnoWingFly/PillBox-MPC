"""Outbox flush against stubbed backend answers (no network, no Qt)."""

from datetime import datetime, timedelta

import pytest
import requests

from smart_pillbox.core import sync
from smart_pillbox.db.database import Database

T0 = datetime(2026, 1, 1, 7, 0, 0)


class _Response:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self) -> dict:
        return self._body


class _Backend:
    """Answers telemetry posts with the queued responses (an exception is raised instead)."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.batches: list[list[dict]] = []

    def post(self, url: str, json: dict, **_: object) -> _Response:
        self.batches.append(json["events"])
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[return-value]


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=tmp_path / "outbox.db")
    database.update_device_state("device_code", "PB-TEST0001")
    database.update_device_state("device_secret", "test-secret-not-real")
    compartment_id = database.get_compartments()[0].id
    for k in range(5):
        database.log_event(compartment_id, 1, "REFILL_MAINTENANCE", T0 + timedelta(seconds=k))
    yield database
    database.close()


def _use(monkeypatch: pytest.MonkeyPatch, backend: _Backend) -> None:
    monkeypatch.setattr(sync, "_http", lambda: backend)


@pytest.mark.parametrize("answer", [requests.ConnectionError("down"), _Response(503), _Response(401), _Response(429)])
def test_network_errors_5xx_and_auth_keep_the_events(db, monkeypatch, answer) -> None:
    _use(monkeypatch, _Backend(answer))
    assert sync.flush_pending_events(db) == 0
    assert len(db.get_unsynced_events()) == 5


def test_a_final_4xx_does_not_block_the_outbox(db, monkeypatch) -> None:
    """A batch the backend refuses for good (e.g. 422) used to be retried forever, blocking every later event."""
    _use(monkeypatch, _Backend(_Response(422, {"error": {"code": "VALIDATION_ERROR"}})))
    assert sync.flush_pending_events(db) == 5
    assert db.get_unsynced_events() == []


def test_batch_too_large_is_resent_in_smaller_chunks(db, monkeypatch) -> None:
    ok = _Response(200, {"results": [], "latest_config_version": 0})
    backend = _Backend(_Response(413), _Response(413), ok)
    _use(monkeypatch, backend)
    assert sync.flush_pending_events(db) == 5
    assert len(backend.batches) == 3  # 413, 413 (chunk halved each time), then accepted
    assert db.get_unsynced_events() == []


def test_events_go_oldest_first_with_their_own_ids(db, monkeypatch) -> None:
    backend = _Backend(_Response(200, {"results": [], "latest_config_version": 0}))
    _use(monkeypatch, backend)
    local = [row["event_id"] for row in db.get_unsynced_events()]
    sync.flush_pending_events(db, offline_flush=True)
    sent = backend.batches[0]
    assert [e["event_id"] for e in sent] == local
    assert [e["occurred_at"] for e in sent] == sorted(e["occurred_at"] for e in sent)


def test_pulled_config_applies_refill_mode_and_timezone(db, monkeypatch) -> None:
    config_body = {
        "config_version": 7, "timezone": "Asia/Makassar", "chime_volume_level": "MEDIUM",
        "is_refill_mode": True, "schedules": [],
    }

    class _ConfigBackend:
        acked: list[dict] = []

        def get(self, url: str, **_: object) -> _Response:
            return _Response(200, config_body)

        def post(self, url: str, json: dict, **_: object) -> _Response:
            self.acked.append(json)
            return _Response(200, {"acknowledged": True})

    backend = _ConfigBackend()
    _use(monkeypatch, backend)  # type: ignore[arg-type]
    sync.pull_latest_config(db)

    assert db.get_device_state("is_refill_mode") == "1"
    assert db.get_device_state("timezone") == "Asia/Makassar"
    assert db.get_device_state("config_version") == "7"
    assert backend.acked and backend.acked[0]["config_version"] == 7


def test_heartbeat_stores_the_server_interval_and_sends_simulated_readings(db, monkeypatch) -> None:
    sent: list[dict] = []

    class _HeartbeatBackend:
        def post(self, url: str, json: dict, **_: object) -> _Response:
            sent.append(json)
            return _Response(200, {"is_paired": True, "heartbeat_interval_seconds": 20,
                                   "latest_config_version": 0, "config_update_available": False})

    _use(monkeypatch, _HeartbeatBackend())  # type: ignore[arg-type]
    sync.send_heartbeat(db, T0.isoformat(), 90, is_online=True)

    assert db.get_device_state("heartbeat_interval_seconds") == "20"
    assert sent[0]["wifi_rssi_dbm"] == sync.config.SIMULATED_WIFI_RSSI_DBM
    assert sent[0]["rtc_backup_active"] is sync.config.SIMULATED_RTC_BACKUP_ACTIVE


def test_config_ack_uses_the_device_clock(db, monkeypatch) -> None:
    acked: list[dict] = []

    class _ConfigBackend:
        def get(self, url: str, **_: object) -> _Response:
            return _Response(200, {"config_version": 3, "schedules": []})

        def post(self, url: str, json: dict, **_: object) -> _Response:
            acked.append(json)
            return _Response(200, {})

    _use(monkeypatch, _ConfigBackend())  # type: ignore[arg-type]
    device_time = "2026-01-01T09:30:00"
    sync.pull_latest_config(db, device_time)
    assert acked == [{"config_version": 3, "applied_at": device_time}]


def test_a_failing_flush_still_sends_the_heartbeat(db, monkeypatch) -> None:
    """A config or disk error in the flush used to skip the heartbeat, so the device went OFFLINE."""
    from smart_pillbox.core.rtc import SimulatedClock
    from smart_pillbox.gui.main_window import SyncWorker

    beats: list[str] = []

    def broken_flush(*_: object, **__: object) -> int:
        raise KeyError("slot_number")

    monkeypatch.setattr(sync, "flush_pending_events", broken_flush)
    monkeypatch.setattr(sync, "send_heartbeat", lambda *args, **kwargs: beats.append(args[1]))
    SyncWorker(db, SimulatedClock(start_at=T0, speed=1.0), battery=80, is_online=True).run()
    assert len(beats) == 1
