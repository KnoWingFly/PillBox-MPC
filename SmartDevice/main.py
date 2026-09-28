import sys

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
