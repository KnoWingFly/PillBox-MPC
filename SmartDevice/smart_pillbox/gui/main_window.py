from __future__ import annotations

import logging
import sys
import time
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
from smart_pillbox.core.audio import play_chime, stop_chime
from smart_pillbox.core import sync
from smart_pillbox.core.ws_client import DeviceSocket
from smart_pillbox.db.database import Database
from smart_pillbox.gui.compartment_widget import CompartmentWidget
from smart_pillbox.gui.lcd_widget import LcdDisplay
from smart_pillbox.gui.caregiver_tray_widget import CaregiverTrayWidget
from smart_pillbox.gui.lansia_tray_widget import LansiaTrayWidget
from smart_pillbox.gui.qr_widget import QrDialog, QrWidget
from smart_pillbox.gui import styles
from smart_pillbox.models import Compartment, ChamberState

logger = logging.getLogger(__name__)


class SyncSignals(QObject):
    finished = Signal(int, str)


class SyncWorker(QRunnable):
    """Background worker to execute telemetry sync without blocking the Qt GUI thread."""

    def __init__(self, db: Database, clock: SimulatedClock, battery: int, is_online: bool, after_reconnect: bool = False):
        super().__init__()
        self.db = db
        self.clock = clock
        self.battery = battery
        self.is_online = is_online
        # Contract §5.3: right after Wi-Fi returns, heartbeat first, then flush the buffer.
        self.after_reconnect = after_reconnect
        self.signals = SyncSignals()

    def _heartbeat(self) -> None:
        # Read the RTC when the heartbeat goes out, not when the sync started: the event flush
        # before it can take seconds, which at 60x is minutes of device time.
        sync.send_heartbeat(self.db, self.clock.now().isoformat(), self.battery, self.is_online, self.clock.speed)

    def run(self):
        if not sync.is_registered(self.db):
            try:
                self.signals.finished.emit(0, "Belum terdaftar ke server: tekan 'Daftarkan Perangkat'.")
            except RuntimeError:
                pass
            return
        try:
            if self.after_reconnect:
                self._heartbeat()
                synced_count = sync.flush_pending_events(self.db, offline_flush=True)
            else:
                # Events first: they are what the caregiver is waiting for.
                synced_count = sync.flush_pending_events(self.db)
                self._heartbeat()
            try:
                if synced_count > 0:
                    self.signals.finished.emit(synced_count, f"Synced {synced_count} event(s) to backend.")
                else:
                    self.signals.finished.emit(0, "Heartbeat OK / Telemetry buffered.")
            except RuntimeError:
                pass
        except Exception as e:
            try:
                self.signals.finished.emit(0, f"Sync error: {e}")
            except RuntimeError:
                pass


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
        try:
            code = sync.register_device(self.db, self.token)
            self.signals.finished.emit(True, code)
        except sync.RegistrationError as exc:
            self.signals.finished.emit(False, str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        title = "Smart Pillbox — Device Simulator (CE739L)"
        self.setWindowTitle(title if config.PROFILE == config.DEFAULT_PROFILE else f"{title} [{config.PROFILE}]")
        self.resize(1260, 840)
        self.setMinimumSize(1180, 780)
        self.setStyleSheet(f"background-color: {styles.BACKGROUND};")

        self.db = Database()
        self.clock = SimulatedClock(speed=config.DEFAULT_SIM_SPEED)
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
        self._config_version_seen = self.db.get_device_state("config_version")
        # True once the lab clock was moved on purpose (+1 hour, speed, jump): the server's
        # clock must then not silently undo it on reconnect. "Sync Jam Nyata" clears it.
        self._manual_clock = False
        # "Bunyikan alarm" / "Test pengingat" from the app: rings until this monotonic time.
        self._alarm_until: float | None = None
        self._alarm_slot: int | None = None  # None = the whole box

        self._build_ui()
        self._refresh_connection_panel()
        self._refresh_virtual_panel()


        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)  # real 1s; simulated speed handled by SimulatedClock
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

        self._socket = DeviceSocket(self)
        self._socket.command_received.connect(self._on_device_command)
        self._socket.welcome_received.connect(self._on_welcome)
        # Backend reachable again: send anything buffered now, not on the next tick.
        self._socket.connected_changed.connect(lambda ok: ok and self._request_sync())
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
            QPushButton {{ background-color: #334155; color: white; padding: 6px; border-radius: 4px; font-size: 11px; border: none; }}
            QPushButton:hover {{ background-color: #475569; }}
            QGroupBox {{ font-size: 11px; font-weight: bold; border: 1px solid {styles.CHASSIS_BORDER}; border-radius: 4px; margin-top: 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; color: {styles.TEXT_MUTED}; }}
        """)
        lab_layout = QHBoxLayout(lab_panel)
        lab_layout.setContentsMargins(15, 10, 15, 10)
        lab_layout.setSpacing(15)

        lab_title = QLabel("Lab Control\nWorkbench", lab_panel)
        lab_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        lab_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab_title.setStyleSheet("border: none; color: #94A3B8;")
        lab_layout.addWidget(lab_title)

        # Time Controls
        time_group = QGroupBox("RTC Controls")
        time_layout = QVBoxLayout(time_group)
        time_inner_layout = QHBoxLayout()
        self._speed_combo = QComboBox()
        self._speed_combo.addItems(["1.0x", "10.0x", "60.0x"])
        self._speed_combo.currentTextChanged.connect(self._on_speed_changed)
        time_lbl = QLabel("Speed:")
        time_lbl.setStyleSheet("border: none;")
        time_inner_layout.addWidget(time_lbl)
        time_inner_layout.addWidget(self._speed_combo)
        
        # Small steps to test a slot's tolerance: pop-up, then +5 / +30 to land late or missed.
        for label, minutes in (("+5 Mnt", 5), ("+30 Mnt", 30), ("+1 Jam", 60)):
            btn_jump = QPushButton(label)
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
        self._btn_wifi.setStyleSheet("background-color: #065F46; font-weight: bold;")
        self._btn_wifi.clicked.connect(self._toggle_wifi)
        net_layout.addWidget(self._btn_wifi)
        lab_layout.addWidget(net_group)

        # Refill Controls
        refill_group = QGroupBox("Maintenance")
        refill_layout = QVBoxLayout(refill_group)
        self._btn_refill = QPushButton("Toggle Refill Mode")
        self._btn_refill.setStyleSheet("background-color: #334155; color: white; font-weight: bold;")
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
        self._lbl_device_code.setStyleSheet("border: none; font-size: 13px; font-weight: bold; color: #E2E8F0;")
        self._lbl_device_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_pair_status = QLabel()
        self._lbl_pair_status.setStyleSheet("border: none; font-size: 11px;")
        # Wide enough for the longest texts ("Kode: PB-XXXXXXXX", "Masukkan kode ini di aplikasi"):
        # the labels change text after layout and would otherwise be clipped.
        for label in (self._lbl_device_code, self._lbl_pair_status):
            label.setMinimumWidth(175)
        conn_info.addWidget(self._lbl_device_code)
        conn_info.addWidget(self._lbl_pair_status)
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
        self.statusBar().setStyleSheet("color: #888;")
        # Extra pillboxes, each its own process and identity (main.py --profile pbN). Lives in the
        # status bar: the lab panel has no room left at the default window width.
        self._lbl_virtual = QLabel(self)
        self._btn_add_virtual = QPushButton("Tambah Pillbox Virtual", self)
        self._btn_add_virtual.setToolTip(
            f"Buka pillbox baru di jendela terpisah dengan identitas sendiri (maks. {len(config.VIRTUAL_PROFILES)})"
        )
        self._btn_add_virtual.setStyleSheet(
            "QPushButton { background-color: #334155; color: white; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background-color: #475569; }"
            "QPushButton:disabled { color: #94A3B8; }"
        )
        self._btn_add_virtual.clicked.connect(self._on_add_virtual_clicked)
        self.statusBar().addPermanentWidget(self._lbl_virtual)
        self.statusBar().addPermanentWidget(self._btn_add_virtual)
        self._refresh_lcd()

    # -- event handlers ------------------------------------------------------
    def _on_tick(self) -> None:
        self.scheduler.tick()
        self._refresh_lcd()
        if self._alarm_until is not None:
            self._update_chime()  # ends an app alarm whose time is up
        self._refresh_connection_panel()
        self._refresh_virtual_panel()

    def _on_sync_tick(self) -> None:
        if not self._is_online:
            self.statusBar().showMessage("Offline - Events buffered locally.", 3000)
            return

        if self._is_syncing:
            # One sync at a time; run again as soon as this one finishes so new
            # events never wait for the next interval.
            self._sync_again = True
            return

        self._is_syncing = True
        worker = SyncWorker(self.db, self.clock, self._battery_percent, self._is_online, after_reconnect=self._reconnected)
        self._reconnected = False
        worker.signals.finished.connect(self._on_sync_finished)
        QThreadPool.globalInstance().start(worker)

    def _request_sync(self) -> None:
        """Something worth reporting happened: sync after a short debounce."""
        self._flush_soon.start()

    def _on_sync_finished(self, synced_count: int, message: str) -> None:
        self._is_syncing = False
        if self._sync_again:
            self._sync_again = False
            self._request_sync()
        self.statusBar().showMessage(message, 3000)
        # A new config from the app was pulled during this sync: apply it live.
        version = self.db.get_device_state("config_version")
        if version != self._config_version_seen:
            self._config_version_seen = version
            self.scheduler.reload_schedules()
            for compartment in self.scheduler.compartments.values():
                self._refresh_widget(compartment)
            self._refresh_lcd()
            self.statusBar().showMessage(f"Jadwal baru dari aplikasi diterapkan (config v{version}).", 4000)

    # -- server connection / pairing -------------------------------------------
    def _refresh_connection_panel(self) -> None:
        code, _ = sync.get_identity(self.db)
        if not sync.is_registered(self.db):
            self._qr.set_payload(None)
            self._lbl_device_code.setText("Kode: -")
            self._lbl_pair_status.setText("Belum terdaftar ke server")
            self._lbl_pair_status.setStyleSheet("border: none; font-size: 11px; color: #FCA5A5;")
            self._btn_register.setText("Mendaftarkan..." if self._is_registering else "Daftarkan Perangkat")
            self._btn_register.setEnabled(not self._is_registering)
            self._btn_forget.setEnabled(False)
            return
        self._lbl_device_code.setText(f"Kode: {code}")
        self._qr.set_payload(code)  # no-op unless the code changed (register / Reset Identitas)
        if sync.is_paired(self.db):
            self._lbl_pair_status.setText("Terpasang ke aplikasi")
            self._lbl_pair_status.setStyleSheet("border: none; font-size: 11px; color: #6EE7B7;")
        else:
            self._lbl_pair_status.setText("Masukkan kode ini di aplikasi")
            self._lbl_pair_status.setStyleSheet("border: none; font-size: 11px; color: #FCD34D;")
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
        self._launching_until = time.monotonic() + 4
        self._refresh_virtual_panel()
        self.statusBar().showMessage(f"Membuka pillbox virtual '{name}' di jendela baru...", 4000)

    def _on_qr_clicked(self) -> None:
        code = self._qr.payload()
        if code:
            QrDialog(code, self).exec()

    def _on_register_clicked(self) -> None:
        if sync.is_registered(self.db):
            code, _ = sync.get_identity(self.db)
            QApplication.clipboard().setText(code or "")
            self.statusBar().showMessage(f"Kode {code} disalin. Tempel di aplikasi: 'Hubungkan Pillbox'.", 4000)
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
        self._config_version_seen = self.db.get_device_state("config_version")
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
            sync.forget_identity(self.db)
            self._refresh_connection_panel()
            self._refresh_socket()

    def _on_widget_interacted(self, compartment_id: int, is_forced: bool = False) -> None:
        compartment = self.scheduler.compartments[compartment_id]
        if self._alarm_until is not None and self._alarm_slot in (None, compartment.slot_number):
            self._alarm_until = self._alarm_slot = None  # someone came to the box: the app alarm stops

        if compartment.door_open:
            # Door is currently open -> clicking closes it
            self.scheduler.close_compartment(compartment_id)
            self.statusBar().showMessage(f"Pintu Slot {compartment.slot_number} ditutup.", 3000)
        elif self.scheduler.is_refill_mode:
            # In refill mode -> lid can be opened/closed for maintenance
            self.scheduler.open_compartment(compartment_id)
            self.statusBar().showMessage(f"Pintu Slot {compartment.slot_number} dibuka untuk inspeksi refill.", 3000)
        elif compartment.state == ChamberState.ACTIVE:
            # Active scheduled dose -> clicking opens it
            self.scheduler.open_compartment(compartment_id)
            self.statusBar().showMessage(f"Pintu Slot {compartment.slot_number} terbuka: Waktunya minum obat.", 3000)
        elif is_forced:
            # Deliberate forced mechanical pry outside schedule
            self.scheduler.open_compartment(compartment_id)
            self.statusBar().showMessage(f"🚨 PERINGATAN: Pintu Slot {compartment.slot_number} dicungkil paksa di luar jadwal! (UNSCHEDULED_OPEN)", 4000)
        else:
            # Strictly locked! Reject action with shake animation
            widget = self._widgets.get(compartment_id)
            if widget:
                widget.trigger_shake()
            self.statusBar().showMessage(f"🔒 AKSES DITOLAK: Slot {compartment.slot_number} terkunci oleh solenoid! (Jadwal: {compartment.schedule_time} WIB)", 3500)
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
        if self.clock.speed != 1.0:
            self._manual_clock = True
        self._on_clock_changed()

    def _on_jump_minutes(self, minutes: int) -> None:
        self._manual_clock = True
        self.clock.jump(timedelta(minutes=minutes))
        self._on_clock_changed()
        self.statusBar().showMessage(f"Jam pillbox dimajukan {minutes} menit ({self.clock.now():%H:%M}).", 3000)

    def _on_jump_next_dose(self) -> None:
        due_at = self.scheduler.next_due_at()
        if due_at is None:
            self.statusBar().showMessage("Tidak ada jadwal aktif dalam 7 hari ke depan.", 4000)
            return
        self._manual_clock = True
        self.clock.set_time(due_at - timedelta(seconds=5))
        self._on_clock_changed()
        self.statusBar().showMessage(f"Jam dimajukan ke 5 detik sebelum jadwal {due_at:%d/%m %H:%M}.", 4000)

    def _on_sync_real_time(self) -> None:
        """Back to wall-clock time at 1.0x, so device events match the backend's schedule windows."""
        self._manual_clock = False
        self._speed_combo.blockSignals(True)
        self._speed_combo.setCurrentIndex(0)
        self._speed_combo.blockSignals(False)
        self.clock.set_speed(1.0)
        self.clock.set_time(datetime.now())
        self._on_clock_changed()
        self.statusBar().showMessage("Jam perangkat disamakan dengan jam nyata (1.0x).", 4000)

    def _on_reset_day(self) -> None:
        self.scheduler.reset_day()
        for compartment in self.scheduler.compartments.values():
            self._refresh_widget(compartment)
        self._refresh_lcd()

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
        self.statusBar().showMessage(f"Sachet loaded to Slot {slot_number} (Stock: {stock} pcs)", 3000)
        self._request_sync()
        
    def _on_sachet_consumed(self, slot_number: int, medication_name: str) -> None:
        self.statusBar().showMessage(f"Patient consumed medication from Slot {slot_number}: {medication_name}", 3000)

    def _on_bulk_fill_requested(self, count: int) -> None:
        for widget in self._widgets.values():
            widget.refresh()
        self.statusBar().showMessage(f"All slots set to {count} sachet(s)", 3000)
        self._request_sync()

    def _toggle_wifi(self) -> None:
        self._is_online = not self._is_online
        if self._is_online:
            self._btn_wifi.setText("Wi-Fi: Online")
            self._btn_wifi.setStyleSheet("background-color: #065F46; color: white; font-weight: bold;")
        else:
            self._btn_wifi.setText("Wi-Fi: Offline")
            self._btn_wifi.setStyleSheet("background-color: #7F1D1D; color: white; font-weight: bold;")
        self._refresh_lcd()
        self._refresh_socket()
        if self._is_online:
            # Contract §5.3: report back immediately (heartbeat, then the buffered events).
            self._reconnected = True
            self._on_sync_tick()

    def _toggle_refill_mode(self) -> None:
        self.scheduler.is_refill_mode = not self.scheduler.is_refill_mode
        self._update_chime()
        self.db.update_device_state("is_refill_mode", "1" if self.scheduler.is_refill_mode else "0")
        
        # Sync Caregiver Tray in Zone 1
        self.caregiver_tray.set_refill_mode(self.scheduler.is_refill_mode)

        if self.scheduler.is_refill_mode:
            self._btn_refill.setText("Refill Mode: Active")
            self._btn_refill.setStyleSheet("background-color: #0E7490; color: white; font-weight: bold;")
            self.statusBar().showMessage("Refill Mode active: Compartment lids unlocked for replenishment.", 4000)
        else:
            self._btn_refill.setText("Toggle Refill Mode")
            self._btn_refill.setStyleSheet("background-color: #334155; color: white; font-weight: bold;")
            self.statusBar().showMessage("Refill Mode closed: Compartment lids locked.", 4000)

        self._refresh_lcd()
        self._request_sync()

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
        
        # Determine next dose or active status
        if self.scheduler.is_refill_mode:
            status = "MAINTENANCE"
            next_dose = "[ REFILL MODE - LID UNLOCKED ]"
        elif self.scheduler.active_chamber_id is not None:
            active_c = self.scheduler.compartments.get(self.scheduler.active_chamber_id)
            if active_c:
                if active_c.stock_count == 0:
                    status = "STOK HABIS (REFILL)"
                    next_dose = f"KOSONG: [Slot {active_c.slot_number}] {active_c.schedule_time} WIB"
                else:
                    status = "WAKTUNYA MINUM"
                    next_dose = f"AMBIL: [Slot {active_c.slot_number}] {active_c.schedule_time} WIB"
            else:
                status = "IDLE"
                next_dose = "NEXT: --:-- WIB"
        else:
            status = "IDLE"
            next_c = self.scheduler.get_next_dose()
            if next_c:
                next_dose = f"NEXT: [Slot {next_c.slot_number}] {next_c.schedule_time} WIB"
            else:
                next_dose = "NEXT: --:-- (SEMUA SELESAI)"

        self._lcd.update_display(
            time_str=time_str,
            next_dose=next_dose,
            status=status,
            battery=self._battery_percent,
            wifi_on=self._is_online,
            is_refill_mode=self.scheduler.is_refill_mode,
        )

    # -- command channel (backend -> device) ---------------------------------------
    def _refresh_socket(self) -> None:
        """Keeps the command channel open while registered and online."""
        code, key = sync.get_identity(self.db)
        if self._is_online and code and key:
            self._socket.start(code, key)
        else:
            self._socket.stop()

    @staticmethod
    def _server_local_time(server_time: object, timezone: object) -> datetime:
        """Server UTC instant -> naive local time, as the simulated RTC keeps it.
        Raises ValueError / ZoneInfoNotFoundError on a bad payload."""
        instant = datetime.fromisoformat(str(server_time))
        return instant.astimezone(ZoneInfo(str(timezone or "Asia/Jakarta"))).replace(tzinfo=None)

    def _on_welcome(self, message: dict) -> None:
        """Command channel connected: correct the RTC from the server clock (a real
        device would use NTP). Skipped while the lab clock was moved on purpose: the
        backend and the app follow the device clock instead (heartbeat rtc_time)."""
        if self.clock.speed != 1.0 or self._manual_clock:
            return
        try:
            server_now = self._server_local_time(message["server_time"], message.get("timezone"))
        except (KeyError, ValueError, ZoneInfoNotFoundError):
            return
        drift = (self.clock.now() - server_now).total_seconds()
        if abs(drift) < 30:
            return
        self.clock.set_time(server_now)
        self._on_clock_changed()
        logger.info("RTC corrected from server time (was %+.0f s off).", drift)
        self.statusBar().showMessage(f"Jam perangkat disinkronkan dengan server (selisih {drift:+.0f} detik).", 5000)

    def _on_device_command(self, command_id: str, command: str, payload: dict) -> None:
        """Handles a command from the app (contract §3) and acks it right away:
        the caregiver's request waits for this ack."""
        if command == "trigger_alarm":
            slot = payload.get("slot_number")
            compartment = next((c for c in self.scheduler.compartments.values() if c.slot_number == slot), None)
            if compartment is not None:
                self.db.log_event(compartment.id, compartment.slot_number, "ALARM_STARTED", self.clock.now())
                self._request_sync()
            # Rings for the requested time ("Bunyikan alarm" 60 s, "Test pengingat" 10 s), not one beep.
            try:
                duration = max(1, int(payload.get("duration_seconds") or 10))
            except (TypeError, ValueError):
                duration = 10
            self._alarm_until = time.monotonic() + duration
            self._alarm_slot = slot if compartment is not None else None
            self._chime_timer.stop()  # restart so it rings right away
            self._update_chime()
            where = f"Slot {slot}" if slot else "semua slot"
            self.statusBar().showMessage(f"Alarm dari aplikasi ({where}, {duration} detik)", 5000)
            self._socket.send_ack(command_id, True, {"ringing": True, "duration_seconds": duration})
        elif command == "schedule_updated":
            self._socket.send_ack(command_id, True)
            self._request_sync()  # pulls the new config now instead of on the next heartbeat
        elif command == "release_slot":
            try:
                slot = int(payload["slot_number"])
                until = datetime.fromisoformat(str(payload["until"])).replace(tzinfo=None)
            except (KeyError, TypeError, ValueError) as exc:
                self._socket.send_ack(command_id, False, error=f"invalid release_slot payload: {exc}")
                return
            refused = self.scheduler.release_late(slot, until)
            if refused:
                self._socket.send_ack(command_id, False, error=refused)
                return
            self.statusBar().showMessage(f"🔓 Slot {slot} dibuka lagi dari aplikasi sampai {until:%H:%M} (dosis terlewat).", 6000)
            self._socket.send_ack(command_id, True, {"released": True, "release_until": until.isoformat()})
        elif command == "refill_mode":
            enabled = bool(payload.get("enabled"))
            if enabled != self.scheduler.is_refill_mode:
                self._toggle_refill_mode()
            self._socket.send_ack(command_id, True, {"is_refill_mode": self.scheduler.is_refill_mode})
        elif command == "time_sync":
            before = self.clock.now()
            try:
                local = self._server_local_time(payload["server_time"], payload.get("timezone"))
            except (KeyError, ValueError, ZoneInfoNotFoundError) as exc:
                self._socket.send_ack(command_id, False, error=f"invalid time_sync payload: {exc}")
                return
            # A caregiver asked for it ("Kalibrasi jam"): real time again, at real speed.
            self._manual_clock = False
            self._speed_combo.blockSignals(True)
            self._speed_combo.setCurrentIndex(0)
            self._speed_combo.blockSignals(False)
            self.clock.set_speed(1.0)
            self.clock.set_time(local)
            self._on_clock_changed()
            self._socket.send_ack(
                command_id, True,
                {"device_time_before": before.isoformat(), "device_time_after": self.clock.now().isoformat()},
            )
        else:
            self._socket.send_ack(command_id, False, error=f"unsupported command {command!r}")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._socket.stop()
        QThreadPool.globalInstance().waitForDone(500)
        self.db.close()
        super().closeEvent(event)

