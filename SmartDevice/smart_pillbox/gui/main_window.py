from __future__ import annotations

import logging
from datetime import timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QStatusBar, QFrame, QGroupBox, QSlider, QCheckBox, QComboBox
)

from smart_pillbox import config
from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.core.scheduler import PillboxScheduler
from smart_pillbox.core import sync
from smart_pillbox.db.database import Database
from smart_pillbox.gui.compartment_widget import CompartmentWidget
from smart_pillbox.gui.lcd_widget import LcdDisplay
from smart_pillbox.gui import styles
from smart_pillbox.models import Compartment, ChamberState

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Pillbox — Device Simulator (CE739L)")
        self.resize(1100, 650)
        self.setStyleSheet(f"background-color: {styles.BACKGROUND};")

        self.db = Database()
        self.clock = SimulatedClock(speed=config.DEFAULT_SIM_SPEED)
        self.scheduler = PillboxScheduler(self.db, self.clock)
        self.scheduler.on_activated.append(self._on_state_changed)
        self.scheduler.on_missed.append(self._on_state_changed)
        self.scheduler.on_taken.append(self._on_state_changed)

        self._widgets: dict[int, CompartmentWidget] = {}
        self._is_online = True
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
        main_layout = QHBoxLayout(central)

        # 1. Physical Device Chassis (Left Side)
        chassis = QFrame(self)
        chassis.setStyleSheet(f"""
            QFrame {{
                background-color: {styles.ABS_WHITE};
                border-radius: 20px;
                border: 2px solid {styles.ABS_SHADOW};
            }}
        """)
        chassis_layout = QVBoxLayout(chassis)
        chassis_layout.setContentsMargins(30, 30, 30, 30)

        # Top section of chassis: LCD and Speaker Grille
        top_chassis_layout = QHBoxLayout()
        self._lcd = LcdDisplay(self)
        top_chassis_layout.addWidget(self._lcd)
        
        # Speaker Grille Mockup
        speaker_grille = QLabel(":::\n:::\n:::")
        speaker_grille.setFont(QFont("Courier", 18, QFont.Weight.Bold))
        speaker_grille.setStyleSheet("color: #AAA; background: transparent;")
        speaker_grille.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_chassis_layout.addStretch()
        top_chassis_layout.addWidget(speaker_grille)
        top_chassis_layout.addStretch()
        
        chassis_layout.addLayout(top_chassis_layout)

        # Bottom section: 2x4 Compartment Matrix
        grid_container = QWidget(chassis)
        grid_container.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_container)
        grid.setSpacing(15)
        
        for compartment in self.scheduler.compartments.values():
            # A mapping: 1-4 is row 0. 5-8 is row 1
            row = 0 if compartment.slot_number <= 4 else 1
            col = (compartment.slot_number - 1) % 4
            widget = CompartmentWidget(compartment, grid_container)
            widget.interacted.connect(self._on_widget_interacted)
            grid.addWidget(widget, row, col)
            self._widgets[compartment.id] = widget
            
        chassis_layout.addWidget(grid_container)

        # 2. Developer Lab Workbench (Right Side)
        lab_panel = QFrame(self)
        lab_panel.setFixedWidth(300)
        lab_panel.setStyleSheet(f"""
            QFrame {{ background-color: {styles.BACKGROUND}; border-left: 1px solid #333; }}
            QLabel, QGroupBox {{ color: {styles.TEXT_LIGHT}; }}
            QPushButton {{ background-color: #333; color: white; padding: 8px; border-radius: 4px; }}
            QPushButton:hover {{ background-color: #444; }}
        """)
        lab_layout = QVBoxLayout(lab_panel)
        lab_layout.setContentsMargins(20, 20, 20, 20)

        lab_title = QLabel("Lab Control Workbench", lab_panel)
        lab_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        lab_layout.addWidget(lab_title)

        # Simulation / Edge-case Controls
        sim_group = QGroupBox("Skenario Interaksi")
        sim_layout = QVBoxLayout(sim_group)
        # (Lid ajar test mode removed in V2 redesign)
        sim_lbl = QLabel("Mode normal: Buka lid menyelesaikan jadwal minum obat.")
        sim_lbl.setWordWrap(True)
        sim_lbl.setStyleSheet("color: #DDD; font-size: 11px;")
        sim_layout.addWidget(sim_lbl)
        lab_layout.addWidget(sim_group)

        # Time Controls
        time_group = QGroupBox("RTC Controls")
        time_layout = QVBoxLayout(time_group)
        self._speed_combo = QComboBox()
        self._speed_combo.addItems(["1.0x", "10.0x", "60.0x"])
        self._speed_combo.currentTextChanged.connect(lambda t: self.clock.set_speed(float(t.replace("x", ""))))
        time_layout.addWidget(QLabel("Speed multiplier:"))
        time_layout.addWidget(self._speed_combo)
        
        btn_jump = QPushButton("Jump +1 Hour")
        btn_jump.clicked.connect(lambda: self.clock.jump(timedelta(hours=1)))
        time_layout.addWidget(btn_jump)
        
        btn_reset = QPushButton("Reset Day to IDLE")
        btn_reset.clicked.connect(self._on_reset_day)
        time_layout.addWidget(btn_reset)
        lab_layout.addWidget(time_group)

        # Network Controls
        net_group = QGroupBox("Network & Sync")
        net_layout = QVBoxLayout(net_group)
        self._btn_wifi = QPushButton("Wi-Fi: ONLINE")
        self._btn_wifi.setStyleSheet("background-color: #27AE60;")
        self._btn_wifi.clicked.connect(self._toggle_wifi)
        net_layout.addWidget(self._btn_wifi)
        lab_layout.addWidget(net_group)

        # Refill Controls
        refill_group = QGroupBox("Refill & Maintenance")
        refill_layout = QVBoxLayout(refill_group)
        self._btn_refill = QPushButton("TOGGLE REFILL MODE")
        self._btn_refill.setStyleSheet("background-color: #333; color: white; font-weight: bold;")
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
        batt_layout.addWidget(self._batt_label)
        batt_layout.addWidget(self._batt_slider)
        lab_layout.addWidget(batt_group)

        lab_layout.addStretch()

        main_layout.addWidget(chassis, stretch=1)
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
            
        now_str = self.clock.now().isoformat()
        sync.send_heartbeat(self.db, now_str, self._battery_percent, self._is_online)
        
        synced_count = sync.flush_pending_events(self.db)
        if synced_count:
            self.statusBar().showMessage(f"Synced {synced_count} event(s) to backend.", 3000)
        else:
            self.statusBar().showMessage("Heartbeat OK / No pending events.", 3000)

    def _on_widget_interacted(self, compartment_id: int) -> None:
        compartment = self.scheduler.compartments[compartment_id]

        if compartment.door_open:
            # Door is currently open -> clicking closes it
            self.scheduler.close_compartment(compartment_id)
        elif compartment.state == ChamberState.ACTIVE:
            # Active -> clicking opens it
            self.scheduler.open_compartment(compartment_id)
        else:
            # Unscheduled open
            self.scheduler.open_compartment(compartment_id)

        self._refresh_widget(compartment)
        self._refresh_lcd()

    def _on_reset_day(self) -> None:
        self.scheduler.reset_day()
        for compartment in self.scheduler.compartments.values():
            self._refresh_widget(compartment)

    def _on_state_changed(self, compartment: Compartment) -> None:
        self._refresh_widget(compartment)
        self._refresh_lcd()

    def _toggle_wifi(self) -> None:
        self._is_online = not self._is_online
        if self._is_online:
            self._btn_wifi.setText("Wi-Fi: ONLINE")
            self._btn_wifi.setStyleSheet("background-color: #27AE60; color: white;")
        else:
            self._btn_wifi.setText("Wi-Fi: OFFLINE")
            self._btn_wifi.setStyleSheet("background-color: #EB5757; color: white;")
        self._refresh_lcd()

    def _toggle_refill_mode(self) -> None:
        self.scheduler.is_refill_mode = not self.scheduler.is_refill_mode
        self.db.update_device_state("is_refill_mode", "1" if self.scheduler.is_refill_mode else "0")
        
        if self.scheduler.is_refill_mode:
            self._btn_refill.setStyleSheet("background-color: #F1C40F; color: black; font-weight: bold;")
        else:
            self._btn_refill.setStyleSheet("background-color: #333; color: white; font-weight: bold;")
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
            status = "REFILL MODE"
            next_dose = "--:-- WIB"
        else:
            active_c = self.scheduler.compartments.get(self.scheduler.active_chamber_id)
            if active_c:
                status = "DOSE READY"
                next_dose = f"[Slot {active_c.slot_number}] {active_c.schedule_time}"
            else:
                status = "IDLE"
                # simple mock for next dose text
                next_dose = "--:-- WIB"

        self._lcd.update_display(
            time_str=time_str,
            next_dose=next_dose,
            status=status,
            battery=self._battery_percent,
            wifi_on=self._is_online
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.db.close()
        super().closeEvent(event)
