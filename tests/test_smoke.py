import ast
import importlib.util
import sys
import py_compile
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = [ROOT / "main.py", ROOT / "teams-transcriber.py"]


def load_module_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scripts_compile():
    for script in SCRIPTS:
        py_compile.compile(str(script), doraise=True)


def test_scripts_parse():
    for script in SCRIPTS:
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script))


def test_transcriber_cli_has_expected_modes():
    source = (ROOT / "teams-transcriber.py").read_text(encoding="utf-8")
    assert 'sub.add_parser("live"' in source
    assert 'sub.add_parser("file"' in source
    assert 'sub.add_parser("summarize"' in source


def test_transcriber_cli_shows_usage_when_no_mode(monkeypatch, capsys):
    module = load_module_from_path("teams_transcriber", ROOT / "teams-transcriber.py")

    monkeypatch.setattr(sys, "argv", ["TeamsTranscriber.exe"])

    result = module.main()

    captured = capsys.readouterr()
    assert result == 0
    assert "usage:" in captured.out.lower()
    assert "live" in captured.out.lower()


def test_toggle_transcriber_starts_live_mode(monkeypatch, tmp_path):
    import main

    fake_exe = tmp_path / "TeamsTranscriber.exe"
    fake_exe.write_bytes(b"stub")

    obj = object.__new__(main.FloatNotes)
    obj._transcriber_proc = None
    obj._mic_btn = type("Widget", (), {"configure": lambda self, **kwargs: None})()
    obj._set_ai_status = lambda msg: None
    obj.after = lambda *args, **kwargs: None

    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "FloatNotes.exe"))
    monkeypatch.setattr(main.os, "startfile", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should use subprocess for live mode")))
    calls = {}

    def fake_popen(args, cwd=None, creationflags=0):
        calls["args"] = args
        calls["cwd"] = cwd
        calls["creationflags"] = creationflags
        return type("Proc", (), {"poll": lambda self: 0})()

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)

    main.FloatNotes._toggle_transcriber(obj)

    assert calls["args"] == [str(fake_exe), "live"]
    assert calls["cwd"] == str(tmp_path)


def test_transcriber_list_devices_is_ascii_safe_for_cp1252(monkeypatch):
    module = load_module_from_path("teams_transcriber", ROOT / "teams-transcriber.py")

    class CaptureOutput:
        encoding = "cp1252"

        def __init__(self):
            self.output = ""

        def write(self, text):
            text.encode(self.encoding)
            self.output += text
            return len(text)

        def flush(self):
            pass

    class FakePyAudio:
        def PyAudio(self):
            class Handle:
                def get_device_count(self):
                    return 2

                def get_device_info_by_index(self, i):
                    return {"name": ["Mic", "Loopback"][i], "maxInputChannels": 1, "isLoopbackDevice": i == 1}

                def terminate(self):
                    pass

            return Handle()

    monkeypatch.setattr(module.sys, "stdout", CaptureOutput())
    monkeypatch.setattr(module, "_get_pyaudio", lambda: FakePyAudio())

    module.list_devices()


def test_toggle_transcriber_is_single_instance(monkeypatch, tmp_path):
    import main

    fake_exe = tmp_path / "TeamsTranscriber.exe"
    fake_exe.write_bytes(b"stub")

    obj = object.__new__(main.FloatNotes)
    obj._transcriber_proc = None
    obj._mic_btn = type("Widget", (), {"configure": lambda self, **kwargs: None})()
    obj._set_ai_status = lambda msg: None
    obj.after = lambda *args, **kwargs: None

    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "FloatNotes.exe"))
    started = []

    def fake_popen(args, cwd=None, creationflags=0):
        started.append((args, cwd, creationflags))
        return type("Proc", (), {"poll": lambda self: None, "terminate": lambda self: None, "wait": lambda self, timeout=None: None})()

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)

    main.FloatNotes._toggle_transcriber(obj)
    main.FloatNotes._toggle_transcriber(obj)

    assert len(started) == 1


def test_transcriber_uses_fast_default_live_settings():
    module = load_module_from_path("teams_transcriber", ROOT / "teams-transcriber.py")
    src = (ROOT / "teams-transcriber.py").read_text(encoding="utf-8")
    assert 'default=10' in src
    assert 'default="medium"' in src
    assert 'lp.add_argument("--model"' in src


def test_toggle_water_bro_starts_companion_app(monkeypatch, tmp_path):
    import main

    fake_exe = tmp_path / "WaterPal.exe"
    fake_exe.write_bytes(b"stub")

    obj = object.__new__(main.FloatNotes)
    obj._water_proc = None
    obj._water_btn = type("Widget", (), {"configure": lambda self, **kwargs: None})()
    obj._set_ai_status = lambda msg: None
    obj.after = lambda *args, **kwargs: None

    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "FloatNotes.exe"))
    calls = {}

    def fake_popen(args, cwd=None, creationflags=0):
        calls["args"] = args
        calls["cwd"] = cwd
        calls["creationflags"] = creationflags
        return type("Proc", (), {"poll": lambda self: 0})()

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)

    main.FloatNotes._toggle_water_bro(obj)

    assert calls["args"] == [str(fake_exe)]
    assert calls["cwd"] == str(tmp_path)


def test_live_model_policy_prefers_medium_then_falls_back_to_base():
    module = load_module_from_path("teams_transcriber", ROOT / "teams-transcriber.py")
    assert hasattr(module, "_should_switch_model")
    assert module._should_switch_model("medium", 12.0, 10.0) == "medium"
    assert module._should_switch_model("medium", 45.0, 10.0) == "base"
    assert module._should_switch_model("base", 8.0, 10.0) == "medium"
