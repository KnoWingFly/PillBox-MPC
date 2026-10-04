from __future__ import annotations

import logging
from datetime import timedelta

from PySide6.QtCore import Qt, QTimer, QRunnable, QThreadPool, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QStatusBar, QFrame, QGroupBox, QSlider, QCheckBox, QComboBox
)

from smart_pillbox import config
from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.core.scheduler import PillboxScheduler
from smart_pillbox.core.audio import play_chime
from smart_pillbox.core import sync
from smart_pillbox.db.database import Database
from smart_pillbox.gui.compartment_widget import CompartmentWidget
from smart_pillbox.gui.lcd_widget import LcdDisplay
from smart_pillbox.gui.caregiver_tray_widget import CaregiverTrayWidget
from smart_pillbox.gui.lansia_tray_widget import LansiaTrayWidget
from smart_pillbox.gui import styles
from smart_pillbox.models import Compartment, ChamberState

logger = logging.getLogger(__name__)


class SyncSignals(QObject):
    finished = Signal(int, str)


class SyncWorker(QRunnable):
    """Background worker to execute telemetry sync without blocking the Qt GUI thread."""

    def __init__(self, db: Database, now_str: str, battery: int, is_online: bool):
        super().__init__()
        self.db = db
        self.now_str = now_str
        self.battery = battery
        self.is_online = is_online
        self.signals = SyncSignals()

    def run(self):
        try:
            sync.send_heartbeat(self.db, self.now_str, self.battery, self.is_online)
            synced_count = sync.flush_pending_events(self.db)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Pillbox — Device Simulator (CE739L)")
        self.resize(1260, 840)
        self.setMinimumSize(1180, 780)
        self.setStyleSheet(f"background-color: {styles.BACKGROUND};")

        self.db = Database()
        self.clock = SimulatedClock(speed=config.DEFAULT_SIM_SPEED)
        self.scheduler = PillboxScheduler(self.db, self.clock)
        self.scheduler.on_activated.append(self._on_state_changed)
        self.scheduler.on_missed.append(self._on_state_changed)
        self.scheduler.on_taken.append(self._on_state_changed)

        self._widgets: dict[int, CompartmentWidget] = {}
        self._is_online = True
        self._is_syncing = False
        self._battery_percent = 100

        self._build_ui()


        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)  # real 1s; simulated speed handled by SimulatedClock
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(config.SYNC_INTERVAL_SECONDS * 1000)
        self._sync_timer.timeout.connect(self._on_sync_tick)
        self._sync_timer.start()

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
        lab_panel.setFixedHeight(110)
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
        self._speed_combo.currentTextChanged.connect(lambda t: self.clock.set_speed(float(t.replace("x", ""))))
        time_lbl = QLabel("Speed:")
        time_lbl.setStyleSheet("border: none;")
        time_inner_layout.addWidget(time_lbl)
        time_inner_layout.addWidget(self._speed_combo)
        
        btn_jump = QPushButton("+1 Hour")
        btn_jump.clicked.connect(self._on_jump_hour)
        time_inner_layout.addWidget(btn_jump)
        time_layout.addLayout(time_inner_layout)
        
        btn_reset = QPushButton("Reset Day to IDLE")
        btn_reset.clicked.connect(self._on_reset_day)
        time_layout.addWidget(btn_reset)
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

        lab_layout.addStretch()

        main_layout.addWidget(lab_panel)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().setStyleSheet("color: #888;")
        self._refresh_lcd()

    # -- event handlers ------------------------------------------------------
    def _on_tick(self) -> None:
        self.scheduler.tick()
        self._refresh_lcd()

    def _on_sync_tick(self) -> None:
        if not self._is_online:
            self.statusBar().showMessage("Offline - Events buffered locally.", 3000)
            return

        if self._is_syncing:
            return  # Prior sync request still in progress; skip to avoid thread congestion

        self._is_syncing = True
        now_str = self.clock.now().isoformat()
        worker = SyncWorker(self.db, now_str, self._battery_percent, self._is_online)
        worker.signals.finished.connect(self._on_sync_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_sync_finished(self, synced_count: int, message: str) -> None:
        self._is_syncing = False
        self.statusBar().showMessage(message, 3000)

    def _on_widget_interacted(self, compartment_id: int, is_forced: bool = False) -> None:
        compartment = self.scheduler.compartments[compartment_id]

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

    def _on_jump_hour(self) -> None:
        self.clock.jump(timedelta(hours=1))
        self.scheduler.tick()
        self._refresh_lcd()

    def _on_reset_day(self) -> None:
        self.scheduler.reset_day()
        for compartment in self.scheduler.compartments.values():
            self._refresh_widget(compartment)
        self._refresh_lcd()

    def _on_state_changed(self, compartment: Compartment) -> None:
        self._refresh_widget(compartment)
        self._refresh_lcd()
        if compartment.state == ChamberState.ACTIVE and compartment.stock_count > 0:
            play_chime()


    def _on_widget_refilled(self, slot_number: int) -> None:
        compartment = self.scheduler.compartments.get(slot_number)
        stock = compartment.stock_count if compartment else "?"
        self.statusBar().showMessage(f"Sachet loaded to Slot {slot_number} (Stock: {stock} pcs)", 3000)
        
    def _on_sachet_consumed(self, slot_number: int, medication_name: str) -> None:
        self.statusBar().showMessage(f"Patient consumed medication from Slot {slot_number}: {medication_name}", 3000)

    def _on_bulk_fill_requested(self, count: int) -> None:
        for widget in self._widgets.values():
            widget.refresh()
        self.statusBar().showMessage(f"All slots set to {count} sachet(s)", 3000)

    def _toggle_wifi(self) -> None:
        self._is_online = not self._is_online
        if self._is_online:
            self._btn_wifi.setText("Wi-Fi: Online")
            self._btn_wifi.setStyleSheet("background-color: #065F46; color: white; font-weight: bold;")
        else:
            self._btn_wifi.setText("Wi-Fi: Offline")
            self._btn_wifi.setStyleSheet("background-color: #7F1D1D; color: white; font-weight: bold;")
        self._refresh_lcd()

    def _toggle_refill_mode(self) -> None:
        self.scheduler.is_refill_mode = not self.scheduler.is_refill_mode
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

    def _on_battery_changed(self, value: int) -> None:
        self._battery_percent = value
        self._batt_label.setText(f"Battery: {value}%")
        self._refresh_lcd()


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

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        QThreadPool.globalInstance().waitForDone(500)
        self.db.close()
        super().closeEvent(event)

