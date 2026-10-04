from __future__ import annotations

import json
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QListWidget, QListWidgetItem, QPushButton
)

from smart_pillbox.gui.sachet_graphic import SachetGraphic
from smart_pillbox.core.scheduler import PillboxScheduler


class WaterGlassWidget(QWidget):
    """Procedural vector illustration of a clear water glass on elderly's bedside tray."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(110)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Center glass
        w = 54.0
        h = 80.0
        x = (self.width() - w) / 2.0
        y = 15.0

        # Coaster shadow underneath
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawEllipse(QRectF(x - 6, y + h - 4, w + 12, 14))

        # Wooden coaster
        coaster_brush = QLinearGradient(QPointF(x, y + h), QPointF(x + w, y + h))
        coaster_brush.setColorAt(0.0, QColor(160, 110, 75))
        coaster_brush.setColorAt(1.0, QColor(120, 80, 50))
        painter.setBrush(coaster_brush)
        painter.drawRoundedRect(QRectF(x - 4, y + h - 6, w + 8, 8), 3, 3)

        # Water body inside glass
        water_rect = QRectF(x + 4, y + 26, w - 8, h - 30)
        water_grad = QLinearGradient(water_rect.topLeft(), water_rect.bottomRight())
        water_grad.setColorAt(0.0, QColor(100, 200, 255, 140))
        water_grad.setColorAt(1.0, QColor(50, 160, 230, 200))
        painter.setBrush(water_grad)
        painter.drawRoundedRect(water_rect, 4, 4)

        # Glass rim & outer transparent reflections
        glass_grad = QLinearGradient(QPointF(x, y), QPointF(x + w, y))
        glass_grad.setColorAt(0.0, QColor(255, 255, 255, 160))
        glass_grad.setColorAt(0.2, QColor(200, 230, 255, 60))
        glass_grad.setColorAt(0.8, QColor(255, 255, 255, 40))
        glass_grad.setColorAt(1.0, QColor(255, 255, 255, 140))

        painter.setPen(QPen(QColor(220, 240, 255, 200), 1.5))
        painter.setBrush(glass_grad)
        painter.drawRoundedRect(QRectF(x, y, w, h), 6, 6)

        # High-gloss shine line down the left side
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1.2))
        painter.drawLine(QPointF(x + 7, y + 10), QPointF(x + 7, y + h - 10))

        painter.end()


class IntakeLogItemWidget(QFrame):
    """Clean two-line medical record card for elderly intake event."""

    def __init__(self, slot_number: int, medication_name: str, time_str: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Top row: Time + Slot badge
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        lbl_time = QLabel(time_str)
        lbl_time.setStyleSheet("color: #94A3B8; font-family: 'Consolas', monospace; font-size: 10px; font-weight: bold; border: none;")
        top_row.addWidget(lbl_time)

        top_row.addStretch()

        lbl_slot = QLabel(f"Slot {slot_number}")
        lbl_slot.setStyleSheet("""
            background-color: #1E293B;
            color: #38BDF8;
            font-size: 9px;
            font-weight: bold;
            border-radius: 3px;
            padding: 1px 5px;
            border: 1px solid #0284C7;
        """)
        top_row.addWidget(lbl_slot)
        layout.addLayout(top_row)

        # Bottom row: Medication name + Status Taken
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)

        lbl_med = QLabel(medication_name)
        lbl_med.setStyleSheet("color: #F8FAFC; font-size: 10px; font-weight: bold; border: none;")
        bot_row.addWidget(lbl_med)

        bot_row.addStretch()

        lbl_status = QLabel("✓ Diminum")
        lbl_status.setStyleSheet("color: #10B981; font-size: 9px; font-weight: bold; border: none;")
        bot_row.addWidget(lbl_status)
        layout.addLayout(bot_row)


class LansiaTrayWidget(QFrame):
    """Zona 3: Meja Minum Lansia.
    Acts as the drop target when elderly takes medicine (drags sachet out of pop-up slot).
    Maintains a session intake history log.
    """

    sachet_consumed = Signal(int, str)  # (slot_number, medication_name)

    def __init__(self, scheduler: PillboxScheduler, parent: QWidget | None = None):
        super().__init__(parent)
        self.scheduler = scheduler
        self.setAcceptDrops(True)
        self.setFixedWidth(240)
        self.setStyleSheet("""
            LansiaTrayWidget {
                background-color: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Title Header
        title_lbl = QLabel("ZONE 3: PATIENT")
        title_lbl.setStyleSheet("color: #06B6D4; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel("PATIENT INTAKE TRAY")
        sub_lbl.setStyleSheet("color: #F8FAFC; font-size: 13px; font-weight: bold;")
        layout.addWidget(sub_lbl)

        # Drop Zone Frame (Tray & Water glass)
        self._tray_dropzone = QFrame()
        self._tray_dropzone.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px dashed #475569;
                border-radius: 10px;
            }
        """)
        tray_layout = QVBoxLayout(self._tray_dropzone)
        tray_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tray_layout.setContentsMargins(6, 10, 6, 10)

        # Vector water glass
        self._glass = WaterGlassWidget(self._tray_dropzone)
        tray_layout.addWidget(self._glass)

        self._drop_hint = QLabel("DROP SACHET HERE")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setStyleSheet("color: #94A3B8; font-size: 9px; font-weight: bold; margin-top: 4px;")
        tray_layout.addWidget(self._drop_hint)

        layout.addWidget(self._tray_dropzone)

        # Intake Log Header
        log_title = QLabel("Session Intake Log")
        log_title.setStyleSheet("color: #94A3B8; font-size: 10px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(log_title)

        # Intake List
        self._log_list = QListWidget()
        self._log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._log_list.setStyleSheet("""
            QListWidget {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 3px;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 2px 0px;
            }
        """)
        layout.addWidget(self._log_list)

        btn_clear = QPushButton("Clear Log")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #F8FAFC;
            }
        """)
        btn_clear.clicked.connect(self._log_list.clear)
        layout.addWidget(btn_clear)

    def add_intake_entry(self, slot_number: int, medication_name: str, time_str: str | None = None) -> None:
        """Adds an intake confirmation record to the tray list using an elegant 2-line card."""
        t_str = time_str if time_str else datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem()
        widget = IntakeLogItemWidget(slot_number, medication_name, t_str)
        item.setSizeHint(widget.sizeHint())
        self._log_list.insertItem(0, item)
        self._log_list.setItemWidget(item, widget)

    # -- Drop Handling from Pop-up Compartment ---------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pillcare-sachet"):
            try:
                data = json.loads(bytes(event.mimeData().data("application/x-pillcare-sachet")).decode("utf-8"))
                if data.get("source_type") == "compartment":
                    event.acceptProposedAction()
                    self._tray_dropzone.setStyleSheet("""
                        QFrame {
                            background-color: #1E293B;
                            border: 2px dashed #06B6D4;
                            border-radius: 10px;
                        }
                    """)
                    return
            except Exception:
                pass
        event.ignore()

    def dragLeaveEvent(self, event):
        self._tray_dropzone.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px dashed #475569;
                border-radius: 10px;
            }
        """)


    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        try:
            data = json.loads(bytes(event.mimeData().data("application/x-pillcare-sachet")).decode("utf-8"))
            if data.get("source_type") == "compartment":
                slot_num = data.get("slot_number")
                med_name = data.get("medication_name", "Amlodipine 5mg")
                
                # Find compartment in scheduler
                target_comp = None
                for c in self.scheduler.compartments.values():
                    if c.slot_number == slot_num:
                        target_comp = c
                        break

                if target_comp:
                    # Take medication!
                    self.scheduler.open_compartment(target_comp.id)
                    now_str = self.scheduler.clock.now().strftime("%H:%M:%S")
                    self.add_intake_entry(slot_num, med_name, now_str)
                    self.sachet_consumed.emit(slot_num, med_name)
                    event.acceptProposedAction()
                    return
        except Exception:
            pass
        event.ignore()
