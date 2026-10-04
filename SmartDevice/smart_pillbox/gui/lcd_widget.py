from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

from smart_pillbox.gui import styles


class LcdDisplay(QFrame):
    """Clean Centered Ultra-Dark OLED module for Smart Pillbox chassis.
    Uses high-contrast white/slate typography without emojis.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(105)
        self.setMinimumWidth(380)
        self.setMaximumWidth(460)
        self.setObjectName("LcdDisplay")
        self.setStyleSheet(f"""
            QFrame#LcdDisplay {{
                background-color: {styles.LCD_BG};
                border: 1px solid {styles.LCD_BORDER};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(4)

        # Top row: Clock, Battery, Wi-Fi
        self.top_row = QLabel("JAM: --:--:-- WIB | BATT: 100% | WIFI: ON")
        self.top_row.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.top_row.setStyleSheet(f"color: {styles.LCD_MUTED}; background: transparent; border: none;")

        # Mid row: Main Schedule Alert / Refill Banner (large & bold)
        self.mid_row = QLabel("NEXT: --:-- WIB")
        self.mid_row.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self.mid_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mid_row.setStyleSheet(f"color: {styles.LCD_TEXT}; background: transparent; border: none;")

        # Bottom row: System Status & Firmware
        self.bot_row = QLabel("STATUS: IDLE | VER: v1")
        self.bot_row.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.bot_row.setStyleSheet(f"color: {styles.LCD_MUTED}; background: transparent; border: none;")

        layout.addWidget(self.top_row)
        layout.addStretch()
        layout.addWidget(self.mid_row)
        layout.addStretch()
        layout.addWidget(self.bot_row)

    def update_display(
        self,
        time_str: str,
        next_dose: str,
        status: str,
        battery: int,
        wifi_on: bool,
        is_refill_mode: bool = False,
    ):
        wifi_str = "ON" if wifi_on else "OFF"
        self.top_row.setText(f"JAM: {time_str} WIB | BATT: {battery}% | WIFI: {wifi_str}")

        if is_refill_mode:
            self.mid_row.setText("[ REFILL MODE - LID UNLOCKED ]")
            self.mid_row.setStyleSheet("color: #E2E8F0; font-weight: bold; background: transparent; border: none;")
            self.bot_row.setText("STATUS: MAINTENANCE")
            self.bot_row.setStyleSheet("color: #94A3B8; font-weight: bold; background: transparent; border: none;")
            self.setStyleSheet(f"""
                QFrame#LcdDisplay {{
                    background-color: {styles.LCD_BG};
                    border: 1px solid #475569;
                    border-radius: 8px;
                }}
            """)
        else:
            if status in ("DOSE READY", "WAKTUNYA MINUM", "STOK HABIS (REFILL)"):
                self.mid_row.setText(next_dose)
                alert_color = "#F87171" if "STOK HABIS" in status else styles.LCD_CYAN
                self.mid_row.setStyleSheet(f"color: {alert_color}; font-weight: bold; background: transparent; border: none;")
                self.bot_row.setText(f"STATUS: {status}")
                self.bot_row.setStyleSheet(f"color: {alert_color}; font-weight: bold; background: transparent; border: none;")
            else:
                self.mid_row.setText(next_dose)
                self.mid_row.setStyleSheet(f"color: {styles.LCD_TEXT}; font-weight: bold; background: transparent; border: none;")
                self.bot_row.setText(f"STATUS: {status} | VER: v1")
                self.bot_row.setStyleSheet(f"color: {styles.LCD_MUTED}; font-weight: bold; background: transparent; border: none;")

            self.setStyleSheet(f"""
                QFrame#LcdDisplay {{
                    background-color: {styles.LCD_BG};
                    border: 1px solid {styles.LCD_BORDER};
                    border-radius: 8px;
                }}
            """)
