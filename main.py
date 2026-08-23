"""
Float Notes — Grammarly-style floating bubble with rounded corners.
Click to expand, drag anywhere, auto-collapses after idle.
"""
import tkinter as tk
from tkinter import ttk
import json, re, uuid, math, ctypes, subprocess, sys, tempfile, threading, os, time
from pathlib import Path
from datetime import datetime

# ── Themes ─────────────────────────────────────────────────────────────────
DARK = dict(
    bg="#0e0e1a", panel="#13131f", header="#1a1a2e", surface="#1e1e30",
    card="#252540", border="#2e2e50", overlay="#5a5a80", sub="#9090b8",
    text="#ddddf0", purple="#a78bfa", indigo="#818cf8", teal="#2dd4bf",
    green="#86efac", yellow="#fde68a", red="#fca5a5", blue="#93c5fd",
    scrollbar="#2e2e50",
)
LIGHT = dict(
    bg="#f5f5ff", panel="#ffffff", header="#ede9fe", surface="#f8f7ff",
    card="#e9e4ff", border="#c4b5fd", overlay="#7c3aed", sub="#6d28d9",
    text="#1e1b4b", purple="#7c3aed", indigo="#4338ca", teal="#0d9488",
    green="#065f46", yellow="#92400e", red="#b91c1c", blue="#1d4ed8",
    scrollbar="#c4b5fd",
)
BUB = dict(bub1="#4f26b8", bub2="#7c3aed", bub3="#a78bfa")
# unique colour used only as transparent key — must never appear in panel widgets
_TRANSP = "#010203"
C: dict = {**DARK, **BUB}

FF = "Segoe UI"
FM = "Cascadia Code"
W_ICON  = 56
W_PANEL = 300
H_PANEL = 390
IDLE_MS = 14_000
AF      = 18    # animation frames
AM      = 11    # ms per frame

DATA_FILE     = Path.home() / ".float_notes" / "notes.json"
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)


# ── Local LLM helpers ──────────────────────────────────────────────────────

def _ollama_available() -> tuple[bool, str]:
    """Return (True, first_model_name) if Ollama is running locally."""
    try:
        import urllib.request
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as r:
            models = json.loads(r.read()).get("models", [])
            preferred = os.environ.get("OLLAMA_MODEL", "").strip()
            names = [model.get("name", "") for model in models]
            model = preferred if preferred in names else (names[0] if names else "")
            return (True, model) if model else (False, "")
    except Exception:
        return (False, "")


def _ollama_generate(prompt: str, model: str) -> str:
    import urllib.request
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    req = urllib.request.Request(
        f"{host}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["response"].strip()


def _ai_run(prompt: str) -> str:
    """Generate text with the locally running Ollama service."""
    ok, model = _ollama_available()
    if not ok:
        raise RuntimeError("Ollama is not running or has no installed model")
    return _ollama_generate(prompt, model)


def _note_ai_messages(note_text: str, prompt: str) -> list[dict[str, str]]:
    instruction = prompt.strip() or (
        "Improve the structure, headings, and readability while preserving meaning."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a note-writing assistant. Rewrite notes in a clean, "
                "well-structured form. Keep the original meaning, improve flow, "
                "use headings or bullets when useful, and return only the final note text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Instruction:\n{instruction}\n\n"
                f"Note:\n{note_text.strip()}\n\n"
                "Return only the revised note text."
            ),
        },
    ]


def _note_ai_generate(note_text: str, prompt: str) -> str:
    ok, model = _ollama_available()
    if not ok:
        raise RuntimeError("Ollama is not running or has no installed model")
    messages = _note_ai_messages(note_text, prompt)
    ollama_prompt = "\n\n".join(
        f"{message['role'].title()}:\n{message['content']}"
        for message in messages
    )
    return _ollama_generate(ollama_prompt, model)


def _load() -> list:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            pass
    return [{"id": str(uuid.uuid4()), "title": "Quick Notes",
             "body": "# ✨ Float Notes\n\nStart writing your notes here.\n\n- **Bold**, *italic*, `code`\n- ## Headings, > quotes\n- Auto-saves • Light/Dark mode",
             "created": datetime.now().isoformat()}]


def _save(notes: list):
    DATA_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), "utf-8")


def _save_all(active: list, archived: list):
    DATA_FILE.write_text(
        json.dumps(active + archived, ensure_ascii=False, indent=2), "utf-8"
    )


def _set_rgn(hwnd: int, w: int, h: int, r: int = 0, circle: bool = False):
    """Apply a window clip region (rounded rect or circle)."""
    try:
        if circle:
            rgn = ctypes.windll.gdi32.CreateEllipticRgn(0, 0, w + 1, h + 1)
        else:
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
    except Exception:
        pass


# ── Windows built-in OCR (no external packages needed) ─────────────────────
_WIN_OCR_PS = """
param([string]$p)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime]
function Aw($t){
    $aw=$t.GetAwaiter()
    while(!$aw.IsCompleted){[System.Threading.Thread]::Sleep(5)}
    $aw.GetResult()}
$f=Aw([Windows.Storage.StorageFile]::GetFileFromPathAsync("$p"))
$s=Aw($f.OpenAsync([Windows.Storage.FileAccessMode]::Read))
$d=Aw([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s))
$b=Aw($d.GetSoftwareBitmapAsync())
$e=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
Write-Output (Aw($e.RecognizeAsync($b))).Text
"""

def _dpi_scale() -> float:
    """Return physical/logical pixel ratio (e.g. 1.5 at 150% DPI)."""
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except Exception:
        return 1.0


def _capture_region(bbox) -> str:
    """Capture screen region to a temp PNG/BMP. Tries PIL then Windows GDI."""
    import struct
    x1, y1, x2, y2 = (int(v) for v in bbox)
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    # Virtual desktop origin (may be negative on multi-monitor setups)
    vx = ctypes.windll.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    vy = ctypes.windll.user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    vw = ctypes.windll.user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    vh = ctypes.windll.user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
    try:
        from PIL import ImageGrab
        # Grab full virtual desktop then crop — eliminates all bbox coord-system ambiguity
        full = ImageGrab.grab(all_screens=True)
        # PIL may return physical pixels; detect scale vs logical virtual desktop size
        sx = full.width  / max(vw, 1)
        sy = full.height / max(vh, 1)
        cx1 = round((x1 - vx) * sx)
        cy1 = round((y1 - vy) * sy)
        cx2 = round((x2 - vx) * sx)
        cy2 = round((y2 - vy) * sy)
        img = full.crop((max(0, cx1), max(0, cy1), min(full.width, cx2), min(full.height, cy2)))
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        tmp.close()
        img.save(tmp.name, 'PNG')
        return tmp.name
    except Exception:
        pass
    # Fallback: Windows GDI via ctypes (no external packages)
    gdi32  = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    hdc = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, hdc, x1, y1, 0x00CC0020)
    row = (w * 3 + 3) & ~3
    bih = struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 24, 0, row*h, 0, 0, 0, 0)
    bmi = ctypes.create_string_buffer(bih)
    buf = ctypes.create_string_buffer(row * h)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, bmi, 0)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, hdc)
    gdi32.DeleteObject(bmp)
    bfh = struct.pack('<2sIHHI', b'BM', 54 + row*h, 0, 0, 54)
    tmp = tempfile.NamedTemporaryFile(suffix='.bmp', delete=False)
    tmp.write(bfh + bih + bytes(buf))
    tmp.close()
    return tmp.name


def _winrt_ocr(src: str) -> str:
    """Windows.Media.OCR via winrt Python bindings — same engine as Snipping Tool."""
    import asyncio, pathlib
    # Pre-import all required winrt namespaces to avoid lazy-load errors in threads
    from winrt.windows.foundation.collections import IIterable          # noqa
    from winrt.windows.storage import StorageFile, FileAccessMode
    from winrt.windows.storage.streams import IRandomAccessStream        # noqa
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine

    # Upscale image before OCR — WinRT accuracy improves significantly at larger sizes
    try:
        from PIL import Image, ImageFilter, ImageEnhance
        img = Image.open(src)
        w, h = img.size
        # Scale to at least 200px height; minimum 2x upscale for small captures
        target_scale = max(2.0, 200 / max(h, 1))
        if target_scale > 1.05:
            new_w, new_h = int(w * target_scale), int(h * target_scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(1.6)
        img = img.filter(ImageFilter.SHARPEN)
        upscaled = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        upscaled.close()
        img.save(upscaled.name, 'PNG')
        ocr_src = upscaled.name
    except Exception:
        ocr_src = src
        upscaled = None

    abs_path = str(pathlib.Path(ocr_src).absolute())

    async def _run():
        sf  = await StorageFile.get_file_from_path_async(abs_path)
        s   = await sf.open_async(FileAccessMode.READ)
        dec = await BitmapDecoder.create_async(s)
        bmp = await dec.get_software_bitmap_async()
        eng = OcrEngine.try_create_from_user_profile_languages()
        res = await eng.recognize_async(bmp)
        return "\n".join(line.text for line in res.lines)

    # Use new_event_loop so this works safely from any thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_run()).strip()
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(None)
        if upscaled:
            try: os.unlink(upscaled.name)
            except Exception: pass


def _ocr_image(src: str) -> str:
    """OCR priority: pytesseract → Windows WinRT OCR → PowerShell OCR."""
    # 1. pytesseract (needs Tesseract binary - https://github.com/UB-Mannheim/tesseract/wiki)
    try:
        import pytesseract
        for _p in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]:
            if os.path.exists(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break
        result = pytesseract.image_to_string(src).strip()
        if result:
            return result
    except ImportError:
        pass
    except Exception as e:
        if "tesseract" not in str(e).lower():
            return f"[pytesseract error: {e}]"
    # 2. Windows WinRT OCR — best for screen text (same engine as Snipping Tool)
    try:
        result = _winrt_ocr(src)
        if result:
            return result
    except Exception:
        pass
    # 3. Windows OCR via PowerShell (fallback when winrt import fails)
    try:
        ps_f = tempfile.NamedTemporaryFile(suffix=".ps1", delete=False, mode="w", encoding="utf-8")
        ps_f.write(_WIN_OCR_PS)
        ps_f.close()
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", ps_f.name, "-p", src],
            capture_output=True, text=True, timeout=55,
        )
        os.unlink(ps_f.name)
        out = r.stdout.strip()
        if out:
            return out
        err = r.stderr.strip()
        if err:
            return f"[Windows OCR error: {err[:250]}]"
        return "[No text detected]"
    except subprocess.TimeoutExpired:
        return "[OCR timed out — try selecting a smaller region]"
    except Exception as e:
        return f"[OCR failed: {e}]"


