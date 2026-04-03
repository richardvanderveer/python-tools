"""
TranscribeApp - Volledig werkende pipeline
==========================================
Bestand  : transcribe.py
Map      : C:/Users/richa/OneDrive/Bureaublad/Python/scripts/baseline/Claude/Transcribreer/
Icoon    : transcribt.ico  (zelfde map als dit script)

Versie   : 1.0.4
Engine   : faster-whisper 1.2.1 + pyannote.audio 4.x
Start    : python transcribe.py
Tests    : python transcribe.py --test
"""
# ── Watermerk ─────────────────────────────────────────────────
__author__    = "Richard van der Veer" 
__version__   = "1.0.4" 
__build__     = "2026-04-03"
__copyright__ = "© 2026 Richard van der Veer — github.com/richardvanderveer"
__watermark__ = "RVDV-TRANSCRIBE-2026-PYTHON-TOOLS"
from __future__ import annotations

import argparse
import configparser
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path
from typing import Callable, Optional

# Verberg CMD venster op Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(
        ctypes.windll.kernel32.GetConsoleWindow(), 0)

warnings.filterwarnings("ignore", message="torchcodec is not installed correctly")
warnings.filterwarnings("ignore", message="std():")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Transcribe")

APP_VERSION    = "1.3"
APP_TITLE      = f"Transcribe v{APP_VERSION}"
GITHUB_VERSION = "https://raw.githubusercontent.com/richardvanderveer/transcribe-app/main/version.txt"
GITHUB_REPO    = "https://github.com/richardvanderveer/transcribe-app"


# ---------------------------------------------------------------------------
# Icoon
# ---------------------------------------------------------------------------
def _resolve_icon() -> Optional[str]:
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "transcribt.ico",
        Path(__file__).resolve().parent / "transcribt.ico",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


