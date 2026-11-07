import logging
import sys

from ic7300 import applog


def test_log_grava_e_le(tmp_path, monkeypatch):
    monkeypatch.setenv("IC7300_APPDATA", str(tmp_path))
    for h in list(applog.log.handlers):
        applog.log.removeHandler(h)
    old = sys.excepthook
    try:
        path = applog.setup()
        applog.log.info("mensagem de teste")
        try:
            raise ValueError("falha simulada")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        for h in applog.log.handlers:
            h.flush()
        text = applog.tail()
        assert path.exists() and "mensagem de teste" in text and "falha simulada" in text
        assert "IC-7300 Station" in text
    finally:
        sys.excepthook = old
        for h in list(applog.log.handlers):
            h.close()
            applog.log.removeHandler(h)
        logging.getLogger("ic7300").setLevel(logging.NOTSET)
