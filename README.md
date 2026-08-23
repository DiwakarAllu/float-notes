# Float Notes

A Windows desktop notes bubble with Markdown preview, screen OCR, local AI helpers, and a Teams meeting transcriber.

## Setup

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

The project targets Python 3.11+ and is tested here with Python 3.13 on Windows.

## Ollama on D:

The app uses Ollama first when its local API is available. To install the supplied
installer and keep the Ollama application and model cache on D:, run PowerShell as
your normal user:

```powershell
.\setup-ollama.ps1
```

This configures `D:\MyOllama\App`, `D:\MyOllama\Models`, and
`http://127.0.0.1:11434`. Open a new terminal after installation and download a
model, for example:

```powershell
ollama pull llama3.2:1b
$env:OLLAMA_MODEL = "llama3.2:1b"
```

The Python app also accepts `OLLAMA_HOST` and `OLLAMA_MODEL`. Ollama is required
for AI suggestions, the AI assistant, and transcript summaries.

## Run

Packaged applications are in `dist/`:

```powershell
.\dist\FloatNotes.exe
.\dist\TeamsTranscriber.exe live --list-devices
```

Keep `FloatNotes.exe` and `TeamsTranscriber.exe` together so the microphone
button can launch the transcriber.

Start the notes bubble:

```powershell
python main.py
```

Inspect audio devices:

```powershell
python teams-transcriber.py live --list-devices
```

The Float Notes microphone button launches live transcription from the source
project. It uses the default Windows speaker loopback; choose a device with
`--device` when needed. The default `medium` Whisper model may require a large
download and significant memory, so `--model small` or `--model tiny` is better
for constrained machines.

Transcribe an audio or video file:

```powershell
python teams-transcriber.py file path\to\recording.mp3
```

Summarize a transcript with Ollama:

```powershell
python teams-transcriber.py summarize path\to\meeting.txt
```

Whisper models download on first use. Live transcription requires a Windows WASAPI loopback device. Tesseract is optional; Windows OCR is used as a fallback.

## Verify

```powershell
python -m pytest -q
python teams-transcriber.py --help
```

Runtime data is stored in `%USERPROFILE%\\.float_notes`; generated transcripts are kept in `transcripts/`.