# ── Screen-region selection overlay ────────────────────────────────────────
class SnipOverlay(tk.Toplevel):
    """Fullscreen crosshair overlay; calls on_done(bbox) with the selected rect."""

    def __init__(self, on_done):
        super().__init__()
        self._on_done  = on_done
        self._start_cv = None   # canvas-relative start coords
        self._sel_rect = None
        # Cover full virtual desktop (handles multi-monitor)
        vx = ctypes.windll.user32.GetSystemMetrics(76)
        vy = ctypes.windll.user32.GetSystemMetrics(77)
        vw = ctypes.windll.user32.GetSystemMetrics(78)
        vh = ctypes.windll.user32.GetSystemMetrics(79)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.38)
        self.configure(bg="#05050f")
        self.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.update()   # force placement so winfo_rootx is accurate
        # Record actual window screen position (may differ from requested +vx+vy)
        self._win_ox = self.winfo_rootx()
        self._win_oy = self.winfo_rooty()
        self._cv = tk.Canvas(self, bg="#05050f", highlightthickness=0, cursor="crosshair")
        self._cv.pack(fill="both", expand=True)
        mx, my = vw // 2, vh // 2
        self._cv.create_text(mx, my - 18,
                             text="✂  Drag to select the text region",
                             fill="white", font=(FF, 15, "bold"), tags="hint")
        self._cv.create_text(mx, my + 14,
                             text="Release to extract  •  Esc to cancel",
                             fill="#9090b8", font=(FF, 11), tags="hint")
        self._cv.bind("<ButtonPress-1>",   self._press)
        self._cv.bind("<B1-Motion>",       self._drag)
        self._cv.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda e: self.destroy())

    def _press(self, e):
        self._start_cv = (e.x, e.y)   # canvas-relative coords
        self._cv.delete("hint")
        if self._sel_rect: self._cv.delete(self._sel_rect)

    def _drag(self, e):
        if not self._start_cv: return
        if self._sel_rect: self._cv.delete(self._sel_rect)
        x1, y1 = self._start_cv
        # Draw using canvas coords — always correct regardless of window position
        self._sel_rect = self._cv.create_rectangle(
            x1, y1, e.x, e.y,
            outline="#a78bfa", width=2, fill="#a78bfa", stipple="gray25",
        )

    def _release(self, e):
        if not self._start_cv: return
        x1c, y1c = self._start_cv
        x2c, y2c = e.x, e.y
        ox, oy = self._win_ox, self._win_oy
        # Convert canvas coords → absolute screen coords for capture
        sx1, sy1 = ox + x1c, oy + y1c
        sx2, sy2 = ox + x2c, oy + y2c
        self.destroy()
        bbox = (min(sx1,sx2), min(sy1,sy2), max(sx1,sx2), max(sy1,sy2))
        if bbox[2]-bbox[0] > 8 and bbox[3]-bbox[1] > 8:
            self._on_done(bbox)
