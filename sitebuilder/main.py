import sys
from PyQt6 import QtWidgets

from MainApp import set_app_icon
from .ui.main_window import MainWindow
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Webineer.WebApp")
    except Exception:
        pass


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    set_app_icon(app, win)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
