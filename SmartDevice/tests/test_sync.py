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
    """A config or disk error in the flush used to skip the heartbeat, so the device went OFFLINE.
    The heartbeat now goes first, and the worker still reports back."""
    from smart_pillbox.core.rtc import SimulatedClock
    from smart_pillbox.gui.main_window import SyncWorker

    beats: list[str] = []

    def broken_flush(*_: object, **__: object) -> int:
        raise KeyError("slot_number")

    def heartbeat(*args: object, **_: object) -> sync.HeartbeatOutcome:
        beats.append(args[1])  # type: ignore[arg-type]
        return sync.HeartbeatOutcome(sync.HeartbeatResult.OK)

    monkeypatch.setattr(sync, "flush_pending_events", broken_flush)
    monkeypatch.setattr(sync, "send_heartbeat", heartbeat)
    reports: list = []
    worker = SyncWorker(db, SimulatedClock(start_at=T0, speed=1.0), battery=80, is_online=True, chambers=[])
    worker.signals.finished.connect(reports.append)
    worker.run()
    assert len(beats) == 1
    assert len(reports) == 1 and reports[0].error  # finished is emitted even when the flush raises
    assert reports[0].pending == 5


def test_worker_reports_not_registered_without_sending(tmp_path, monkeypatch) -> None:
    from smart_pillbox.core.rtc import SimulatedClock
    from smart_pillbox.gui.main_window import SyncWorker

    database = Database(db_path=tmp_path / "fresh.db")
    monkeypatch.setattr(sync, "_http", lambda: pytest.fail("nothing may be sent"))
    reports: list = []
    worker = SyncWorker(database, SimulatedClock(start_at=T0), battery=80, is_online=True, chambers=[])
    worker.signals.finished.connect(reports.append)
    worker.run()
    assert [r.result for r in reports] == [sync.HeartbeatResult.NOT_REGISTERED]
    database.close()


# --- heartbeat result states ------------------------------------------------------

class _HeartbeatAnswer:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.sent: list[dict] = []

    def post(self, url: str, json: dict, **_: object) -> object:
        self.sent.append(json)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class _NotJson(_Response):
    def json(self) -> dict:
        raise requests.JSONDecodeError("bad", "doc", 0)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (requests.ConnectionError("refused"), sync.HeartbeatResult.NETWORK),
        (requests.Timeout("slow"), sync.HeartbeatResult.NETWORK),
        (_Response(401), sync.HeartbeatResult.UNAUTHORIZED),
        (_Response(503), sync.HeartbeatResult.HTTP_ERROR),
        (_NotJson(200), sync.HeartbeatResult.HTTP_ERROR),
        (_Response(200, {"is_paired": False, "server_time": "2026-01-01T00:00:00Z"}), sync.HeartbeatResult.OK),
    ],
)
def test_heartbeat_result_states(db, monkeypatch, answer, expected) -> None:
    _use(monkeypatch, _HeartbeatAnswer(answer))  # type: ignore[arg-type]
    outcome = sync.send_heartbeat(db, T0.isoformat(), 90, is_online=True)
    assert outcome.result == expected
    assert outcome.result.server_unreachable == (expected in (sync.HeartbeatResult.NETWORK, sync.HeartbeatResult.HTTP_ERROR))
    if expected == sync.HeartbeatResult.OK:
        assert outcome.server_time == "2026-01-01T00:00:00Z" and outcome.received_at is not None


def test_heartbeat_offline_and_unregistered_send_nothing(db, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sync, "_http", lambda: pytest.fail("nothing may be sent"))
    assert sync.send_heartbeat(db, T0.isoformat(), 90, is_online=False).result == sync.HeartbeatResult.OFFLINE
    fresh = Database(db_path=tmp_path / "fresh.db")
    assert sync.send_heartbeat(fresh, T0.isoformat(), 90, is_online=True).result == sync.HeartbeatResult.NOT_REGISTERED
    fresh.close()