class MDRenderer:
    _HEAD  = re.compile(r"^(#{1,6})\s+(.*)")
    _BOLD  = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
    _ITAL  = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
    _CODE  = re.compile(r"`([^`\n]+?)`")
    _LINK  = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")
    _TASK  = re.compile(r"^(\s*)[-*+]\s+\[( |x|X)\]\s+(.*)")
    _BULL  = re.compile(r"^(\s*)[-*+]\s+(.*)")
    _NUM   = re.compile(r"^(\s*)\d+[.)]\s+(.*)")
    _BQUOT = re.compile(r"^>\s*(.*)")
    _FENCE = re.compile(r"^```")
    _HR    = re.compile(r"^[-*_]{3,}\s*$")

    def __init__(self, w: tk.Text):
        self.w = w
        self._setup_tags()

    def _setup_tags(self):
        t = self.w
        t.tag_configure("h1", font=(FF,19,"bold"), foreground=C["purple"],  spacing1=7,spacing3=4)
        t.tag_configure("h2", font=(FF,15,"bold"), foreground=C["indigo"],  spacing1=5,spacing3=3)
        t.tag_configure("h3", font=(FF,13,"bold"), foreground=C["teal"],    spacing1=4,spacing3=2)
        t.tag_configure("h4", font=(FF,12,"bold"), foreground=C["yellow"])
        t.tag_configure("h5", font=(FF,11,"bold"), foreground=C["sub"])
        t.tag_configure("h6", font=(FF,10,"bold"), foreground=C["overlay"])
        t.tag_configure("bold",   font=(FF,11,"bold"))
        t.tag_configure("italic", font=(FF,11,"italic"))
        t.tag_configure("code",   font=(FM,10), background=C["card"], foreground=C["green"])
        t.tag_configure("fence",  font=(FM,10), background=C["card"], foreground=C["yellow"],
                        lmargin1=12,lmargin2=12,spacing1=3,spacing3=3)
        t.tag_configure("quote",  font=(FF,11,"italic"), foreground=C["blue"],
                        lmargin1=18,lmargin2=18,background=C["surface"])
        t.tag_configure("bullet", lmargin1=8,  lmargin2=22)
        t.tag_configure("num",    lmargin1=8,  lmargin2=26)
        t.tag_configure("link",   foreground=C["indigo"], underline=True)
        t.tag_configure("hr",     foreground=C["border"])
        t.tag_configure("normal", font=(FF,11))

    def render(self, text: str):
        w = self.w
        w.configure(state="normal")
        w.delete("1.0", "end")
        lines = text.split("\n")
        in_fence, fbuf = False, []
        for line in lines:
            if self._FENCE.match(line):
                if not in_fence: in_fence, fbuf = True, []
                else:
                    w.insert("end", "\n".join(fbuf)+"\n","fence"); in_fence=False
                continue
            if in_fence: fbuf.append(line); continue
            if self._HR.match(line):   w.insert("end","─"*42+"\n","hr"); continue
            m=self._HEAD.match(line)
            if m: self._inline(m.group(2)+"\n",f"h{len(m.group(1))}"); continue
            m=self._BQUOT.match(line)
            if m: self._inline(m.group(1)+"\n","quote"); continue
            m=self._TASK.match(line)
            if m:
                mark = "☑" if m.group(2).lower() == "x" else "☐"
                self._inline("  "*(len(m.group(1))//2)+f"{mark} {m.group(3)}\n","bullet")
                continue
            m=self._BULL.match(line)
            if m: self._inline("  "*(len(m.group(1))//2)+"• "+m.group(2)+"\n","bullet"); continue
            m=self._NUM.match(line)
            if m: self._inline(line.lstrip()+"\n","num"); continue
            if not line.strip(): w.insert("end","\n","normal"); continue
            self._inline(line+"\n","normal")
        w.configure(state="disabled")

    def _inline(self, text: str, base: str):
        w = self.w
        spans: list = []
        for m in self._BOLD.finditer(text):
            spans.append((m.start(),m.end(),"bold",  m.group(1) or m.group(2)))
        for m in self._ITAL.finditer(text):
            if not any(s[0]<=m.start()<s[1] for s in spans):
                spans.append((m.start(),m.end(),"italic",m.group(1)))
        for m in self._CODE.finditer(text):
            if not any(s[0]<=m.start()<s[1] for s in spans):
                spans.append((m.start(),m.end(),"code",m.group(1)))
        for m in self._LINK.finditer(text):
            if not any(s[0]<=m.start()<s[1] for s in spans):
                spans.append((m.start(),m.end(),"link",m.group(1)))
        if not spans: w.insert("end",text,base); return
        spans.sort(key=lambda x:x[0])
        pos=0
        for s,e,tag,content in spans:
            if pos<s: w.insert("end",text[pos:s],base)
            w.insert("end",content,(base,tag) if base!="normal" else tag)
            pos=e
        if pos<len(text): w.insert("end",text[pos:],base)


# ── Main widget ────────────────────────────────────────────────────────────
class FloatNotes(tk.Tk):
    HEADER_H = 40
    CORNER   = 22   # border-radius px for panel

    def __init__(self):
        super().__init__()
        all_notes       = _load()
        self._notes     = [n for n in all_notes if not n.get("archived")]
        self._archived  = [n for n in all_notes if n.get("archived")]
        self._idx       = 0
        self._mode      = "preview"
        self._state     = "icon"   # icon | panel | animating
        self._dark      = True
        self._idle_job  = None
        self._save_job  = None
        self._ai_job    = None
        self._ai_seq    = 0
        self._ai_auto   = False
        self._ai_busy   = False
        self._ai_text   = ""
        self._pulse_i   = 0
        # drag state
        self._drag_off       = None     # (ox, oy) offset from window origin
        self._drag_moved    = False
        self._transcriber_proc = None   # running Popen handle when recording

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=_TRANSP)
        self.attributes("-transparentcolor", _TRANSP)  # makes bubble corners invisible
        self.attributes("-alpha", 0.0)

        self._place_default()
        self._build_bubble()
        self._build_panel()

        # ── Global drag handling (fires for all widgets) ──────────────────
        self.bind_all("<ButtonPress-1>",   self._g_press)
        self.bind_all("<B1-Motion>",       self._g_motion)
        self.bind_all("<ButtonRelease-1>", self._g_release)
        self.bind_all("<Key>",             self._reset_idle)

        self._show_bubble()
        self.after(60, self._fade_in)
        self._file_mtime   = DATA_FILE.stat().st_mtime if DATA_FILE.exists() else 0
        self._last_save_ts = time.time()
        self.after(2000, self._watch_notes_file)

    def _watch_notes_file(self):
        """Reload notes from disk only when the panel is closed (icon state)."""
        if self._state == "icon" and DATA_FILE.exists():
            mtime = DATA_FILE.stat().st_mtime
            if mtime > self._file_mtime and (time.time() - self._last_save_ts) > 3.0:
                self._file_mtime = mtime
                all_notes    = _load()
                new_active   = [n for n in all_notes if not n.get("archived")]
                new_archived = [n for n in all_notes if n.get("archived")]
                if new_active != self._notes or new_archived != self._archived:
                    if self._notes:
                        self._notes[self._idx]["body"] = self._editor.get("1.0", "end-1c")
                    cur_id = self._notes[self._idx]["id"] if self._notes else None
                    self._notes    = new_active
                    self._archived = new_archived
                    new_idx = next((i for i, n in enumerate(new_active) if n["id"] == cur_id), 0)
                    self._idx = new_idx
                    self._refresh_tabs()
                    self._load_note()
        self.after(2000, self._watch_notes_file)

    # ── Startup position ───────────────────────────────────────────────────
    def _place_default(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{W_ICON}x{W_ICON}+{sw-W_ICON-24}+{sh-W_ICON-60}")

    # ── Global drag / click ────────────────────────────────────────────────
    def _g_press(self, event):
        self._drag_off   = None
        self._drag_moved = False
        # Ignore clicks that originate in a different Toplevel (dialogs etc.)
        widget = getattr(event, "widget", None)
        if not hasattr(widget, "winfo_toplevel"):
            return
        if widget.winfo_toplevel() is not self:
            return
        if getattr(widget, "_no_drag", False):
            return
        if self._state == "icon":
            self._drag_off = (event.x_root - self.winfo_x(),
                              event.y_root - self.winfo_y())
        elif self._state == "panel":
            wy = event.y_root - self.winfo_y()
            if wy <= self.HEADER_H:
                self._drag_off = (event.x_root - self.winfo_x(),
                                  event.y_root - self.winfo_y())
            self._reset_idle()

    def _g_motion(self, event):
        if self._drag_off is None:
            return
        widget = getattr(event, "widget", None)
        if not hasattr(widget, "winfo_toplevel"):
            return
        if widget.winfo_toplevel() is not self:
            return
        ox, oy = self._drag_off
        nx, ny = event.x_root - ox, event.y_root - oy
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        cw, ch = self.winfo_width(), self.winfo_height()
        nx = max(0, min(nx, sw - cw))
        ny = max(0, min(ny, sh - ch))
        # 8 px dead zone so clicking the title entry doesn't accidentally drag
        if abs(nx - self.winfo_x()) > 8 or abs(ny - self.winfo_y()) > 8:
            self._drag_moved = True
        if not self._drag_moved:
            return
        self.geometry(f"+{nx}+{ny}")

    def _g_release(self, event):
        off, moved = self._drag_off, self._drag_moved
        self._drag_off   = None
        self._drag_moved = False
        # Click-to-expand (bubble): press + release without drag
        if self._state == "icon" and off is not None and not moved:
            self._expand()

    # ── Bubble ─────────────────────────────────────────────────────────────
    def _build_bubble(self):
        self._bcanvas = tk.Canvas(
            self, width=W_ICON, height=W_ICON,
            bg=_TRANSP, highlightthickness=0, cursor="hand2",
        )
        r = W_ICON // 2
        self._bshadow = self._bcanvas.create_oval(4,4,W_ICON-4,W_ICON-4, fill=C["bub1"],outline="")
        self._bcirc   = self._bcanvas.create_oval(5,5,W_ICON-5,W_ICON-5, fill=C["bub2"],outline="")
        self._bhigh   = self._bcanvas.create_oval(12,10,W_ICON-14,W_ICON-16,
                                                   fill=C["bub3"],outline="",stipple="gray50")
        self._bglyph  = self._bcanvas.create_text(r, r, text="✏", font=(FF,18), fill="white")
        self._btip    = tk.Label(self, text="Float Notes", bg=C["card"],
                                 fg=C["sub"], font=(FF, 8), padx=6, pady=3)
        self._bcanvas.bind("<Enter>", self._bubble_enter)
        self._bcanvas.bind("<Leave>", self._bubble_leave)

    def _bubble_enter(self, _=None):
        self._bcanvas.itemconfig(self._bcirc, fill=C["bub3"])
        self._btip.place(relx=0.5, rely=-0.1, anchor="s")
        self.after(1400, lambda: self._btip.place_forget())

    def _bubble_leave(self, _=None):
        self._bcanvas.itemconfig(self._bcirc, fill=C["bub2"])
        self._btip.place_forget()

    def _pulse_step(self):
        if self._state != "icon": return
        self._pulse_i += 1
        t = self._pulse_i * 0.05
        s = 1.0 + 0.055 * math.sin(t)
        cx = cy = W_ICON / 2
        r = (W_ICON / 2 - 5) * s
        self._bcanvas.coords(self._bcirc, cx-r, cy-r, cx+r, cy+r)
        self.after(40, self._pulse_step)

    # ── Panel ──────────────────────────────────────────────────────────────
    def _build_panel(self):
        self._panel = tk.Frame(self, bg=C["panel"])
        self._build_header()
        self._build_tabs()
        self._build_toolbar()
        self._build_pane()
        self._build_statusbar()
        self._build_grip()

    def _build_header(self):
        h = tk.Frame(self._panel, bg=C["header"], height=self.HEADER_H)
        h.pack(fill="x")
        h.pack_propagate(False)
        # Accent top border
        tk.Frame(self._panel, bg=C["purple"], height=2).pack(fill="x")

  # Right: theme toggle + library + preview + minimize + close
        right = tk.Frame(h, bg=C["header"])
        right.pack(side="right", padx=1)

        # Left: icon + title
        left = tk.Frame(h, bg=C["header"])
        left.pack(side="left", fill="both", expand=True, padx=(3, 0))
        tk.Label(left, text="✏", bg=C["header"], fg=C["purple"],
                 font=(FF, 13)).pack(side="left", pady=0)
        self._title_var = tk.StringVar()
        self._title_var.trace_add("write", lambda *_: self._on_title_change())
        self._title_entry = tk.Entry(
            left, textvariable=self._title_var,
            bg=C["header"], fg=C["text"],
            insertbackground=C["purple"],
            relief="flat", font=(FF, 11, "bold"),
            selectbackground=C["border"],
            highlightthickness=0, bd=0,
        )
        self._title_entry.pack(side="left", fill="x", expand=True, padx=(4,0))
        # title entry is draggable; 8 px dead zone in _g_motion prevents accidental drag while typing

        # # Right: theme toggle + library + preview + minimize + close
        # right = tk.Frame(h, bg=C["header"])
        # right.pack(side="right", padx=1)

        self._theme_btn = self._hbtn(right, "☀️", self._toggle_theme, hfg=C["yellow"])
        # self._hbtn(right, "✨", self._open_ai_panel, hfg=C["yellow"])
        self._hbtn(right, "📂", self._open_library, hfg=C["teal"])
        self._mode_btn = self._hbtn(right, "👁", self._toggle_mode, hfg=C["purple"])
        self._mic_btn  = self._hbtn(right, "🎙", self._toggle_transcriber, hfg=C["teal"])
        self._hbtn(right, "—", self._collapse, hfg=C["sub"])
        self._hbtn(right, "✕", self.destroy,   hfg=C["red"])

    def _toggle_transcriber(self):
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        # prefer TeamsTranscriber.exe (distributed alongside FloatNotes.exe)
        exe = Path(sys.executable).parent / "TeamsTranscriber.exe"
        if exe.exists():
            os.startfile(str(exe))
            return

        shortcut = base / "Teams Transcriber.lnk"
        if shortcut.exists():
            os.startfile(str(shortcut))
            return

        script = Path(__file__).with_name("teams-transcriber.py")
        if not script.exists():
            self._set_ai_status("Teams transcriber script not found")
            return

        try:
            creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            self._transcriber_proc = subprocess.Popen(
                [sys.executable, str(script), "live"],
                cwd=str(script.parent),
                creationflags=creation_flags,
            )
            self._mic_btn.configure(fg=C["green"])
            self._set_ai_status("Teams transcriber started")
            self.after(1000, self._poll_transcriber)
        except OSError as exc:
            self._set_ai_status(f"Could not start transcriber: {exc}")

    def _poll_transcriber(self):
        """Reset mic button colour when the transcriber process exits."""
        if self._transcriber_proc and self._transcriber_proc.poll() is None:
            self.after(1000, self._poll_transcriber)
        else:
            self._mic_btn.configure(fg=C["overlay"])
            self._transcriber_proc = None

    def _hbtn(self, parent, text, cmd, hfg=None):
        b = tk.Label(parent, text=text, bg=C["header"], fg=C["overlay"],
                     font=(FF, 10), cursor="hand2", padx=2, pady=10)
        b.pack(side="left")
        b._no_drag = True   # prevent global drag from activating on these buttons
        if hfg:
            b.bind("<Enter>", lambda e: b.configure(fg=hfg, bg=C["card"]))
            b.bind("<Leave>", lambda e: b.configure(fg=C["overlay"], bg=C["header"]))
        b.bind("<ButtonPress-1>", lambda e: (cmd(), "break")[1])
        return b

    def _build_tabs(self):
        self._tab_frame = tk.Frame(self._panel, bg=C["surface"], height=30)
        self._tab_frame.pack(fill="x")
        self._tab_frame.pack_propagate(False)
        self._refresh_tabs()

    def _refresh_tabs(self):
        for w in self._tab_frame.winfo_children():
            w.destroy()
        n = len(self._notes)

        def _navbtn(text, side, cmd, active=True):
            fg = C["purple"] if active else C["border"]
            cur = "hand2" if active else "arrow"
            b = tk.Label(self._tab_frame, text=text, bg=C["surface"], fg=fg,
                         font=(FF, 9, "bold"), cursor=cur, padx=5)
            b.pack(side=side, pady=4)
            b._no_drag = True
            if active:
                b.bind("<Enter>",         lambda e: b.configure(bg=C["card"]))
                b.bind("<Leave>",         lambda e: b.configure(bg=C["surface"]))
                b.bind("<ButtonPress-1>", lambda e: (cmd(), "break")[1])

        # Pack right-side items first so they always get space
        np = tk.Label(self._tab_frame, text=" + ", bg=C["surface"],
                      fg=C["purple"], font=(FF,9,"bold"), cursor="hand2", padx=4)
        np.pack(side="right", pady=5, padx=2)
        np._no_drag = True
        np.bind("<Enter>",         lambda e: np.configure(bg=C["card"]))
        np.bind("<Leave>",         lambda e: np.configure(bg=C["surface"]))
        np.bind("<ButtonPress-1>", lambda e: (self._new_note(), "break")[1])

        if n > 1:
            _navbtn("»", "right", lambda: self._switch_note(n - 1), self._idx < n - 1)
            _navbtn("›", "right", lambda: self._switch_note(self._idx + 1), self._idx < n - 1)

        if n > 1:
            _navbtn("«", "left", lambda: self._switch_note(0), self._idx > 0)
            _navbtn("‹", "left", lambda: self._switch_note(self._idx - 1), self._idx > 0)

        # Show a window of up to 4 tabs centred on the active note
        half = 2
        start = max(0, min(self._idx - half, n - 4))
        visible = self._notes[start:start + 4]
        for li, note in enumerate(visible):
            ri = start + li
            active = ri == self._idx
            tbg = C["card"] if active else C["surface"]
            tfg = C["text"] if active else C["sub"]
            tab = tk.Frame(self._tab_frame, bg=tbg, cursor="hand2")
            tab.pack(side="left", fill="y", padx=(2,0), pady=(3 if active else 5, 0))
            title = note["title"][:9]+"…" if len(note["title"])>9 else note["title"]
            lbl = tk.Label(tab, text=title, bg=tbg, fg=tfg, font=(FF,8), padx=5, pady=2)
            lbl.pack(side="left")
            if active and n > 1:
                cl = tk.Label(tab, text="×", bg=tbg, fg=C["overlay"],
                              font=(FF,8), cursor="hand2", padx=3)
                cl.pack(side="left")
                cl._no_drag = True
                cl.bind("<ButtonPress-1>", lambda e, i=ri: (self._confirm_del_note(i), "break")[1])
            for w in (tab, lbl):
                w.bind("<ButtonPress-1>", lambda e, i=ri: self._switch_note(i))

    def _build_toolbar(self):
        tb = tk.Frame(self._panel, bg=C["panel"], pady=3)
        tb.pack(fill="x", padx=6)

        def tbtn(label, cmd):
            b = tk.Label(tb, text=label, bg=C["surface"], fg=C["sub"],
                         font=(FF,8), cursor="hand2", padx=4, pady=4)
            b.pack(side="left", padx=1)
            b._no_drag = True
            b.bind("<Enter>",         lambda e: b.configure(bg=C["card"], fg=C["purple"]))
            b.bind("<Leave>",         lambda e: b.configure(bg=C["surface"], fg=C["sub"]))
            b.bind("<ButtonPress-1>", lambda e: (cmd(), "break")[1])

        tbtn("B",  lambda: self._wrap("**","**"))
        tbtn("I",  lambda: self._wrap("*", "*"))
        tbtn("<>", lambda: self._wrap("`", "`"))
        tbtn("H1", lambda: self._pfx("# "))
        tbtn("H2", lambda: self._pfx("## "))
        tbtn("•",  lambda: self._pfx("- "))
        tbtn("1.", lambda: self._pfx("1. "))
        tbtn("☐",  lambda: self._pfx("- [ ] "))
        tbtn("❝",  lambda: self._pfx("> "))
        tbtn("📋", self._copy_markdown)
        tbtn("✂",  self._start_snip)   # screen-to-text OCR

    def _build_pane(self):
        pane = tk.Frame(self._panel, bg=C["panel"])
        pane.pack(fill="both", expand=True, padx=4, pady=(0,2))
        content = tk.Frame(pane, bg=C["panel"])
        content.pack(fill="both", expand=True)

        # Edit frame
        self._ef = tk.Frame(content, bg=C["panel"])
        vs = ttk.Scrollbar(self._ef, style="Slim.Vertical.TScrollbar")
        vs.pack(side="right", fill="y")
        self._editor = tk.Text(
            self._ef, bg=C["surface"], fg=C["text"],
            insertbackground=C["purple"], selectbackground=C["border"],
            relief="flat", font=(FF,11), wrap="word",
            undo=True, maxundo=80,
            yscrollcommand=vs.set,
            padx=12, pady=10, spacing1=2, spacing3=2,
            highlightthickness=0, bd=0,
        )
        self._editor.pack(side="left", fill="both", expand=True)
        vs.configure(command=self._editor.yview)
        self._editor.bind("<<Modified>>", self._on_edit)
        self._editor.bind("<Return>", self._on_return)

        # Preview frame
        self._pf = tk.Frame(content, bg=C["panel"])
        vs2 = ttk.Scrollbar(self._pf, style="Slim.Vertical.TScrollbar")
        vs2.pack(side="right", fill="y")
        self._preview = tk.Text(
            self._pf, bg=C["surface"], fg=C["text"],
            relief="flat", font=(FF,11), wrap="word",
            state="disabled", cursor="arrow",
            yscrollcommand=vs2.set,
            padx=12, pady=10, spacing1=2, spacing3=2,
            highlightthickness=0, bd=0,
        )
        self._preview.pack(side="left", fill="both", expand=True)
        vs2.configure(command=self._preview.yview)
        self._renderer = MDRenderer(self._preview)
        self._preview.bind("<ButtonPress-1>", self._preview_click)

        self._build_statusbar()
        self._build_ai_assistant(content)
        if self._mode == "edit":
            self._assist.pack(side="bottom", fill="x", padx=4, pady=(0, 2))

        if self._mode == "preview":
            self._pf.pack(fill="both", expand=True)
        else:
            self._ef.pack(fill="both", expand=True)

    def _build_statusbar(self):
        sb = tk.Frame(self._panel, bg=C["bg"], height=22)
        sb.pack(fill="x")
        sb.pack_propagate(False)
        self._sb = sb
        # Right-side items must be packed before the expanding left label
        self._wc_lbl = tk.Label(sb, text="", bg=C["bg"], fg=C["overlay"],
                                font=(FF,8), padx=6)
        self._wc_lbl.pack(side="right")
        self._status_lbl = tk.Label(sb, text="", bg=C["bg"], fg=C["overlay"],
                                    font=(FF,8), anchor="w", padx=10)
        self._status_lbl.pack(side="left", fill="both", expand=True)

    def _build_ai_assistant(self, pane):
        self._assist = tk.Frame(pane, bg=C["surface"])
        top = tk.Frame(self._assist, bg=C["surface"])
        top.pack(fill="x", padx=4, pady=(4, 2))

        tk.Label(top, text="AI", bg=C["surface"], fg=C["purple"],
                 font=(FF, 8, "bold")).pack(side="left", padx=(2, 2))

        self._ai_prompt_var = tk.StringVar(
            value="Improve structure and readability while preserving meaning."
        )
        self._ai_prompt_entry = tk.Entry(
            top, textvariable=self._ai_prompt_var, bg=C["surface"], fg=C["text"],
            insertbackground=C["purple"], relief="flat", font=(FF, 8),
            highlightthickness=0, bd=0,
        )
        self._ai_prompt_entry.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self._ai_prompt_entry._no_drag = True

        self._ai_auto_btn = tk.Label(top, text="Auto OFF", bg=C["card"], fg=C["sub"],
                                     font=(FF, 8, "bold"), cursor="hand2", padx=8, pady=4)
        self._ai_auto_btn.pack(side="left", padx=(0, 4))
        self._ai_auto_btn._no_drag = True
        self._ai_auto_btn.bind("<ButtonPress-1>", lambda e: (self._toggle_ai_auto(), "break")[1])

        self._ai_go_btn = tk.Label(top, text="Suggest", bg=C["purple"], fg=C["panel"],
                                   font=(FF, 8, "bold"), cursor="hand2", padx=8, pady=4)
        self._ai_go_btn.pack(side="left", padx=(0, 4))
        self._ai_go_btn._no_drag = True
        self._ai_go_btn.bind("<ButtonPress-1>", lambda e: (self._kick_ai_suggest(force=True), "break")[1])

        self._ai_apply_btn = tk.Label(top, text="Apply", bg=C["surface"], fg=C["teal"],
                                      font=(FF, 8, "bold"), cursor="hand2", padx=8, pady=4)
        self._ai_apply_btn.pack(side="left")
        self._ai_apply_btn._no_drag = True
        self._ai_apply_btn.bind("<ButtonPress-1>", lambda e: (self._apply_ai_suggestion(), "break")[1])

        self._ai_preview = tk.Text(
            self._assist, height=4, bg=C["panel"], fg=C["text"],
            relief="flat", font=(FF, 8), wrap="word",
            state="disabled", cursor="arrow",
            highlightthickness=0, bd=0,
            padx=8, pady=6,
        )
        self._ai_preview.pack(fill="x", padx=4, pady=(0, 4))
        self._ai_preview._no_drag = True
        self._set_ai_preview("AI suggestion will appear here.")

    def _build_grip(self):
        g = tk.Label(self._panel, text="◢", bg=C["bg"], fg=C["border"],
                     font=(FF,8), cursor="size_nw_se")
        g.place(relx=1.0, rely=1.0, anchor="se")
        g._no_drag = True
        g.bind("<ButtonPress-1>",   self._rsz_start)
        g.bind("<B1-Motion>",       self._rsz_move)
        g.bind("<ButtonRelease-1>", self._rsz_end)
        self._rsz_data = None

    def _set_ai_preview(self, text: str):
        if not hasattr(self, "_ai_preview"):
            return
        self._ai_preview.configure(state="normal")
        self._ai_preview.delete("1.0", "end")
        self._ai_preview.insert("1.0", text)
        self._ai_preview.configure(state="disabled")

    def _set_ai_status(self, text: str):
        if hasattr(self, "_status_lbl"):
            self._status_lbl.configure(text=text)

    def _toggle_ai_auto(self):
        if self._mode != "edit":
            return
        self._ai_auto = not self._ai_auto
        if hasattr(self, "_ai_auto_btn"):
            if self._ai_auto:
                self._ai_auto_btn.configure(text="Auto ON", bg=C["purple"], fg=C["panel"])
                self._kick_ai_suggest(force=True)
            else:
                self._ai_auto_btn.configure(text="Auto OFF", bg=C["card"], fg=C["sub"])
                if self._ai_job:
                    self.after_cancel(self._ai_job)
                    self._ai_job = None
                self._set_ai_status("AI auto mode off")

    def _kick_ai_suggest(self, force: bool = False):
        if self._mode != "edit":
            return
        if not force and not self._ai_auto:
            return
        if self._ai_job:
            self.after_cancel(self._ai_job)
        self._ai_job = self.after(900 if not force else 1, self._run_ai_suggest)

    def _ai_target_text(self) -> tuple[str, str]:
        try:
            selected = self._editor.get("sel.first", "sel.last").strip()
            if selected:
                return selected, "selection"
        except tk.TclError:
            pass
        return self._editor.get("1.0", "end-1c").strip(), "note"

    def _run_ai_suggest(self):
        self._ai_job = None
        if self._mode != "edit":
            return
        target_text, target_kind = self._ai_target_text()
        if not target_text:
            self._set_ai_preview("Type some text first, then ask the model to improve it.")
            return

        prompt = self._ai_prompt_var.get().strip() if hasattr(self, "_ai_prompt_var") else ""
        seq = self._ai_seq = self._ai_seq + 1
        self._ai_busy = True
        self._set_ai_status("⏳ Generating AI suggestion…")
        self._set_ai_preview("Thinking…")

        def _work():
            try:
                result = _note_ai_generate(target_text, prompt)
            except Exception as exc:
                result = f"[AI error: {exc}]"

            def _done():
                if seq != self._ai_seq:
                    return
                self._ai_busy = False
                self._set_ai_preview(result)
                self._set_ai_status(f"✓ AI suggestion ready ({target_kind})")

            self.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    def _apply_ai_suggestion(self):
        if not hasattr(self, "_ai_preview"):
            return
        txt = self._ai_preview.get("1.0", "end-1c").strip()
        if not txt or txt in {"Thinking…", "AI suggestion will appear here."}:
            return
        try:
            self._editor.edit_separator()
            if self._editor.tag_ranges("sel"):
                self._editor.delete("sel.first", "sel.last")
                self._editor.insert("insert", txt)
            else:
                self._editor.delete("1.0", "end")
                self._editor.insert("1.0", txt)
            self._on_edit()
            self._set_ai_status("✓ Applied AI suggestion")
        except tk.TclError:
            pass

    # ── Show / hide ────────────────────────────────────────────────────────
    def _show_bubble(self):
        self._panel.pack_forget()
        self._bcanvas.place(x=0, y=0, width=W_ICON, height=W_ICON)
        self._state = "icon"
        self.configure(bg=_TRANSP)
        self.update_idletasks()
        self._pulse_i = 0
        self._pulse_step()

    def _show_panel_ui(self):
        self._bcanvas.place_forget()
        self._btip.place_forget()
        self._panel.pack(fill="both", expand=True)
        self.configure(bg=C["panel"])

    # ── Expand animation ───────────────────────────────────────────────────
    def _expand(self):
        if self._state != "icon": return
        self._state = "animating"
        ix, iy = self.winfo_x(), self.winfo_y()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        px = max(0, min(ix - W_PANEL + W_ICON, sw - W_PANEL))
        py = max(0, min(iy - H_PANEL + W_ICON, sh - H_PANEL))
        _set_rgn(self.winfo_id(), sw, sh)  # clear clip during animation
        # Hide bubble; show only the panel background colour — content revealed after
        self._bcanvas.place_forget()
        self._btip.place_forget()
        self.configure(bg=C["panel"])

        def step(f):
            if f > AF:
                self._show_panel_ui()
                self._state = "panel"
                self._load_note()
                self._editor.focus_set()
                self.update_idletasks()
                _set_rgn(self.winfo_id(), self.winfo_width(), self.winfo_height(),
                         r=self.CORNER * 2)
                self.after(400, self._hover_monitor)  # start hover-based collapse
                return
            t = 1 - (1 - f/AF)**3
            self.geometry(f"{int(W_ICON+(W_PANEL-W_ICON)*t)}x"
                          f"{int(W_ICON+(H_PANEL-W_ICON)*t)}+"
                          f"{int(ix+(px-ix)*t)}+{int(iy+(py-iy)*t)}")
            self.after(AM, lambda: step(f+1))
        step(0)

    # ── Collapse animation ─────────────────────────────────────────────────
    def _collapse(self):
        if self._state != "panel": return
        self._cancel_idle()
        self._flush_save()
        self._state = "animating"
        cx, cy = self.winfo_x(), self.winfo_y()
        tx = cx + self.winfo_width()  - W_ICON
        ty = cy + self.winfo_height() - W_ICON
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        _set_rgn(self.winfo_id(), sw, sh)  # clear clip during animation

        def step(f):
            if f > AF:
                self.geometry(f"{W_ICON}x{W_ICON}+{tx}+{ty}")
                self._show_bubble()
                return
            t = 1 - (1 - f/AF)**3
            cw = self.winfo_width()
            ch = self.winfo_height()
            self.geometry(f"{int(cw+(W_ICON-cw)*t)}x"
                          f"{int(ch+(W_ICON-ch)*t)}+"
                          f"{int(cx+(tx-cx)*t)}+{int(cy+(ty-cy)*t)}")
            self.after(AM, lambda: step(f+1))
        step(0)

    # ── Fade in ────────────────────────────────────────────────────────────
    def _fade_in(self, a: float = 0.0):
        a = min(1.0, a + 0.14)
        self.attributes("-alpha", a)
        if a < 1.0: self.after(18, lambda: self._fade_in(a))

    # ── Hover-based collapse ────────────────────────────────────────────────
    def _hover_monitor(self):
        """Poll every 350 ms; cancel collapse while cursor is inside the window."""
        if self._state != "panel":
            return
        try:
            mx, my = self.winfo_pointerxy()
            wx, wy = self.winfo_x(), self.winfo_y()
            ww, wh = self.winfo_width(), self.winfo_height()
            if wx <= mx <= wx + ww and wy <= my <= wy + wh:
                self._cancel_idle()           # cursor inside — keep open
            elif self._idle_job is None:
                self._idle_job = self.after(IDLE_MS, self._collapse)  # cursor left
        except tk.TclError:
            return
        self.after(350, self._hover_monitor)

    # ── Idle timer ─────────────────────────────────────────────────────────
    def _reset_idle(self, *_):
        self._cancel_idle()
        if self._state == "panel":
            self._idle_job = self.after(IDLE_MS, self._collapse)

    def _cancel_idle(self):
        if self._idle_job:
            self.after_cancel(self._idle_job)
            self._idle_job = None

    # ── Theme toggle ───────────────────────────────────────────────────────
    def _toggle_theme(self):
        self._dark = not self._dark
        C.update({**DARK, **BUB} if self._dark else {**LIGHT, **BUB})
        # Save current note text before rebuilding
        body = self._editor.get("1.0","end-1c")
        self._notes[self._idx]["body"] = body
        old_mode = self._mode
        self._panel.destroy()
        self._build_panel()
        self._panel.pack(fill="both", expand=True)
        self.configure(bg=C["panel"])
        self._mode = "preview"   # reset to preview, then restore
        self._load_note()
        if old_mode == "edit": self._toggle_mode()
        self._theme_btn.configure(text="☀️" if self._dark else "🌙")
        self.update_idletasks()
        _set_rgn(self.winfo_id(), self.winfo_width(), self.winfo_height(), r=self.CORNER*2)
        self.after(400, self._hover_monitor)

    # ── Note CRUD ──────────────────────────────────────────────────────────
    def _load_note(self):
        note = self._notes[self._idx]
        self._title_var.set(note["title"])
        self._editor.delete("1.0","end")
        self._editor.insert("1.0", note["body"])
        self._editor.edit_modified(False)
        self._editor.edit_reset()
        if hasattr(self, "_ai_preview"):
            self._set_ai_preview("AI suggestion will appear here.")
            self._set_ai_status("")
        if self._mode == "preview": self._renderer.render(note["body"])
        self._update_wc()

    def _new_note(self):
        self._flush_save()
        note = {"id": str(uuid.uuid4()), "title": "New Note",
                "body": "", "created": datetime.now().isoformat()}
        self._notes.append(note)
        self._idx = len(self._notes) - 1
        self._refresh_tabs()
        if self._mode == "preview": self._toggle_mode()  # new notes start in edit mode
        self._load_note()
        self._title_entry.focus_set()
        self._title_entry.select_range(0,"end")
        self._reset_idle()

    def _confirm_del_note(self, idx: int):
        """Ask keep/delete before removing a note."""
        note = self._notes[idx]
        d = tk.Toplevel(self)
        d.title("Close note")
        d.resizable(False, False)
        d.configure(bg=C["bg"])
        d.attributes("-topmost", True)

        tk.Frame(d, bg=C["purple"], height=3).pack(fill="x")
        tk.Label(d, text="Close note", bg=C["bg"], fg=C["text"],
                 font=(FF, 11, "bold"), padx=18, pady=10).pack(anchor="w", pady=(6, 0))
        preview = note["body"][:60].replace("\n", " ") + ("…" if len(note["body"]) > 60 else "")
        tk.Label(d, text=f"“{preview}”", bg=C["bg"], fg=C["sub"],
                 font=(FF, 9), padx=18, wraplength=260, justify="left").pack(anchor="w")
        tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=18, pady=10)

        btn_row = tk.Frame(d, bg=C["bg"])
        btn_row.pack(padx=18, pady=(0, 16), fill="x")

        def _btn(parent, text, bg, fg, cmd):
            b = tk.Label(parent, text=text, bg=bg, fg=fg,
                         font=(FF, 9, "bold"), cursor="hand2", padx=14, pady=6)
            b.pack(side="left", padx=(0, 8))
            b.bind("<ButtonPress-1>", lambda e: (cmd(), "break")[1])
            b.bind("<Enter>", lambda e: b.configure(bg=C["card"]))
            b.bind("<Leave>", lambda e: b.configure(bg=bg))

        def do_keep():
            d.destroy()
            # Archive: keep in JSON but close from the active pane
            note["archived"] = True
            self._archived.append(self._notes.pop(idx))
            _save_all(self._notes, self._archived)
            new_idx = max(0, idx - 1) if self._notes else 0
            self._idx = new_idx
            self._refresh_tabs()
            if self._notes:
                self._load_note()

        def do_delete():
            d.destroy()
            self._del_note(idx)

        _btn(btn_row, "Keep",   C["surface"],  C["text"],  do_keep)
        _btn(btn_row, "Delete", C["red"],      "#000",    do_delete)
        _btn(btn_row, "Cancel", C["surface"],  C["sub"],   d.destroy)

        d.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - d.winfo_width())  // 2
        y = self.winfo_y() + (self.winfo_height() - d.winfo_height()) // 2
        d.geometry(f"+{max(0,x)}+{max(0,y)}")
        d.lift()
        d.focus_force()
        d.bind("<Escape>", lambda _: d.destroy())

    def _open_ai_panel(self):
        if hasattr(self, "_ai_win") and self._ai_win and self._ai_win.winfo_exists():
            self._ai_win.lift(); return

        note_body = self._editor.get("1.0", "end-1c")

        d = tk.Toplevel(self)
        d.title("✨ AI Assistant")
        d.configure(bg=C["bg"])
        d.resizable(True, True)
        d.attributes("-topmost", True)
        self._ai_win = d

        tk.Frame(d, bg=C["purple"], height=3).pack(fill="x")
        hdr = tk.Frame(d, bg=C["header"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="✨  AI Assistant", bg=C["header"], fg=C["text"],
                 font=(FF, 12, "bold"), padx=14, pady=10).pack(side="left")
        engine_var = tk.StringVar(value="detecting…")
        tk.Label(hdr, textvariable=engine_var, bg=C["header"], fg=C["sub"],
                 font=(FF, 8), padx=6).pack(side="left")

        def _detect_engine():
            ok, m = _ollama_available()
            engine_var.set(f"Ollama · {m}" if ok else "Ollama unavailable")
        threading.Thread(target=_detect_engine, daemon=True).start()

        # Quick-action row
        qa_frame = tk.Frame(d, bg=C["surface"])
        qa_frame.pack(fill="x", padx=10, pady=(8, 2))

        def _qabtn(text, prompt_fn):
            b = tk.Label(qa_frame, text=text, bg=C["card"], fg=C["sub"],
                         font=(FF, 8), cursor="hand2", padx=8, pady=5)
            b.pack(side="left", padx=(0, 4))
            b.bind("<Enter>", lambda e: b.configure(fg=C["purple"]))
            b.bind("<Leave>", lambda e: b.configure(fg=C["sub"]))
            b.bind("<ButtonPress-1>", lambda e: (run_ai(prompt_fn()), "break")[1])

        _qabtn("Summarise",    lambda: f"Summarise this note in 2-3 sentences:\n\n{note_body}")
        _qabtn("Fix grammar",  lambda: f"Fix grammar and spelling, keep original meaning:\n\n{note_body}")
        _qabtn("Make shorter", lambda: f"Make this more concise while keeping all key info:\n\n{note_body}")
        _qabtn("Continue →",  lambda: f"Continue writing the following note naturally:\n\n{note_body}")

        # Custom prompt
        pf = tk.Frame(d, bg=C["surface"])
        pf.pack(fill="x", padx=10, pady=4)
        prompt_var = tk.StringVar()
        pe = tk.Entry(pf, textvariable=prompt_var, bg=C["surface"], fg=C["text"],
                      insertbackground=C["purple"], relief="flat", font=(FF, 10),
                      highlightthickness=0, bd=0)
        pe.pack(side="left", fill="x", expand=True, padx=(6, 4), pady=6)
        pe.insert(0, "Ask anything about this note…")
        pe.bind("<FocusIn>",  lambda e: pe.delete(0, "end") if pe.get().startswith("Ask") else None)
        pe.bind("<Return>",   lambda e: run_ai(
            f"{prompt_var.get().strip()}\n\nNote content:\n{note_body}"))
        send_btn = tk.Label(pf, text="Send", bg=C["purple"], fg=C["panel"],
                            font=(FF, 8, "bold"), cursor="hand2", padx=10, pady=6)
        send_btn.pack(side="right", padx=(0, 4))
        send_btn.bind("<ButtonPress-1>", lambda e: run_ai(
            f"{prompt_var.get().strip()}\n\nNote content:\n{note_body}"))

        # Response area
        resp_frame = tk.Frame(d, bg=C["panel"])
        resp_frame.pack(fill="both", expand=True, padx=10, pady=(4, 2))
        resp_vs = ttk.Scrollbar(resp_frame, style="Slim.Vertical.TScrollbar")
        resp_vs.pack(side="right", fill="y")
        resp_txt = tk.Text(resp_frame, bg=C["surface"], fg=C["text"],
                           font=(FF, 10), wrap="word", relief="flat",
                           yscrollcommand=resp_vs.set, state="disabled",
                           insertbackground=C["purple"])
        resp_txt.pack(fill="both", expand=True)
        resp_vs.configure(command=resp_txt.yview)

        # Bottom bar
        bot = tk.Frame(d, bg=C["bg"])
        bot.pack(fill="x", padx=10, pady=(2, 8))
        status_lbl = tk.Label(bot, text="", bg=C["bg"], fg=C["sub"], font=(FF, 8), anchor="w")
        status_lbl.pack(side="left", fill="x", expand=True)

        def _insert_response():
            txt = resp_txt.get("1.0", "end-1c").strip()
            if txt:
                self._editor.insert("insert", "\n" + txt)
                self._on_edit()
        ins_btn = tk.Label(bot, text="Insert into note ↩", bg=C["card"], fg=C["purple"],
                           font=(FF, 8, "bold"), cursor="hand2", padx=10, pady=5)
        ins_btn.pack(side="right")
        ins_btn.bind("<ButtonPress-1>", lambda e: (_insert_response(), "break")[1])

        def run_ai(prompt: str):
            if not prompt.strip() or prompt.startswith("Ask"):
                return
            resp_txt.configure(state="normal")
            resp_txt.delete("1.0", "end")
            resp_txt.configure(state="disabled")
            status_lbl.configure(text="⏳ Thinking…")
            send_btn.configure(bg=C["border"])

            def _work():
                try:
                    result = _ai_run(prompt)
                except Exception as ex:
                    result = f"[AI error: {ex}]"
                def _done():
                    resp_txt.configure(state="normal")
                    resp_txt.insert("end", result)
                    resp_txt.configure(state="disabled")
                    status_lbl.configure(text="✓ Done")
                    send_btn.configure(bg=C["purple"])
                d.after(0, _done)
            threading.Thread(target=_work, daemon=True).start()

        # Mousewheel for response box
        def _mw(e): resp_txt.yview_scroll(int(-1*(e.delta/120)), "units")
        d.bind_all("<MouseWheel>", _mw)
        d.bind("<Destroy>", lambda e: d.unbind_all("<MouseWheel>"))

        d.update_idletasks()
        w_ai, h_ai = 340, 420
        x = self.winfo_x() + self.winfo_width() + 8
        sw = self.winfo_screenwidth()
        if x + w_ai > sw: x = self.winfo_x() - w_ai - 8
        y = self.winfo_y()
        d.geometry(f"{w_ai}x{h_ai}+{max(0,x)}+{max(0,y)}")
        pe.focus_set()
        d.bind("<Escape>", lambda _: d.destroy())

    def _open_library(self):
        """Browse all saved notes; click a row to switch to it."""
        if hasattr(self, "_lib_win") and self._lib_win and self._lib_win.winfo_exists():
            self._lib_win.lift()
            return
        d = tk.Toplevel(self)
        d.title("Notes Library")
        d.configure(bg=C["bg"])
        d.resizable(True, True)
        d.attributes("-topmost", True)
        self._lib_win = d

        tk.Frame(d, bg=C["purple"], height=3).pack(fill="x")
        hdr = tk.Frame(d, bg=C["header"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="📂  Notes Library", bg=C["header"], fg=C["text"],
                 font=(FF, 12, "bold"), padx=14, pady=10).pack(side="left")
        total = len(self._notes) + len(self._archived)
        tk.Label(hdr, text=f"{len(self._notes)} active  {len(self._archived)} archived",
                 bg=C["header"], fg=C["sub"], font=(FF, 9), padx=6).pack(side="left")

        # Search bar
        sf = tk.Frame(d, bg=C["surface"])
        sf.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(sf, text="🔍", bg=C["surface"], fg=C["sub"], font=(FF,10), padx=6).pack(side="left")
        sv = tk.StringVar()
        se = tk.Entry(sf, textvariable=sv, bg=C["surface"], fg=C["text"],
                      insertbackground=C["purple"], relief="flat", font=(FF, 10),
                      highlightthickness=0, bd=0)
        se.pack(side="left", fill="x", expand=True, pady=6)

        # Scrollable list
        list_outer = tk.Frame(d, bg=C["bg"])
        list_outer.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        canvas = tk.Canvas(list_outer, bg=C["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["bg"])
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _refresh_list(query=""):
            for w in inner.winfo_children():
                w.destroy()
            q = query.lower()
            # active notes first, then archived
            all_rows = [(i, n, False) for i, n in enumerate(self._notes)] + \
                       [(i, n, True)  for i, n in enumerate(self._archived)]
            shown = [(ri, n, arch) for ri, n, arch in all_rows
                     if not q or q in n["title"].lower() or q in n["body"].lower()]
            for i, (ri, note, archived) in enumerate(shown):
                active = (not archived) and ri == self._idx
                row_bg = C["card"] if active else (C["surface"] if i % 2 == 0 else C["bg"])
                row = tk.Frame(inner, bg=row_bg, cursor="hand2")
                row.pack(fill="x", pady=1)
                title_txt = note["title"] or "Untitled"
                if archived: title_txt = "📦 " + title_txt
                words = len(note["body"].split()) if note["body"].strip() else 0
                date  = note.get("created", "")[:10]
                tk.Label(row, text=title_txt, bg=row_bg, fg=C["sub"] if archived else C["text"],
                         font=(FF, 10, "bold"), padx=12, pady=6, anchor="w").pack(side="left")
                tk.Label(row, text=f"{words}w  {date}", bg=row_bg, fg=C["sub"],
                         font=(FF, 8), padx=8).pack(side="right")
                def _open(idx=ri, is_arch=archived, note=note):
                    if is_arch:
                        # Unarchive: move back to active notes
                        note.pop("archived", None)
                        self._archived.pop(self._archived.index(note))
                        self._notes.append(note)
                        _save_all(self._notes, self._archived)
                        self._idx = len(self._notes) - 1
                    else:
                        self._flush_save()
                        self._idx = idx
                    self._refresh_tabs()
                    self._load_note()
                    d.destroy()
                row.bind("<ButtonPress-1>", lambda e, fn=_open: fn())
                for child in row.winfo_children():
                    child.bind("<ButtonPress-1>", lambda e, fn=_open: fn())
                row.bind("<Enter>", lambda e, r=row, b=row_bg: r.configure(bg=C["border"]))
                row.bind("<Leave>", lambda e, r=row, b=row_bg: r.configure(bg=b))
            inner.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(inner_id, width=e.width))

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        d.bind_all("<MouseWheel>", _on_mousewheel)
        d.bind("<Destroy>", lambda e: d.unbind_all("<MouseWheel>"))

        sv.trace_add("write", lambda *_: _refresh_list(sv.get()))
        _refresh_list()

        d.transient(self)
        d.update_idletasks()
        total_notes = len(self._notes) + len(self._archived)
        w_lib, h_lib = 340, min(520, 120 + total_notes * 40)
        x = self.winfo_x() - w_lib - 8
        if x < 0: x = self.winfo_x() + self.winfo_width() + 8
        y = self.winfo_y()
        d.geometry(f"{w_lib}x{h_lib}+{max(0,x)}+{max(0,y)}")
        se.focus_set()
        d.bind("<Escape>", lambda _: d.destroy())

    def _del_note(self, idx: int):
        if len(self._notes) <= 1: return
        self._notes.pop(idx)
        self._idx = max(0, idx - 1)
        _save_all(self._notes, self._archived)
        self._refresh_tabs()
        self._load_note()

    def _switch_note(self, idx: int):
        if idx == self._idx: return
        self._flush_save()
        self._idx = idx
        self._refresh_tabs()
        self._load_note()
        self._reset_idle()

    def _flush_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
            self._save_job = None
        if self._notes:
            self._notes[self._idx]["body"] = self._editor.get("1.0","end-1c")
            _save_all(self._notes, self._archived)
            self._last_save_ts = time.time()
            self._file_mtime   = DATA_FILE.stat().st_mtime if DATA_FILE.exists() else 0

    # ── Edit ───────────────────────────────────────────────────────────────
    def _on_edit(self, _=None):
        if not self._editor.edit_modified(): return
        self._editor.edit_modified(False)
        body = self._editor.get("1.0","end-1c")
        self._notes[self._idx]["body"] = body
        self._update_wc()
        if self._save_job: self.after_cancel(self._save_job)
        self._save_job = self.after(900, self._autosave)
        if self._mode == "preview": self._renderer.render(body)
        if self._ai_auto:
            self._kick_ai_suggest()

    def _autosave(self):
        _save_all(self._notes, self._archived)
        self._status_lbl.configure(text="saved ✓")
        self.after(1800, lambda: self._status_lbl.configure(text=""))
        self._save_job = None

    def _on_title_change(self):
        if self._notes:
            self._notes[self._idx]["title"] = self._title_var.get()
            self._refresh_tabs()

    def _update_wc(self):
        body  = self._editor.get("1.0","end-1c")
        words = len(body.split()) if body.strip() else 0
        self._wc_lbl.configure(text=f"{words}w")

    # ── Toolbar ────────────────────────────────────────────────────────────
    def _on_return(self, event):
        """Continue bullet or numbered list on Enter; double-Enter breaks out."""
        line_start = self._editor.index("insert linestart")
        line_text  = self._editor.get(line_start, "insert lineend")
        # Bullet list
        m = re.match(r'^(\s*)([-*+])\s+(.*)', line_text)
        if m:
            indent, marker, content = m.group(1), m.group(2), m.group(3)
            if not content.strip():          # empty item → break out of list
                self._editor.delete(line_start, "insert lineend")
                return
            self._editor.insert("insert", f"\n{indent}{marker} ")
            return "break"
        # Numbered list
        m = re.match(r'^(\s*)(\d+)([.)])\s+(.*)', line_text)
        if m:
            indent, num, sep, content = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            if not content.strip():          # empty item → break out of list
                self._editor.delete(line_start, "insert lineend")
                return
            self._editor.insert("insert", f"\n{indent}{num+1}{sep} ")
            return "break"

    def _copy_markdown(self):
        try:
            txt = self._editor.get("sel.first", "sel.last")
        except tk.TclError:
            txt = self._editor.get("1.0", "end-1c")
        if not txt:
            return
        self.clipboard_clear()
        self.clipboard_append(txt)
        self._set_ai_status("Copied to clipboard")
        self.after(1600, lambda: self._set_ai_status(""))
        self._reset_idle()

    def _wrap(self, a: str, b: str):
        if self._mode == "preview": self._toggle_mode()
        try:
            sel = self._editor.get("sel.first","sel.last")
            self._editor.delete("sel.first","sel.last")
            self._editor.insert("insert",f"{a}{sel}{b}")
        except tk.TclError:
            self._editor.insert("insert",f"{a}{b}")
            r,c = map(int, self._editor.index("insert").split("."))
            self._editor.mark_set("insert",f"{r}.{c-len(b)}")
        self._editor.focus_set()
        self._reset_idle()

    def _pfx(self, m: str):
        if self._mode == "preview": self._toggle_mode()
        try:
            s = self._editor.index("sel.first linestart")
            e = self._editor.index("sel.last lineend")
            lines = self._editor.get(s,e).split("\n")
            self._editor.delete(s,e)
            self._editor.insert(s, "\n".join(m+l for l in lines))
        except tk.TclError:
            self._editor.insert(self._editor.index("insert linestart"), m)
        self._editor.focus_set()
        self._reset_idle()

    def _preview_click(self, e):
        if self._mode != "preview":
            return
        idx = self._preview.index(f"@{e.x},{e.y}")
        line_no = int(idx.split(".")[0])
        body = self._editor.get("1.0", "end-1c")
        lines = body.split("\n")
        if line_no < 1 or line_no > len(lines):
            return
        line = lines[line_no - 1]
        m = re.match(r"^(\s*[-*+]\s+)\[( |x|X)\](\s+.*)$", line)
        if not m:
            return
        mark = "x" if m.group(2) == " " else " "
        lines[line_no - 1] = f"{m.group(1)}[{mark}]{m.group(3)}"
        new_body = "\n".join(lines)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", new_body)
        self._editor.edit_modified(False)
        self._notes[self._idx]["body"] = new_body
        self._renderer.render(new_body)
        self._update_wc()
        self._autosave()
        return "break"

    def _toggle_mode(self):
        if self._mode == "edit":
            self._mode = "preview"
            self._ef.pack_forget()
            if hasattr(self, "_assist"):
                self._assist.pack_forget()
            self._pf.pack(fill="both", expand=True)
            self._renderer.render(self._editor.get("1.0","end-1c"))
            self._mode_btn.configure(text="✏", fg=C["teal"], bg=C["card"])
        else:
            self._mode = "edit"
            self._pf.pack_forget()
            if hasattr(self, "_assist"):
                self._assist.pack(side="bottom", fill="x", padx=4, pady=(0, 2))
                self._set_ai_status("")
            self._ef.pack(fill="both", expand=True)
            self._mode_btn.configure(text="👁", fg=C["overlay"], bg=C["header"])
            self._editor.focus_set()
        self._reset_idle()

    # ── Resize grip ────────────────────────────────────────────────────────
    def _rsz_start(self, e):
        self._rsz_data = (e.x_root, e.y_root, self.winfo_width(), self.winfo_height())

    def _rsz_move(self, e):
        if not self._rsz_data: return
        rx,ry,w0,h0 = self._rsz_data
        nw = max(300, w0 + e.x_root - rx)
        nh = max(300, h0 + e.y_root - ry)
        self.geometry(f"{nw}x{nh}")
        self.update_idletasks()
        _set_rgn(self.winfo_id(), nw, nh, r=self.CORNER*2)
        self._reset_idle()

    def _rsz_end(self, _):
        self._rsz_data = None

    # ── Cleanup ────────────────────────────────────────────────────────────
    def destroy(self):
        self._cancel_idle()
        self._flush_save()
        super().destroy()

    # ── Snip-to-text ──────────────────────────────────────────────────
    def _start_snip(self):
        self._cancel_idle()
        self.withdraw()
        self.after(120, self._launch_overlay)  # wait for widget to disappear from screen

    def _launch_overlay(self):
        SnipOverlay(self._on_snip_done)

    def _on_snip_done(self, bbox: tuple):
        x1, y1, x2, y2 = bbox
        region_info = f"({x1},{y1})→({x2},{y2})  {x2-x1}×{y2-y1}px"
        
        def run():
            time.sleep(0.15)   # let overlay fully close
            img_path = None
            try:
                img_path = _capture_region(bbox)
            except Exception as e:
                self.after(0, lambda: (self.deiconify(), self._insert_ocr_text(f"[Capture: {e}]")))
                return

            def show_working():
                self.deiconify()
                self.attributes("-topmost", True)
                self.lift()
                # Flash red border so user can confirm the captured region
                try:
                    f = tk.Toplevel()
                    f.overrideredirect(True)
                    f.attributes("-topmost", True)
                    f.attributes("-alpha", 0.65)
                    f.configure(bg="#ff3366")
                    f.geometry(f"{x2-x1}x{y2-y1}+{x1}+{y1}")
                    f.after(700, f.destroy)
                except Exception:
                    pass
                if hasattr(self, "_status_lbl"):
                    self._status_lbl.configure(text=f"✂ {region_info}  — Showing preview…")
            self.after(0, show_working)
            
            # Show preview dialog on main thread and wait for response
            result = [None]
            
            def show_preview():
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(img_path)
                    # Resize for preview if too large
                    max_preview = 400
                    if img.width > max_preview or img.height > max_preview:
                        img.thumbnail((max_preview, max_preview), Image.LANCZOS)
                    
                    d = tk.Toplevel(self)
                    d.title("✂ Capture Preview")
                    d.resizable(False, False)
                    d.configure(bg=C["bg"])
                    
                    # Show image
                    photo = ImageTk.PhotoImage(img)
                    lbl_img = tk.Label(d, image=photo, bg=C["bg"])
                    lbl_img.image = photo
                    lbl_img.pack(padx=5, pady=5)
                    
                    # Info label
                    info = tk.Label(d, text=f"Region: {region_info}\nDoes this look correct?", 
                                   font=(FF, 10), fg=C["text"], bg=C["bg"])
                    info.pack(pady=5)
                    
                    # Buttons
                    btn_frame = tk.Frame(d, bg=C["bg"])
                    btn_frame.pack(pady=5)
                    
                    def on_extract():
                        result[0] = True
                        d.destroy()
                    
                    def on_cancel():
                        result[0] = False
                        d.destroy()
                    
                    tk.Button(btn_frame, text="✓ Extract", bg=C["green"], fg="#000", 
                             font=(FF, 10, "bold"), command=on_extract,
                             relief="flat", padx=12, pady=6).pack(side="left", padx=5)
                    tk.Button(btn_frame, text="✗ Cancel", bg=C["red"], fg="#000",
                             font=(FF, 10, "bold"), command=on_cancel,
                             relief="flat", padx=12, pady=6).pack(side="left", padx=5)
                    
                    d.transient(self)
                    d.grab_set()
                    d.attributes("-topmost", True)
                    # Center on parent
                    d.update_idletasks()
                    x = self.winfo_x() + (self.winfo_width() - d.winfo_width()) // 2
                    y = self.winfo_y() + (self.winfo_height() - d.winfo_height()) // 2
                    d.geometry(f"+{max(0, x)}+{max(0, y)}")
                    
                    # Poll for dialog close
                    def wait_for_dialog():
                        if d.winfo_exists():
                            self.after(50, wait_for_dialog)
                        else:
                            # Dialog closed, proceed with OCR if approved
                            proceed_with_ocr()
                    self.after(50, wait_for_dialog)
                    
                except Exception as e:
                    print(f"Preview error: {e}")
                    result[0] = True  # fallback: proceed anyway
                    proceed_with_ocr()
            
            def proceed_with_ocr():
                if result[0] is False:
                    # User cancelled
                    if hasattr(self, "_status_lbl"):
                        self._status_lbl.configure(text="✂ Cancelled")
                        self.after(2000, lambda: self._status_lbl.configure(text=""))
                    if img_path and os.path.exists(img_path):
                        try: os.unlink(img_path)
                        except Exception: pass
                    return
                
                # Proceed with OCR
                if hasattr(self, "_status_lbl"):
                    self._status_lbl.configure(text=f"✂ {region_info}  — OCR running…")
                
                try:
                    text = _ocr_image(img_path)
                except Exception as e:
                    text = f"[OCR error: {e}]"
                finally:
                    if img_path and os.path.exists(img_path):
                        try: os.unlink(img_path)
                        except Exception: pass

                def done():
                    self._insert_ocr_text(text)
                    if hasattr(self, "_status_lbl"):
                        ok = bool(text) and not text.startswith("[")
                        lbl = "✂ Done" if ok else ("✂ " + text[:45])
                        self._status_lbl.configure(text=lbl)
                        self.after(3500, lambda: self._status_lbl.configure(text=""))
                    self.after(400, self._hover_monitor)
                self.after(0, done)
            
            # Show preview on main thread
            self.after(0, show_preview)

        threading.Thread(target=run, daemon=True).start()

    def _insert_ocr_text(self, text: str):
        if self._mode == "preview":
            self._toggle_mode()
        self._editor.insert("insert", text)
        self._editor.focus_set()
        if hasattr(self, "_status_lbl"):
            ok = text and not text.startswith("[")
            self._status_lbl.configure(text="✂ Done" if ok else "✂ Failed")
            self.after(2500, lambda: self._status_lbl.configure(text=""))
        self.after(400, self._hover_monitor)


def _style(root: tk.Tk):
    s = ttk.Style(root)
    s.theme_use("clam")
    for n in ("Slim.Vertical.TScrollbar", "Vertical.TScrollbar"):
        s.configure(n, background=C["scrollbar"], troughcolor=C["surface"],
                    borderwidth=0, arrowsize=0, width=5)
        s.map(n, background=[("active", C["purple"])])


if __name__ == "__main__":
    app = FloatNotes()
    _style(app)
    app.mainloop()