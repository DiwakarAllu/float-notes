import ast
import py_compile
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = [ROOT / "main.py", ROOT / "teams-transcriber.py"]


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


def test_note_suggestions_use_ollama_when_available(monkeypatch):
    import main

    monkeypatch.setattr(main, "_ollama_available", lambda: (True, "llama3.2:1b"))
    monkeypatch.setattr(main, "_ollama_generate", lambda prompt, model: "Ollama suggestion")

    result = main._note_ai_generate("Draft note", "Improve it")

    assert result == "Ollama suggestion"
