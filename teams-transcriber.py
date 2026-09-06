#!/usr/bin/env python3
"""
Teams Meeting Transcriber
──────────────────────────
Captures system audio (what you hear through your speakers/headphones)
and transcribes it locally using Whisper AI — no Teams admin access needed.

Usage:
    python teams-transcriber.py live                   # Start live transcription
    python teams-transcriber.py live --list-devices    # Show audio devices
    python teams-transcriber.py live --chunk 20        # Transcribe every 20 seconds
    python teams-transcriber.py live --device 10       # Use the speaker loopback
    python teams-transcriber.py live --model small     # Use a more accurate model
    python teams-transcriber.py file recording.mp3     # Transcribe a saved recording
"""

import argparse
import datetime
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np


_WHISPER_MODEL_IDS   = {
    "tiny":     "Systran/faster-whisper-tiny",
    "base":     "Systran/faster-whisper-base",
    "small":    "Systran/faster-whisper-small",
    "medium":   "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}
_CHUNK_SIZE          = 3000   # chars per chunk
_MAX_CHUNKS          = 5      # cap to keep total time under ~15 min on CPU

# Used per-chunk in the map pass to extract key points
_EXTRACT_PROMPT = """\
You are a meeting note-taker. From this meeting transcript segment, extract:
- Key points and topics discussed
- Any decisions made
- Any action items or tasks mentioned (with owner if stated)

SEGMENT:
{chunk}

Be concise. Use bullet points only.
"""


def _ollama_available() -> tuple[bool, str]:
    import urllib.request
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as response:
            models = json.loads(response.read()).get("models", [])
            preferred = os.environ.get("OLLAMA_MODEL", "").strip()
            names = [model.get("name", "") for model in models]
            selected = preferred if preferred in names else (names[0] if names else "")
            return (True, selected) if selected else (False, "")
    except Exception:
        return False, ""


def _ollama_generate(prompt: str, model: str) -> str:
    import urllib.request
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    request = urllib.request.Request(
        f"{host}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())["response"].strip()

# Used in the final reduce pass over all extracted notes
_SUMMARY_PROMPT = """\
You are a meeting assistant. Combine these extracted notes from different parts of the same meeting into one clear, structured summary. Remove duplicates.

EXTRACTED NOTES:
{transcript}

Respond using exactly this structure:

## Meeting Summary
(2-3 sentences covering what this meeting was about overall)

## Key Decisions
- (list decisions made; write 'None noted' if unclear)

## Action Items
- [Owner if mentioned] What needs to be done

## Priorities & Follow-ups
- (open questions, next steps, things to check)
"""


# ─── Whisper helpers ──────────────────────────────────────────────────────────

def load_model(model_size: str, _fallback: str = "base"):
    from faster_whisper import WhisperModel
    for size in dict.fromkeys([model_size, _fallback]):  # deduplicated, order preserved
        model_id = _WHISPER_MODEL_IDS[size]
        try:
            print(f"Loading Whisper '{size}' model (first run downloads — may take a moment)...")
            model = WhisperModel(model_id, device="cpu", compute_type="int8")
            print(f"Model ready: '{size}'.\n")
            return model
        except Exception as exc:
            if size == _fallback:
                raise
            print(f"Could not load '{size}' ({exc.__class__.__name__}: {exc})")
            print(f"Falling back to '{_fallback}'...\n")


# Performance-based model switching: prefer Medium, but switch to Base only when
# the model is demonstrably too slow for the incoming audio stream.
LIVE_MODEL_SWITCH_RATIO = 4.0
LIVE_MODEL_RECOVER_RATIO = 1.5
LIVE_MODEL_SWITCH_COUNT = 2


def _transcription_ratio(processing_seconds: float, audio_seconds: float) -> float:
    if audio_seconds <= 0:
        return 0.0
    return processing_seconds / audio_seconds


def _should_switch_model(current_model: str, processing_seconds: float, audio_seconds: float) -> str:
    """Use live throughput to decide whether the active model is unhealthy."""
    ratio = _transcription_ratio(processing_seconds, audio_seconds)
    if current_model == "medium" and ratio >= LIVE_MODEL_SWITCH_RATIO:
        return "base"
    if current_model == "base" and ratio <= LIVE_MODEL_RECOVER_RATIO:
        return "medium"
    return current_model


def transcribe_array(model, audio: np.ndarray, sample_rate: int) -> str:
    """Transcribe a float32 mono numpy array; resamples to 16 kHz if needed."""
    if sample_rate != 16000:
        import scipy.signal
        audio = scipy.signal.resample_poly(audio, 16000, sample_rate).astype(np.float32)

    segments, _ = model.transcribe(audio, language="en", beam_size=5)
    return " ".join(seg.text.strip() for seg in segments)


# ─── Audio device helpers ─────────────────────────────────────────────────────

def _get_pyaudio():
    try:
        import pyaudiowpatch as pyaudio
        return pyaudio
    except ImportError:
        print("ERROR: pyaudiowpatch is not installed.")
        print("       Run:  pip install pyaudiowpatch")
        sys.exit(1)


def list_devices():
    pyaudio = _get_pyaudio()
    p = pyaudio.PyAudio()
    print("\nAvailable input / loopback devices:")
    print("-" * 58)
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if info.get("maxInputChannels", 0) > 0:
            tag = " [LOOPBACK]" if info.get("isLoopbackDevice") else ""
            print(f"  [{i:2d}]  {info['name']}{tag}")
    p.terminate()


def _default_loopback(p, pyaudio):
    """Return (index, info) for the WASAPI loopback of the default speakers."""
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        speaker = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        for lb in p.get_loopback_device_info_generator():
            if speaker["name"] in lb["name"]:
                return lb["index"], lb
        # Fallback: first available loopback
        for lb in p.get_loopback_device_info_generator():
            return lb["index"], lb
    except Exception:
        pass
    return None, None


# ─── Live transcription ───────────────────────────────────────────────────────

def live_transcribe(model, chunk_seconds: int, output_file: Path, device_index: int = None):
    pyaudio = _get_pyaudio()
    p = pyaudio.PyAudio()

    if device_index is None:
        idx, info = _default_loopback(p, pyaudio)
        if idx is None:
            p.terminate()
            print("No WASAPI loopback device found.")
            print("Tip: Enable 'Stereo Mix' in Windows Sound settings, then retry.")
            sys.exit(1)
    else:
        idx = device_index
        info = p.get_device_info_by_index(idx)

    sample_rate = int(info["defaultSampleRate"])
    channels = min(int(info["maxInputChannels"]), 2)
    frames_per_chunk = sample_rate * chunk_seconds

    wav_path = output_file.with_suffix(".wav")

    print(f"Source  : {info['name']}")
    print(f"Rate    : {sample_rate} Hz  |  Channels: {channels}")
    print(f"Chunk   : every {chunk_seconds}s")
    print(f"Output  : {output_file}")
    print(f"Audio   : {wav_path}")
    print("\nPress Ctrl+C to stop.\n")
    print("-" * 58)

    buffer: list[np.ndarray] = []
    active_model = "medium"
    low_ratio_hits = 0
    high_ratio_hits = 0

    def _callback(in_data, frame_count, time_info, status):
        buffer.append(np.frombuffer(in_data, dtype=np.float32).copy())
        return (None, pyaudio.paContinue)

    stream = p.open(
        format=pyaudio.paFloat32,
        channels=channels,
        rate=sample_rate,
        input=True,
        input_device_index=idx,
        frames_per_buffer=1024,
        stream_callback=_callback,
    )
    stream.start_stream()

    _WAV_RATE = 16000  # 16 kHz mono is sufficient for speech and keeps files small

    def _to_mono16k(buf: list[np.ndarray]) -> np.ndarray:
        """Concatenate buffer, mix to mono float32, resample to 16 kHz."""
        audio = np.concatenate(buf)
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1).astype(np.float32)
        if sample_rate != _WAV_RATE:
            import scipy.signal
            audio = scipy.signal.resample_poly(audio, _WAV_RATE, sample_rate).astype(np.float32)
        return audio

    def _write_wav_chunk(wav_writer: wave.Wave_write, audio: np.ndarray):
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        wav_writer.writeframes(pcm.tobytes())

    def _flush_text(buf: list[np.ndarray]) -> str:
        audio = np.concatenate(buf)
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1).astype(np.float32)
        return transcribe_array(model, audio, sample_rate)

    model_name = active_model
    model = load_model(model_name, _fallback="base")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    wav_writer = wave.open(str(wav_path), "wb")
    wav_writer.setnchannels(1)
    wav_writer.setsampwidth(2)  # int16
    wav_writer.setframerate(_WAV_RATE)

    try:
        with open(output_file, "a", encoding="utf-8") as f:
            header = f"=== Session: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n"
            f.write(header)

            while stream.is_active():
                time.sleep(0.5)
                total = sum(len(b) // channels for b in buffer)
                if total < frames_per_chunk:
                    continue

                chunk, buffer[:] = list(buffer), []
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                audio_seconds = max(len(chunk) / sample_rate, 1e-6)
                start = time.perf_counter()
                print(f"[{ts}] Transcribing ...", end="\r", flush=True)
                _write_wav_chunk(wav_writer, _to_mono16k(chunk))
                text = _flush_text(chunk)
                elapsed = time.perf_counter() - start
                ratio = _transcription_ratio(elapsed, audio_seconds)

                if text.strip():
                    line = f"[{ts}]  {text.strip()}"
                    print(line + " " * 20)
                    f.write(line + "\n")
                    f.flush()

                print(f"[{ts}] model={active_model} audio={audio_seconds:.1f}s elapsed={elapsed:.1f}s ratio={ratio:.2f}x")

                if active_model == "medium" and ratio >= LIVE_MODEL_SWITCH_RATIO:
                    high_ratio_hits += 1
                    if high_ratio_hits >= LIVE_MODEL_SWITCH_COUNT:
                        print(f"Medium is too slow ({ratio:.2f}x real time) — switching to base model")
                        active_model = "base"
                        model = load_model("base", _fallback="base")
                        high_ratio_hits = 0
                        low_ratio_hits = 0
                else:
                    high_ratio_hits = 0

                if active_model == "base" and ratio <= LIVE_MODEL_RECOVER_RATIO:
                    low_ratio_hits += 1
                    if low_ratio_hits >= LIVE_MODEL_SWITCH_COUNT:
                        print(f"Base is fast enough ({ratio:.2f}x real time) — retrying medium model")
                        active_model = "medium"
                        model = load_model("medium", _fallback="base")
                        low_ratio_hits = 0
                        high_ratio_hits = 0
                else:
                    low_ratio_hits = 0

    except KeyboardInterrupt:
        print("\n\nStopped. Finishing last chunk...")
        if buffer:
            _write_wav_chunk(wav_writer, _to_mono16k(buffer))
            text = _flush_text(buffer)
            if text.strip():
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                line = f"[{ts}]  {text.strip()}"
                print(line)
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
    finally:
        wav_writer.close()
        stream.stop_stream()
        stream.close()
        p.terminate()

    print(f"\nTranscript saved → {output_file}")
    print(f"Audio saved     → {wav_path}")
    summary_path = output_file.with_suffix(".summary.txt")
    summarize_transcript(output_file, summary_path)


# ─── File transcription ───────────────────────────────────────────────────────

def file_transcribe(model, input_path: Path, output_file: Path):
    print(f"Transcribing: {input_path}\n")
    from faster_whisper import WhisperModel  # already loaded via model param
    segments, info = model.transcribe(str(input_path), language="en", beam_size=5)

    print(f"Language detected: {info.language}  (confidence: {info.language_probability:.0%})")
    print("-" * 58)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"File : {input_path}\n")
        f.write(f"Date : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        for seg in segments:
            start = str(datetime.timedelta(seconds=int(seg.start)))
            end   = str(datetime.timedelta(seconds=int(seg.end)))
            line  = f"[{start} → {end}]  {seg.text.strip()}"
            print(line)
            f.write(line + "\n")

    print(f"\nTranscript saved → {output_file}")


# ─── Summarization ───────────────────────────────────────────────────────────

def summarize_transcript(transcript_path: Path, output_path: Path):
    print("\nGenerating meeting summary with Ollama...\n")
    ok, model = _ollama_available()
    if not ok:
        raise RuntimeError("Ollama is not running or has no installed model")

    # Strip header, timestamps, and silence artefacts ("You" lines Whisper emits for silence)
    lines = []
    for l in transcript_path.read_text(encoding="utf-8").splitlines():
        if not l.strip() or l.startswith("==="):
            continue
        text = l.split("]  ", 1)[1] if (l.startswith("[") and "]  " in l) else l
        if text.strip().lower() in ("you", "you.", "you,"):
            continue
        lines.append(text)
    transcript_text = "\n".join(lines)

    def _generate(prompt: str, max_tokens: int) -> str:
        return _ollama_generate(prompt, model)

    # Short transcript: single pass is faster and avoids redundant map overhead
    if len(transcript_text) <= _CHUNK_SIZE * 2:
        print(f"Short transcript ({len(transcript_text)} chars) - single pass.\n")
        summary = _generate(_SUMMARY_PROMPT.format(transcript=transcript_text[:6000]), max_tokens=600)
    else:
        # Split into fixed-size chunks, then sample evenly up to _MAX_CHUNKS
        raw_chunks = [
            transcript_text[i : i + _CHUNK_SIZE]
            for i in range(0, len(transcript_text), _CHUNK_SIZE)
        ]
        if len(raw_chunks) <= _MAX_CHUNKS:
            chunks = raw_chunks
        else:
            step = (len(raw_chunks) - 1) / (_MAX_CHUNKS - 1)
            chunks = [raw_chunks[round(i * step)] for i in range(_MAX_CHUNKS)]

        total = len(chunks)
        skipped = len(raw_chunks) - total
        print(f"Transcript: {len(raw_chunks)} chunks — processing {total}"
              + (f" (sampling evenly, {skipped} skipped)" if skipped else "") + "\n")

        # Map: extract key points from every sampled chunk
        partial_notes = []
        for i, chunk in enumerate(chunks, 1):
            print(f"  Chunk {i}/{total} ...", end="\r", flush=True)
            notes = _generate(_EXTRACT_PROMPT.format(chunk=chunk), max_tokens=200)
            partial_notes.append(f"--- Part {i} ---\n{notes}")

        print(f"  All {total} chunks processed.          ")
        print("Generating final structured summary...\n")

        combined = "\n\n".join(partial_notes)
        if len(combined) > 8000:
            combined = combined[:8000]
        summary = _generate(_SUMMARY_PROMPT.format(transcript=combined), max_tokens=600)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"Transcript : {transcript_path}\n")
        f.write(f"Generated  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Model      : {model}\n\n")
        f.write(summary)

    print("=" * 58)
    print(summary)
    print("=" * 58)
    print(f"Summary saved → {output_path}")
    _push_to_float_notes(summary, transcript_path)


