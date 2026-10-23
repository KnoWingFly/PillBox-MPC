from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont, QPixmap
)


class SachetGraphic:
    """Procedural vector renderer for realistic unit-dose medication sachets,
    translucent ghost dragging pixmaps, and adaptive chamber stack visualization.
    """

    @staticmethod
    def draw_sachet(
        painter: QPainter,
        rect: QRectF,
        medication_name: str = "Amlodipine 5mg",
        is_elevated: bool = False,
        opacity: float = 1.0,
    ) -> None:
        """Draws a realistic unit-dose blister/pouch with heat-seal grooves and medication print."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(opacity)

        # Drop shadow if elevated/dragged
        if is_elevated:
            shadow_rect = rect.translated(0, 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 70))
            painter.drawRoundedRect(shadow_rect, 6, 6)

        # 1. Pouch translucent body gradient
        body_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        body_grad.setColorAt(0.0, QColor(245, 250, 255, 230))
        body_grad.setColorAt(0.5, QColor(225, 238, 250, 210))
        body_grad.setColorAt(1.0, QColor(210, 225, 240, 220))

        painter.setPen(QPen(QColor(160, 185, 210, 220), 1.2))
        painter.setBrush(body_grad)
        painter.drawRoundedRect(rect, 5, 5)

        # 2. Top and bottom crimped heat-seal bands
        seal_height = max(7.0, rect.height() * 0.12)
        top_seal = QRectF(rect.x() + 1, rect.y() + 1, rect.width() - 2, seal_height)
        bottom_seal = QRectF(rect.x() + 1, rect.bottom() - seal_height - 1, rect.width() - 2, seal_height)

        seal_brush = QBrush(QColor(190, 210, 230, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(seal_brush)
        painter.drawRoundedRect(top_seal, 3, 3)
        painter.drawRoundedRect(bottom_seal, 3, 3)

        # Crimped ridges texture
        painter.setPen(QPen(QColor(150, 175, 200, 140), 1.0))
        step = 5.0
        cur_x = top_seal.left() + 4
        while cur_x < top_seal.right() - 2:
            painter.drawLine(QPointF(cur_x, top_seal.top() + 1), QPointF(cur_x, top_seal.bottom() - 1))
            painter.drawLine(QPointF(cur_x, bottom_seal.top() + 1), QPointF(cur_x, bottom_seal.bottom() - 1))
            cur_x += step

        # 3. Medical accent bar (teal/cyan pharmacy color)
        accent_rect = QRectF(rect.x() + 6, rect.y() + seal_height + 4, rect.width() - 12, 5)
        painter.setBrush(QColor(0, 168, 150))
        painter.drawRoundedRect(accent_rect, 2, 2)

        # 4. Visible tablet/pill silhouette inside the pocket
        center_y = rect.y() + rect.height() * 0.52
        pill_rect = QRectF(rect.center().x() - 11, center_y - 6, 22, 12)
        
        # Pill shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(140, 160, 180, 80))
        painter.drawRoundedRect(pill_rect.translated(1, 1), 6, 6)

        # Pill body (white scored caplet)
        painter.setPen(QPen(QColor(200, 210, 220), 0.8))
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.drawRoundedRect(pill_rect, 6, 6)
        
        # Score line in pill
        painter.setPen(QPen(QColor(190, 200, 210), 0.8))
        painter.drawLine(
            QPointF(pill_rect.center().x(), pill_rect.top() + 2),
            QPointF(pill_rect.center().x(), pill_rect.bottom() - 2)
        )

        # 5. Medication label typography
        font = QFont("Arial", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(30, 45, 60))
        text_rect = QRectF(rect.x() + 4, rect.bottom() - seal_height - 18, rect.width() - 8, 14)
        display_name = medication_name if medication_name else "Amlodipine 5mg"
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, display_name)

        painter.restore()

    @staticmethod
    def create_drag_pixmap(
        width: int = 110,
        height: int = 140,
        medication_name: str = "Amlodipine 5mg",
        opacity: float = 0.75,
    ) -> QPixmap:
        """Renders an anti-aliased semi-transparent sachet pixmap for Qt Drag cursor."""
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(5, 5, width - 10, height - 10)
        SachetGraphic.draw_sachet(
            painter, rect, medication_name=medication_name, is_elevated=True, opacity=opacity
        )
        painter.end()
        return pixmap

    @staticmethod
    def draw_adaptive_stack(
        painter: QPainter,
        target_rect: QRectF,
        stock_count: int,
        is_active: bool = False,
        medication_name: str = "Amlodipine 5mg",
    ) -> None:
        """Draws the recessed chamber floor with adaptive layered sachets.
        - stock == 0: Empty recess
        - 1 <= stock <= 6: Layered physical sheets (2px vertical shift each)
        - stock >= 7: Visually capped full stack with badge counter [x14 / x30]
        - is_active: Top sachet pops up and elevates out of the chamber
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 1. Background chamber recess
        recess_brush = QLinearGradient(target_rect.topLeft(), target_rect.bottomLeft())
        recess_brush.setColorAt(0.0, QColor(25, 30, 38))
        recess_brush.setColorAt(1.0, QColor(15, 18, 24))
        painter.setPen(QPen(QColor(50, 60, 75), 1.0))
        painter.setBrush(recess_brush)
        painter.drawRoundedRect(target_rect, 8, 8)

        if stock_count <= 0:
            # Empty recess slot state
            painter.setPen(QPen(QColor(80, 95, 115, 100), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inner_box = target_rect.adjusted(8, 8, -8, -8)
            painter.drawRoundedRect(inner_box, 6, 6)

            font = QFont("Arial", 8)
            painter.setFont(font)
            painter.setPen(QColor(90, 105, 125, 180))
            painter.drawText(target_rect, Qt.AlignmentFlag.AlignCenter, "EMPTY\n(Refill)")
            painter.restore()
            return

        # Dimensions of each sachet inside the slot
        sachet_w = target_rect.width() - 18
        sachet_h = target_rect.height() - 24
        base_x = target_rect.x() + 9
        base_y = target_rect.bottom() - sachet_h - 8

        # Determine visible layers (clamped between 1 and 6 to avoid visual overflow)
        visible_layers = min(6, stock_count)
        shift_per_layer = 2.5

        # Draw stacked background layers
        for layer_idx in range(visible_layers - 1):
            offset_y = layer_idx * shift_per_layer
            layer_rect = QRectF(base_x, base_y - offset_y, sachet_w, sachet_h)
            
            # Subdued lower layers
            painter.setPen(QPen(QColor(120, 140, 160, 120), 0.8))
            painter.setBrush(QColor(180, 200, 220, 140))
            painter.drawRoundedRect(layer_rect, 4, 4)

        # Top sachet calculation
        top_offset_y = (visible_layers - 1) * shift_per_layer
        top_rect = QRectF(base_x, base_y - top_offset_y, sachet_w, sachet_h)

        if is_active:
            # Pop-Up effect: Elevated upward by 16px
            top_rect = top_rect.translated(0, -16)
            
            # Glowing Cyan halo around active protruding sachet
            glow_rect = top_rect.adjusted(-3, -3, 3, 3)
            painter.setPen(QPen(QColor(6, 182, 212, 220), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(glow_rect, 7, 7)


        # Draw the top detailed sachet
        SachetGraphic.draw_sachet(
            painter,
            top_rect,
            medication_name=medication_name,
            is_elevated=is_active,
            opacity=1.0,
        )

        # 3. Numeric Badge for Stock Indicator (e.g. x7, x14, x30)
        badge_text = f"x{stock_count}"
        badge_w = 34.0 if stock_count >= 10 else 26.0
        badge_rect = QRectF(target_rect.right() - badge_w - 6, target_rect.top() + 6, badge_w, 16.0)

        badge_bg = QColor(10, 20, 30, 220) if stock_count < 7 else QColor(39, 174, 96, 230)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 0.8))
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge_rect, 8, 8)

        badge_font = QFont("Arial", 8, QFont.Weight.Bold)
        painter.setFont(badge_font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        painter.restore()
