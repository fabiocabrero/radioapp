import sys
import time

from PySide6 import QtCore, QtWidgets

from . import applog
from .ui.main_window import MainWindow


def selftest(app: QtWidgets.QApplication, out: str) -> int:
    """Abre a janela com o simulador, percorre todas as telas e grava OK/erro em `out` (usado para testar o instalador)."""
    errors: list[str] = []
    sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")
    win = MainWindow()
    win.show()
    win.btn_connect.click()

    def pump(sec: float) -> None:
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    pump(1.0)
    connected = win.radio is not None
    for key in list(win.pages):
        win.show_page(key)
        pump(0.1)
    win.close()
    pump(0.2)
    result = "OK" if connected and not errors else "ERRO: " + "; ".join(errors or ["simulador não conectou"])
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f"{result} paginas={len(win.pages)}\n")
    return 0 if result == "OK" else 1


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    if "--selftest" in sys.argv:
        return selftest(app, sys.argv[sys.argv.index("--selftest") + 1])
    applog.setup()
    win = MainWindow()
    win.show()
    QtCore.QTimer.singleShot(800, win.maybe_first_run)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