def _push_to_float_notes(summary: str, transcript_path: Path):
    """Inject the meeting summary as a new note into Float Notes."""
    import uuid as _uuid
    float_notes_file = Path.home() / ".float_notes" / "notes.json"
    if not float_notes_file.exists():
        print("Float Notes data file not found — skipping note creation.")
        return

    title = f"Meeting {datetime.datetime.now().strftime('%d-%b-%y')}"
    body  = f"# {title}\n\n{summary}\n\n---\n*Transcript: {transcript_path.name}*"

    try:
        notes = json.loads(float_notes_file.read_text("utf-8"))
    except Exception:
        notes = []

    notes.insert(0, {
        "id":      str(_uuid.uuid4()),
        "title":   title,
        "body":    body,
        "created": datetime.datetime.now().isoformat(),
    })

    float_notes_file.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"Note '{title}' added to Float Notes ✓")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transcribe MS Teams meetings using local Whisper AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="mode")

    # live
    lp = sub.add_parser("live", help="Real-time transcription from system audio")
    lp.add_argument("--device",       type=int, default=None,
                    help="Audio device index (see --list-devices)")
    lp.add_argument("--chunk",        type=int, default=10,
                    help="Seconds per transcription chunk (default: 10)")
    lp.add_argument("--model",        default="medium",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    help="Whisper model (default: medium, fallback: base)")
    lp.add_argument("--output",       type=str, default=None,
                    help="Transcript file path (default: transcripts/<timestamp>.txt)")
    lp.add_argument("--list-devices", action="store_true",
                    help="List audio devices and exit")

    # file
    fp = sub.add_parser("file", help="Transcribe an audio/video recording")
    fp.add_argument("input",   help="Audio file path (.mp3 .wav .mp4 .m4a …)")
    fp.add_argument("--model", default="medium",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    help="Whisper model (default: medium, fallback: base)")
    fp.add_argument("--output", type=str, default=None,
                    help="Transcript file path")

    # summarize
    sp = sub.add_parser("summarize", help="Summarize an existing transcript file")
    sp.add_argument("input", nargs="?", default=None,
                    help="Transcript .txt file (default: latest in transcripts/)")
    sp.add_argument("--output", type=str, default=None, help="Summary output path")

    args = parser.parse_args()
    if not args.mode:
        parser.print_help()
        print("\nNo mode selected. Choose one of: live, file, summarize")
        return 0

    transcripts_dir = Path("transcripts")

    if args.mode == "live":
        if args.list_devices:
            list_devices()
            return
        out = Path(args.output) if args.output else \
              transcripts_dir / f"meeting_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        live_transcribe(load_model(args.model, _fallback="base"), args.chunk, out, args.device)

    elif args.mode == "summarize":
        if args.input:
            src = Path(args.input)
        else:
            # Pick the latest transcript in the transcripts dir
            candidates = sorted(Path("transcripts").glob("meeting_*.txt"))
            candidates = [c for c in candidates if not c.stem.endswith("summary")]
            if not candidates:
                print("No transcript files found in transcripts/")
                sys.exit(1)
            src = candidates[-1]
            print(f"Using latest transcript: {src}")
        out = Path(args.output) if args.output else src.with_suffix(".summary.txt")
        summarize_transcript(src, out)

    elif args.mode == "file":
        src = Path(args.input)
        if not src.exists():
            print(f"File not found: {src}")
            sys.exit(1)
        out = Path(args.output) if args.output else \
              transcripts_dir / (src.stem + "_transcript.txt")
        file_transcribe(load_model(args.model, _fallback="base"), src, out)


if __name__ == "__main__":
    raise SystemExit(main())