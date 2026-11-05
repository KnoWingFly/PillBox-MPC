"""App alarm commands on the emulator window (Qt offscreen, temporary database, no network)."""

import pytest
from PySide6.QtWidgets import QApplication

from smart_pillbox import config
from smart_pillbox.gui import main_window
from smart_pillbox.models import ChamberState


@pytest.fixture
def window(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pillbox.db")
    monkeypatch.setattr(main_window, "play_chime", lambda: None)
    monkeypatch.setattr(main_window, "stop_chime", lambda: None)
    win = main_window.MainWindow()
    acks: list[tuple[str, bool, dict | None]] = []
    monkeypatch.setattr(win._socket, "send_ack", lambda cid, ok, result=None, error=None: acks.append((cid, ok, result)))
    monkeypatch.setattr(win, "_request_sync", lambda: None)
    win.acks = acks  # type: ignore[attr-defined]
    yield win
    win._sync_timer.stop()
    win.db.close()


def test_stop_alarm_silences_an_alarm_started_from_the_app(window) -> None:
    window._on_device_command("cmd-1", "trigger_alarm", {"slot_number": 1, "duration_seconds": 60})
    assert window._alarm_until is not None and window._chime_timer.isActive()

    window._on_device_command("cmd-2", "stop_alarm", {"reason": "caregiver_request"})

    assert window._alarm_until is None and not window._chime_timer.isActive()
    assert window.acks[-1] == ("cmd-2", True, {"ringing": False})
    logged = [e["event_type"] for e in window.db.get_unsynced_events()]
    assert logged[-2:] == ["ALARM_STARTED", "ALARM_STOPPED"]


def test_stop_alarm_keeps_a_dose_reminder_ringing(window) -> None:
    compartment = next(iter(window.scheduler.compartments.values()))
    compartment.state = ChamberState.ACTIVE
    compartment.stock_count = 3
    window.scheduler.active_chamber_id = compartment.id
    window._on_device_command("cmd-1", "trigger_alarm", {"slot_number": None, "duration_seconds": 60})

    window._on_device_command("cmd-2", "stop_alarm", {})

    assert window._alarm_until is None
    assert window._chime_timer.isActive()  # the popped-up dose still rings
    assert window.acks[-1] == ("cmd-2", True, {"ringing": False})
