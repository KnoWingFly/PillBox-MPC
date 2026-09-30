from __future__ import annotations

import json
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QRectF, QPoint
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QLinearGradient, QDrag
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame,
    QGraphicsOpacityEffect, QGraphicsDropShadowEffect
)

from smart_pillbox.gui import styles
from smart_pillbox.gui.sachet_graphic import SachetGraphic
from smart_pillbox.models import ChamberState, Compartment
from smart_pillbox.core.audio import play_chime
from smart_pillbox.core.scheduler import PillboxScheduler


class ChamberCanvas(QWidget):
    """Custom canvas inside the compartment that procedurally draws the sachet stack."""

    def __init__(self, compartment: Compartment, parent: QWidget | None = None):
        super().__init__(parent)
        self.compartment = compartment
        self.is_highlighted = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)

        # Draw adaptive stacked sachets
        is_active = (self.compartment.state == ChamberState.ACTIVE)
        SachetGraphic.draw_adaptive_stack(
            painter,
            rect,
            stock_count=self.compartment.stock_count,
            is_active=is_active,
            medication_name=self.compartment.medication_name or "Amlodipine 5mg",
        )

        # Highlight outline if hovered during valid drag & drop
        if self.is_highlighted:
            painter.setPen(QPen(QColor(6, 182, 212, 230), 2.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

        painter.end()


class CompartmentWidget(QWidget):
    """One of the 8 physical compartments in the 2x4 chassis (Zona 2).
    Supports Direct Physical Manipulation (Drag-and-Drop):
    - Refill Drop Target: Receives sachet from Caregiver Tray during REFILL MODE.
    - Intake Drag Source: Lansia drags protruding popped-up sachet to Lansia Tray when ACTIVE.
    - Unload Drag Source: Caregiver can drag sachet back to Caregiver Tray during REFILL MODE.
    """

    interacted = Signal(int, bool)  # emits (compartment_id, is_forced)
    refilled = Signal(int)          # emits slot_number

    def __init__(self, compartment: Compartment, scheduler: PillboxScheduler | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.compartment = compartment
        self.compartment_id = compartment.id
        self.scheduler = scheduler
        self.setAcceptDrops(True)

        self.setFixedSize(155, 235)
        self._drag_start_pos: QPoint | None = None

        # 1. Main Housing Frame (Clean Dark Slate 800 with Slate 700 border)
        self._housing = QFrame(self)
        self._housing.setGeometry(0, 0, 155, 235)
        self._housing.setStyleSheet(f"""
            QFrame {{
                background-color: {styles.IDLE_SLOT_BG};
                border: 1px solid {styles.IDLE_SLOT_BORDER};
                border-radius: 12px;
            }}
        """)

        # LED Indicator strip at the top
        self._led = QFrame(self._housing)
        self._led.setGeometry(12, 10, 131, 5)
        
        self._opacity_effect = QGraphicsOpacityEffect(self._led)
        self._led.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(1.0)
        
        self._breathing_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._breathing_anim.setDuration(900)
        self._breathing_anim.setStartValue(1.0)
        self._breathing_anim.setEndValue(0.2)
        self._breathing_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breathing_anim.setLoopCount(-1)

        # Title / Slot relation label
        self._title_label = QLabel(compartment.label, self._housing)
        self._title_label.setGeometry(8, 20, 139, 18)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("font-family: 'Segoe UI'; font-weight: bold; color: #E2E8F0; font-size: 11px;")

        # 2. Chamber Canvas (holds the layered sachet graphics)
        self._canvas = ChamberCanvas(self.compartment, self._housing)
        self._canvas.setGeometry(12, 42, 131, 160)

        # Status badge label
        self._status_label = QLabel("IDLE", self._housing)
        self._status_label.setGeometry(8, 208, 139, 16)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(f"font-family: 'Segoe UI'; color: {styles.TEXT_MUTED}; font-size: 10px; font-weight: bold;")

        self.refresh(compartment)

    def refresh(self, compartment: Compartment | None = None, test_mode: bool = False) -> None:
        """Re-render from the authoritative Compartment state."""
        if compartment is not None:
            self.compartment = compartment
            self._canvas.compartment = compartment

        color, status_text, breathing, is_active = self._visuals_for(self.compartment)

        # Border styling: ONLY ACTIVE slot gets glowing Cyan border
        if is_active:
            self._housing.setStyleSheet(f"""
                QFrame {{
                    background-color: {styles.IDLE_SLOT_BG};
                    border: 2px solid {styles.ACTIVE_CYAN};
                    border-radius: 12px;
                }}
            """)
        else:
            self._housing.setStyleSheet(f"""
                QFrame {{
                    background-color: {styles.IDLE_SLOT_BG};
                    border: 1px solid {styles.IDLE_SLOT_BORDER};
                    border-radius: 12px;
                }}
            """)

        self._led.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        self._status_label.setText(status_text.upper())
        self._status_label.setStyleSheet(f"font-family: 'Segoe UI'; color: {color}; font-size: 10px; font-weight: bold;")

        if breathing and self._breathing_anim.state() != QPropertyAnimation.State.Running:
            self._breathing_anim.start()
        elif not breathing:
            self._breathing_anim.stop()
            self._opacity_effect.setOpacity(1.0)


        # Repaint sachet canvas
        self._canvas.update()

    def trigger_shake(self) -> None:
        """Physical tactile vibration effect when an action is rejected on a locked slot."""
        if hasattr(self, "_shake_anim") and self._shake_anim.state() == QPropertyAnimation.State.Running:
            return

        self._shake_anim = QPropertyAnimation(self._housing, b"pos", self)
        self._shake_anim.setDuration(280)
        orig_pos = QPoint(0, 0)
        self._shake_anim.setKeyValueAt(0.0, orig_pos)
        self._shake_anim.setKeyValueAt(0.15, QPoint(-7, 0))
        self._shake_anim.setKeyValueAt(0.35, QPoint(7, 0))
        self._shake_anim.setKeyValueAt(0.55, QPoint(-5, 0))
        self._shake_anim.setKeyValueAt(0.75, QPoint(5, 0))
        self._shake_anim.setKeyValueAt(0.9, QPoint(-2, 0))
        self._shake_anim.setKeyValueAt(1.0, orig_pos)

        # Temporary Red Border flash to visually signify mechanical lock rejection
        self._housing.setStyleSheet(f"""
            QFrame {{
                background-color: {styles.IDLE_SLOT_BG};
                border: 2px solid #EF4444;
                border-radius: 12px;
            }}
        """)
        self._shake_anim.start()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(350, self.refresh)

    # -- Mouse events for Dragging sachet OUT of slot & Forced Open ------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # If door is already open, clicking on it closes the lid
            if self.compartment.door_open:
                self.interacted.emit(self.compartment_id, False)
                event.accept()
                return

            # If slot is locked (not refill mode and not active):
            # Normal clicking is REJECTED with physical vibration/shake!
            if not self.scheduler.is_refill_mode and self.compartment.state != ChamberState.ACTIVE:
                self.trigger_shake()
                if hasattr(self.window(), "statusBar") and self.window().statusBar():
                    self.window().statusBar().showMessage(
                        f"🔒 AKSES DITOLAK: Slot {self.compartment.slot_number} terkunci oleh solenoid! (Jadwal: {self.compartment.schedule_time} WIB)",
                        3500,
                    )
                event.accept()
                return

            # Check if drag is allowed:
            # 1. Intake: When ACTIVE and sachet is popped up
            # 2. Refill Unload: When REFILL_MODE is active and slot has stock
            if (self.compartment.state == ChamberState.ACTIVE and self.compartment.stock_count > 0) or \
               (self.scheduler.is_refill_mode and self.compartment.stock_count > 0):
                self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # If door is already open, double-clicking also closes the lid
            if self.compartment.door_open:
                self.interacted.emit(self.compartment_id, False)
                event.accept()
                return

            # If in refill mode: double-click opens lid for inspection
            if self.scheduler.is_refill_mode:
                self.interacted.emit(self.compartment_id, False)
                event.accept()
                return

            # If active: opening lid
            if self.compartment.state == ChamberState.ACTIVE:
                self.interacted.emit(self.compartment_id, False)
                event.accept()
                return

            # If locked (IDLE / TAKEN / MISSED):
            # Check if developer/tester used Alt+Double-Click for simulated forced pry
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.interacted.emit(self.compartment_id, True)  # is_forced = True
                event.accept()
                return

            # Normal double-click on locked slot: FIRMLY REJECTED with vibration!
            self.trigger_shake()
            if hasattr(self.window(), "statusBar") and self.window().statusBar():
                self.window().statusBar().showMessage(
                    f"🔒 AKSES DITOLAK: Pintu Slot {self.compartment.slot_number} terkunci rapat oleh solenoid! (Gunakan Alt + Double-Click untuk simulasi cungkil paksa).",
                    4000,
                )
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or not self._drag_start_pos:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < 5:
            return

        # Prepare QDrag
        drag = QDrag(self)
        from PySide6.QtCore import QMimeData

        mime_data = QMimeData()
        payload = {
            "source_type": "compartment",
            "slot_number": self.compartment.slot_number,
            "medication_name": self.compartment.medication_name or "Amlodipine 5mg",
        }
        mime_data.setData("application/x-pillcare-sachet", json.dumps(payload).encode("utf-8"))
        drag.setMimeData(mime_data)

        # Ghost Pixmap (75% opacity)
        ghost = SachetGraphic.create_drag_pixmap(
            width=110,
            height=140,
            medication_name=self.compartment.medication_name or "Amlodipine 5mg",
            opacity=0.75,
        )
        drag.setPixmap(ghost)
        drag.setHotSpot(QPoint(ghost.width() // 2, ghost.height() // 2))

        # Execute drag
        result = drag.exec(Qt.DropAction.MoveAction)
        self._drag_start_pos = None
        self.refresh()

    # -- Drop events for Refilling sachet INTO slot ----------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pillcare-sachet"):
            try:
                data = json.loads(bytes(event.mimeData().data("application/x-pillcare-sachet")).decode("utf-8"))
                # Strictly validate Refill Mode and Capacity <= 30
                if data.get("source_type") == "caregiver_tray":
                    if not self.scheduler.is_refill_mode:
                        self.trigger_shake()
                        if hasattr(self.window(), "statusBar") and self.window().statusBar():
                            self.window().statusBar().showMessage(
                                f"🚫 PENGISIAN DITOLAK: Slot {self.compartment.slot_number} terkunci! Aktifkan Refill Mode di Meja Caregiver terlebih dahulu.",
                                3500,
                            )
                        event.ignore()
                        return

                    if self.compartment.stock_count >= 30:
                        self.trigger_shake()
                        if hasattr(self.window(), "statusBar") and self.window().statusBar():
                            self.window().statusBar().showMessage(
                                f"⚠️ Slot {self.compartment.slot_number} sudah penuh (Maksimal 30 sachet).",
                                3000,
                            )
                        event.ignore()
                        return

                    event.acceptProposedAction()
                    self._canvas.is_highlighted = True
                    self._canvas.update()
                    return
            except Exception:
                pass
        # Reject drop -> triggers snap-back
        event.ignore()

    def dragLeaveEvent(self, event):
        self._canvas.is_highlighted = False
        self._canvas.update()

    def dropEvent(self, event):
        self._canvas.is_highlighted = False
        self._canvas.update()

        try:
            data = json.loads(bytes(event.mimeData().data("application/x-pillcare-sachet")).decode("utf-8"))
            if data.get("source_type") == "caregiver_tray":
                if not self.scheduler.is_refill_mode:
                    self.trigger_shake()
                    event.ignore()
                    return

                if self.compartment.stock_count < 30:
                    # Refill slot by +1
                    new_stock = self.scheduler.refill_slot(self.compartment.slot_number, 1)
                    self.compartment.stock_count = new_stock
                    self.refilled.emit(self.compartment.slot_number)
                    self.refresh()
                    event.acceptProposedAction()
                    return
                else:
                    self.trigger_shake()
                    event.ignore()
                    return
        except Exception:
            pass
        event.ignore()

    @staticmethod
    def _visuals_for(compartment: Compartment) -> tuple[str, str, bool, bool]:
        # returns: (led_color, status_text, is_breathing, is_active)
        if compartment.door_open:
            return styles.ACTIVE_CYAN, "LID OPEN", False, False

        if compartment.state == ChamberState.ACTIVE:
            if compartment.stock_count == 0:
                return styles.MISSED_COLOR, "STOK HABIS", True, True
            return styles.ACTIVE_CYAN, "WAKTUNYA MINUM", True, True
            
        if compartment.state == ChamberState.TAKEN:
            return styles.TAKEN_COLOR, "TAKEN", False, False
            
        if compartment.state == ChamberState.MISSED:
            return styles.MISSED_COLOR, "MISSED", False, False
            
        return styles.TEXT_MUTED, f"DUE: {compartment.schedule_time}", False, False