def test_heartbeat_reports_an_open_door(db, monkeypatch) -> None:
    """Door state lives only in the scheduler's compartments; the database copy is always closed."""
    from smart_pillbox.core.rtc import SimulatedClock
    from smart_pillbox.core.scheduler import PillboxScheduler

    scheduler = PillboxScheduler(db, SimulatedClock(start_at=T0))
    opened = next(c for c in scheduler.compartments.values() if c.slot_number == 3)
    scheduler.open_compartment(opened.id)  # unscheduled open: the lid is now open
    backend = _HeartbeatAnswer(_Response(200, {"is_paired": True}))
    _use(monkeypatch, backend)  # type: ignore[arg-type]

    sync.send_heartbeat(db, T0.isoformat(), 90, True, chambers=sync.chamber_report(scheduler.compartments.values()))

    doors = {c["slot_number"]: c["door"] for c in backend.sent[0]["chambers"]}
    assert doors[3] == "OPEN"
    assert [slot for slot, door in doors.items() if door == "OPEN"] == [3]
    assert len(doors) == sync.config.NUM_CHAMBERS


def test_heartbeat_key_rejected_keeps_pairing_state(db, monkeypatch) -> None:
    """A 401 is shown as "key rejected", not as the pairing prompt."""
    db.update_device_state("is_paired", "1")
    _use(monkeypatch, _HeartbeatAnswer(_Response(401)))  # type: ignore[arg-type]
    assert sync.send_heartbeat(db, T0.isoformat(), 90, True).result == sync.HeartbeatResult.UNAUTHORIZED
    assert db.get_device_state("is_paired") == "1"


# --- outbox status handling -------------------------------------------------------

@pytest.mark.parametrize("status", [302, 304, 101])
def test_a_status_that_is_no_answer_keeps_the_events(db, monkeypatch, status) -> None:
    """Only 2xx and the contract's final 4xx mark events synced (contract §2.4); a redirect from a
    captive portal or proxy is no answer for the events and used to drop them."""
    _use(monkeypatch, _Backend(_Response(status)))
    assert sync.flush_pending_events(db) == 0
    assert len(db.get_unsynced_events()) == 5


@pytest.mark.parametrize(
    "answer",
    [
        _NotJson(404),                                   # wrong URL / proxy page, not JSON
        _Response(404, {"detail": "Not Found"}),         # JSON, but not the PillCare envelope
        _Response(403, {"error": "blocked by portal"}),  # "error" that is not an object with a code
    ],
)
def test_a_4xx_without_the_backend_error_body_keeps_the_events(db, monkeypatch, answer) -> None:
    """Contract §2.4: a 4xx is final only with {"error": {"code": ...}}; anything else did not
    come from the backend (wrong URL, proxy, captive portal)."""
    _use(monkeypatch, _Backend(answer))
    assert sync.flush_pending_events(db) == 0
    assert len(db.get_unsynced_events()) == 5


def test_a_422_with_the_error_envelope_is_final(db, monkeypatch) -> None:
    _use(monkeypatch, _Backend(_Response(422, {"error": {"code": "VALIDATION_ERROR", "message": "bad"}})))
    assert sync.flush_pending_events(db) == 5
    assert db.get_unsynced_events() == []


def test_payload_too_large_is_resent_in_smaller_chunks(db, monkeypatch) -> None:
    ok = _Response(200, {"results": []})
    backend = _Backend(_Response(413, {"error": {"code": "PAYLOAD_TOO_LARGE"}}), ok)
    _use(monkeypatch, backend)
    assert sync.flush_pending_events(db) == 5
    assert len(backend.batches) == 2


