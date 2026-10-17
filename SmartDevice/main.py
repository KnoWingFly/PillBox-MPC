import os
import sys

# Qt's Wayland text-input plugin logs "QWaylandTextInputv3::disableSurface ... but 0x0 is focused" on
# focus changes (a harmless Qt bug); hide just that category, keep any rules the user set.
os.environ["QT_LOGGING_RULES"] = ";".join(
    filter(None, [os.environ.get("QT_LOGGING_RULES"), "qt.qpa.wayland.textinput=false"])
)

from PySide6.QtWidgets import QApplication

from smart_pillbox.gui.main_window import MainWindow
from smart_pillbox.utils.logging_config import configure_logging


def main() -> None:
    configure_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
