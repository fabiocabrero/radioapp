import sys

from ic7300 import extapps


def test_catalog_is_consistent():
    keys = [a.key for a in extapps.APPS]
    assert len(keys) == len(set(keys))
    assert {"winlink_express", "vara_hf", "varac", "pat", "ardopcf", "wsjtx", "js8call", "fldigi"} <= set(keys)
    assert all(a.group in extapps.GROUPS and a.exe and a.url.startswith("http") for a in extapps.APPS)
    assert "8300" in " ".join(extapps.by_key("vara_hf").tips) and "VARA" in extapps.by_key("varac").tips[0]
    # só programas que usam o rigctl pedem para ativá-lo
    assert extapps.by_key("wsjtx").needs_rigctl and not extapps.by_key("vara_hf").needs_rigctl


def test_find_prefers_custom_path_then_globs_then_path(tmp_path, monkeypatch):
    app = extapps.by_key("varac")
    assert extapps.find(app, "") is None or extapps.find(app, "").name.lower() == "varac.exe"
    fake = tmp_path / "VarAC" / "VarAC.exe"
    fake.parent.mkdir()
    fake.write_text("x")
    assert extapps.find(app, str(fake)) == fake                      # caminho escolhido pelo usuário
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(extapps, "shutil", type("S", (), {"which": staticmethod(lambda n: None)}))
    assert extapps.find(app, "") == tmp_path / "VarAC" / "VarAC.exe"  # padrão %LOCALAPPDATA%/VarAC/VarAC.exe
    assert extapps.find(app, str(tmp_path / "nao-existe.exe")) == tmp_path / "VarAC" / "VarAC.exe"  # custom inválido é ignorado


def test_find_uses_path_variable(tmp_path, monkeypatch):
    exe = tmp_path / "pat.exe"
    exe.write_text("x")
    app = extapps.by_key("pat")
    monkeypatch.setattr(extapps, "glob", type("G", (), {"glob": staticmethod(lambda p: [])}))
    monkeypatch.setattr(extapps.shutil, "which", lambda n: str(exe) if n == "pat.exe" else None)
    assert extapps.find(app) == exe


def test_launch_runs_detached_in_the_programs_folder(tmp_path, monkeypatch):
    calls = {}

    class P:
        pid = 4321

    def fake_popen(args, **kw):
        calls["args"], calls["kw"] = args, kw
        return P()

    monkeypatch.setattr(extapps.subprocess, "Popen", fake_popen)
    exe = tmp_path / "app.exe"
    exe.write_text("x")
    assert extapps.launch(exe) == 4321
    assert calls["args"] == [str(exe)] and calls["kw"]["cwd"] == str(tmp_path)
    if sys.platform == "win32":
        assert calls["kw"]["creationflags"] & extapps.subprocess.DETACHED_PROCESS
