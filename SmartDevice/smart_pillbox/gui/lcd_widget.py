from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from smart_pillbox.gui import styles

class LcdDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        self.setMinimumWidth(300)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {styles.LCD_BG};
                border: 4px solid #111;
                border-radius: 8px;
            }}
            QLabel {{
                color: {styles.LCD_TEXT};
                background-color: transparent;
                border: none;
                font-family: monospace;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.top_row = QLabel("JAM: --:--:-- WIB | BATT: 100% | WI-FI: ON")
        self.top_row.setFont(QFont("Courier", 11, QFont.Weight.Bold))
        
        self.mid_row = QLabel("NEXT: --:-- WIB")
        self.mid_row.setFont(QFont("Courier", 14, QFont.Weight.Bold))
        self.mid_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.bot_row = QLabel("STATUS: IDLE | VER: v1")
        self.bot_row.setFont(QFont("Courier", 10))
        
        layout.addWidget(self.top_row)
        layout.addStretch()
        layout.addWidget(self.mid_row)
        layout.addStretch()
        layout.addWidget(self.bot_row)

    def update_display(self, time_str: str, next_dose: str, status: str, battery: int, wifi_on: bool):
        wifi_str = "ON" if wifi_on else "OFF"
        self.top_row.setText(f"JAM: {time_str} WIB | BATT: {battery}% | WI-FI: {wifi_str}")
        self.mid_row.setText(f"NEXT: {next_dose}")
        self.bot_row.setText(f"STATUS: {status} | VER: v1")