# ---------------------------------------------------------------------------
# Auto-patch pyannote io.py
# ---------------------------------------------------------------------------
def _patch_pyannote() -> None:
    try:
        import pyannote.audio
        io_path = Path(pyannote.audio.__file__).parent / "core" / "io.py"
        with open(io_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "_sf_fallback" in content:
            log.debug("pyannote io.py patch al actief")
            return
        old = "    from torchcodec.decoders import AudioDecoder, AudioStreamMetadata"
        if old not in content:
            log.debug("pyannote io.py: patch niet nodig")
            return
        new = """    from torchcodec.decoders import AudioDecoder, AudioStreamMetadata
except Exception:
    import soundfile as _sf_fallback
    import torch as _torch_fallback

    class AudioStreamMetadata:
        def __init__(self, path):
            info = _sf_fallback.info(path)
            self.duration_seconds_from_header = info.duration
            self.sample_rate = info.samplerate
            self.num_frames = info.frames
            self.num_channels = info.channels
            self.duration = info.duration

    class _AudioSamples:
        def __init__(self, data, sample_rate):
            self.data = data
            self.sample_rate = sample_rate
            self.pts_seconds = 0.0

    class AudioDecoder:
        def __init__(self, path):
            self._path = path
            self.metadata = AudioStreamMetadata(path)

        def get_all_samples(self):
            data, sr = _sf_fallback.read(
                self._path, dtype="float32", always_2d=True
            )
            waveform = _torch_fallback.from_numpy(data.T)
            return _AudioSamples(waveform, sr)

        def get_samples_played_in_range(self, start, end):
            sr = self.metadata.sample_rate
            start_frame = int(start * sr)
            end_frame   = int(end * sr)
            data, _ = _sf_fallback.read(
                self._path,
                start=start_frame,
                stop=end_frame,
                dtype="float32",
                always_2d=True,
            )
            waveform = _torch_fallback.from_numpy(data.T)
            return _AudioSamples(waveform, sr)

        def __iter__(self):
            yield self.get_all_samples()"""
        content = content.replace(old, new, 1)
        with open(io_path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info("pyannote io.py patch toegepast: %s", io_path)
    except Exception as exc:
        log.warning("pyannote patch mislukt (niet kritiek): %s", exc)


# ---------------------------------------------------------------------------
# Update-check
# ---------------------------------------------------------------------------
def _check_update(callback: Callable[[str], None]) -> None:
    def _run():
        try:
            import urllib.request
            with urllib.request.urlopen(GITHUB_VERSION, timeout=5) as resp:
                remote = resp.read().decode().strip()
            local_parts  = [int(x) for x in APP_VERSION.split(".")]
            remote_parts = [int(x) for x in remote.split(".")]
            if remote_parts > local_parts:
                log.info("Update beschikbaar: v%s -> v%s", APP_VERSION, remote)
                callback(remote)
            else:
                log.debug("App is up-to-date (v%s)", APP_VERSION)
        except Exception as exc:
            log.debug("Update-check mislukt: %s", exc)
    threading.Thread(target=_run, daemon=True).start()


# ===========================================================================
# LAAG 1 — CONFIG
# ===========================================================================
class ConfigManager:
    APP_NAME = "TranscribeApp"
    DEFAULTS = {
        "language":      "nl",
        "model":         "small",
        "output_mode":   "1",
        "hf_token":      "",
        "max_speakers":  "auto",
        "diarize_model": "Nauwkeurig (aanbevolen)",
        "export_txt":    "1",
        "export_srt":    "0",
    }

    def __init__(self) -> None:
        self._config = configparser.ConfigParser()
        self._path = self._resolve_path()
        self._load()

    def _resolve_path(self) -> Path:
        base = Path(os.environ.get("APPDATA", Path.home())) if sys.platform == "win32" \
               else Path.home() / ".config"
        folder = base / self.APP_NAME
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "config.ini"

    def _load(self) -> None:
        self._config["app"] = self.DEFAULTS.copy()
        if self._path.exists():
            self._config.read(self._path, encoding="utf-8")

    def get(self, key: str) -> str:
        return self._config.get("app", key, fallback=self.DEFAULTS.get(key, ""))

    def set(self, key: str, value: str) -> None:
        self._config["app"][key] = value
        with open(self._path, "w", encoding="utf-8") as f:
            self._config.write(f)

    def path(self) -> Path:
        return self._path


# ===========================================================================
# LAAG 2 — AUDIO PREPROCESSOR
# ===========================================================================
class Preprocessor:
    SUPPORTED_EXTENSIONS = {
        ".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".flac",
        ".webm", ".mkv", ".avi", ".mov",
    }
    _CF = 0x08000000 if sys.platform == "win32" else 0

    @staticmethod
    def _find_binary(name: str) -> Optional[str]:
        import shutil
        script_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        local = script_dir / (name + (".exe" if sys.platform == "win32" else ""))
        if local.exists():
            return str(local)
        return shutil.which(name)

    @classmethod
    def check_ffmpeg(cls) -> dict[str, str]:
        result: dict[str, str] = {}
        for binary in ("ffmpeg", "ffprobe"):
            path = cls._find_binary(binary)
            if path is None:
                raise RuntimeError(f"{binary} niet gevonden.")
            out = subprocess.check_output(
                [path, "-version"], stderr=subprocess.STDOUT,
                creationflags=cls._CF, timeout=10,
            )
            result[binary] = out.decode(errors="replace").splitlines()[0]
        return result

    @classmethod
    def get_duration(cls, input_path: str) -> float:
        probe = cls._find_binary("ffprobe")
        if probe is None:
            return 0.0
        try:
            out = subprocess.check_output(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", input_path],
                stderr=subprocess.DEVNULL, creationflags=cls._CF, timeout=30,
            )
            return float(out.strip())
        except Exception:
            return 0.0

    @classmethod
    def to_wav(cls, input_path: str, output_wav: str) -> str:
        ffmpeg = cls._find_binary("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg niet gevonden.")
        cmd = [ffmpeg, "-y", "-i", input_path,
               "-ar", "16000", "-ac", "1", "-f", "wav", output_wav]
        log.info("ffmpeg: %s -> WAV 16kHz mono", Path(input_path).name)
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=cls._CF, timeout=300,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg conversie mislukt:\n{err}")
        return output_wav


# ===========================================================================
# LAAG 3 — OUTPUT FORMATTER
# ===========================================================================
class OutputFormatter:
    MODES = {
        "1": "Platte tekst",
        "2": "Tijdgestempeld",
        "3": "Spreker-labels",
        "4": "Ondertiteling (.srt)",
    }

    @staticmethod
    def format(segments: list[dict], mode: str, language: str = "nl") -> str:
        if mode == "1":
            return OutputFormatter._plain(segments)
        elif mode == "2":
            return OutputFormatter._timestamped(segments)
        elif mode == "3":
            return OutputFormatter._speaker(segments, language)
        elif mode == "4":
            return OutputFormatter._srt(segments)
        raise ValueError(f"Onbekende modus: {mode}")

    @staticmethod
    def _ts(sec: float) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _plain(segments: list[dict]) -> str:
        return "\n".join(s.get("text", "").strip() for s in segments)

    @staticmethod
    def _timestamped(segments: list[dict]) -> str:
        return "\n".join(
            f"[{OutputFormatter._ts(s.get('start', 0.0))}] {s.get('text', '').strip()}"
            for s in segments
        )

    @staticmethod
    def _speaker(segments: list[dict], language: str) -> str:
        rtl = "\u200f" if language == "ar" else ""
        lines = []
        for s in segments:
            speaker = s.get("speaker", "Spreker ?")
            ts = OutputFormatter._ts(s.get("start", 0.0))
            lines.append(f"{rtl}{speaker} [{ts}]: {s.get('text', '').strip()}")
        return "\n".join(lines)

    @staticmethod
    def _srt(segments: list[dict]) -> str:
        def srt_ts(sec: float) -> str:
            h, rem = divmod(int(sec), 3600)
            m, s = divmod(rem, 60)
            ms = int((sec - int(sec)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines = []
        for i, s in enumerate(segments, 1):
            lines += [str(i),
                      f"{srt_ts(s.get('start', 0.0))} --> {srt_ts(s.get('end', 0.0))}",
                      s.get("text", "").strip(), ""]
        return "\n".join(lines)

    @staticmethod
    def word_count(text: str) -> int:
        return len(text.split())


# ===========================================================================
# LAAG 4 — WORKERS
# ===========================================================================
ProgressCallback = Callable[[float, str], None]
ResultCallback   = Callable[[str, list[dict], Optional[str]], None]

DIARIZE_MODELS = {
    "Nauwkeurig (aanbevolen)":    "pyannote/speaker-diarization-3.1",
    "Sneller, minder nauwkeurig": "pyannote/speaker-diarization-community-1",
}

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "turbo"]


class TranscribeWorker:
    def __init__(self, input_path: str, language: str, model: str,
                 output_mode: str, hf_token: str, max_speakers: Optional[int],
                 diarize_model: str,
                 on_progress: ProgressCallback,
                 on_result: ResultCallback) -> None:
        self.input_path    = input_path
        self.language      = language
        self.model         = model
        self.output_mode   = output_mode
        self.hf_token      = hf_token
        self.max_speakers  = max_speakers
        self.diarize_model = diarize_model
        self.on_progress   = on_progress
        self.on_result     = on_result
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        try:
            self._pipeline()
        except Exception as exc:
            log.exception("Worker fout")
            self.on_result("", [], str(exc))

    def _pipeline(self) -> None:
        if not os.path.isfile(self.input_path):
            self.on_result("", [], f"Bestand niet gevonden: {self.input_path}")
            return
        ext = Path(self.input_path).suffix.lower()
        if ext not in Preprocessor.SUPPORTED_EXTENSIONS:
            self.on_result("", [], f"Niet-ondersteund formaat: {ext}")
            return

        self.on_progress(0.03, "Audioduur bepalen...")
        duration = Preprocessor.get_duration(self.input_path)
        log.info("Audioduur: %.1f sec", duration)

        if self._stop_event.is_set():
            return

        self.on_progress(0.08, "Audio converteren (ffmpeg)...")
        tmp_wav = tempfile.mktemp(suffix=".wav")
        try:
            Preprocessor.to_wav(self.input_path, tmp_wav)
        except Exception as exc:
            self.on_result("", [], f"Audio-conversie mislukt: {exc}")
            return

        if self._stop_event.is_set():
            _cleanup(tmp_wav)
            return

        # Vertaal "turbo" naar echte modelnaam
        model_name = "large-v3-turbo" if self.model == "turbo" else self.model

        self.on_progress(0.15, f"Whisper model laden ({self.model})...")
        try:
            from faster_whisper import WhisperModel
            fw_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            log.info("WhisperModel geladen: %s", model_name)
        except Exception as exc:
            _cleanup(tmp_wav)
            self.on_result("", [], f"Model laden mislukt: {exc}")
            return

        if self._stop_event.is_set():
            _cleanup(tmp_wav)
            return

        self.on_progress(0.20, "Transcriptie bezig...")
        lang = None if self.language == "auto" else self.language
        detected_lang = self.language
        try:
            segments_gen, info = fw_model.transcribe(
                tmp_wav,
                language=lang,
                beam_size=5,
                word_timestamps=(self.output_mode in ("2", "3", "4")),
            )
            detected_lang = info.language
            log.info("Taal gedetecteerd: %s (%.0f%%)",
                     info.language, info.language_probability * 100)

            segments: list[dict] = []
            for seg in segments_gen:
                if self._stop_event.is_set():
                    break
                segments.append({
                    "start": seg.start,
                    "end":   seg.end,
                    "text":  seg.text,
                })
                if duration > 0:
                    fraction = 0.20 + (seg.end / duration) * 0.55
                    self.on_progress(
                        min(fraction, 0.75),
                        f"[{OutputFormatter._ts(seg.start)}] {seg.text.strip()[:60]}"
                    )

        except Exception as exc:
            _cleanup(tmp_wav)
            self.on_result("", [], f"Transcriptie mislukt: {exc}")
            return

        if self._stop_event.is_set():
            _cleanup(tmp_wav)
            return

        if self.output_mode == "3":
            self.on_progress(0.78, "Sprekerherkenning laden...")
            if not self.hf_token:
                _cleanup(tmp_wav)
                self.on_result("", [], "HuggingFace-token vereist voor sprekerherkenning.\n"
                                       "Vul het in via Instellingen.")
                return
            try:
                segments = self._diarize(segments, tmp_wav)
            except Exception as exc:
                log.warning("Diarisatie mislukt, doorgaan zonder labels: %s", exc)
                for s in segments:
                    s["speaker"] = "Spreker ?"

        self.on_progress(0.95, "Uitvoer opmaken...")
        out_lang = self.language if self.language != "auto" else detected_lang
        transcript = OutputFormatter.format(segments, self.output_mode, out_lang)

        _cleanup(tmp_wav)
        self.on_progress(1.00, "Gereed.")
        self.on_result(transcript, segments, None)

    def _diarize(self, segments: list[dict], wav_path: str) -> list[dict]:
        import warnings as _w
        _w.filterwarnings("ignore", message="torchcodec")
        _w.filterwarnings("ignore", message="std():")
        from pyannote.audio import Pipeline
        import torch

        model_id = DIARIZE_MODELS.get(self.diarize_model,
                                      "pyannote/speaker-diarization-3.1")
        log.info("Diarisatie-model: %s", model_id)
        self.on_progress(0.80, f"Diarisatie laden ({self.diarize_model})...")

        pipeline = Pipeline.from_pretrained(model_id, token=self.hf_token)
        pipeline.to(torch.device("cpu"))

        self.on_progress(0.88, "Sprekers herkennen...")
        kwargs: dict = {}
        if self.max_speakers is not None:
            kwargs["min_speakers"] = 1
            kwargs["max_speakers"] = self.max_speakers
            log.info("Sprekers hint: 1 - %d", self.max_speakers)
        else:
            log.info("Sprekers: automatische detectie")

        diarization = pipeline(wav_path, **kwargs)

        tracks: list[tuple] = []
        try:
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                tracks.append((turn, speaker))
        except AttributeError:
            for turn, speaker in diarization.speaker_diarization:
                tracks.append((turn, speaker))

        unique = set(sp for _, sp in tracks)
        log.info("Unieke sprekers: %d (%s)", len(unique), sorted(unique))

        speaker_map: dict[str, str] = {}
        speaker_counter = 0

        for seg in segments:
            seg_start = seg["start"]
            seg_end   = seg["end"]
            best_speaker = None
            best_overlap = 0.0

            for turn, speaker in tracks:
                overlap = min(turn.end, seg_end) - max(turn.start, seg_start)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = speaker

            if best_speaker is None:
                min_dist = float("inf")
                for turn, speaker in tracks:
                    dist = min(abs(turn.start - seg_start),
                               abs(turn.end - seg_end))
                    if dist < min_dist:
                        min_dist = dist
                        best_speaker = speaker

            if best_speaker:
                if best_speaker not in speaker_map:
                    speaker_counter += 1
                    speaker_map[best_speaker] = f"Spreker {chr(64 + speaker_counter)}"
                seg["speaker"] = speaker_map[best_speaker]
            else:
                seg["speaker"] = "Spreker ?"

        log.info("Sprekermap: %s", speaker_map)
        return segments


class ExportWorker:
    def __init__(self, text: str, output_path: str,
                 on_done: Callable[[bool, str], None]) -> None:
        self.text        = text
        self.output_path = output_path
        self.on_done     = on_done

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            path = Path(self.output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(self.text)
            self.on_done(True, str(path))
        except Exception as exc:
            self.on_done(False, str(exc))


def _cleanup(path: str) -> None:
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"


# ===========================================================================
# LAAG 5 — GUI
# ===========================================================================
def _build_gui(controller: "AppController"):
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        import tkinter as tk
        root = tk.Tk()
        DND_FILES = None

    import tkinter as tk
    from tkinter import filedialog, ttk

    root.title(APP_TITLE)
    root.geometry("860x820")
    root.minsize(740, 740)
    controller.root = root

    _icon = _resolve_icon()
    if _icon:
        try:
            root.iconbitmap(_icon)
        except Exception:
            pass

    root.bind("<Escape>", lambda _e: controller.stop_transcription())

    C_BG     = "#F5F5F5"
    C_PANEL  = "#FFFFFF"
    C_ACCENT = "#2563A8"
    C_BTN    = "#2563A8"
    C_BTN_FG = "#FFFFFF"
    C_BORDER = "#CCCCCC"
    C_TEXT   = "#1A1A1A"
    C_MUTED  = "#666666"
    C_GREEN  = "#1B6B3A"
    C_RED    = "#8B1A1A"
    C_LOCK   = "#E8F0FE"

    root.configure(bg=C_BG)

    # Bovenste balk
    top_bar = tk.Frame(root, bg=C_ACCENT, height=48)
    top_bar.pack(fill=tk.X)
    top_bar.pack_propagate(False)
    tk.Label(top_bar, text=APP_TITLE, bg=C_ACCENT, fg=C_BTN_FG,
             font=("Segoe UI", 14, "bold"), padx=16).pack(side=tk.LEFT, pady=10)
    tk.Label(top_bar, text="lokale AI-transcriptie", bg=C_ACCENT, fg="#B8D4F0",
             font=("Segoe UI", 10)).pack(side=tk.LEFT, pady=10)

    main = tk.Frame(root, bg=C_BG)
    main.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

    left  = tk.Frame(main, bg=C_BG, width=320)
    right = tk.Frame(main, bg=C_BG)
    left.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 8))
    right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    left.pack_propagate(False)

    def card(parent, title):
        f = tk.LabelFrame(parent, text=title, bg=C_PANEL, fg=C_ACCENT,
                          font=("Segoe UI", 9, "bold"),
                          relief=tk.GROOVE, bd=1, padx=10, pady=8)
        f.pack(fill=tk.X, pady=(0, 6))
        return f

    def labeled_combo(parent, label_text, var, values, default):
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill=tk.X, pady=3)
        tk.Label(row, text=label_text, bg=C_PANEL, fg=C_TEXT,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side=tk.LEFT)
        combo = ttk.Combobox(row, textvariable=var, values=values,
                             state="readonly", width=16)
        combo.set(default)
        combo.pack(side=tk.LEFT)

    # ── Invoerbestand ────────────────────────────────────────────────
    card_file = card(left, "Invoerbestand")
    drop_zone = tk.Label(card_file,
                         text="Sleep een bestand hierheen\nof klik om te bladeren",
                         bg="#EBF2FB", fg=C_ACCENT, font=("Segoe UI", 9),
                         relief=tk.GROOVE, bd=1, width=28, height=4, cursor="hand2")
    drop_zone.pack(fill=tk.X, pady=(0, 6))

    controller._file_var = tk.StringVar(value="")
    tk.Label(card_file, textvariable=controller._file_var, bg=C_PANEL, fg=C_MUTED,
             font=("Segoe UI", 8), wraplength=280, anchor="w").pack(fill=tk.X)

    def _on_browse():
        path = filedialog.askopenfilename(
            title="Kies audiobestand",
            filetypes=[("Audio/Video",
                        "*.mp3 *.mp4 *.wav *.m4a *.ogg *.flac *.webm *.mkv *.avi *.mov"),
                       ("Alle bestanden", "*.*")])
        if path:
            controller.set_input_file(path)

    drop_zone.bind("<Button-1>", lambda _e: _on_browse())
    if DND_FILES:
        def _on_drop(event):
            raw = event.data.strip()
            path = raw.strip("{}") if raw.startswith("{") else raw.split()[0]
            controller.set_input_file(path)
        drop_zone.drop_target_register(DND_FILES)
        drop_zone.dnd_bind("<<Drop>>", _on_drop)

    tk.Button(card_file, text="Bladeren...", bg=C_BTN, fg=C_BTN_FG,
              font=("Segoe UI", 9), relief=tk.FLAT,
              activebackground="#1A3A5C", activeforeground=C_BTN_FG,
              command=_on_browse).pack(fill=tk.X, pady=(6, 0))

    # ── Instellingen ─────────────────────────────────────────────────
    card_settings = card(left, "Instellingen")
    controller._lang_var          = tk.StringVar()
    controller._model_var         = tk.StringVar()
    controller._mode_var          = tk.StringVar()
    controller._max_speakers_var  = tk.StringVar()
    controller._diarize_model_var = tk.StringVar()

    labeled_combo(card_settings, "Taal:", controller._lang_var,
                  ["nl — Nederlands", "en — Engels", "ar — Arabisch",
                   "auto — Automatisch"],
                  "nl — Nederlands")

    labeled_combo(card_settings, "Model:", controller._model_var,
                  WHISPER_MODELS,
                  controller.config.get("model"))

    labeled_combo(card_settings, "Uitvoermodus:", controller._mode_var,
                  ["1 — Platte tekst", "2 — Tijdgestempeld",
                   "3 — Spreker-labels", "4 — Ondertiteling (.srt)"],
                  "1 — Platte tekst")

    saved_dm = controller.config.get("diarize_model")
    labeled_combo(card_settings, "Diarisatie:",
                  controller._diarize_model_var,
                  list(DIARIZE_MODELS.keys()),
                  saved_dm if saved_dm in DIARIZE_MODELS
                  else "Nauwkeurig (aanbevolen)")

    dm_info = tk.Label(card_settings, text="", bg=C_PANEL, fg=C_MUTED,
                       font=("Segoe UI", 7), wraplength=270,
                       justify="left", anchor="w")
    dm_info.pack(fill=tk.X, pady=(0, 2))

    def _update_dm_info(*_):
        dm = controller._diarize_model_var.get()
        if dm == "Nauwkeurig (aanbevolen)":
            dm_info.config(text="Beste keuze voor vergaderingen en meerdere sprekers")
        else:
            dm_info.config(
                text="Sneller bij korte opnames, minder geschikt voor 3+ sprekers")

    controller._diarize_model_var.trace_add("write", _update_dm_info)
    _update_dm_info()

    # Max sprekers
    spk_row = tk.Frame(card_settings, bg=C_PANEL)
    spk_row.pack(fill=tk.X, pady=3)
    tk.Label(spk_row, text="Max sprekers:", bg=C_PANEL, fg=C_TEXT,
             font=("Segoe UI", 9), width=14, anchor="w").pack(side=tk.LEFT)
    saved_spk = controller.config.get("max_speakers")
    controller._max_speakers_var.set(saved_spk if saved_spk else "auto")
    tk.Entry(spk_row, textvariable=controller._max_speakers_var,
             font=("Segoe UI", 9), width=6,
             bg=C_PANEL, fg=C_TEXT).pack(side=tk.LEFT)
    tk.Label(spk_row, text="(auto of 1-20)", bg=C_PANEL, fg=C_MUTED,
             font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 0))

    # HF-token
    tk.Label(card_settings, text="HF-token (modus 3):", bg=C_PANEL, fg=C_TEXT,
             font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, pady=(6, 0))
    token_frame = tk.Frame(card_settings, bg=C_PANEL)
    token_frame.pack(fill=tk.X)

    controller._token_var    = tk.StringVar(value=controller.config.get("hf_token"))
    controller._token_locked = tk.BooleanVar(value=True)

    hf_entry = tk.Entry(token_frame, textvariable=controller._token_var,
                        show="*", font=("Segoe UI", 9),
                        state="disabled",
                        disabledbackground=C_LOCK,
                        disabledforeground=C_MUTED)
    hf_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _toggle_token_lock():
        if controller._token_locked.get():
            hf_entry.config(state="normal", bg=C_PANEL)
            lock_btn.config(text="Vergrendel")
            controller._token_locked.set(False)
        else:
            controller.config.set("hf_token", controller._token_var.get())
            hf_entry.config(state="disabled",
                            disabledbackground=C_LOCK,
                            disabledforeground=C_MUTED)
            lock_btn.config(text="Wijzig")
            controller._token_locked.set(True)

    lock_btn = tk.Button(token_frame, text="Wijzig",
                         bg=C_BG, fg=C_ACCENT,
                         font=("Segoe UI", 8), relief=tk.GROOVE, bd=1,
                         command=_toggle_token_lock)
    lock_btn.pack(side=tk.LEFT, padx=(4, 0))

    tk.Label(card_settings,
             text="Klik 'Wijzig' om token te bewerken, 'Vergrendel' om op te slaan",
             bg=C_PANEL, fg=C_MUTED, font=("Segoe UI", 7),
             wraplength=270, justify="left").pack(anchor="w")

    # ── Uitvoer ──────────────────────────────────────────────────────
    card_output = card(left, "Uitvoer")
    controller._output_var = tk.StringVar(value="")
    tk.Entry(card_output, textvariable=controller._output_var,
             font=("Segoe UI", 8), state="readonly",
             disabledbackground=C_PANEL,
             disabledforeground=C_MUTED).pack(fill=tk.X, pady=(0, 4))

    def _on_output_browse():
        path = filedialog.asksaveasfilename(
            title="Opslaan als...", defaultextension=".txt",
            filetypes=[("Tekstbestand", "*.txt"), ("SRT", "*.srt"),
                       ("Alle", "*.*")])
        if path:
            controller._output_var.set(path)

    tk.Button(card_output, text="Kies locatie...", bg=C_BTN, fg=C_BTN_FG,
              font=("Segoe UI", 9), relief=tk.FLAT,
              activebackground="#1A3A5C", activeforeground=C_BTN_FG,
              command=_on_output_browse).pack(fill=tk.X, pady=(0, 6))

    export_row = tk.Frame(card_output, bg=C_PANEL)
    export_row.pack(fill=tk.X)
    tk.Label(export_row, text="Exporteer als:", bg=C_PANEL, fg=C_TEXT,
             font=("Segoe UI", 9)).pack(side=tk.LEFT)
    controller._export_txt_var = tk.BooleanVar(
        value=controller.config.get("export_txt") == "1")
    controller._export_srt_var = tk.BooleanVar(
        value=controller.config.get("export_srt") == "1")
    tk.Checkbutton(export_row, text=".txt",
                   variable=controller._export_txt_var,
                   bg=C_PANEL, fg=C_TEXT, font=("Segoe UI", 9),
                   selectcolor=C_PANEL,
                   activebackground=C_PANEL).pack(side=tk.LEFT, padx=(8, 0))
    tk.Checkbutton(export_row, text=".srt",
                   variable=controller._export_srt_var,
                   bg=C_PANEL, fg=C_TEXT, font=("Segoe UI", 9),
                   selectcolor=C_PANEL,
                   activebackground=C_PANEL).pack(side=tk.LEFT, padx=(4, 0))

    # ── Acties ───────────────────────────────────────────────────────
    card_actions = card(left, "Acties")

    controller._btn_start = tk.Button(
        card_actions, text="Start transcriptie",
        bg=C_GREEN, fg=C_BTN_FG, font=("Segoe UI", 10, "bold"),
        relief=tk.FLAT, activebackground="#0F4527", activeforeground=C_BTN_FG,
        command=controller.start_transcription)
    controller._btn_start.pack(fill=tk.X, pady=(0, 4))

    controller._btn_stop = tk.Button(
        card_actions, text="Stop  [Esc]",
        bg=C_RED, fg=C_BTN_FG, font=("Segoe UI", 9), relief=tk.FLAT,
        activebackground="#5C0E0E", activeforeground=C_BTN_FG,
        state=tk.DISABLED, command=controller.stop_transcription)
    controller._btn_stop.pack(fill=tk.X, pady=(0, 4))

    btn_row = tk.Frame(card_actions, bg=C_PANEL)
    btn_row.pack(fill=tk.X, pady=(0, 4))
    for label, cmd in [
        ("Kopieer",      controller.copy_to_clipboard),
        ("Open bestand", controller.open_output_file),
        ("Open map",     controller.open_output_folder),
    ]:
        tk.Button(btn_row, text=label, bg=C_BG, fg=C_TEXT,
                  font=("Segoe UI", 8), relief=tk.GROOVE, bd=1,
                  command=cmd).pack(side=tk.LEFT, expand=True,
                                    fill=tk.X, padx=2)

    controller._btn_edit = tk.Button(
        card_actions, text="Bewerk transcript",
        bg=C_BG, fg=C_ACCENT,
        font=("Segoe UI", 9, "bold"), relief=tk.GROOVE, bd=1,
        command=controller.toggle_edit_mode)
    controller._btn_edit.pack(fill=tk.X, pady=(0, 2))

    tk.Button(card_actions, text="Hernoem sprekers",
              bg=C_BG, fg=C_ACCENT,
              font=("Segoe UI", 9, "bold"), relief=tk.GROOVE, bd=1,
              command=controller.rename_speakers).pack(fill=tk.X, pady=(0, 2))

    # ── Voortgang ────────────────────────────────────────────────────
    prog_frame = tk.Frame(right, bg=C_BG)
    prog_frame.pack(fill=tk.X, pady=(0, 6))
    tk.Label(prog_frame, text="Voortgang:", bg=C_BG, fg=C_MUTED,
             font=("Segoe UI", 8)).pack(anchor="w")
    controller._progress_canvas = tk.Canvas(
        prog_frame, height=18, bg=C_BORDER, bd=0, highlightthickness=0)
    controller._progress_canvas.pack(fill=tk.X, pady=2)
    controller._progress_bar = controller._progress_canvas.create_rectangle(
        0, 0, 0, 18, fill=C_ACCENT, outline="")
    controller._status_var = tk.StringVar(value="Gereed.")
    tk.Label(prog_frame, textvariable=controller._status_var,
             bg=C_BG, fg=C_MUTED, font=("Segoe UI", 8),
             anchor="w").pack(fill=tk.X)

    # ── Preview ──────────────────────────────────────────────────────
    preview_frame = tk.Frame(right, bg=C_PANEL, relief=tk.GROOVE, bd=1)
    preview_frame.pack(fill=tk.BOTH, expand=True)
    controller._preview_text = tk.Text(
        preview_frame, font=("Segoe UI", 10), bg=C_PANEL, fg=C_TEXT,
        wrap=tk.WORD, relief=tk.FLAT, padx=8, pady=8,
        insertbackground=C_TEXT)
    scrollbar = tk.Scrollbar(preview_frame,
                             command=controller._preview_text.yview)
    controller._preview_text.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    controller._preview_text.pack(fill=tk.BOTH, expand=True)
    controller._preview_text.insert("1.0",
                                    "Transcript verschijnt hier na transcriptie...")
    controller._preview_text.config(state=tk.DISABLED)

    # ── Statusbalk ───────────────────────────────────────────────────
    tk.Frame(root, bg=C_BORDER, height=1).pack(fill=tk.X)
    status_bar = tk.Frame(root, bg=C_BG)
    status_bar.pack(fill=tk.X, pady=2)

    controller._update_label = tk.Label(
        status_bar, text="", bg=C_BG, fg="#E67E22",
        font=("Segoe UI", 8, "underline"), cursor="hand2")
    controller._update_label.pack(side=tk.RIGHT, padx=8)

    tk.Label(status_bar,
             text=f"{APP_TITLE} · faster-whisper · pyannote · volledig offline",
             bg=C_BG, fg=C_MUTED,
             font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=8)

    controller._stats_var = tk.StringVar(value="")
    tk.Label(status_bar, textvariable=controller._stats_var,
             bg=C_BG, fg=C_MUTED,
             font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=8)

    root.protocol("WM_DELETE_WINDOW", controller.on_close)
    return root


