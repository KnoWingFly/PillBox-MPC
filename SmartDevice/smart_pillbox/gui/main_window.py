from __future__ import annotations

import logging
from datetime import timedelta

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QStatusBar,
)

from smart_pillbox import config
from smart_pillbox.core.rtc import SimulatedClock
from smart_pillbox.core.scheduler import PillboxScheduler
from smart_pillbox.core import sync
from smart_pillbox.db.database import Database
from smart_pillbox.gui.compartment_widget import CompartmentWidget
from smart_pillbox.models import Compartment

logger = logging.getLogger(__name__)

_ROW_ORDER = ["sebelum_makan", "sesudah_makan"]
_COL_ORDER = ["pagi", "siang", "sore", "malam"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Pillbox — Device Simulator (CE739L)")
        self.resize(1000, 560)

        self.db = Database()
        self.clock = SimulatedClock(speed=config.DEFAULT_SIM_SPEED)
        self.scheduler = PillboxScheduler(self.db, self.clock)
        self.scheduler.on_activated.append(self._on_state_changed)
        self.scheduler.on_missed.append(self._on_state_changed)
        self.scheduler.on_taken.append(self._on_state_changed)

        self._widgets: dict[int, CompartmentWidget] = {}

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
        outer = QVBoxLayout(central)

        outer.addLayout(self._build_toolbar())

        grid_container = QWidget(central)
        grid = QGridLayout(grid_container)
        for compartment in self.scheduler.compartments.values():
            row = _ROW_ORDER.index(compartment.meal_relation)
            col = _COL_ORDER.index(compartment.meal_time)
            widget = CompartmentWidget(compartment)
            widget.interacted.connect(self._on_widget_interacted)
            grid.addWidget(widget, row, col)
            self._widgets[compartment.id] = widget
        outer.addWidget(grid_container)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self._refresh_clock_label()

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        self._clock_label = QLabel(self)
        bar.addWidget(self._clock_label)
        bar.addStretch(1)

        bar.addWidget(QLabel("Speed (x realtime):", self))
        speed_spin = QDoubleSpinBox(self)
        speed_spin.setRange(1.0, 3600.0)
        speed_spin.setValue(config.DEFAULT_SIM_SPEED)
        speed_spin.setDecimals(0)
        speed_spin.valueChanged.connect(lambda v: self.clock.set_speed(v))
        bar.addWidget(speed_spin)

        jump_button = QPushButton("Jump +1 hour", self)
        jump_button.clicked.connect(lambda: self.clock.jump(timedelta(hours=1)))
        bar.addWidget(jump_button)

        reset_button = QPushButton("Reset Day", self)
        reset_button.clicked.connect(self._on_reset_day)
        bar.addWidget(reset_button)

        return bar

    # -- event handlers ------------------------------------------------------
    def _on_tick(self) -> None:
        self.scheduler.tick()
        self._refresh_clock_label()

    def _on_sync_tick(self) -> None:
        synced_count = sync.flush_pending_events(self.db)
        if synced_count:
            self.statusBar().showMessage(f"Synced {synced_count} event(s) to backend.", 3000)
        else:
            self.statusBar().showMessage("Backend unreachable — buffering locally.", 3000)

    def _on_widget_interacted(self, compartment_id: int) -> None:
        self.scheduler.interact(compartment_id)
        self._refresh_widget(self.scheduler.compartments[compartment_id])

    def _on_reset_day(self) -> None:
        self.scheduler.reset_day()
        for compartment in self.scheduler.compartments.values():
            self._refresh_widget(compartment)

    def _on_state_changed(self, compartment: Compartment) -> None:
        self._refresh_widget(compartment)

    # -- helpers -----------------------------------------------------------
    def _refresh_widget(self, compartment: Compartment) -> None:
        self._widgets[compartment.id].refresh(compartment)

    def _refresh_clock_label(self) -> None:
        now = self.clock.now()
        self._clock_label.setText(f"Simulated time: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.db.close()
        super().closeEvent(event)
