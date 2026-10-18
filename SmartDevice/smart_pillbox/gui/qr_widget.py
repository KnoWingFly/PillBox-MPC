"""QR code of the device code, for pairing from the PillCare app.

The payload is ONLY the public device code (e.g. ``PB-1A2B3C4D``): never the device secret
or the provisioning token. The app validates the format before sending anything.
"""
from __future__ import annotations

import segno
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

QUIET_ZONE = 4  # modules of white border the QR spec requires around the symbol


def qr_matrix(payload: str) -> list[list[bool]]:
    """Module matrix (True = dark) of a standard QR code for ``payload``.

    ``make_qr`` rather than ``make``: for short data ``segno.make`` picks a Micro QR, which
    most phone scanners (including expo-camera) cannot read.
    """
    qr = segno.make_qr(payload, error="m", boost_error=False)
    return [[bool(bit) for bit in row] for row in qr.matrix]


class QrWidget(QWidget):
    """Paints a QR code with QPainter (no Pillow). Black on white regardless of the theme,
    with whole-pixel modules so the code stays crisp enough to scan off a screen."""

    clicked = Signal()

    def __init__(self, size: int, clickable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._payload: str | None = None
        self._matrix: list[list[bool]] = []
        self.setFixedSize(size, size)
        self.setStyleSheet("border: none;")
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def payload(self) -> str | None:
        return self._payload

    def set_payload(self, payload: str | None) -> None:
        if payload == self._payload:
            return
        self._payload = payload
        self._matrix = qr_matrix(payload) if payload else []
        self.setToolTip(f"QR kode perangkat {payload}. Klik untuk memperbesar." if payload else "")
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._payload and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        if not self._matrix:
            painter.setPen(QPen(QColor("#64748B"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            painter.setPen(QColor("#94A3B8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Belum\nterdaftar")
            return

        modules = len(self._matrix) + 2 * QUIET_ZONE
        scale = max(1, min(self.width(), self.height()) // modules)
        side = scale * modules
        left = (self.width() - side) // 2
        top = (self.height() - side) // 2
        painter.fillRect(QRect(left, top, side, side), QColor("white"))
        dark = QColor("black")
        for y, row in enumerate(self._matrix):
            for x, is_dark in enumerate(row):
                if is_dark:
                    painter.fillRect(
                        left + (x + QUIET_ZONE) * scale, top + (y + QUIET_ZONE) * scale, scale, scale, dark
                    )


class QrDialog(QDialog):
    """Large QR for scanning with the phone camera."""

    def __init__(self, payload: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("QR Pairing")
        layout = QVBoxLayout(self)
        qr = QrWidget(300, parent=self)
        qr.set_payload(payload)
        layout.addWidget(qr, alignment=Qt.AlignmentFlag.AlignCenter)
        code = QLabel(payload, self)
        code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code.setStyleSheet("font-size: 18px; font-weight: bold;")
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(code)
        hint = QLabel("Di aplikasi PillCare: Hubungkan Pillbox → Pindai QR", self)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