# ===========================================================================
# LAAG 6 — CONTROLLER
# ===========================================================================
class AppController:
    def __init__(self) -> None:
        self.config  = ConfigManager()
        self.root    = None
        self._worker: Optional[TranscribeWorker] = None
        self._current_transcript: str = ""
        self._current_segments: list[dict] = []
        self._edit_mode: bool = False
        self._start_time: Optional[float] = None

        self._file_var           = None
        self._lang_var           = None
        self._model_var          = None
        self._mode_var           = None
        self._token_var          = None
        self._token_locked       = None
        self._output_var         = None
        self._max_speakers_var   = None
        self._diarize_model_var  = None
        self._export_txt_var     = None
        self._export_srt_var     = None
        self._status_var         = None
        self._stats_var          = None
        self._update_label       = None
        self._preview_text       = None
        self._progress_canvas    = None
        self._progress_bar       = None
        self._btn_start          = None
        self._btn_stop           = None
        self._btn_edit           = None

    def set_input_file(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        if ext not in Preprocessor.SUPPORTED_EXTENSIONS:
            self._show_error(f"Niet-ondersteund formaat: {ext}")
            return
        self._file_var.set(path)
        if not self._output_var.get():
            self._output_var.set(str(Path(path).with_suffix(".txt")))
        if self.root:
            self.root.title(f"{APP_TITLE} — {Path(path).name}")

    def _parse_max_speakers(self) -> Optional[int]:
        raw = (self._max_speakers_var.get()
               if self._max_speakers_var else "auto").strip().lower()
        if raw in ("", "auto", "0"):
            return None
        try:
            return max(1, min(int(raw), 20))
        except ValueError:
            return None

    def start_transcription(self) -> None:
        input_path = self._file_var.get() if self._file_var else ""
        if not input_path:
            self._show_error("Kies eerst een audiobestand.")
            return
        if not os.path.isfile(input_path):
            self._show_error(f"Bestand niet gevonden:\n{input_path}")
            return

        output_path = self._output_var.get() or \
                      str(Path(input_path).with_suffix(".txt"))
        self._output_var.set(output_path)

        lang          = (self._lang_var.get()  or "nl — Nederlands").split(" ")[0]
        model         = (self._model_var.get() or "small")
        mode          = (self._mode_var.get()  or "1 — Platte tekst").split(" ")[0]
        token         = self._token_var.get() if self._token_var else ""
        max_speakers  = self._parse_max_speakers()
        diarize_model = (self._diarize_model_var.get()
                         if self._diarize_model_var
                         else "Nauwkeurig (aanbevolen)")

        self.config.set("model", model)
        self.config.set("max_speakers",
                        self._max_speakers_var.get()
                        if self._max_speakers_var else "auto")
        self.config.set("diarize_model", diarize_model)
        self.config.set("export_txt",
                        "1" if self._export_txt_var and
                        self._export_txt_var.get() else "0")
        self.config.set("export_srt",
                        "1" if self._export_srt_var and
                        self._export_srt_var.get() else "0")

        self._start_time = time.time()
        self._stats_var.set("")
        self._set_busy(True)
        self._update_progress(0.0, "Transcriptie starten...")

        filename = Path(input_path).name
        if self.root:
            self.root.title(f"{APP_TITLE} (0%) — {filename}")

        self._worker = TranscribeWorker(
            input_path=input_path, language=lang, model=model,
            output_mode=mode, hf_token=token, max_speakers=max_speakers,
            diarize_model=diarize_model,
            on_progress=self._on_progress, on_result=self._on_result,
        )
        self._worker.start()

    def stop_transcription(self) -> None:
        if self._worker and self._worker.is_alive():
            self._worker.stop()
        self._set_busy(False)
        self._update_progress(0.0, "Gestopt door gebruiker.")
        self._start_time = None
        filename = Path(self._file_var.get()).name \
                   if self._file_var and self._file_var.get() else ""
        if self.root:
            self.root.title(
                f"{APP_TITLE}{' — ' + filename if filename else ''}")

    def copy_to_clipboard(self) -> None:
        if self.root and self._current_transcript:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._current_transcript)
            self._update_status("Tekst gekopieerd naar klembord.")

    def open_output_file(self) -> None:
        path = self._output_var.get() if self._output_var else ""
        if path and os.path.isfile(path):
            os.startfile(path) if sys.platform == "win32" \
                else subprocess.Popen(["xdg-open", path])
        else:
            self._show_error("Outputbestand nog niet aangemaakt.")

    def open_output_folder(self) -> None:
        path = self._output_var.get() if self._output_var else ""
        folder = str(Path(path).parent) if path else ""
        if folder and os.path.isdir(folder):
            subprocess.Popen(["explorer", folder]) if sys.platform == "win32" \
                else subprocess.Popen(["xdg-open", folder])
        else:
            self._show_error("Outputmap niet gevonden.")

    def toggle_edit_mode(self) -> None:
        import tkinter as tk
        if not self._preview_text:
            return
        self._edit_mode = not self._edit_mode
        if self._edit_mode:
            self._preview_text.config(state=tk.NORMAL, bg="#FFFDE7")
            if self._btn_edit:
                self._btn_edit.config(text="Vergrendel transcript")
            self._update_status(
                "Bewerkingsmodus — wijzig het transcript, klik 'Vergrendel' om op te slaan.")
        else:
            self._current_transcript = self._preview_text.get(
                "1.0", tk.END).rstrip()
            self._preview_text.config(state=tk.DISABLED, bg="#FFFFFF")
            if self._btn_edit:
                self._btn_edit.config(text="Bewerk transcript")
            self._update_status("Transcript vergrendeld en bijgewerkt.")
            output_path = self._output_var.get() if self._output_var else ""
            if output_path and self._current_transcript:
                ExportWorker(self._current_transcript,
                             str(Path(output_path).with_suffix(".txt")),
                             self._on_export_done).start()

    def rename_speakers(self) -> None:
        import tkinter.simpledialog as sd

        if not self._current_transcript:
            self._show_error("Geen transcript aanwezig om te bewerken.")
            return

        speakers = sorted(set(re.findall(
            r"Spreker (?:[A-Z]|\?)", self._current_transcript)))
        if not speakers:
            self._show_error(
                "Geen spreker-labels gevonden.\n"
                "Gebruik modus 3 (Spreker-labels) voor sprekerherkenning."
            )
            return

        renamed: dict[str, str] = {}
        for speaker in speakers:
            name = sd.askstring(
                "Spreker hernoemen",
                f"Naam voor '{speaker}':\n(leeg laten = niet wijzigen)",
                parent=self.root,
            )
            if name and name.strip():
                renamed[speaker] = name.strip()

        if not renamed:
            self._update_status("Geen wijzigingen aangebracht.")
            return

        new_transcript = self._current_transcript
        for old, new in sorted(renamed.items(),
                                key=lambda x: len(x[0]), reverse=True):
            new_transcript = re.sub(
                r'(?<!\w)' + re.escape(old) + r'(?!\w)',
                new, new_transcript
            )

        self._current_transcript = new_transcript
        self._show_transcript(new_transcript)
        self._update_status(
            "Bijgewerkt: " +
            ", ".join(f"{o} -> {n}" for o, n in renamed.items())
        )

        output_path = self._output_var.get() if self._output_var else ""
        if output_path:
            ExportWorker(new_transcript,
                         str(Path(output_path).with_suffix(".txt")),
                         self._on_export_done).start()

    def notify_update(self, remote_version: str) -> None:
        if not self._update_label or not self.root:
            return
        def _show():
            self._update_label.config(
                text=f"Nieuwe versie v{remote_version} beschikbaar — klik om te downloaden"
            )
            self._update_label.bind(
                "<Button-1>",
                lambda _e: subprocess.Popen(
                    ["start", GITHUB_REPO], shell=True)
            )
        self.root.after(0, _show)

    def _on_progress(self, fraction: float, message: str) -> None:
        if self.root:
            self.root.after(0, self._update_progress, fraction, message)
            filename = Path(self._file_var.get()).name \
                       if self._file_var and self._file_var.get() else ""
            pct = int(fraction * 100)
            self.root.after(0, self.root.title,
                            f"{APP_TITLE} ({pct}%) — {filename}")

    def _on_result(self, transcript: str, segments: list[dict],
                   error: Optional[str]) -> None:
        if self.root:
            self.root.after(0, self._handle_result, transcript, segments, error)

    def _handle_result(self, transcript: str, segments: list[dict],
                       error: Optional[str]) -> None:
        self._set_busy(False)
        filename = Path(self._file_var.get()).name \
                   if self._file_var and self._file_var.get() else ""

        if error:
            self._update_progress(0.0, "Fout opgetreden.")
            self._show_error(error)
            if self.root:
                self.root.title(f"{APP_TITLE} — {filename}")
            return

        self._current_transcript = transcript
        self._current_segments   = segments

        elapsed = ""
        if self._start_time:
            elapsed = _format_duration(time.time() - self._start_time)
            self._start_time = None

        words = OutputFormatter.word_count(transcript)
        n_seg = len(segments)
        stats = f"Gereed in {elapsed} · {words} woorden · {n_seg} segmenten"
        self._update_progress(1.0, stats)
        if self._stats_var:
            self._stats_var.set(stats)

        self._show_transcript(transcript)

        if self.root:
            self.root.title(f"{APP_TITLE} — {filename} \u2713")

        output_path = self._output_var.get() if self._output_var else ""
        export_txt = self._export_txt_var.get() if self._export_txt_var else True
        export_srt = self._export_srt_var.get() if self._export_srt_var else False

        if output_path and export_txt:
            ExportWorker(transcript,
                         str(Path(output_path).with_suffix(".txt")),
                         self._on_export_done).start()

        if output_path and export_srt:
            srt_text = OutputFormatter._srt(segments) if segments \
                       else transcript
            ExportWorker(srt_text,
                         str(Path(output_path).with_suffix(".srt")),
                         self._on_export_done).start()

    def _on_export_done(self, success: bool, message: str) -> None:
        if self.root:
            self.root.after(0, self._update_status,
                            f"Opgeslagen: {message}" if success
                            else f"Opslagfout: {message}")

    def _update_progress(self, fraction: float, message: str) -> None:
        self._update_status(message)
        if self._progress_canvas and self._progress_bar:
            w = self._progress_canvas.winfo_width()
            self._progress_canvas.coords(
                self._progress_bar, 0, 0, int(w * fraction), 18)

    def _update_status(self, message: str) -> None:
        if self._status_var:
            self._status_var.set(message)

    def _show_transcript(self, text: str) -> None:
        if not self._preview_text:
            return
        import tkinter as tk
        lang = (self._lang_var.get() or "nl").split(" ")[0]
        self._preview_text.config(state=tk.NORMAL)
        self._preview_text.delete("1.0", tk.END)
        if lang == "ar":
            self._preview_text.tag_configure("rtl", justify="right")
            self._preview_text.insert("1.0", text, "rtl")
        else:
            self._preview_text.insert("1.0", text)
        if not self._edit_mode:
            self._preview_text.config(state=tk.DISABLED, bg="#FFFFFF")

    def _set_busy(self, busy: bool) -> None:
        import tkinter as tk
        if self._btn_start:
            self._btn_start.config(state=tk.DISABLED if busy else tk.NORMAL)
        if self._btn_stop:
            self._btn_stop.config(state=tk.NORMAL if busy else tk.DISABLED)

    def _show_error(self, message: str) -> None:
        import tkinter.messagebox as mb
        log.error(message)
        if self.root:
            mb.showerror("Transcribe", message)

    def on_close(self) -> None:
        if self._worker and self._worker.is_alive():
            self._worker.stop()
        if self.root:
            self.root.destroy()


