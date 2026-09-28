from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFrame, QGraphicsOpacityEffect

from smart_pillbox.gui import styles
from smart_pillbox.models import ChamberState, Compartment


class CompartmentWidget(QWidget):
    """One of the 8 physical compartments. Pure display + one user action
    (`interacted`) — all state decisions live in the scheduler, not here."""

    interacted = Signal(int)  # emits compartment_id

    def __init__(self, compartment: Compartment, parent: QWidget | None = None):
        super().__init__(parent)
        self.compartment_id = compartment.id

        self._led = QFrame(self)
        self._led.setFixedHeight(56)
        self._led.setFrameShape(QFrame.Shape.StyledPanel)

        self._opacity_effect = QGraphicsOpacityEffect(self._led)
        self._led.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(1.0)
        self._breathing_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._breathing_anim.setDuration(900)
        self._breathing_anim.setStartValue(1.0)
        self._breathing_anim.setEndValue(0.35)
        self._breathing_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breathing_anim.setLoopCount(-1)

        self._title_label = QLabel(compartment.label, self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label = QLabel("Idle", self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._action_button = QPushButton("Ambil Obat\n(Buka → Tutup)", self)
        self._action_button.setEnabled(False)
        self._action_button.clicked.connect(lambda: self.interacted.emit(self.compartment_id))

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._led)
        layout.addWidget(self._status_label)
        layout.addWidget(self._action_button)

        self.refresh(compartment)

    def refresh(self, compartment: Compartment) -> None:
        """Re-render from the authoritative Compartment state."""
        color, status_text, breathing = self._visuals_for(compartment)
        self._led.setStyleSheet(f"background-color: {color}; border-radius: 8px;")
        self._status_label.setText(status_text)
        self._action_button.setEnabled(compartment.state == ChamberState.ACTIVE)

        if breathing and self._breathing_anim.state() != QPropertyAnimation.State.Running:
            self._breathing_anim.start()
        elif not breathing:
            self._breathing_anim.stop()
            self._opacity_effect.setOpacity(1.0)

    @staticmethod
    def _visuals_for(compartment: Compartment) -> tuple[str, str, bool]:
        if compartment.state == ChamberState.ACTIVE:
            color = (
                styles.ACTIVE_BEFORE_MEAL_COLOR
                if compartment.meal_relation == "sebelum_makan"
                else styles.ACTIVE_AFTER_MEAL_COLOR
            )
            return color, "🔔 Active — chime sounding", True
        if compartment.state == ChamberState.TAKEN:
            return styles.TAKEN_COLOR, "✅ Taken", False
        if compartment.state == ChamberState.MISSED:
            return styles.MISSED_COLOR, "⚠️ MISSED", False
        return styles.IDLE_COLOR, f"Idle — due {compartment.schedule_time}", False
