import logging
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

def play_chime():
    """Play a soft chime using QApplication beep to avoid blocking and OS-dependency."""
    logger.info("Chime sounded (Audio beep triggered)")
    app = QApplication.instance()
    if app:
        app.beep()