# ===========================================================================
# TESTRUNNER
# ===========================================================================
class SkeletonTests:
    PASS = "\033[92mPASS\033[0m"
    FAIL = "\033[91mFAIL\033[0m"
    SKIP = "\033[93mSKIP\033[0m"

    def __init__(self) -> None:
        self.results: list[tuple] = []

    def run_all(self) -> bool:
        print("\n" + "=" * 60)
        print(f"  {APP_TITLE} — verificatietests")
        print("=" * 60)
        self._t1_imports()
        self._t2_instantiation()
        self._t3_config()
        self._t4_ffmpeg()
        self._t5_worker_thread()
        self._t6_gui()
        self._t7_whisper_import()
        self._t8_pyannote_import()
        return self._report()

    def _record(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append((name, self.PASS if passed else self.FAIL, detail))
        print(f"  [{'v' if passed else 'x'}] {name}")
        if detail:
            print(f"       {detail}")

    def _skip(self, name: str, reason: str) -> None:
        self.results.append((name, self.SKIP, reason))
        print(f"  [-] {name}  (overgeslagen: {reason})")

    def _t1_imports(self) -> None:
        try:
            import configparser, threading, subprocess, tempfile, os, sys, re
            self._record("T1 — Imports & stdlib", True)
        except Exception as exc:
            self._record("T1 — Imports & stdlib", False, str(exc))

    def _t2_instantiation(self) -> None:
        try:
            assert ConfigManager() and Preprocessor() and OutputFormatter() \
                   and AppController()
            self._record("T2 — Laaginstantiatie", True)
        except Exception as exc:
            self._record("T2 — Laaginstantiatie", False, str(exc))

    def _t3_config(self) -> None:
        try:
            cfg = ConfigManager()
            sentinel = f"tok_{int(time.time())}"
            cfg.set("hf_token", sentinel)
            assert ConfigManager().get("hf_token") == sentinel
            cfg.set("hf_token", "")
            self._record("T3 — Config lezen/schrijven", True, str(cfg.path()))
        except Exception as exc:
            self._record("T3 — Config lezen/schrijven", False, str(exc))

    def _t4_ffmpeg(self) -> None:
        try:
            v = Preprocessor.check_ffmpeg()
            self._record("T4 — ffmpeg/ffprobe", True,
                         " | ".join(f"{k}: {v[k][:50]}" for k in v))
        except RuntimeError as exc:
            self._skip("T4 — ffmpeg/ffprobe", str(exc))
        except Exception as exc:
            self._record("T4 — ffmpeg/ffprobe", False, str(exc))

    def _t5_worker_thread(self) -> None:
        try:
            done = threading.Event()
            results = []
            TranscribeWorker(
                "__nonexistent__.mp3", "nl", "tiny", "1", "", None,
                "Nauwkeurig (aanbevolen)",
                lambda f, m: None,
                lambda t, s, e: (results.append(e), done.set()),
            ).start()
            assert done.wait(5.0) and results[0] is not None
            self._record("T5 — Worker thread", True,
                         f"Fout correct: {results[0][:60]}")
        except Exception as exc:
            self._record("T5 — Worker thread", False, str(exc))

    def _t6_gui(self) -> None:
        if os.environ.get("CI") or os.environ.get("NO_DISPLAY"):
            self._skip("T6 — GUI", "geen scherm")
            return
        try:
            ctrl = AppController()
            root = _build_gui(ctrl)
            root.after(300, root.destroy)
            root.mainloop()
            self._record("T6 — GUI opent/sluit", True)
        except Exception as exc:
            self._record("T6 — GUI opent/sluit", False, str(exc))

    def _t7_whisper_import(self) -> None:
        try:
            from faster_whisper import WhisperModel
            self._record("T7 — faster-whisper", True, "WhisperModel beschikbaar")
        except Exception as exc:
            self._record("T7 — faster-whisper", False, str(exc))

    def _t8_pyannote_import(self) -> None:
        try:
            import warnings
            warnings.filterwarnings("ignore", message="torchcodec")
            from pyannote.audio import Pipeline
            self._record("T8 — pyannote.audio", True, "Pipeline beschikbaar")
        except Exception as exc:
            self._record("T8 — pyannote.audio", False, str(exc))

    def _report(self) -> bool:
        passed  = sum(1 for _, s, _ in self.results if "PASS" in s)
        skipped = sum(1 for _, s, _ in self.results if "SKIP" in s)
        failed  = sum(1 for _, s, _ in self.results if "FAIL" in s)
        print("\n" + "-" * 60)
        print(f"  Resultaat: {passed} geslaagd / {skipped} overgeslagen / "
              f"{failed} mislukt")
        print("  Klaar voor gebruik." if failed == 0 else "  Los fouten op.")
        print("=" * 60 + "\n")
        return failed == 0


# ===========================================================================
# ENTRYPOINT
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        sys.exit(0 if SkeletonTests().run_all() else 1)

    log.info("%s starten...", APP_TITLE)
    _patch_pyannote()
    controller = AppController()
    root = _build_gui(controller)
    root.after(2000, lambda: _check_update(controller.notify_update))
    root.mainloop()


if __name__ == "__main__":
    main()