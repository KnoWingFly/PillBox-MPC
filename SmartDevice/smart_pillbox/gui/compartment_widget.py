from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame,
    QGraphicsOpacityEffect, QGraphicsDropShadowEffect
)

from smart_pillbox.gui import styles
from smart_pillbox.models import ChamberState, Compartment
from smart_pillbox.core.audio import play_chime


class CompartmentWidget(QWidget):
    """One of the 8 physical compartments. Rendered as a realistic hardware lid
    with a single intuitive smart action button. Features a simulated physical lid 
    that slides open to reveal a recessed pill chamber."""

    interacted = Signal(int)  # emits compartment_id

    def __init__(self, compartment: Compartment, parent: QWidget | None = None):
        super().__init__(parent)
        self.compartment_id = compartment.id

        self.setFixedSize(150, 200)

        # 1. Recessed Chamber (Background)
        self._chamber_bg = QFrame(self)
        self._chamber_bg.setGeometry(10, 10, 130, 120)
        self._chamber_bg.setStyleSheet(f"""
            QFrame {{
                background-color: #D5DBDB;
                border: 2px solid #BDC3C7;
                border-radius: 12px;
            }}
        """)
        
        # Pill Indicator inside chamber
        self._pill_indicator = QFrame(self._chamber_bg)
        self._pill_indicator.setGeometry(45, 40, 40, 40)
        self._pill_indicator.setStyleSheet(f"""
            QFrame {{
                background-color: {styles.IDLE_COLOR};
                border-radius: 20px;
            }}
        """)

        # 2. The Lid (Physical Panel)
        self._lid_frame = QFrame(self)
        self._lid_frame.setGeometry(10, 10, 130, 120)
        
        # Shadow effect to simulate popup elevation
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(10)
        self._shadow.setColor(QColor(0, 0, 0, 60))
        self._shadow.setOffset(0, 2)
        self._lid_frame.setGraphicsEffect(self._shadow)

        # Breathing LED Ring inside the lid
        self._led = QFrame(self._lid_frame)
        self._led.setGeometry(10, 10, 110, 6)
        
        self._opacity_effect = QGraphicsOpacityEffect(self._led)
        self._led.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(1.0)
        
        self._breathing_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._breathing_anim.setDuration(900)
        self._breathing_anim.setStartValue(1.0)
        self._breathing_anim.setEndValue(0.2)
        self._breathing_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breathing_anim.setLoopCount(-1)

        # Lid Animation
        self._lid_anim = QPropertyAnimation(self._lid_frame, b"geometry", self)
        self._lid_anim.setDuration(350)
        self._lid_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Labels on the Lid
        self._title_label = QLabel(compartment.label, self._lid_frame)
        self._title_label.setGeometry(5, 25, 120, 20)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("font-family: 'Segoe UI'; font-weight: bold; color: #333; font-size: 11px;")

        self._status_label = QLabel("TERTUTUP", self._lid_frame)
        self._status_label.setGeometry(5, 48, 120, 20)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(f"font-family: 'Segoe UI'; color: {styles.TEXT_DARK}; font-size: 10px; font-weight: 600;")

        # Single Smart Action Button
        self._smart_btn = QPushButton(self)
        self._smart_btn.setGeometry(15, 140, 120, 45)
        self._smart_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._smart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._smart_btn.clicked.connect(lambda: self.interacted.emit(self.compartment_id))

        self.refresh(compartment)

    def refresh(self, compartment: Compartment, test_mode: bool = False) -> None:
        """Re-render from the authoritative Compartment state."""
        color, status_text, breathing, elevated = self._visuals_for(compartment)
        
        # Lid Styling (Elevated when active or open)
        if elevated:
            self._shadow.setOffset(0, 6)
            self._shadow.setBlurRadius(15)
            self._lid_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {styles.ABS_WHITE};
                    border: 2px solid {color};
                    border-radius: 12px;
                }}
            """)
        else:
            self._shadow.setOffset(0, 1)
            self._shadow.setBlurRadius(5)
            self._lid_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {styles.ABS_DARK};
                    border: 1px solid #B0B0B0;
                    border-radius: 12px;
                }}
            """)

        self._led.setStyleSheet(f"background-color: {color}; border-radius: 3px;")
        self._status_label.setText(status_text.upper())
        self._status_label.setStyleSheet(f"font-family: 'Segoe UI'; color: {color}; font-size: 10px; font-weight: bold;")
        
        # Update pill indicator inside chamber
        self._pill_indicator.setStyleSheet(f"background-color: {color}; border-radius: 20px;")
        
        # Handle Lid animation based on door_open
        target_geometry = QRect(10, -90, 130, 120) if compartment.door_open else QRect(10, 10, 130, 120)
        if self._lid_frame.geometry() != target_geometry:
            self._lid_anim.setEndValue(target_geometry)
            self._lid_anim.start()

        # Configure Single Smart Button dynamically
        if compartment.door_open:
            self._smart_btn.setEnabled(True)
            self._smart_btn.setText("TUTUP LID")
            self._smart_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F39C12;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #D68910;
                }
            """)
        elif compartment.state == ChamberState.ACTIVE:
            self._smart_btn.setEnabled(True)
            btn_text = "BUKA LID" if test_mode else "AMBIL OBAT"
            self._smart_btn.setText(btn_text)
            self._smart_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {color}DD;
                }}
            """)
        elif compartment.state == ChamberState.TAKEN:
            self._smart_btn.setEnabled(False)
            self._smart_btn.setText("DIMINUM")
            self._smart_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E8F8F5;
                    color: #1ABC9C;
                    border: 1px solid #A3E4D7;
                    border-radius: 6px;
                    font-weight: bold;
                }
            """)
        elif compartment.state == ChamberState.MISSED:
            self._smart_btn.setEnabled(False)
            self._smart_btn.setText("TERLEWAT")
            self._smart_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FDEDEC;
                    color: #E74C3C;
                    border: 1px solid #FADBD8;
                    border-radius: 6px;
                    font-weight: bold;
                }
            """)
        else: # IDLE
            if test_mode:
                self._smart_btn.setEnabled(True)
                self._smart_btn.setText("UJI BUKA")
                self._smart_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #EAECEE;
                        color: #566573;
                        border: 1px solid #D5DBDB;
                        border-radius: 6px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #D5DBDB;
                    }
                """)
            else:
                self._smart_btn.setEnabled(False)
                self._smart_btn.setText(f"{compartment.schedule_time}")
                self._smart_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #F8F9F9;
                        color: #ABB2B9;
                        border: 1px solid #E5E8E8;
                        border-radius: 6px;
                        font-weight: bold;
                    }
                """)

        # Audio chime logic
        if compartment.state == ChamberState.ACTIVE:
            play_chime()

        if breathing and self._breathing_anim.state() != QPropertyAnimation.State.Running:
            self._breathing_anim.start()
        elif not breathing:
            self._breathing_anim.stop()
            self._opacity_effect.setOpacity(1.0)

    @staticmethod
    def _visuals_for(compartment: Compartment) -> tuple[str, str, bool, bool]:
        # returns: (led_color, status_text, is_breathing, is_elevated)
        if compartment.door_open:
            return styles.ACTIVE_BEFORE_MEAL_COLOR, "LID TERBUKA", False, True

        if compartment.state == ChamberState.ACTIVE:
            color = (
                styles.ACTIVE_BEFORE_MEAL_COLOR
                if compartment.meal_relation == "sebelum_makan"
                else styles.ACTIVE_AFTER_MEAL_COLOR
            )
            return color, "WAKTUNYA MINUM", True, True
            
        if compartment.state == ChamberState.TAKEN:
            return styles.TAKEN_COLOR, "SUDAH DIMINUM", False, False
            
        if compartment.state == ChamberState.MISSED:
            return styles.MISSED_COLOR, "TERLEWAT", False, False
            
        return styles.IDLE_COLOR, f"DUE: {compartment.schedule_time}", False, False