def test_heartbeat_flags_a_waiting_config_without_pulling_it(db, monkeypatch) -> None:
    """The heartbeat stays one short request; the worker pulls the config after the flush."""
    class _Backend200:
        gets = 0

        def post(self, url: str, json: dict, **_: object) -> _Response:
            return _Response(200, {"is_paired": True, "latest_config_version": 3, "config_update_available": True})

        def get(self, url: str, **_: object) -> _Response:
            _Backend200.gets += 1
            return _Response(304)

    _use(monkeypatch, _Backend200())  # type: ignore[arg-type]
    outcome = sync.send_heartbeat(db, T0.isoformat(), 90, True)
    assert outcome.config_update is True
    assert _Backend200.gets == 0


def test_a_boolean_latest_version_is_not_a_version(db, monkeypatch) -> None:
    db.update_device_state("config_version", "0")
    _use(monkeypatch, _HeartbeatAnswer(_Response(200, {"latest_config_version": True})))  # type: ignore[arg-type]
    assert sync.send_heartbeat(db, T0.isoformat(), 90, True).config_update is False


def test_flush_stops_between_chunks_when_asked(db, monkeypatch) -> None:
    import threading

    stop = threading.Event()
    stop.set()
    backend = _Backend(_Response(200, {"results": []}))
    _use(monkeypatch, backend)
    assert sync.flush_pending_events(db, stop=stop) == 0
    assert backend.batches == []


# --- config apply -----------------------------------------------------------------

class _ConfigAnswer:
    def __init__(self, body: object) -> None:
        self.body = body
        self.acked: list[dict] = []

    def get(self, url: str, **_: object) -> _Response:
        return _Response(200, self.body)  # type: ignore[arg-type]

    def post(self, url: str, json: dict, **_: object) -> _Response:
        self.acked.append(json)
        return _Response(200, {})


GOOD_SCHEDULE = {"slot_number": 1, "window_start": "09:00", "window_end": "09:15", "tolerance_minutes": 20,
                 "days_of_week": [1, 2, 3], "active": True, "schedule_id": "sch-1", "medication_name": "A"}


@pytest.mark.parametrize(
    "body",
    [
        {"config_version": 8, "schedules": [GOOD_SCHEDULE, {"slot_number": 2, "window_start": "25:00"}]},
        {"config_version": 8, "schedules": [GOOD_SCHEDULE, {"window_start": "08:00"}]},
        {"config_version": 8, "schedules": [GOOD_SCHEDULE, {"slot_number": 9, "window_start": "08:00"}]},
        {"config_version": 8, "schedules": [GOOD_SCHEDULE, {**GOOD_SCHEDULE, "tolerance_minutes": -5}]},
        {"config_version": 8, "schedules": [GOOD_SCHEDULE, GOOD_SCHEDULE]},
        {"config_version": 8, "schedules": "not a list"},
        {"config_version": None, "schedules": [GOOD_SCHEDULE]},
        {"schedules": [GOOD_SCHEDULE]},
        {"config_version": 8, "timezone": "Mars/Olympus", "schedules": [GOOD_SCHEDULE]},
        {"config_version": 8, "chime_volume_level": "LOUDEST", "schedules": [GOOD_SCHEDULE]},
        {"config_version": 8, "is_refill_mode": "yes", "schedules": [GOOD_SCHEDULE]},
        ["not", "an", "object"],
    ],
)
def test_bad_or_partial_config_keeps_the_old_config(db, monkeypatch, body) -> None:
    db.update_device_states({"config_version": "4", "is_refill_mode": "0", "timezone": "Asia/Jakarta"})
    before = [(c.slot_number, c.schedule_time, c.tolerance_minutes, c.is_active) for c in db.get_compartments()]
    backend = _ConfigAnswer(body)
    _use(monkeypatch, backend)  # type: ignore[arg-type]

    assert sync.pull_latest_config(db) is False

    after = [(c.slot_number, c.schedule_time, c.tolerance_minutes, c.is_active) for c in db.get_compartments()]
    assert after == before
    assert db.get_device_state("config_version") == "4"  # never "None", never half applied
    assert db.get_device_state("is_refill_mode") == "0"
    assert db.get_device_state("timezone") == "Asia/Jakarta"
    assert backend.acked == []  # an invalid config is not acked


