"""Small vector icons drawn with QPainter, so they look the same on every OS (no emoji font)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap


def speaker_pixmap(size: int, color: str, device_pixel_ratio: float = 2.0) -> QPixmap:
    """A speaker with two sound waves, `size` logical pixels square."""
    pixmap = QPixmap(round(size * device_pixel_ratio), round(size * device_pixel_ratio))
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    s = size / 24.0  # drawn on a 24x24 grid
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ink = QColor(color)

    # Speaker body: a small box with a cone opening to the right.
    body = QPainterPath()
    body.moveTo(3 * s, 9 * s)
    body.lineTo(7 * s, 9 * s)
    body.lineTo(12 * s, 4.5 * s)
    body.lineTo(12 * s, 19.5 * s)
    body.lineTo(7 * s, 15 * s)
    body.lineTo(3 * s, 15 * s)
    body.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    painter.drawPath(body)

    # Two sound waves (arcs centred on the cone's mouth).
    pen = QPen(ink, 1.9 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    centre = QPointF(12 * s, 12 * s)
    for radius in (4.0 * s, 7.5 * s):
        rect = QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)
        painter.drawArc(rect, -50 * 16, 100 * 16)  # Qt angles are 1/16 degree
    painter.end()
    return pixmap
