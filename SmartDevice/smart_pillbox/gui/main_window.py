from __future__ import annotations

import logging
import sqlite3
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PySide6.QtCore import Qt, QTimer, QRunnable, QThreadPool, QObject, Signal, QLockFile, QProcess
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QStatusBar, QFrame, QGroupBox, QSlider, QCheckBox, QComboBox,
    QApplication, QInputDialog, QLineEdit, QMessageBox
)

from smart_pillbox import config
from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.core.scheduler import PillboxScheduler
from smart_pillbox.core.audio import play_chime, set_volume_level, stop_chime
from smart_pillbox.core import sync
from smart_pillbox.core.sync import HeartbeatResult
from smart_pillbox.core.ws_client import DeviceSocket
from smart_pillbox.db.database import Database, backup_corrupt_database
from smart_pillbox.gui.compartment_widget import CompartmentWidget, locked_message
from smart_pillbox.gui.lcd_widget import (
    REFILL_BANNER, STATUS_DOSE, STATUS_EMPTY, STATUS_IDLE, STATUS_MAINTENANCE, LcdDisplay,
)
from smart_pillbox.gui.caregiver_tray_widget import CaregiverTrayWidget
from smart_pillbox.gui.lansia_tray_widget import LansiaTrayWidget
from smart_pillbox.gui.qr_widget import QrDialog, QrWidget
from smart_pillbox.gui import styles
from smart_pillbox.models import Compartment, ChamberState

logger = logging.getLogger(__name__)

# device_state keys the window follows; the sync worker reads them so the GUI thread does not.
_STATE_KEYS = (
    config.STATE_CONFIG_VERSION, config.STATE_IS_REFILL_MODE, config.STATE_TIMEZONE, config.STATE_HEARTBEAT_INTERVAL_SECONDS, config.STATE_IS_PAIRED, config.STATE_CHIME_VOLUME_LEVEL,
)

_KEY_REJECTED = "Kunci perangkat ditolak server: daftarkan ulang perangkat."
_SERVER_UNREACHABLE = "Server tidak terjangkau: event disimpan di perangkat."
_NOT_REGISTERED = "Belum terdaftar ke server: tekan 'Daftarkan Perangkat'."
_OFFLINE = "Offline - Events buffered locally."
# Status bar text after a sync, by heartbeat result (OK is built from the synced count).
_SYNC_MESSAGES = {
    HeartbeatResult.NOT_REGISTERED: _NOT_REGISTERED,
    HeartbeatResult.OFFLINE: _OFFLINE,
    HeartbeatResult.UNAUTHORIZED: _KEY_REJECTED,
    HeartbeatResult.HTTP_ERROR: "Server menjawab dengan galat: event disimpan di perangkat.",
    HeartbeatResult.NETWORK: _SERVER_UNREACHABLE,
    HeartbeatResult.ERROR: "Sinkronisasi gagal di perangkat (lihat log).",
}


@dataclass
class SyncReport:
    """What one background sync did, plus the state the window follows (read on the worker)."""

    result: HeartbeatResult = HeartbeatResult.ERROR  # until the heartbeat ran
    synced: int = 0
    pending: int | None = None          # unsynced events left in the outbox (None: unknown)
    server_time: str | None = None      # from the heartbeat answer, for the RTC drift check
    received_at: float | None = None    # time.monotonic() when that answer arrived
    error: str | None = None            # an unexpected exception, logged with its traceback
    state: dict[str, str | None] = field(default_factory=dict)
    compartments: list[Compartment] | None = None  # re-read when a new config was applied


class SyncSignals(QObject):
    finished = Signal(object)  # SyncReport


class SyncWorker(QRunnable):
    """Background worker to execute telemetry sync without blocking the Qt GUI thread."""

    def __init__(
        self,
        db: Database,
        clock: SimulatedClock,
        battery: int,
        is_online: bool,
        chambers: list[dict],
        config_version_seen: str | None = None,
        after_reconnect: bool = False,
        stop: threading.Event | None = None,
    ):
        super().__init__()
        self.db = db
        self.clock = clock
        self.battery = battery
        self.is_online = is_online
        self.chambers = chambers  # sync.chamber_report() of the live compartments, taken on the GUI thread
        self.config_version_seen = config_version_seen
        # Contract §5.3: right after Wi-Fi returns, heartbeat first, then flush the buffer.
        self.after_reconnect = after_reconnect
        self.stop = stop
        self.signals = SyncSignals()

    def run(self):
        report = SyncReport()
        try:
            self._sync(report)
        except Exception as exc:  # noqa: BLE001 - finished must always be emitted; logged
            logger.exception("Sync failed.")
            report.error = str(exc)
        finally:
            try:
                report.pending = self.db.count_unsynced_events()
                report.state = self.db.get_device_states(_STATE_KEYS)
                if report.state.get(config.STATE_CONFIG_VERSION) != self.config_version_seen:
                    report.compartments = self.db.get_compartments()
            except Exception:  # noqa: BLE001 - e.g. the database closed during shutdown
                logger.exception("Could not read the device state after a sync.")
            try:
                self.signals.finished.emit(report)
            except RuntimeError:
                pass  # the window is already gone

    def _sync(self, report: SyncReport) -> None:
        if not sync.is_registered(self.db):
            report.result = HeartbeatResult.NOT_REGISTERED
            return
        # Heartbeat first, in its own short request: a slow flush or config pull must never push it
        # past the backend's offline timeout. Read the RTC when it goes out (contract §2.1).
        outcome = sync.send_heartbeat(
            self.db, self.clock.now().isoformat(), self.battery, self.is_online, self.clock.speed, self.chambers
        )
        report.result, report.server_time, report.received_at = outcome.result, outcome.server_time, outcome.received_at
        if outcome.result in (HeartbeatResult.NETWORK, HeartbeatResult.UNAUTHORIZED):
            return  # the server was not reached, or rejects this key: a flush now cannot succeed
        if self.stop is not None and self.stop.is_set():
            return
        version_at_heartbeat = sync.applied_config_version(self.db)
        report.synced = sync.flush_pending_events(
            self.db, offline_flush=self.after_reconnect, device_time=self.clock.now().isoformat(), stop=self.stop
        )
        # Contract §5.3: heartbeat, flush, then the config (unless the flush already pulled it).
        stopped = self.stop is not None and self.stop.is_set()
        if outcome.config_update and not stopped and sync.applied_config_version(self.db) == version_at_heartbeat:
            sync.pull_latest_config(self.db, self.clock.now().isoformat())


class RegisterSignals(QObject):
    finished = Signal(bool, str)


