from __future__ import annotations

import json
from PySide6.QtCore import Qt, Signal, QPoint, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QDrag, QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)

from smart_pillbox.gui.sachet_graphic import SachetGraphic
from smart_pillbox.core.scheduler import PillboxScheduler


class DraggableSachetCard(QWidget):
    """Visual sachet supply pile inside Caregiver's tray that initiates QDrag."""

    def __init__(self, medication_name: str = "Amlodipine 5mg", parent: QWidget | None = None):
        super().__init__(parent)
        self.medication_name = medication_name
        self.setFixedSize(130, 170)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_start_pos: QPoint | None = None
        self.setToolTip("Drag sachet to slot to refill")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or not self._drag_start_pos:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < 5:
            return

        # Start Qt Drag
        drag = QDrag(self)
        from PySide6.QtCore import QMimeData

        mime_data = QMimeData()
        payload = {
            "source_type": "caregiver_tray",
            "medication_name": self.medication_name,
            "slot_number": None,
        }
        mime_data.setData("application/x-pillcare-sachet", json.dumps(payload).encode("utf-8"))
        drag.setMimeData(mime_data)

        # 75% opacity translucent ghost image
        ghost_pixmap = SachetGraphic.create_drag_pixmap(
            width=110, height=140, medication_name=self.medication_name, opacity=0.75
        )
        drag.setPixmap(ghost_pixmap)
        drag.setHotSpot(QPoint(ghost_pixmap.width() // 2, ghost_pixmap.height() // 2))

        self.setCursor(Qt.CursorShape.OpenHandCursor)
        drag.exec(Qt.DropAction.CopyAction)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Draw tray slot backing
        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        
        # Subtle stack layers underneath to indicate a pile of stock
        for i in range(2, 0, -1):
            offset_rect = rect.translated(i * 3, i * 3)
            painter.setPen(QPen(QColor(160, 180, 200, 100), 1))
            painter.setBrush(QColor(220, 235, 248, 140))
            painter.drawRoundedRect(offset_rect, 6, 6)

        # Main front sachet
        front_rect = QRectF(4, 4, rect.width() - 8, rect.height() - 8)
        SachetGraphic.draw_sachet(
            painter, front_rect, medication_name=self.medication_name, is_elevated=False, opacity=1.0
        )
        painter.end()


class CaregiverTrayWidget(QFrame):
    """Zona 1: Meja Stok Caregiver.
    Contains the supply tray of unit-dose sachets and bulk refill test actions.
    Supports receiving unloaded sachets if caregiver drags them back from pillbox during refill.
    """

    refill_requested = Signal(int, int)  # (slot_number, delta)
    bulk_fill_all_requested = Signal(int) # (count)
    toggle_refill_requested = Signal()

    def __init__(self, scheduler: PillboxScheduler, parent: QWidget | None = None):
        super().__init__(parent)
        self.scheduler = scheduler
        self.setAcceptDrops(True)
        self.setFixedWidth(240)
        self.setStyleSheet("""
            CaregiverTrayWidget {
                background-color: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Title Header
        title_lbl = QLabel("ZONE 1: CAREGIVER")
        title_lbl.setStyleSheet("color: #06B6D4; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel("MEDICATION SUPPLY")
        sub_lbl.setStyleSheet("color: #F8FAFC; font-size: 13px; font-weight: bold;")
        layout.addWidget(sub_lbl)

        # -- REFILL MODE CONTROL PANEL --
        refill_box = QFrame()
        refill_box.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        refill_box_layout = QVBoxLayout(refill_box)
        refill_box_layout.setContentsMargins(10, 10, 10, 10)
        refill_box_layout.setSpacing(6)

        refill_box_title = QLabel("DEVICE ACCESS")
        refill_box_title.setStyleSheet("color: #94A3B8; font-size: 10px; font-weight: bold; border: none;")
        refill_box_layout.addWidget(refill_box_title)

        self._refill_status_badge = QLabel("DEVICE LOCKED")
        self._refill_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refill_status_badge.setStyleSheet("""
            background-color: #0F172A;
            color: #94A3B8;
            font-size: 10px;
            font-weight: bold;
            border-radius: 4px;
            padding: 4px;
            border: 1px solid #334155;
        """)
        refill_box_layout.addWidget(self._refill_status_badge)

        self._btn_toggle_refill = QPushButton("Unlock Device (Refill Mode)")
        self._btn_toggle_refill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_toggle_refill.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #F8FAFC;
                font-weight: bold;
                font-size: 11px;
                padding: 7px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        self._btn_toggle_refill.clicked.connect(self.toggle_refill_requested.emit)
        refill_box_layout.addWidget(self._btn_toggle_refill)

        layout.addWidget(refill_box)

        # Sachet Container Card
        card_container = QFrame()
        card_container.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px dashed #334155;
                border-radius: 10px;
            }
        """)
        card_layout = QVBoxLayout(card_container)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setContentsMargins(8, 10, 8, 10)

        self._sachet_card = DraggableSachetCard("Amlodipine 5mg", card_container)
        card_layout.addWidget(self._sachet_card)

        drag_hint = QLabel("DRAG TO COMPARTMENT")
        drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drag_hint.setStyleSheet("color: #64748B; font-size: 9px; font-weight: bold; margin-top: 4px;")
        card_layout.addWidget(drag_hint)

        layout.addWidget(card_container)

        # Quick Batch Actions
        quick_title = QLabel("Quick Actions:")
        quick_title.setStyleSheet("color: #94A3B8; font-size: 10px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(quick_title)

        btn_fill_7 = QPushButton("Fill 7 Days")
        btn_fill_7.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_fill_7.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #06B6D4;
            }
        """)
        btn_fill_7.clicked.connect(lambda: self._on_bulk_fill(7))
        layout.addWidget(btn_fill_7)

        btn_fill_30 = QPushButton("Fill 30 Days")
        btn_fill_30.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_fill_30.setStyleSheet("""
            QPushButton {
                background-color: #0F766E;
                color: white;
                border: 1px solid #14B8A6;
                border-radius: 6px;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #115E59;
            }
        """)
        btn_fill_30.clicked.connect(lambda: self._on_bulk_fill(30))
        layout.addWidget(btn_fill_30)

        btn_empty = QPushButton("Clear All")
        btn_empty.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_empty.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #94A3B8;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7F1D1D;
                color: #F87171;
            }
        """)
        btn_empty.clicked.connect(lambda: self._on_bulk_fill(0))
        layout.addWidget(btn_empty)

        layout.addStretch()


    def _on_bulk_fill(self, count: int) -> None:
        """Helper to batch set all slots."""
        if not self.scheduler.is_refill_mode:
            if hasattr(self.window(), "statusBar") and self.window().statusBar():
                self.window().statusBar().showMessage(
                    "🔒 PERANGKAT TERKUNCI: Tekan 'Unlock Device (Refill Mode)' terlebih dahulu sebelum mengisi sachet!",
                    4000,
                )
            return

        for slot_num in range(1, 9):
            self.scheduler.db.set_stock(slot_num, count)
        for c in self.scheduler.compartments.values():
            c.stock_count = count
        self.bulk_fill_all_requested.emit(count)

    def set_refill_mode(self, is_refill: bool) -> None:
        """Updates the visual refill controls in Zone 1 according to device state."""
        if is_refill:
            self._refill_status_badge.setText("REFILL MODE ACTIVE")
            self._refill_status_badge.setStyleSheet("""
                background-color: #0F172A;
                color: #06B6D4;
                font-size: 10px;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px;
                border: 1px solid #06B6D4;
            """)
            self._btn_toggle_refill.setText("Lock Device (Finish Refill)")
            self._btn_toggle_refill.setStyleSheet("""
                QPushButton {
                    background-color: #0E7490;
                    color: #FFFFFF;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 7px;
                    border-radius: 6px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #0891B2;
                }
            """)
        else:
            self._refill_status_badge.setText("DEVICE LOCKED")
            self._refill_status_badge.setStyleSheet("""
                background-color: #0F172A;
                color: #94A3B8;
                font-size: 10px;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px;
                border: 1px solid #334155;
            """)
            self._btn_toggle_refill.setText("Unlock Device (Refill Mode)")
            self._btn_toggle_refill.setStyleSheet("""
                QPushButton {
                    background-color: #334155;
                    color: #F8FAFC;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 7px;
                    border-radius: 6px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #475569;
                }
            """)

    # -- Drop handling (when sachet is unloaded back to caregiver tray) ---------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pillcare-sachet"):
            try:
                data = json.loads(bytes(event.mimeData().data("application/x-pillcare-sachet")).decode("utf-8"))
                if data.get("source_type") == "compartment" and self.scheduler.is_refill_mode:
                    event.acceptProposedAction()
                    self.setStyleSheet("""
                        CaregiverTrayWidget {
                            background-color: #0F172A;
                            border: 1px dashed #06B6D4;
                            border-radius: 14px;
                        }
                    """)
                    return
            except Exception:
                pass
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            CaregiverTrayWidget {
                background-color: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 14px;
            }
        """)

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        try:
            data = json.loads(bytes(event.mimeData().data("application/x-pillcare-sachet")).decode("utf-8"))
            slot_num = data.get("slot_number")
            if slot_num is not None and self.scheduler.is_refill_mode:
                # Caregiver unloads 1 sachet back
                self.scheduler.unload_slot(slot_num, 1)
                event.acceptProposedAction()
                return
        except Exception:
            pass
        event.ignore()