def test_good_config_applies_window_end_schedule_id_and_volume(db, monkeypatch) -> None:
    backend = _ConfigAnswer({"config_version": 9, "chime_volume_level": "HIGH", "schedules": [GOOD_SCHEDULE]})
    _use(monkeypatch, backend)  # type: ignore[arg-type]
    assert sync.pull_latest_config(db) is True
    slot1 = next(c for c in db.get_compartments() if c.slot_number == 1)
    assert (slot1.schedule_time, slot1.window_end, slot1.schedule_id) == ("09:00", "09:15", "sch-1")
    assert slot1.days_of_week == [1, 2, 3]
    assert db.get_device_state("chime_volume_level") == "HIGH"
    assert db.get_device_state("config_version") == "9"
    assert backend.acked[0]["config_version"] == 9


def test_unreadable_stored_version_pulls_a_full_config(db) -> None:
    db.update_device_state("config_version", "None")  # written by an older emulator
    assert sync.applied_config_version(db) == 0


# --- identity reset -------------------------------------------------------------------

def test_forget_identity_clears_the_outbox_and_the_old_server_state(db) -> None:
    db.update_device_states({"config_version": "12", "timezone": "Asia/Makassar", "is_refill_mode": "1", "is_paired": "1"})
    synced_id = db.get_unsynced_events()[0]["id"]
    db.mark_synced([synced_id])

    sync.forget_identity(db)

    assert db.get_unsynced_events() == []
    assert db._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1  # history is kept
    assert db.get_device_state("device_code") == "" and db.get_device_state("device_secret") == ""
    assert sync.applied_config_version(db) == 0
    assert db.get_device_state("is_refill_mode") == "0"
    assert sync.device_timezone(db) == sync.config.DEFAULT_DEVICE_TIMEZONE
    assert not sync.is_paired(db)


# --- backoff --------------------------------------------------------------------------

def test_backoff_grows_exponentially_and_is_capped() -> None:
    cfg = sync.config
    no_jitter = lambda: 0.5  # noqa: E731 - rand() = 0.5 means no jitter
    delays = [sync.backoff_delay(n, no_jitter) for n in range(1, 10)]
    assert delays[0] == cfg.SYNC_BACKOFF_MIN_SECONDS
    assert delays[1] == 2 * cfg.SYNC_BACKOFF_MIN_SECONDS
    assert max(delays) == cfg.SYNC_BACKOFF_MAX_SECONDS
    assert delays == sorted(delays)
    assert sync.backoff_delay(0) == 0
    low, high = sync.backoff_delay(1, lambda: 0.0), sync.backoff_delay(1, lambda: 1.0)
    assert low == pytest.approx(cfg.SYNC_BACKOFF_MIN_SECONDS * (1 - cfg.SYNC_BACKOFF_JITTER))
    assert high == pytest.approx(cfg.SYNC_BACKOFF_MIN_SECONDS * (1 + cfg.SYNC_BACKOFF_JITTER))


def test_worker_pulls_a_waiting_config_after_the_flush(db, monkeypatch) -> None:
    """Contract §5.3: heartbeat, then the buffered events, then the config."""
    from smart_pillbox.core.rtc import SimulatedClock
    from smart_pillbox.gui.main_window import SyncWorker

    calls: list[str] = []
    monkeypatch.setattr(sync, "send_heartbeat", lambda *a, **k: calls.append("heartbeat")
                        or sync.HeartbeatOutcome(sync.HeartbeatResult.OK, config_update=True))
    monkeypatch.setattr(sync, "flush_pending_events", lambda *a, **k: calls.append("flush") or 0)
    monkeypatch.setattr(sync, "pull_latest_config", lambda *a, **k: calls.append("config") or True)
    SyncWorker(db, SimulatedClock(start_at=T0), battery=80, is_online=True, chambers=[]).run()
    assert calls == ["heartbeat", "flush", "config"]
