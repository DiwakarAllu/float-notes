# Float Notes

Float Notes is a Windows desktop note-taking app designed for fast capture, clean organization, and local AI assistance. It combines a floating note bubble, Markdown editing, instant screen OCR, AI-powered rewriting, and a built-in Teams meeting transcriber — all while keeping the workflow local and private.

## Why Float Notes

Most note tools force you to switch context, leave the task you are doing, or depend on cloud services for every action. Float Notes keeps your notes available in a compact floating workspace so you can:

- capture ideas while working in a browser, chat app, or meeting
- turn any visible text on screen into editable notes
- generate summaries and polished rewrites locally with Ollama
- record and transcribe meetings without uploading content to a remote service
- keep your notes, transcript history, and AI output organized in one place

## Key Features

### 1. Floating notes bubble

- lightweight always-available note window
- draggable, compact, and designed to stay out of the way
- quick note creation, switching, and archiving
- note content auto-saved to disk

### 2. Markdown editing with live preview

- write with headings, bold text, italic text, lists, code, and blockquotes
- preview and clean formatting without leaving the note
- useful for meeting notes, task lists, project planning, and personal capture

### 3. Screen-to-text OCR

- select a region of the screen and extract text from it
- works with Windows OCR tooling and optional Tesseract fallback
- ideal for copying text from documents, web pages, screenshots, and app windows

### 4. Local AI assistant

- generate suggestions, rewrites, and improvements for notes
- supports prompts like “make this concise”, “turn this into bullet points”, or “rewrite with action items”
- runs through Ollama locally when available
- keeps AI output private and offline-friendly

### 5. Teams meeting transcriber

- listens to system audio via Windows loopback capture
- transcribes live meetings without requiring Teams admin access
- supports file transcription and transcript summarization
- writes text output into the transcripts folder and can add summaries back into the notes app

### 6. Meeting summaries and action items

- convert raw transcript text into structured summaries
- extract key decisions, open questions, and action items
- reduce the effort of manually reviewing long meeting recordings

### 7. Theme and note library workflow

- light and dark theme support
- browse a note library and archived notes
- quick navigation between notes without losing context

### 8. Windows-first desktop experience

- optimized for Windows users
- uses native Windows audio and OCR capabilities where available
- works well for local productivity workflows and internal tools

## Benefits

### Productivity

- capture ideas instantly without opening a heavy app
- convert screenshots and visible text into usable notes quickly
- keep action items and meeting notes organized in one workflow

### Privacy

- transcriptions and AI processing can stay local on your machine
- avoids sending sensitive notes or meeting content to external cloud services by default
- useful for internal documentation, team meetings, and personal notes

### Better note-taking

- faster than traditional editors for quick information capture
- easier to polish notes with AI suggestions and formatting tools
- ideal for brainstorming, task tracking, standups, and meeting recaps

### Meeting efficiency

- reduce manual note-taking during calls
- surface key decisions and next steps automatically
- helps turn a conversation into a usable summary in minutes

### Flexible workflow

- works as a notes app, OCR utility, AI writing assistant, and meeting recorder
- can be used both for personal productivity and light professional workflows

## Setup

### Install Python dependencies

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

The project targets Python 3.11+ and is tested here with Python 3.13 on Windows.

### Install and configure Ollama

The app uses Ollama when a local API is available. To install the supplied setup script and keep the application and model cache on D:, run PowerShell as your normal user:

```powershell
.\setup-ollama.ps1
```

This configures:

- D:\MyOllama\App
- D:\MyOllama\Models
- http://127.0.0.1:11434

Then pull a model and set your default model:

```powershell
ollama pull llama3.2:1b
$env:OLLAMA_MODEL = "llama3.2:1b"
```

The app also supports `OLLAMA_HOST` and `OLLAMA_MODEL` environment variables. Ollama is required for AI suggestions, the AI assistant, and transcript summarization.

## Run the app

### Start the notes UI

```powershell
python main.py
```

### Start the transcriber directly

Inspect audio devices:

```powershell
python teams-transcriber.py live --list-devices
```

Start live transcription:

```powershell
python teams-transcriber.py live --device 10
```

### Transcribe a file

```powershell
python teams-transcriber.py file path\to\recording.mp3
```

### Summarize a transcript with Ollama

```powershell
python teams-transcriber.py summarize path\to\meeting.txt
```

## Packaging

Packaged apps are generated in the dist folder:

```powershell
.\dist\FloatNotes.exe
.\dist\TeamsTranscriber.exe live --list-devices
```

Keep both executables together so the microphone button in Float Notes can launch the transcriber correctly.

## Notes on audio and OCR

- live transcription uses a Windows WASAPI loopback device
- the float note mic button launches the source project transcriber in development mode
- Whisper models download on first use
- Tesseract is optional; Windows OCR is used as a fallback
- transcript outputs are stored in the transcripts folder
- runtime data is stored under `%USERPROFILE%\.float_notes`

## Verification

```powershell
python -m pytest -q
python teams-transcriber.py --help
```

## Summary

Float Notes is a practical local desktop workspace for:

- writing notes quickly
- collecting text from any screen region
- improving notes with AI
- transcribing meetings locally
- turning meetings into readable summaries and action lists

It is designed to reduce friction between thinking, capturing, and organizing information — without forcing you into a cloud-first workflow.