class RegisterWorker(QRunnable):
    """Registers the device with the backend off the GUI thread."""

    def __init__(self, db: Database, token: str):
        super().__init__()
        self.db = db
        self.token = token
        self.signals = RegisterSignals()

    def run(self):
        ok, message = False, ""
        try:
            message = sync.register_device(self.db, self.token)
            ok = True
        except sync.RegistrationError as exc:
            message = str(exc)
        except Exception:  # noqa: BLE001 - finished must always be emitted; logged
            logger.exception("Registration failed.")
            message = "Registrasi gagal karena galat tak terduga (lihat log)."
        try:
            self.signals.finished.emit(ok, message)
        except RuntimeError:
            pass  # the window is already gone


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        title = "Smart Pillbox — Device Simulator (CE739L)"
        self.setWindowTitle(title if config.PROFILE == config.DEFAULT_PROFILE else f"{title} [{config.PROFILE}]")
        self.resize(1260, 840)
        self.setMinimumSize(1180, 780)
        self.setStyleSheet(f"background-color: {styles.BACKGROUND};")

        self.db = self._open_database()
        state = self.db.get_device_states(_STATE_KEYS)
        self._timezone = state[config.STATE_TIMEZONE] or config.DEFAULT_DEVICE_TIMEZONE
        self._zone = sync.device_zone(self._timezone)
        self._tz_label = self._zone_label()
        # The RTC starts on the device's local time, not the PC's (they differ for a non-WIB device).
        self.clock = SimulatedClock(start_at=self._device_now(), speed=config.DEFAULT_SIM_SPEED)
        self._prune_old_events()
        set_volume_level(state[config.STATE_CHIME_VOLUME_LEVEL])
        self.scheduler = PillboxScheduler(self.db, self.clock)
        self.scheduler.on_activated.append(self._on_state_changed)
        self.scheduler.on_missed.append(self._on_state_changed)
        self.scheduler.on_taken.append(self._on_state_changed)
        for hook in (self.scheduler.on_activated, self.scheduler.on_missed, self.scheduler.on_taken):
            hook.append(lambda _compartment: self._request_sync())
        self.scheduler.on_restored.append(self._on_day_restored)

        self._widgets: dict[int, CompartmentWidget] = {}
        self._is_online = True
        self._is_syncing = False
        self._sync_again = False  # a sync was requested while one was running
        self._reconnected = False  # next sync is the first after Wi-Fi returned
        self._is_registering = False
        self._launching_until = 0.0  # monotonic: "Tambah Pillbox Virtual" waits for the new window
        self._battery_percent = 100
        self._config_version_seen = state[config.STATE_CONFIG_VERSION]
        # Cached so the 1 s tick never reads SQLite: updated when they change (sync, register, reset).
        self._identity = sync.get_identity(self.db)
        self._paired = state[config.STATE_IS_PAIRED] == config.STATE_TRUE
        self._link_state: HeartbeatResult | None = None  # result of the last heartbeat
        self._pending: int | None = self.db.count_unsynced_events()
        self._sync_failures = 0  # in a row, for the backoff
        self._stop = threading.Event()  # set by closeEvent; workers stop between steps
        self._closing = False
        self._next_profile_check = 0.0  # monotonic
        # True once the lab clock was moved on purpose (+1 hour, speed, jump): the server's
        # clock must then not silently undo it on reconnect. "Sync Jam Nyata" clears it.
        self._manual_clock = False
        # "Bunyikan alarm" / "Test pengingat" from the app: rings until this monotonic time.
        self._alarm_until: float | None = None
        self._alarm_slot: int | None = None  # None = the whole box

        self._build_ui()
        self._apply_refill_ui()  # refill mode survives a restart
        self._refresh_connection_panel()
        self._refresh_virtual_panel()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(config.TICK_INTERVAL_MS)  # simulated speed handled by SimulatedClock
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        # Rings again every few seconds while a chamber is popped up, like the real buzzer.
        self._chime_timer = QTimer(self)
        self._chime_timer.setInterval(config.CHIME_REPEAT_SECONDS * 1000)
        self._chime_timer.timeout.connect(play_chime)

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(config.SYNC_INTERVAL_SECONDS * 1000)
        self._sync_timer.timeout.connect(self._on_sync_tick)
        self._sync_timer.start()

        # Events are sent right away instead of waiting up to SYNC_INTERVAL_SECONDS;
        # the short debounce sends a burst (e.g. open + close) as one batch.
        self._flush_soon = QTimer(self)
        self._flush_soon.setSingleShot(True)
        self._flush_soon.setInterval(config.SYNC_DEBOUNCE_MS)
        self._flush_soon.timeout.connect(self._on_sync_tick)

        # After a failed sync the next one waits (exponential backoff with jitter, sync.backoff_delay).
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(lambda: self._on_sync_tick(force=True))

        self._socket = DeviceSocket(self)
        self._socket.command_received.connect(self._on_device_command)
        self._socket.welcome_received.connect(self._on_welcome)
        self._socket.auth_rejected.connect(self._on_auth_rejected)
        self._socket.heartbeat_failed.connect(self._on_ws_heartbeat_failed)
        self._apply_heartbeat_interval(state[config.STATE_HEARTBEAT_INTERVAL_SECONDS])
        self._acked_commands: OrderedDict[str, tuple[bool, dict | None, str | None]] = OrderedDict()
        # Backend reachable again: send anything buffered now, not on the next tick.
        self._socket.connected_changed.connect(lambda ok: ok and self._on_server_reachable())
        self._refresh_socket()

    # -- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(15, 12, 15, 12)
        main_layout.setSpacing(12)

        # -- Top Section: 3-Zone Architecture --
        zones_layout = QHBoxLayout()
        zones_layout.setSpacing(14)

        # Zone 1: Caregiver Tray (Left Side)
        self.caregiver_tray = CaregiverTrayWidget(scheduler=self.scheduler, parent=central)
        self.caregiver_tray.bulk_fill_all_requested.connect(self._on_bulk_fill_requested)
        self.caregiver_tray.toggle_refill_requested.connect(self._toggle_refill_mode)
        zones_layout.addWidget(self.caregiver_tray)

        # Zone 2: Physical Device Chassis (Center)
        self.chassis = QFrame(self)
        self.chassis.setStyleSheet(f"""
            QFrame {{
                background-color: {styles.CHASSIS_BG};
                border-radius: 16px;
                border: 1px solid {styles.CHASSIS_BORDER};
            }}
        """)
        chassis_layout = QVBoxLayout(self.chassis)
        chassis_layout.setContentsMargins(20, 16, 20, 20)
        chassis_layout.setSpacing(12)

        # Top section of chassis: Centered OLED Display
        top_chassis_layout = QHBoxLayout()
        top_chassis_layout.addStretch()
        self._lcd = LcdDisplay(self)
        top_chassis_layout.addWidget(self._lcd)
        top_chassis_layout.addStretch()
        
        chassis_layout.addLayout(top_chassis_layout)

        # Bottom section: 2x4 Compartment Matrix
        grid_container = QWidget(self.chassis)
        grid_container.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_container)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)
        
        for compartment in self.scheduler.compartments.values():
            # A mapping: 1-4 is row 0. 5-8 is row 1
            row = 0 if compartment.slot_number <= 4 else 1
            col = (compartment.slot_number - 1) % 4
            widget = CompartmentWidget(compartment, scheduler=self.scheduler, parent=grid_container)
            widget.interacted.connect(self._on_widget_interacted)
            widget.refilled.connect(self._on_widget_refilled)
            grid.addWidget(widget, row, col)
            self._widgets[compartment.id] = widget
            
        chassis_layout.addWidget(grid_container)
        zones_layout.addWidget(self.chassis, stretch=1)

        # Zone 3: Lansia Tray (Right Side)
        self.lansia_tray = LansiaTrayWidget(scheduler=self.scheduler, parent=central)
        self.lansia_tray.sachet_consumed.connect(self._on_sachet_consumed)
        zones_layout.addWidget(self.lansia_tray)

        main_layout.addLayout(zones_layout, stretch=1)

        # -- Bottom Section: Developer Lab Workbench --
        lab_panel = QFrame(self)
        lab_panel.setFixedHeight(120)
        lab_panel.setStyleSheet(f"""
            QFrame {{ background-color: {styles.CHASSIS_BG}; border: 1px solid {styles.CHASSIS_BORDER}; border-radius: 8px; }}
            QLabel, QGroupBox {{ color: {styles.TEXT_LIGHT}; }}
            QPushButton {{ background-color: {styles.BUTTON_BG}; color: {styles.BUTTON_TEXT}; padding: 6px; border-radius: 4px; font-size: 11px; border: none; }}
            QPushButton:hover {{ background-color: {styles.BUTTON_HOVER_BG}; }}
            QGroupBox {{ font-size: 11px; font-weight: bold; border: 1px solid {styles.CHASSIS_BORDER}; border-radius: 4px; margin-top: 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; color: {styles.TEXT_MUTED}; }}
        """)
        lab_layout = QHBoxLayout(lab_panel)
        lab_layout.setContentsMargins(15, 10, 15, 10)
        lab_layout.setSpacing(15)

        lab_title = QLabel("Lab Control\nWorkbench", lab_panel)
        lab_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        lab_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab_title.setStyleSheet(f"border: none; color: {styles.TEXT_MUTED};")
        lab_layout.addWidget(lab_title)

        # Time Controls
        time_group = QGroupBox("RTC Controls")
        time_layout = QVBoxLayout(time_group)
        time_inner_layout = QHBoxLayout()
        self._speed_combo = QComboBox()
        self._speed_combo.addItems([f"{speed}x" for speed in config.SIM_SPEEDS])
        self._speed_combo.currentTextChanged.connect(self._on_speed_changed)
        time_lbl = QLabel("Speed:")
        time_lbl.setStyleSheet("border: none;")
        time_inner_layout.addWidget(time_lbl)
        time_inner_layout.addWidget(self._speed_combo)
        
        # Small steps to test a slot's tolerance: pop-up, then +5 / +30 to land late or missed.
        for minutes in config.CLOCK_JUMP_MINUTES:
            hours, rest = divmod(minutes, 60)
            btn_jump = QPushButton(f"+{hours} Jam" if hours and not rest else f"+{minutes} Mnt")
            btn_jump.setToolTip(f"Majukan jam pillbox {minutes} menit")
            btn_jump.clicked.connect(lambda _checked=False, m=minutes: self._on_jump_minutes(m))
            time_inner_layout.addWidget(btn_jump)
        time_layout.addLayout(time_inner_layout)
        
        time_buttons = QHBoxLayout()
        # Jumping by whole hours can skip a dose window entirely (it then turns MISSED without
        # ringing); this lands just before the next pop-up instead.
        btn_next = QPushButton("Jadwal Berikutnya")
        btn_next.clicked.connect(self._on_jump_next_dose)
        time_buttons.addWidget(btn_next)
        btn_reset = QPushButton("Reset Day")
        btn_reset.clicked.connect(self._on_reset_day)
        time_buttons.addWidget(btn_reset)
        # Back to real time at 1x (the backend and the app follow the pillbox clock either way).
        btn_real_time = QPushButton("Sync Jam Nyata")
        btn_real_time.clicked.connect(self._on_sync_real_time)
        time_buttons.addWidget(btn_real_time)
        time_layout.addLayout(time_buttons)
        lab_layout.addWidget(time_group)

        # Network Controls
        net_group = QGroupBox("Network & Sync")
        net_layout = QVBoxLayout(net_group)
        self._btn_wifi = QPushButton("Wi-Fi: Online")
        self._btn_wifi.setStyleSheet(f"background-color: {styles.WIFI_ONLINE_BG}; font-weight: bold;")
        self._btn_wifi.clicked.connect(self._toggle_wifi)
        net_layout.addWidget(self._btn_wifi)
        lab_layout.addWidget(net_group)

        # Refill Controls
        refill_group = QGroupBox("Maintenance")
        refill_layout = QVBoxLayout(refill_group)
        self._btn_refill = QPushButton()  # text and colour set by _apply_refill_ui
        self._btn_refill.clicked.connect(self._toggle_refill_mode)
        refill_layout.addWidget(self._btn_refill)
        lab_layout.addWidget(refill_group)


        # Battery Controls
        batt_group = QGroupBox("Power Management")
        batt_layout = QVBoxLayout(batt_group)
        self._batt_slider = QSlider(Qt.Orientation.Horizontal)
        self._batt_slider.setRange(0, 100)
        self._batt_slider.setValue(100)
        self._batt_slider.valueChanged.connect(self._on_battery_changed)
        self._batt_label = QLabel("Battery: 100%")
        self._batt_label.setStyleSheet("border: none;")
        batt_layout.addWidget(self._batt_label)
        batt_layout.addWidget(self._batt_slider)
        lab_layout.addWidget(batt_group)

        # Server connection / pairing
        conn_group = QGroupBox(
            "Koneksi Server" if config.PROFILE == config.DEFAULT_PROFILE else f"Koneksi Server · {config.PROFILE}"
        )
        conn_layout = QHBoxLayout(conn_group)
        # QR of the device code only (no secret); refreshed by _refresh_connection_panel.
        self._qr = QrWidget(76, clickable=True, parent=conn_group)
        self._qr.clicked.connect(self._on_qr_clicked)
        conn_layout.addWidget(self._qr)
        conn_info = QVBoxLayout()
        self._lbl_device_code = QLabel()
        self._lbl_device_code.setStyleSheet(f"border: none; font-size: 13px; font-weight: bold; color: {styles.LCD_TEXT};")
        self._lbl_device_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_pair_status = QLabel()
        # Unsent events in the local outbox (the events table, synced = 0).
        self._lbl_outbox = QLabel()
        # Wide enough for the longest texts ("Kode: PB-XXXXXXXX", "Masukkan kode ini di aplikasi"):
        # the labels change text after layout and would otherwise be clipped.
        for label in (self._lbl_device_code, self._lbl_pair_status, self._lbl_outbox):
            label.setMinimumWidth(175)
        conn_info.addWidget(self._lbl_device_code)
        conn_info.addWidget(self._lbl_pair_status)
        conn_info.addWidget(self._lbl_outbox)
        conn_layout.addLayout(conn_info)
        conn_buttons = QVBoxLayout()
        self._btn_register = QPushButton()
        self._btn_register.clicked.connect(self._on_register_clicked)
        self._btn_forget = QPushButton("Reset Identitas")
        self._btn_forget.clicked.connect(self._on_forget_clicked)
        conn_buttons.addWidget(self._btn_register)
        conn_buttons.addWidget(self._btn_forget)
        conn_layout.addLayout(conn_buttons)
        lab_layout.addWidget(conn_group)

        lab_layout.addStretch()

        main_layout.addWidget(lab_panel)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().setStyleSheet(f"color: {styles.STATUS_BAR_TEXT};")
        # Extra pillboxes, each its own process and identity (main.py --profile pbN). Lives in the
        # status bar: the lab panel has no room left at the default window width.
        self._lbl_virtual = QLabel(self)
        self._btn_add_virtual = QPushButton("Tambah Pillbox Virtual", self)
        self._btn_add_virtual.setToolTip(
            f"Buka pillbox baru di jendela terpisah dengan identitas sendiri (maks. {len(config.VIRTUAL_PROFILES)})"
        )
        self._btn_add_virtual.setStyleSheet(
            f"QPushButton {{ background-color: {styles.BUTTON_BG}; color: {styles.BUTTON_TEXT}; padding: 4px 10px; border-radius: 4px; border: none; }}"
            f"QPushButton:hover {{ background-color: {styles.BUTTON_HOVER_BG}; }}"
            f"QPushButton:disabled {{ color: {styles.TEXT_MUTED}; }}"
        )
        self._btn_add_virtual.clicked.connect(self._on_add_virtual_clicked)
        self.statusBar().addPermanentWidget(self._lbl_virtual)
        self.statusBar().addPermanentWidget(self._btn_add_virtual)
        self._refresh_lcd()

    # -- startup helpers -------------------------------------------------------
    def _open_database(self) -> Database:
        """Opens the profile's database; a damaged one can be backed up and recreated."""
        try:
            return Database()
        except sqlite3.OperationalError as exc:
            # Locked or unreadable (permissions, disk): the file itself may be fine, so never move it.
            logger.exception("Database %s cannot be opened.", config.DB_PATH)
            QMessageBox.critical(self, "Database tidak dapat dibuka", f"{config.DB_PATH}\n\n{exc}")
            raise SystemExit(1) from exc
        except sqlite3.DatabaseError as exc:
            logger.exception("Database %s is damaged.", config.DB_PATH)
            answer = QMessageBox.critical(
                self,
                "Database rusak",
                f"Database pillbox tidak dapat dibuka ({exc}).\n\n"
                "Cadangkan file lama dan buat database baru? Identitas perangkat, jadwal dan event "
                "yang belum terkirim tidak ikut ke database baru.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                raise SystemExit(1) from exc
            backup = backup_corrupt_database(config.DB_PATH)
            QMessageBox.information(self, "Database baru dibuat", f"File lama disimpan sebagai:\n{backup}")
            return Database()

    def _prune_old_events(self) -> None:
        cutoff = self.clock.now() - timedelta(days=config.SYNCED_EVENT_RETENTION_DAYS)
        try:
            pruned = self.db.prune_synced_events(cutoff)
        except sqlite3.Error:
            logger.exception("Could not prune old events.")
            return
        if pruned:
            logger.info("Pruned %d synced event(s) older than %d days.", pruned, config.SYNCED_EVENT_RETENTION_DAYS)

    def _device_now(self) -> datetime:
        """Wall-clock time in the device timezone, naive like the simulated RTC."""
        return datetime.now(self._zone).replace(tzinfo=None)

    def _zone_label(self) -> str:
        return datetime.now(self._zone).tzname() or self._timezone

    def _apply_timezone(self, name: str | None) -> None:
        name = name or config.DEFAULT_DEVICE_TIMEZONE
        if name != self._timezone:
            self._timezone = name
            self._zone = sync.device_zone(name)
            self._tz_label = self._zone_label()
            self._refresh_lcd()

    # -- event handlers ------------------------------------------------------
    def _on_tick(self) -> None:
        self.scheduler.tick()
        self._refresh_lcd()
        if self._alarm_until is not None:
            self._update_chime()  # ends an app alarm whose time is up
        if time.monotonic() >= self._next_profile_check:
            self._refresh_virtual_panel()

    def _on_sync_tick(self, force: bool = False) -> None:
        """Starts a background sync. force: the backoff wait is over (or the server is known to be
        back); otherwise nothing is sent while a backoff wait runs."""
        if self._closing:
            return
        if not self._is_online:
            self.statusBar().showMessage(_OFFLINE, config.STATUS_MESSAGE_SHORT_MS)
            return
        if self._retry_timer.isActive() and not (force or self._reconnected):
            return  # backing off after a failure: the retry timer syncs when the wait is over

        if self._is_syncing:
            # One sync at a time; run again as soon as this one finishes so new
            # events never wait for the next interval.
            self._sync_again = True
            return

        self._is_syncing = True
        self._retry_timer.stop()
        worker = SyncWorker(
            self.db,
            self.clock,
            self._battery_percent,
            self._is_online,
            chambers=sync.chamber_report(self.scheduler.compartments.values()),
            config_version_seen=self._config_version_seen,
            after_reconnect=self._reconnected,
            stop=self._stop,
        )
        self._reconnected = False
        worker.signals.finished.connect(self._on_sync_finished)
        QThreadPool.globalInstance().start(worker)

    def _request_sync(self) -> None:
        """Something worth reporting happened: sync after a short debounce."""
        self._flush_soon.start()

    def _on_server_reachable(self) -> None:
        """The command channel connected: the backend is up, so stop any backoff and sync now."""
        self._sync_failures = 0
        self._retry_timer.stop()
        self._request_sync()

    def _on_auth_rejected(self) -> None:
        self._link_state = HeartbeatResult.UNAUTHORIZED
        self._refresh_connection_panel()
        self.statusBar().showMessage(_KEY_REJECTED, config.STATUS_MESSAGE_ALERT_MS)

    def _on_ws_heartbeat_failed(self) -> None:
        """Heartbeats go over REST today; should one go over the socket and not be stored, the
        status shows it like a failed REST heartbeat."""
        self._link_state = HeartbeatResult.HTTP_ERROR
        self._refresh_connection_panel()
        self.statusBar().showMessage(_SYNC_MESSAGES[HeartbeatResult.HTTP_ERROR], config.STATUS_MESSAGE_SHORT_MS)

    def _on_sync_finished(self, report: SyncReport) -> None:
        self._is_syncing = False
        if self._closing:
            return
        # A failure on the device itself is not blamed on the server.
        self._link_state = HeartbeatResult.ERROR if report.error else report.result
        if report.pending is not None:
            self._pending = report.pending
        if report.result.server_unreachable or report.error:
            self._sync_failures += 1
            delay = sync.backoff_delay(self._sync_failures)
            self._retry_timer.start(int(delay * 1000))
            logger.info("Sync failed (%s); next try in %.0f s.", report.result.value, delay)
        elif report.result == HeartbeatResult.OK:
            self._sync_failures = 0
        if self._sync_again:
            self._sync_again = False
            self._request_sync()
        self.statusBar().showMessage(self._sync_message(report), config.STATUS_MESSAGE_SHORT_MS)

        state = report.state
        if state:
            self._paired = state.get(config.STATE_IS_PAIRED) == config.STATE_TRUE
            self._apply_heartbeat_interval(state.get(config.STATE_HEARTBEAT_INTERVAL_SECONDS))
            self._apply_timezone(state.get(config.STATE_TIMEZONE))
            set_volume_level(state.get(config.STATE_CHIME_VOLUME_LEVEL))
        if report.result == HeartbeatResult.OK and report.server_time and report.received_at is not None:
            self._correct_rtc_from_heartbeat(report.server_time, report.received_at)
        # A new config from the app was pulled during this sync: apply it live.
        version = state.get(config.STATE_CONFIG_VERSION) if state else self._config_version_seen
        if version != self._config_version_seen and report.compartments is not None:
            self._config_version_seen = version
            self.scheduler.reload_schedules(report.compartments)
            # Refill mode set in the app while the command channel was down arrives with the config.
            refill = state.get(config.STATE_IS_REFILL_MODE) == config.STATE_TRUE
            if refill != self.scheduler.is_refill_mode:
                self._set_refill_mode(refill)
            for compartment in self.scheduler.compartments.values():
                self._refresh_widget(compartment)
            self._refresh_lcd()
            self.statusBar().showMessage(f"Jadwal baru dari aplikasi diterapkan (config v{version}).", config.STATUS_MESSAGE_MS)
        self._refresh_connection_panel()

    @staticmethod
    def _sync_message(report: SyncReport) -> str:
        if report.error:
            return f"{_SYNC_MESSAGES[HeartbeatResult.ERROR]} {report.error}"
        if report.result == HeartbeatResult.OK:
            return f"{report.synced} event terkirim ke server." if report.synced else "Heartbeat OK."
        return _SYNC_MESSAGES[report.result]

    # -- server connection / pairing -------------------------------------------
    def _set_label(self, label: QLabel, text: str, color: str) -> None:
        """setText + setStyleSheet, the latter only when the colour changed (it re-polishes)."""
        label.setText(text)
        sheet = f"border: none; font-size: 11px; color: {color};"
        if label.styleSheet() != sheet:
            label.setStyleSheet(sheet)

    def _refresh_connection_panel(self) -> None:
        """From cached state only (no SQLite): called when that state changes, not every tick."""
        if self._pending:
            self._set_label(self._lbl_outbox, f"Antrean: {self._pending} event belum terkirim", styles.STATUS_WARN)
        else:
            self._set_label(self._lbl_outbox, "Antrean: kosong", styles.TEXT_MUTED)
        code, key = self._identity
        if not (code and key):
            self._qr.set_payload(None)
            self._lbl_device_code.setText("Kode: -")
            self._set_label(self._lbl_pair_status, "Belum terdaftar ke server", styles.STATUS_ERROR)
            self._btn_register.setText("Mendaftarkan..." if self._is_registering else "Daftarkan Perangkat")
            self._btn_register.setEnabled(not self._is_registering)
            self._btn_forget.setEnabled(False)
            return
        self._lbl_device_code.setText(f"Kode: {code}")
        self._qr.set_payload(code)  # no-op unless the code changed (register / Reset Identitas)
        if self._link_state == HeartbeatResult.UNAUTHORIZED:
            self._set_label(self._lbl_pair_status, "Kunci ditolak: daftarkan ulang", styles.STATUS_ERROR)
        elif self._link_state == HeartbeatResult.ERROR:
            self._set_label(self._lbl_pair_status, "Galat sinkronisasi (lihat log)", styles.STATUS_ERROR)
        elif self._link_state is not None and self._link_state.server_unreachable:
            self._set_label(self._lbl_pair_status, "Server tidak terjangkau", styles.STATUS_ERROR)
        elif not self._is_online:
            self._set_label(self._lbl_pair_status, "Offline: event disimpan", styles.STATUS_WARN)
        elif self._paired:
            self._set_label(self._lbl_pair_status, "Terpasang ke aplikasi", styles.STATUS_OK)
        else:
            self._set_label(self._lbl_pair_status, "Masukkan kode ini di aplikasi", styles.STATUS_WARN)
        self._btn_register.setText("Salin Kode")
        self._btn_register.setEnabled(True)
        self._btn_forget.setEnabled(True)

    # -- virtual pillboxes -------------------------------------------------------------
    @staticmethod
    def _profile_running(name: str) -> bool:
        if name == config.PROFILE:
            return True
        if not config.profile_dir(name).exists():
            return False
        probe = QLockFile(str(config.lock_path(name)))
        probe.setStaleLockTime(0)  # same policy as main.py: only a live process holds it
        if probe.tryLock(0):
            probe.unlock()
            return False
        return True

    def _refresh_virtual_panel(self) -> None:
        """Probes the other profiles' lock files: every PROFILE_CHECK_INTERVAL_SECONDS, not every tick."""
        self._next_profile_check = time.monotonic() + config.PROFILE_CHECK_INTERVAL_SECONDS
        running = [p for p in config.VIRTUAL_PROFILES if self._profile_running(p)]
        free = len(config.VIRTUAL_PROFILES) - len(running)
        launching = time.monotonic() < self._launching_until
        self._lbl_virtual.setText(f"Pillbox virtual aktif: {len(running)}/{len(config.VIRTUAL_PROFILES)}")
        self._btn_add_virtual.setEnabled(free > 0 and not launching)
        self._btn_add_virtual.setText("Membuka..." if launching else "Tambah Pillbox Virtual")

    def _on_add_virtual_clicked(self) -> None:
        name = next((p for p in config.VIRTUAL_PROFILES if not self._profile_running(p)), None)
        if name is None:
            QMessageBox.information(
                self, "Batas tercapai", f"Maksimal {len(config.VIRTUAL_PROFILES)} pillbox virtual berjalan bersamaan."
            )
            return
        config.profile_dir(name).mkdir(parents=True, exist_ok=True)
        ok, _pid = QProcess.startDetached(
            sys.executable, [str(config.BASE_DIR / "main.py"), "--profile", name], str(config.BASE_DIR)
        )
        if not ok:
            QMessageBox.warning(self, "Gagal membuka", f"Pillbox virtual '{name}' tidak dapat dijalankan.")
            return
        # The new process takes its lock a moment after starting: avoid launching the same profile twice.
        self._launching_until = time.monotonic() + config.PROFILE_LAUNCH_GUARD_SECONDS
        self._refresh_virtual_panel()
        self.statusBar().showMessage(f"Membuka pillbox virtual '{name}' di jendela baru...", config.STATUS_MESSAGE_MS)

    def _on_qr_clicked(self) -> None:
        code = self._qr.payload()
        if code:
            QrDialog(code, self).exec()

    def _on_register_clicked(self) -> None:
        code, key = self._identity
        if code and key:
            QApplication.clipboard().setText(code or "")
            self.statusBar().showMessage(f"Kode {code} disalin. Tempel di aplikasi: 'Hubungkan Pillbox'.", config.STATUS_MESSAGE_MS)
            return
        token = config.provisioning_token()
        if not token:
            token, ok = QInputDialog.getText(
                self,
                "Daftarkan Perangkat",
                "PROVISIONING_TOKEN dari Backend/.env tidak ditemukan.\nTempel token di sini:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not token.strip():
                return
            token = token.strip()
        self._is_registering = True
        self._refresh_connection_panel()
        worker = RegisterWorker(self.db, token)
        worker.signals.finished.connect(self._on_register_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_register_finished(self, ok: bool, message: str) -> None:
        self._is_registering = False
        if self._closing:
            return
        self._config_version_seen = self.db.get_device_state(config.STATE_CONFIG_VERSION)
        self._identity = sync.get_identity(self.db)
        self._paired = False
        self._link_state = None
        self._refresh_connection_panel()
        self._refresh_socket()
        if ok:
            QApplication.clipboard().setText(message)
            QMessageBox.information(
                self,
                "Perangkat terdaftar",
                f"Kode perangkat: {message}\n\n"
                "Kode sudah disalin. Di aplikasi PillCare, buka 'Hubungkan Pillbox', "
                "masukkan kode ini dan buat PIN 4 digit.",
            )
        else:
            QMessageBox.warning(self, "Pendaftaran gagal", message)

    def _on_forget_clicked(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset Identitas",
            "Hapus kode & kunci perangkat ini dari emulator? Perangkat harus didaftarkan "
            "dan dipasangkan ulang di aplikasi.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            sync.forget_identity(self.db)  # also drops the old identity's outbox, version and refill mode
            self._identity = sync.get_identity(self.db)  # an env override may still give one
            self._paired = False
            self._link_state = None
            self._pending = self.db.count_unsynced_events()
            self._config_version_seen = self.db.get_device_state(config.STATE_CONFIG_VERSION)
            if self.scheduler.is_refill_mode:
                self._set_refill_mode(False)
            self._apply_timezone(None)
            self._refresh_connection_panel()
            self._refresh_socket()

    def _on_widget_interacted(self, compartment_id: int, is_forced: bool = False) -> None:
        compartment = self.scheduler.compartments[compartment_id]
        if self._alarm_until is not None and self._alarm_slot in (None, compartment.slot_number):
            self._alarm_until = self._alarm_slot = None  # someone came to the box: the app alarm stops

        if compartment.door_open:
            # Door is currently open -> clicking closes it
            self.scheduler.close_compartment(compartment_id)
            self.statusBar().showMessage(f"Pintu Slot {compartment.slot_number} ditutup.", config.STATUS_MESSAGE_SHORT_MS)
        elif self.scheduler.is_refill_mode:
            # In refill mode -> lid can be opened/closed for maintenance
            self.scheduler.open_compartment(compartment_id)
            self.statusBar().showMessage(f"Pintu Slot {compartment.slot_number} dibuka untuk inspeksi refill.", config.STATUS_MESSAGE_SHORT_MS)
        elif compartment.state == ChamberState.ACTIVE:
            # Active scheduled dose -> clicking opens it
            self.scheduler.open_compartment(compartment_id)
            self.statusBar().showMessage(f"Pintu Slot {compartment.slot_number} terbuka: Waktunya minum obat.", config.STATUS_MESSAGE_SHORT_MS)
        elif is_forced:
            # Deliberate forced mechanical pry outside schedule
            self.scheduler.open_compartment(compartment_id)
            self.statusBar().showMessage(f"🚨 PERINGATAN: Pintu Slot {compartment.slot_number} dicungkil paksa di luar jadwal! (UNSCHEDULED_OPEN)", config.STATUS_MESSAGE_MS)
        else:
            # Strictly locked! Reject action with shake animation
            widget = self._widgets.get(compartment_id)
            if widget:
                widget.trigger_shake()
            self.statusBar().showMessage(locked_message(compartment), config.STATUS_MESSAGE_SHORT_MS)
            return

        self._refresh_widget(compartment)
        self._refresh_lcd()
        self._update_chime()
        self._request_sync()

    def _on_clock_changed(self) -> None:
        """After any change to the simulated RTC: apply it now and report it right away (the
        heartbeat carries rtc_time + speed), so the backend and the app follow the new time."""
        self.scheduler.tick()
        self._refresh_lcd()
        self._request_sync()

    def _on_speed_changed(self, text: str) -> None:
        self.clock.set_speed(float(text.replace("x", "")))
        if self.clock.speed != config.REAL_TIME_SPEED:
            self._manual_clock = True
        self._on_clock_changed()

    def _on_jump_minutes(self, minutes: int) -> None:
        self._manual_clock = True
        self.clock.jump(timedelta(minutes=minutes))
        self._on_clock_changed()
        self.statusBar().showMessage(f"Jam pillbox dimajukan {minutes} menit ({self.clock.now():%H:%M}).", config.STATUS_MESSAGE_SHORT_MS)

    def _on_jump_next_dose(self) -> None:
        due_at = self.scheduler.next_due_at()
        if due_at is None:
            self.statusBar().showMessage("Tidak ada jadwal aktif dalam 7 hari ke depan.", config.STATUS_MESSAGE_MS)
            return
        self._manual_clock = True
        self.clock.set_time(due_at - timedelta(seconds=config.NEXT_DOSE_LEAD_SECONDS))
        self._on_clock_changed()
        self.statusBar().showMessage(
            f"Jam dimajukan ke {config.NEXT_DOSE_LEAD_SECONDS} detik sebelum jadwal {due_at:%d/%m %H:%M}.", config.STATUS_MESSAGE_MS
        )

    def _set_real_time(self, local: datetime) -> None:
        """Real speed again, at `local` (naive device-local time)."""
        self._manual_clock = False
        self._speed_combo.blockSignals(True)
        self._speed_combo.setCurrentIndex(config.SIM_SPEEDS.index(config.REAL_TIME_SPEED))
        self._speed_combo.blockSignals(False)
        self.clock.set_speed(config.REAL_TIME_SPEED)
        self.clock.set_time(local)
        self._on_clock_changed()

    def _on_sync_real_time(self) -> None:
        """Back to wall-clock time in the DEVICE timezone at 1.0x, so device events match the
        backend's schedule windows even when the PC runs in another timezone."""
        self._set_real_time(self._device_now())
        self.statusBar().showMessage(
            f"Jam perangkat disamakan dengan jam nyata ({self._tz_label}, {config.REAL_TIME_SPEED}x).", config.STATUS_MESSAGE_MS
        )

    def _on_reset_day(self) -> None:
        self.scheduler.reset_day()
        for compartment in self.scheduler.compartments.values():
            self._refresh_widget(compartment)
        self._refresh_lcd()
        self._update_chime()  # a ringing chamber was put back to IDLE

    def _on_state_changed(self, compartment: Compartment) -> None:
        self._refresh_widget(compartment)
        self._refresh_lcd()
        self._update_chime()

    def _on_day_restored(self) -> None:
        for compartment in self.scheduler.compartments.values():
            self._refresh_widget(compartment)
        self._refresh_lcd()
        self._update_chime()

    def _update_chime(self) -> None:
        """Rings (and keeps ringing) while a chamber with sachets is popped up, or while an alarm
        from the app lasts; silent otherwise. The speaker badges show what is ringing."""
        if self._alarm_until is not None and time.monotonic() >= self._alarm_until:
            self._alarm_until = self._alarm_slot = None
        app_alarm = self._alarm_until is not None

        active_id = self.scheduler.active_chamber_id
        active = self.scheduler.compartments.get(active_id) if active_id else None
        scheduled = (
            active is not None
            and active.state == ChamberState.ACTIVE
            and active.stock_count > 0
            and not self.scheduler.is_refill_mode
        )

        if scheduled or app_alarm:
            if not self._chime_timer.isActive():
                play_chime()
                self._chime_timer.start()
        elif self._chime_timer.isActive():
            self._chime_timer.stop()
            stop_chime()

        ringing_slots = set()
        if scheduled:
            ringing_slots.add(active.slot_number)
        if app_alarm and self._alarm_slot is not None:
            ringing_slots.add(self._alarm_slot)
        for widget in self._widgets.values():
            widget.set_ringing(widget.compartment.slot_number in ringing_slots)
        if app_alarm:
            where = f"SLOT {self._alarm_slot}" if self._alarm_slot else "SEMUA"
            self._lcd.set_sound(f"ALARM APLIKASI · {where}")
        elif scheduled:
            self._lcd.set_sound(f"BERBUNYI · SLOT {active.slot_number}")
        else:
            self._lcd.set_sound(None)

    def _on_widget_refilled(self, slot_number: int) -> None:
        compartment = self.scheduler.compartments.get(slot_number)
        stock = compartment.stock_count if compartment else "?"
        self.statusBar().showMessage(f"Sachet loaded to Slot {slot_number} (Stock: {stock} pcs)", config.STATUS_MESSAGE_SHORT_MS)
        self._request_sync()
        
    def _on_sachet_consumed(self, slot_number: int, medication_name: str) -> None:
        self.statusBar().showMessage(f"Patient consumed medication from Slot {slot_number}: {medication_name}", config.STATUS_MESSAGE_SHORT_MS)

    def _on_bulk_fill_requested(self, count: int) -> None:
        for widget in self._widgets.values():
            widget.refresh()
        self.statusBar().showMessage(f"All slots set to {count} sachet(s)", config.STATUS_MESSAGE_SHORT_MS)
        self._request_sync()

    def _toggle_wifi(self) -> None:
        self._is_online = not self._is_online
        self._btn_wifi.setText("Wi-Fi: Online" if self._is_online else "Wi-Fi: Offline")
        background = styles.WIFI_ONLINE_BG if self._is_online else styles.WIFI_OFFLINE_BG
        self._btn_wifi.setStyleSheet(f"background-color: {background}; color: {styles.BUTTON_TEXT}; font-weight: bold;")
        self._refresh_lcd()
        self._refresh_socket()
        self._link_state = HeartbeatResult.OFFLINE if not self._is_online else None
        self._refresh_connection_panel()
        if self._is_online:
            # Contract §5.3: report back immediately (heartbeat, then the buffered events).
            self._reconnected = True
            self._sync_failures = 0
            self._on_sync_tick(force=True)

    def _toggle_refill_mode(self) -> None:
        self._set_refill_mode(not self.scheduler.is_refill_mode)

    def _set_refill_mode(self, enabled: bool) -> None:
        self.scheduler.set_refill_mode(enabled)  # persisted: survives a restart
        self._update_chime()
        self._apply_refill_ui()
        if enabled:
            self.statusBar().showMessage("Refill Mode active: Compartment lids unlocked for replenishment.", config.STATUS_MESSAGE_MS)
        else:
            self.statusBar().showMessage("Refill Mode closed: Compartment lids locked.", config.STATUS_MESSAGE_MS)
        self._refresh_lcd()
        self._request_sync()

    def _apply_refill_ui(self) -> None:
        """Lab button and caregiver tray (Zone 1) follow the scheduler's refill mode."""
        enabled = self.scheduler.is_refill_mode
        self.caregiver_tray.set_refill_mode(enabled)
        self._btn_refill.setText("Refill Mode: Active" if enabled else "Toggle Refill Mode")
        background = styles.REFILL_ACTIVE_BG if enabled else styles.BUTTON_BG
        self._btn_refill.setStyleSheet(f"background-color: {background}; color: {styles.BUTTON_TEXT}; font-weight: bold;")

    def _on_battery_changed(self, value: int) -> None:
        self._battery_percent = value
        self._batt_label.setText(f"Battery: {value}%")
        self._refresh_lcd()
        self._request_sync()  # the debounce waits until the slider stops moving


    # -- helpers -----------------------------------------------------------
    def _refresh_widget(self, compartment: Compartment) -> None:
        self._widgets[compartment.id].refresh(compartment, test_mode=False)

    def _refresh_lcd(self) -> None:
        now = self.clock.now()
        time_str = now.strftime('%H:%M:%S')
        tz = self._tz_label

        # Determine next dose or active status
        if self.scheduler.is_refill_mode:
            status = STATUS_MAINTENANCE
            next_dose = REFILL_BANNER
        elif self.scheduler.active_chamber_id is not None:
            active_c = self.scheduler.compartments.get(self.scheduler.active_chamber_id)
            if active_c:
                if active_c.stock_count == 0:
                    status = STATUS_EMPTY
                    next_dose = f"KOSONG: [Slot {active_c.slot_number}] {active_c.schedule_time} {tz}"
                else:
                    status = STATUS_DOSE
                    next_dose = f"AMBIL: [Slot {active_c.slot_number}] {active_c.schedule_time} {tz}"
            else:
                status = STATUS_IDLE
                next_dose = f"NEXT: --:-- {tz}"
        else:
            status = STATUS_IDLE
            next_c = self.scheduler.get_next_dose()
            if next_c:
                next_dose = f"NEXT: [Slot {next_c.slot_number}] {next_c.schedule_time} {tz}"
            else:
                next_dose = "NEXT: --:-- (SEMUA SELESAI)"

        self._lcd.update_display(
            time_str=time_str,
            next_dose=next_dose,
            status=status,
            battery=self._battery_percent,
            wifi_on=self._is_online,
            is_refill_mode=self.scheduler.is_refill_mode,
            tz_label=tz,
        )

    # -- command channel (backend -> device) ---------------------------------------
    def _refresh_socket(self) -> None:
        """Keeps the command channel open while registered and online."""
        code, key = self._identity
        if self._is_online and code and key:
            self._socket.start(code, key)
        else:
            self._socket.stop()

    def _server_local_time(self, server_time: object, timezone: object) -> datetime:
        """Server UTC instant -> naive local time, as the simulated RTC keeps it.
        Raises ValueError / ZoneInfoNotFoundError on a bad payload."""
        instant = datetime.fromisoformat(str(server_time))
        zone = timezone or self._timezone
        return instant.astimezone(ZoneInfo(str(zone))).replace(tzinfo=None)

    def _correct_rtc(self, server_now: datetime) -> None:
        """Sets the RTC to the server clock when it drifted (a real device would use NTP), e.g.
        after the PC slept: the simulated RTC stands still while it does. Skipped while the lab
        clock was moved on purpose: the backend and the app follow the device clock then."""
        if self.clock.speed != config.REAL_TIME_SPEED or self._manual_clock:
            return
        drift = (self.clock.now() - server_now).total_seconds()
        if abs(drift) < config.RTC_DRIFT_CORRECT_SECONDS:
            return
        self.clock.set_time(server_now)
        self._on_clock_changed()
        logger.info("RTC corrected from server time (was %+.0f s off).", drift)
        self.statusBar().showMessage(f"Jam perangkat disinkronkan dengan server (selisih {drift:+.0f} detik).", config.STATUS_MESSAGE_LONG_MS)

    def _correct_rtc_from_heartbeat(self, server_time: str, received_at: float) -> None:
        try:
            server_now = self._server_local_time(server_time, None)
        except (ValueError, ZoneInfoNotFoundError):
            logger.warning("Heartbeat server_time %r is unreadable.", server_time)
            return
        # The answer arrived a moment ago (the flush ran after it): age it to now.
        self._correct_rtc(server_now + timedelta(seconds=time.monotonic() - received_at))

    def _on_welcome(self, message: dict) -> None:
        """Command channel connected: correct the RTC from the server clock."""
        self._apply_heartbeat_interval(message.get("heartbeat_interval_seconds"))
        try:
            server_now = self._server_local_time(message["server_time"], message.get("timezone"))
        except (KeyError, ValueError, ZoneInfoNotFoundError):
            logger.warning("Welcome message without a readable server_time.")
            return
        self._correct_rtc(server_now)

    def _apply_heartbeat_interval(self, value: object) -> None:
        """Heartbeats follow the backend's heartbeat_interval_seconds (contract §2.1)."""
        try:
            seconds = int(str(value))
        except (TypeError, ValueError):
            return
        if seconds > 0 and self._sync_timer.interval() != seconds * 1000:
            self._sync_timer.setInterval(seconds * 1000)
            logger.info("Heartbeat interval set to %d s by the backend.", seconds)

    def _ack(self, command_id: str, ok: bool, result: dict | None = None, error: str | None = None) -> None:
        """Acks a command and remembers the answer for a re-delivered command_id."""
        self._acked_commands[command_id] = (ok, result, error)
        while len(self._acked_commands) > config.COMMAND_DEDUPE_SIZE:
            self._acked_commands.popitem(last=False)
        self._socket.send_ack(command_id, ok, result, error)

    def _on_device_command(self, command_id: str, command: str, payload: dict) -> None:
        """Handles a command from the app (contract §3) and acks it right away:
        the caregiver's request waits for this ack. A command_id seen before is answered with
        its first ack and not run again (e.g. no second alarm, no second ALARM_STARTED)."""
        if command_id and command_id in self._acked_commands:
            ok, result, error = self._acked_commands[command_id]
            self._socket.send_ack(command_id, ok, result, error)
            return
        if command == "trigger_alarm":
            slot = payload.get("slot_number")
            compartment = next((c for c in self.scheduler.compartments.values() if c.slot_number == slot), None)
            if compartment is not None:
                self.db.log_event(compartment.id, compartment.slot_number, "ALARM_STARTED", self.clock.now())
                self._request_sync()
            # Rings for the requested time ("Bunyikan alarm" 60 s, "Test pengingat" 10 s), not one beep.
            try:
                duration = max(
                    config.MIN_ALARM_DURATION_SECONDS,
                    int(payload.get("duration_seconds") or config.DEFAULT_ALARM_DURATION_SECONDS),
                )
            except (TypeError, ValueError):
                duration = config.DEFAULT_ALARM_DURATION_SECONDS
            self._alarm_until = time.monotonic() + duration
            self._alarm_slot = slot if compartment is not None else None
            self._chime_timer.stop()  # restart so it rings right away
            self._update_chime()
            where = f"Slot {slot}" if slot else "semua slot"
            self.statusBar().showMessage(f"Alarm dari aplikasi ({where}, {duration} detik)", config.STATUS_MESSAGE_LONG_MS)
            self._ack(command_id, True, {"ringing": True, "duration_seconds": duration})
        elif command == "stop_alarm":
            # Only an alarm started from the app stops: a popped-up dose keeps ringing so the
            # elderly person is still reminded (docs/DEVICE_CONTRACT.md §3).
            slot = self._alarm_slot
            was_ringing = self._alarm_until is not None
            self._alarm_until = self._alarm_slot = None
            self._update_chime()
            compartment = next((c for c in self.scheduler.compartments.values() if c.slot_number == slot), None)
            if was_ringing and compartment is not None:
                self.db.log_event(compartment.id, compartment.slot_number, "ALARM_STOPPED", self.clock.now())
                self._request_sync()
            if was_ringing:
                self.statusBar().showMessage("Alarm dari aplikasi dihentikan", config.STATUS_MESSAGE_LONG_MS)
            self._ack(command_id, True, {"ringing": False})
        elif command == "schedule_updated":
            self._ack(command_id, True)
            self._request_sync()  # pulls the new config now instead of on the next heartbeat
        elif command == "release_slot":
            try:
                slot = int(payload["slot_number"])
                until = datetime.fromisoformat(str(payload["until"])).replace(tzinfo=None)
                scheduled_raw = payload.get("scheduled_for")
                scheduled_for = (
                    datetime.fromisoformat(str(scheduled_raw)).replace(tzinfo=None) if scheduled_raw else None
                )
            except (KeyError, TypeError, ValueError) as exc:
                self._ack(command_id, False, error=f"invalid release_slot payload: {exc}")
                return
            refused = self.scheduler.release_late(slot, until, scheduled_for)
            if refused:
                self._ack(command_id, False, error=refused)
                return
            self.statusBar().showMessage(f"🔓 Slot {slot} dibuka lagi dari aplikasi sampai {until:%H:%M} (dosis terlewat).", config.STATUS_MESSAGE_LONG_MS)
            self._ack(command_id, True, {"released": True, "release_until": until.isoformat()})
        elif command == "refill_mode":
            enabled = bool(payload.get("enabled"))
            if enabled != self.scheduler.is_refill_mode:
                self._toggle_refill_mode()
            self._ack(command_id, True, {"is_refill_mode": self.scheduler.is_refill_mode})
        elif command == "time_sync":
            before = self.clock.now()
            try:
                local = self._server_local_time(payload["server_time"], payload.get("timezone"))
            except (KeyError, ValueError, ZoneInfoNotFoundError) as exc:
                self._ack(command_id, False, error=f"invalid time_sync payload: {exc}")
                return
            # A caregiver asked for it ("Kalibrasi jam"): real time again, at real speed.
            self._set_real_time(local)
            self._ack(
                command_id, True,
                {"device_time_before": before.isoformat(), "device_time_after": self.clock.now().isoformat()},
            )
        else:
            self._ack(command_id, False, error=f"unsupported command {command!r}")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Stops everything that could touch the database, waits for a running worker, then
        closes the database (a worker still running after the wait fails on its next query and
        logs it; its events stay unsynced and go out on the next start)."""
        self._closing = True
        self._stop.set()
        for timer in (self._tick_timer, self._chime_timer, self._sync_timer, self._flush_soon, self._retry_timer):
            timer.stop()
        stop_chime()
        self._socket.stop()
        if not QThreadPool.globalInstance().waitForDone(config.SHUTDOWN_WAIT_MS):
            logger.warning("A background sync was still running after %d ms at shutdown.", config.SHUTDOWN_WAIT_MS)
        self.db.close()
        super().closeEvent(event)

