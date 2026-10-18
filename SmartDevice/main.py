import argparse
import os
import sys

# Qt's Wayland text-input plugin logs "QWaylandTextInputv3::disableSurface ... but 0x0 is focused" on
# focus changes (a harmless Qt bug); hide just that category, keep any rules the user set.
os.environ["QT_LOGGING_RULES"] = ";".join(
    filter(None, [os.environ.get("QT_LOGGING_RULES"), "qt.qpa.wayland.textinput=false"])
)

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from smart_pillbox import config
from smart_pillbox.utils.logging_config import configure_logging


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="PillCare smart pillbox simulator")
    parser.add_argument(
        "--profile",
        default=config.DEFAULT_PROFILE,
        help="Virtual pillbox to run (own identity and database), e.g. pb2. Default: %(default)s",
    )
    # Unknown arguments (e.g. Qt's -platform) are passed on to QApplication.
    args, rest = parser.parse_known_args(argv[1:])
    return args, [argv[0], *rest]


def main() -> None:
    args, qt_argv = parse_args(sys.argv)
    try:
        config.use_profile(args.profile)
    except ValueError as exc:
        sys.exit(str(exc))
    configure_logging()
    app = QApplication(qt_argv)

    # One process per profile: two windows on the same database would share one identity and
    # keep replacing each other's WebSocket on the server.
    lock = QLockFile(str(config.lock_path(config.PROFILE)))
    lock.setStaleLockTime(0)  # never stale by age; a crashed holder is still detected by its PID
    if not lock.tryLock(0):
        QMessageBox.warning(
            None,
            "Pillbox sudah berjalan",
            f"Pillbox virtual '{config.PROFILE}' sudah terbuka di jendela lain.",
        )
        sys.exit(1)

    # Imported after use_profile(): nothing may open the database before the profile is set.
    from smart_pillbox.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
