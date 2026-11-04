from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel

from smart_pillbox import config
from smart_pillbox.gui import styles
from smart_pillbox.gui.icons import speaker_pixmap

# Status texts the window passes to update_display (shared, so both sides use the same strings).
STATUS_IDLE = "IDLE"
STATUS_DOSE = "WAKTUNYA MINUM"
STATUS_EMPTY = "STOK HABIS (REFILL)"
STATUS_MAINTENANCE = "MAINTENANCE"
REFILL_BANNER = "[ REFILL MODE - LID UNLOCKED ]"

_MODE_IDLE, _MODE_DOSE, _MODE_EMPTY, _MODE_REFILL = "idle", "dose", "empty", "refill"


def _frame_style(border: str) -> str:
    return f"""
        QFrame#LcdDisplay {{
            background-color: {styles.LCD_BG};
            border: 1px solid {border};
            border-radius: 8px;
        }}
    """


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
        self.setStyleSheet(_frame_style(styles.LCD_BORDER))
        self._mode: str | None = None  # update_display restyles only when this changes

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(4)

        # Top row: Clock, Battery, Wi-Fi
        self.top_row = QLabel("JAM: --:--:--")
        self.top_row.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.top_row.setStyleSheet(f"color: {styles.LCD_MUTED}; background: transparent; border: none;")

        # Mid row: Main Schedule Alert / Refill Banner (large & bold)
        self.mid_row = QLabel("NEXT: --:--")
        self.mid_row.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self.mid_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mid_row.setStyleSheet(f"color: {styles.LCD_TEXT}; background: transparent; border: none;")

        # Bottom row: System Status & Firmware
        self.bot_row = QLabel(f"STATUS: {STATUS_IDLE} | VER: {config.FIRMWARE_VERSION}")
        self.bot_row.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.bot_row.setStyleSheet(f"color: {styles.LCD_MUTED}; background: transparent; border: none;")

        # Sound indicator, right of the status row: shown while the buzzer rings (set_sound).
        self.sound_badge = QFrame()
        self.sound_badge.setObjectName("SoundBadge")
        self.sound_badge.setStyleSheet(f"QFrame#SoundBadge {{ background: {styles.SOUND_BADGE_BG}; border: none; border-radius: 4px; }}")
        badge_layout = QHBoxLayout(self.sound_badge)
        badge_layout.setContentsMargins(6, 1, 7, 1)
        badge_layout.setSpacing(4)
        sound_icon = QLabel()
        sound_icon.setPixmap(speaker_pixmap(14, styles.SOUND_BADGE_TEXT))
        sound_icon.setStyleSheet("background: transparent; border: none;")
        self.sound_text = QLabel()
        self.sound_text.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.sound_text.setStyleSheet(f"color: {styles.SOUND_BADGE_TEXT}; background: transparent; border: none;")
        badge_layout.addWidget(sound_icon)
        badge_layout.addWidget(self.sound_text)
        self.sound_badge.hide()
        # Right end of the status row: the clock row above has no room to spare.
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.bot_row)
        bottom.addStretch()
        bottom.addWidget(self.sound_badge)

        layout.addWidget(self.top_row)
        layout.addStretch()
        layout.addWidget(self.mid_row)
        layout.addStretch()
        layout.addLayout(bottom)

    def update_display(
        self,
        time_str: str,
        next_dose: str,
        status: str,
        battery: int,
        wifi_on: bool,
        is_refill_mode: bool = False,
        tz_label: str = "",
    ):
        """Called every tick: texts are set each time, styles only when the display mode changes
        (setStyleSheet re-polishes the widget, too costly once a second)."""
        wifi_str = "ON" if wifi_on else "OFF"
        self.top_row.setText(f"JAM: {time_str} {tz_label} | BATT: {battery}% | WIFI: {wifi_str}")

        if is_refill_mode:
            mode, mid_text, bot_text = _MODE_REFILL, REFILL_BANNER, f"STATUS: {STATUS_MAINTENANCE}"
        elif status in (STATUS_DOSE, STATUS_EMPTY):
            mode = _MODE_EMPTY if status == STATUS_EMPTY else _MODE_DOSE
            mid_text, bot_text = next_dose, f"STATUS: {status}"
        else:
            mode, mid_text, bot_text = _MODE_IDLE, next_dose, f"STATUS: {status} | VER: {config.FIRMWARE_VERSION}"
        self.mid_row.setText(mid_text)
        self.bot_row.setText(bot_text)
        if mode != self._mode:
            self._mode = mode
            self._apply_mode_style(mode)

    def _apply_mode_style(self, mode: str) -> None:
        mid_color, bot_color, border = {
            _MODE_REFILL: (styles.LCD_TEXT, styles.LCD_MUTED, styles.LCD_REFILL_BORDER),
            _MODE_DOSE: (styles.LCD_CYAN, styles.LCD_CYAN, styles.LCD_BORDER),
            _MODE_EMPTY: (styles.LCD_ALERT, styles.LCD_ALERT, styles.LCD_BORDER),
            _MODE_IDLE: (styles.LCD_TEXT, styles.LCD_MUTED, styles.LCD_BORDER),
        }[mode]
        self.mid_row.setStyleSheet(f"color: {mid_color}; font-weight: bold; background: transparent; border: none;")
        self.bot_row.setStyleSheet(f"color: {bot_color}; font-weight: bold; background: transparent; border: none;")
        self.setStyleSheet(_frame_style(border))

    def set_sound(self, text: str | None) -> None:
        """Shows the speaker icon and `text` while the buzzer rings; None hides it."""
        if text is None:
            self.sound_badge.hide()
        else:
            self.sound_text.setText(text)
            self.sound_badge.show()  # no-op while already shown
