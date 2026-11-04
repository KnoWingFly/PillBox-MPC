"""Offscreen smoke tests of the window's sync handling (run with QT_QPA_PLATFORM=offscreen).
No backend: sync reports are fed to the window directly."""

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from smart_pillbox import config  # noqa: E402
from smart_pillbox.core.sync import HeartbeatResult  # noqa: E402
from smart_pillbox.db.database import Database  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    db_path = tmp_path / "window.db"
    seed = Database(db_path=db_path)
    seed.update_device_states(
        {"device_code": "PB-SMOKE001", "device_secret": "not-a-real-secret", "is_paired": "1", "is_refill_mode": "1"}
    )
    seed.close()
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.delenv("PILLCARE_DEVICE_CODE", raising=False)
    monkeypatch.delenv("PILLCARE_DEVICE_KEY", raising=False)

    from smart_pillbox.gui.main_window import MainWindow

    monkeypatch.setattr("smart_pillbox.gui.main_window.DeviceSocket.start", lambda *a, **k: None)
    win = MainWindow()
    yield win
    win.close()


def test_refill_mode_is_restored_at_startup(window):
    assert window.scheduler.is_refill_mode
    assert window._btn_refill.text() == "Refill Mode: Active"


def test_unreachable_server_backs_off_and_is_shown(window):
    from smart_pillbox.gui.main_window import SyncReport

    window._is_syncing = True
    window._on_sync_finished(SyncReport(result=HeartbeatResult.NETWORK, pending=3))
    assert window._lbl_pair_status.text() == "Server tidak terjangkau"
    assert "3" in window._lbl_outbox.text()
    assert window._retry_timer.isActive()
    assert "tidak terjangkau" in window.statusBar().currentMessage()

    window._on_sync_finished(SyncReport(result=HeartbeatResult.UNAUTHORIZED, pending=3))
    assert window._lbl_pair_status.text() == "Kunci ditolak: daftarkan ulang"


def test_ok_heartbeat_corrects_a_drifted_rtc(window):
    from smart_pillbox.gui.main_window import SyncReport

    window.clock.set_time(window.clock.now() - timedelta(hours=2))  # e.g. the PC slept
    server_time = datetime.now(timezone.utc).isoformat()
    window._on_sync_finished(
        SyncReport(result=HeartbeatResult.OK, pending=0, server_time=server_time, received_at=time.monotonic(),
                   state={"is_paired": "1", "config_version": window._config_version_seen})
    )
    drift = abs((window.clock.now() - window._device_now()).total_seconds())
    assert drift < config.RTC_DRIFT_CORRECT_SECONDS
    assert window._lbl_pair_status.text() == "Terpasang ke aplikasi"
    assert window._lbl_outbox.text() == "Antrean: kosong"


def test_close_stops_timers_and_the_database(window):
    window.close()
    assert window._stop.is_set()
    assert not window._tick_timer.isActive()
    assert not window._sync_timer.isActive()
