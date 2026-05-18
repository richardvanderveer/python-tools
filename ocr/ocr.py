"""
OCR.py  v3.9  —  Offline OCR tool
===================================
Engine : Tesseract (volledig offline na installatie)
Talen  : via Tesseract taalbestanden (.traineddata) — ook offline
Exe    : PyInstaller build via build_ocr.bat

Installatie:
    pip install opencv-python pytesseract pillow python-docx numpy tkinterdnd2
    Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
    Extra talen: installeer via Tesseract installer of kopieer .traineddata
                 naar C:\\Program Files\\Tesseract-OCR\\tessdata\\

Exe bouwen:
    build_ocr.bat
"""

import os
import base64
import json
import traceback

# ── PyInstaller sys.path patch ────────────────────────────────────────────────
# Wanneer de app als .exe draait (PyInstaller) zijn grote ML-pakketten
# (torch, transformers, easyocr) niet gebundeld. Dit blok zoekt de systeem
# Python site-packages op en voegt ze toe aan sys.path zodat de exe die
# pakketten toch kan vinden als ze op het systeem geïnstalleerd zijn.
import sys as _sys
if getattr(_sys, "frozen", False):
    import os as _os
    _extra_paths = []
    # Zoek in %LOCALAPPDATA%\Programs\Python\Python3xx\Lib\site-packages
    try:
        _lad = _os.path.expandvars("%LOCALAPPDATA%")
        _py_root = _os.path.join(_lad, "Programs", "Python")
        if _os.path.isdir(_py_root):
            for _d in sorted(_os.listdir(_py_root), reverse=True):
                _sp = _os.path.join(_py_root, _d, "Lib", "site-packages")
                if _os.path.isdir(_sp):
                    _extra_paths.append(_sp)
                # Roaming site-packages (bijv. easyocr)
                _ap = _os.path.expandvars("%APPDATA%")
                _rsp = _os.path.join(_ap, "Python", _d, "site-packages")
                if _os.path.isdir(_rsp):
                    _extra_paths.append(_rsp)
    except Exception:
        pass
    # Voeg toe aan sys.path (na positie 0 = eigen _MEIPASS)
    for _p in _extra_paths:
        if _p not in _sys.path:
            _sys.path.insert(1, _p)
    del _os, _extra_paths
del _sys
# ── Einde sys.path patch ─────────────────────────────────────────────────────

import sys
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageTk
import pytesseract

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except ImportError:
    _DND = False

# ── Tesseract pad ────────────────────────────────────────────────────────────
for _p in [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]:
    if os.path.exists(_p):
        pytesseract.pytesseract.tesseract_cmd = _p
        break

# ── Kleuren / fonts ──────────────────────────────────────────────────────────
C_BG  = "#1e1e2e"; C_PAN = "#2a2a3e"; C_ACC = "#4a9eff"
C_TXT = "#cdd6f4"; C_MUT = "#6c7086"; C_BTN = "#313244"
C_SEL = "#f38ba8"; C_GRN = "#a6e3a1"
FS = ("Segoe UI", 9); FM = ("Consolas", 10); FT = ("Segoe UI", 12, "bold")

TALEN = {
    "Nederlands":  "nld",
    "Engels":      "eng",
    "NL + EN":     "nld+eng",
    "Duits":       "deu",
    "Frans":       "fra",
    "Arabisch":    "ara",
}

PSM_OPTIES = {
    "11 — Sparse (handschrift/bord)": 11,
    "6  — Uniform blok (gedrukt)":    6,
    "4  — Kolom (meerdere kolommen)": 4,
    "3  — Volledig auto":             3,
    "13 — Raw line":                  13,
}

MODI = {
    "Whiteboard / Sauvola":  "sauvola",
    "Whiteboard / Otsu":     "otsu",
    "Adaptief (document)":   "adaptief",
    "Origineel (geen)":      "raw",
}

MIN_W = 2500   # minimale breedte voor Tesseract — kleiner = slechter
APP_VERSION = "3.9"


# ═══════════════════════════════════════════════════════════════════════════════
# Preprocessing
# ═══════════════════════════════════════════════════════════════════════════════

def _upscale(img, min_w=MIN_W):
    h, w = img.shape[:2]
    if w < min_w:
        s = min_w / w
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return img

def _trim_randen(grijs: np.ndarray, drempel: int = 30) -> tuple[int,int,int,int]:
    """
    Geef bounding box (ry0, ry1, rx0, rx1) van niet-zwarte content.
    Donkere randen (< drempel) worden weggeknipt zodat preprocessing
    en regeldetectie niet door de zwarte whiteboard-kaders worden verstoord.
    """
    mask = grijs > drempel
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any():
        h, w = grijs.shape
        return 0, h, 0, w
    ry0, ry1 = np.where(rows)[0][[0, -1]]
    rx0, rx1 = np.where(cols)[0][[0, -1]]
    return int(ry0), int(ry1)+1, int(rx0), int(rx1)+1

def _crop_content(img_bgr: np.ndarray) -> np.ndarray:
    """Snijd donkere randen weg. Geeft origineel terug als er niets te knippen valt."""
    grijs = _grijswaarde(img_bgr)
    ry0, ry1, rx0, rx1 = _trim_randen(grijs)
    h, w = grijs.shape
    # Alleen knippen als er substantieel iets te knippen is (> 2% rand)
    if ry0 < h*0.02 and rx0 < w*0.02 and ry1 > h*0.98 and rx1 > w*0.98:
        return img_bgr
    return img_bgr[ry0:ry1, rx0:rx1]

def _grijswaarde(img):
    if len(img.shape) == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img

def prep_sauvola(img):
    """
    Sauvola lokale drempelwaarde — beste voor ongelijke verlichting.
    Werkt goed op whiteboard-foto's waar het licht van de zijkant komt.
    """
    img  = _upscale(img)
    gray = _grijswaarde(img).astype(np.float32)
    # Normaliseer verlichting eerst
    bg   = cv2.GaussianBlur(gray, (0,0), 51)
    gray = cv2.divide(gray, bg, scale=255)
    # Sauvola: threshold = mean * (1 + k * (std/R - 1))
    k, R, sz = 0.15, 128, 61
    mean = cv2.boxFilter(gray, cv2.CV_32F, (sz, sz))
    sq   = cv2.boxFilter(gray*gray, cv2.CV_32F, (sz, sz))
    std  = np.sqrt(np.maximum(sq - mean*mean, 0))
    thr  = mean * (1.0 + k * (std / R - 1.0))
    out  = np.where(gray >= thr, 255, 0).astype(np.uint8)
    # Morfologisch sluiten — verbindt gebroken penstreken
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2,2))
    return cv2.morphologyEx(out, cv2.MORPH_CLOSE, k2)

def prep_otsu(img):
    """Otsu na verlichting-normalisatie — sneller dan Sauvola."""
    img  = _upscale(img)
    gray = _grijswaarde(img)
    bg   = cv2.GaussianBlur(gray.astype(np.float32), (0,0), 51)
    norm = cv2.divide(gray.astype(np.float32), bg, scale=255).astype(np.uint8)
    _, out = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return out

def prep_adaptief(img):
    """Adaptieve drempelwaarde — goed voor gedrukte documenten."""
    img  = _upscale(img)
    gray = cv2.medianBlur(_grijswaarde(img), 3)
    return cv2.adaptiveThreshold(gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)

def prep_raw(img):
    img = _upscale(img)
    return _grijswaarde(img)

PREP = {"sauvola": prep_sauvola, "otsu": prep_otsu,
        "adaptief": prep_adaptief, "raw": prep_raw}

def preprocess(img_bgr, modus):
    img_bgr = _crop_content(img_bgr)   # verwijder donkere randen voor alle modi
    return PREP.get(modus, prep_sauvola)(img_bgr)


# ═══════════════════════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════════════════════

def ocr(clean, taal, psm):
    import re as _re, xml.etree.ElementTree as _ET
    cfg = f"--oem 3 --psm {psm} -c preserve_interword_spaces=1"
    try:
        hocr = pytesseract.image_to_pdf_or_hocr(clean, lang=taal, config=cfg, extension="hocr").decode("utf-8")
        root = _ET.fromstring(hocr)
        lines_data = []
        for line in root.iter():
            if line.get("class") != "ocr_line": continue
            m = _re.search(r"bbox (\d+) (\d+) (\d+) (\d+)", line.get("title",""))
            if not m: continue
            x1, y1 = int(m.group(1)), int(m.group(2))
            words = [w.text or "" for w in line.iter() if w.get("class") == "ocrx_word" and w.text]
            if words: lines_data.append((y1, x1, " ".join(words)))
        if not lines_data: raise ValueError("leeg")
        lines_data.sort(key=lambda r: (r[0], r[1]))
        x_min = min(r[1] for r in lines_data)
        ys = [r[0] for r in lines_data]
        gaps = [ys[i+1]-ys[i] for i in range(len(ys)-1)]
        med = sorted(gaps)[len(gaps)//2] if gaps else 30
        out, prev_y = [], None
        for y, x, tekst in lines_data:
            if prev_y is not None and (y - prev_y) > med * 2.2: out.append("")
            out.append("  " * max(0, int((x - x_min) / 18)) + tekst)
            prev_y = y
        return "\n".join(out).strip()
    except Exception:
        return pytesseract.image_to_string(clean, lang=taal, config=cfg).strip()

def laad(pad):
    img = cv2.imread(str(pad))
    if img is None:
        raise ValueError(f"Kan niet laden: {pad}")
    return img


# ═══════════════════════════════════════════════════════════════════════════════
# Engine constanten
# ═══════════════════════════════════════════════════════════════════════════════

ENGINE_TESSERACT = "Tesseract (offline, gedrukt)"
ENGINE_OLLAMA    = "Ollama Vision (offline)"
ENGINE_TROCR     = "TrOCR (offline na download, handschrift)"
ENGINE_EASYOCR   = "EasyOCR (offline na download, handschrift)"
ENGINES = [ENGINE_TESSERACT, ENGINE_EASYOCR, ENGINE_OLLAMA, ENGINE_TROCR]

# ═══════════════════════════════════════════════════════════════════════════════
# EasyOCR — meerregelig handschrift
# ═══════════════════════════════════════════════════════════════════════════════

_easyocr_reader = None
_easyocr_talen  = None

def easyocr_beschikbaar() -> bool:
    try:
        import easyocr  # noqa
        return True
    except ImportError:
        return False

def easyocr_ocr(img_bgr: "np.ndarray", talen: list, status_cb=None) -> str:
    """
    EasyOCR pipeline — woord voor woord van links-boven naar rechts-onder.

    EasyOCR geeft per woord: (bbox, tekst, confidence)
    bbox = [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] (linksboven met de klok mee)

    Aanpak:
      1. Bereken voor elk woord: x_links, y_midden, bbox_hoogte
      2. Sorteer alle woorden op y_midden
      3. Groepeer op regels: woorden waarvan y_midden binnen 50% van de
         gemiddelde bbox-hoogte van elkaar liggen horen op dezelfde regel
      4. Binnen elke regel sorteren op x_links
      5. Regels samenvoegen met newline, woorden met spatie
    """
    import easyocr
    global _easyocr_reader, _easyocr_talen

    if status_cb:
        status_cb("⟳ EasyOCR laden...")

    if _easyocr_reader is None or _easyocr_talen != talen:
        _easyocr_reader = easyocr.Reader(talen, gpu=False)
        _easyocr_talen  = talen

    if status_cb:
        status_cb("⟳ EasyOCR bezig...")

    results = _easyocr_reader.readtext(img_bgr)

    if not results:
        return ""

    # Bereken per woord de meetwaarden
    woorden = []
    for bbox, tekst, conf in results:
        x_links  = bbox[0][0]                          # linker x
        y_top    = bbox[0][1]                          # bovenste y
        y_bottom = bbox[2][1]                          # onderste y
        y_mid    = (y_top + y_bottom) / 2.0            # verticaal middelpunt
        hoogte   = max(1, y_bottom - y_top)            # bbox hoogte
        woorden.append((x_links, y_mid, hoogte, tekst))

    # Gemiddelde hoogte als drempel voor regelgroepering
    gem_hoogte = sum(w[2] for w in woorden) / len(woorden)
    drempel    = gem_hoogte * 0.6   # woorden binnen 60% van gem. hoogte = zelfde regel

    # Sorteer op y_midden dan x_links
    woorden.sort(key=lambda w: (w[1], w[0]))

    # Groepeer op regels via y_midden
    regels = []
    huidige_regel = [woorden[0]]
    for woord in woorden[1:]:
        y_vorige = sum(w[1] for w in huidige_regel) / len(huidige_regel)  # gemiddeld y van huidige regel
        if abs(woord[1] - y_vorige) <= drempel:
            huidige_regel.append(woord)
        else:
            regels.append(huidige_regel)
            huidige_regel = [woord]
    regels.append(huidige_regel)

    # Binnen elke regel sorteren op x_links
    for regel in regels:
        regel.sort(key=lambda w: w[0])

    # Samenvoegen
    return "\n".join(" ".join(w[3] for w in regel) for regel in regels)

# ═══════════════════════════════════════════════════════════════════════════════
# Ollama vision OCR
# ═══════════════════════════════════════════════════════════════════════════════

OLLAMA_URL   = "http://127.0.0.1:11434"
OLLAMA_MODELLEN = []   # wordt gevuld bij check

# Vision-capable model name fragments — alleen modellen die afbeeldingen accepteren
_VISION_NAMEN = [
    "llava", "qwen2-vl", "qwen2.5-vl", "minicpm-v", "minicpm_v",
    "moondream", "bakllava", "llama3.2-vision", "granite3.2-vision",
    "llama3.2:11b", "llama3.2:90b", "gemma3", "phi3.5-vision",
    "internvl", "cogvlm", "florence",
]

def _is_vision_model(naam: str) -> bool:
    n = naam.lower()
    return any(v in n for v in _VISION_NAMEN)

def ollama_beschikbaar() -> tuple[bool, list[str]]:
    """Controleer of Ollama draait en geef uitsluitend vision-modellen terug."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        alle = [m["name"] for m in data.get("models", [])]
        vision = [m for m in alle if _is_vision_model(m)]
        return True, vision
    except Exception:
        return False, []

def ollama_start_en_wacht(status_cb=None, timeout=40) -> tuple[bool, str]:
    """
    Start Ollama als het niet draait en wacht tot het bereikbaar is.
    status_cb(pct: int, tekst: str) voor voortgang (0–100).
    Geeft (success, bericht) terug.
    """
    import subprocess, time, shutil

    ok, mods = ollama_beschikbaar()
    if ok:
        msg = (f"✓ Ollama actief — {len(mods)} vision model(len)" if mods
               else "✓ Ollama actief — geen vision model")
        if status_cb:
            status_cb(100 if mods else 80, msg)
        return True, msg

    # Zoek ollama executable
    exe = shutil.which("ollama")
    if not exe:
        import os
        for cand in [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
            r"C:\Program Files\Ollama\ollama.exe",
            r"C:\Program Files (x86)\Ollama\ollama.exe",
        ]:
            if os.path.exists(cand):
                exe = cand
                break

    if not exe:
        msg = "Ollama niet gevonden — installeer via https://ollama.com"
        if status_cb:
            status_cb(0, f"✗ {msg}")
        return False, msg

    if status_cb:
        status_cb(5, "⟳ Ollama starten...")

    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as ex:
        msg = f"Kon Ollama niet starten: {ex}"
        if status_cb:
            status_cb(0, f"✗ {msg}")
        return False, msg

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        time.sleep(0.8)
        elapsed  = time.monotonic() - start
        pct      = min(95, int(elapsed / timeout * 100))
        ok, mods = ollama_beschikbaar()
        if status_cb:
            status_cb(pct, f"⟳ Wachten op Ollama... ({int(elapsed)}s)")
        if ok:
            msg = (f"✓ Ollama gestart — {len(mods)} vision model(len)" if mods
                   else "✓ Ollama gestart — geen vision model gevonden")
            if status_cb:
                status_cb(100 if mods else 80, msg)
            return True, msg

    msg = f"Ollama start time-out ({timeout}s) — probeer handmatig: ollama serve"
    if status_cb:
        status_cb(0, f"✗ {msg}")
    return False, msg

def ollama_ocr(img_bgr: "np.ndarray", model: str,
               prompt: str = "Read all the text in this image exactly as written. "
                             "Transcribe every line from top to bottom. "
                             "Output only the raw text, no commentary.") -> str:
    """Stuur afbeelding naar Ollama vision model, geef herkende tekst terug."""
    # Geen strenge vision check — gebruiker kiest zelf
    # Encode naar JPEG bytes
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError("Kan afbeelding niet encoderen")
    b64 = base64.b64encode(buf.tobytes()).decode()

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.0},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    tekst = data.get("response", "").strip()
    # Detecteer als model de afbeelding niet kon lezen (tekst-model dat vision weigert)
    _weiger_zinnen = [
        "cannot see", "can't see", "no image", "don't see an image",
        "provide the text", "cannot interpret", "i don't have the ability",
        "as an ai", "i'm unable to view",
    ]
    if any(s in tekst.lower() for s in _weiger_zinnen):
        raise RuntimeError(
            f"Model '{model}' kon de afbeelding niet lezen.\n\n"
            "Gebruik een vision model zoals llava of llama3.2-vision."
        )
    return tekst


# ═══════════════════════════════════════════════════════════════════════════════
# TrOCR (Microsoft handschrift model — offline na eenmalige download ~300MB)
# ═══════════════════════════════════════════════════════════════════════════════

_trocr_processor = None
_trocr_model     = None
TROCR_MODELLEN = {
    "large-handwritten (~2.2GB)": "microsoft/trocr-large-handwritten",
    "base-handwritten  (~400MB)": "microsoft/trocr-base-handwritten",
    # large-printed is uitgeschakeld: incompatibel met transformers>=4.40
    # (embed_positions._float_tensor buffer blijft op meta-device)
    "base-printed      (~400MB)": "microsoft/trocr-base-printed",
}
TROCR_MODEL_ID = "microsoft/trocr-large-handwritten"  # fallback

def trocr_beschikbaar() -> bool:
    try:
        import transformers  # noqa
        return True
    except ImportError:
        return False

def trocr_in_cache(model_id: str) -> bool:
    """Controleer of TrOCR model al in lokale HuggingFace cache staat."""
    try:
        from huggingface_hub import scan_cache_dir
        cache = scan_cache_dir()
        for repo in cache.repos:
            if repo.repo_id == model_id:
                return True
        return False
    except Exception:
        # Fallback: zoek in standaard cache pad
        import os
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache",
                                 "huggingface", "hub")
        repo_naam = "models--" + model_id.replace("/", "--")
        return os.path.isdir(os.path.join(cache_dir, repo_naam))

_trocr_huidig_model = None  # bijhouden welk model geladen is

def trocr_laden(model_id=None, status_cb=None):
    """
    Laad TrOCR model (cached na eerste download).
    Wisselt automatisch als een ander model geselecteerd wordt.
    """
    global _trocr_processor, _trocr_model, _trocr_huidig_model
    if model_id is None:
        model_id = TROCR_MODEL_ID
    # Al geladen en zelfde model? Skip
    if _trocr_processor is not None and _trocr_huidig_model == model_id:
        return
    # Ander model → opnieuw laden
    _trocr_processor = None
    _trocr_model     = None
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    if status_cb:
        status_cb(f"⟳ TrOCR laden: {model_id.split('/')[-1]}...")
    import warnings
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    warnings.filterwarnings("ignore")

    # Probeer eerst offline (cache), dan online als dat faalt
    for offline in (True, False):
        try:
            kwargs = {"local_files_only": offline}
            if status_cb:
                status_cb(f"⟳ TrOCR laden ({'cache' if offline else 'download'})...")
            _trocr_processor    = TrOCRProcessor.from_pretrained(model_id, **kwargs)
            import torch as _torch
            # Laad met low_cpu_mem_usage=False om meta-tensors te vermijden.
            # large-printed heeft een non-persistent buffer (embed_positions._float_tensor)
            # die als "UNEXPECTED" wordt gemeld maar toch op meta-device belandt.
            # Na laden: forceer alle resterende meta-tensors naar CPU.
            _trocr_model        = VisionEncoderDecoderModel.from_pretrained(
                model_id,
                low_cpu_mem_usage=False,
                torch_dtype=_torch.float32,
                device_map=None,
                **kwargs,
            )
            # Materializeer eventuele resterende meta-tensors/buffers.
            # get_submodule("") faalt bij toplevel attributen — gebruik _get_parent.
            def _get_parent(model, dotted_name):
                parts = dotted_name.split(".")
                parent = model
                for p in parts[:-1]:
                    parent = getattr(parent, p)
                return parent, parts[-1]

            for name, param in list(_trocr_model.named_parameters()):
                if param.device.type == "meta":
                    parent, attr = _get_parent(_trocr_model, name)
                    setattr(parent, attr,
                            _torch.nn.Parameter(
                                _torch.empty(param.shape, dtype=_torch.float32)))

            for name, buf in list(_trocr_model.named_buffers()):
                if buf is not None and buf.device.type == "meta":
                    parent, attr = _get_parent(_trocr_model, name)
                    parent.register_buffer(
                        attr,
                        _torch.zeros(buf.shape, dtype=_torch.float32))

            _trocr_model        = _trocr_model.to(_torch.device("cpu"))
            _trocr_model.eval()
            _trocr_huidig_model = model_id
            return   # gelukt
        except Exception as ex:
            _trocr_processor = None
            _trocr_model     = None
            if offline:
                # Cache mislukt — probeer online
                if status_cb:
                    status_cb("⟳ Niet in cache — downloaden...")
                continue
            # Online ook mislukt
            raise RuntimeError(
                f"TrOCR model '{model_id}' laden mislukt.\n\n"
                f"Controleer internetverbinding of run setup_ocr.bat.\n\n"
                f"Fout: {ex}"
            )

def _detecteer_regels(img_bgr):
    """
    Detecteer tekstregels via horizontale intensiteitsprojectie.
    - Knipt eerst donkere randen weg (whiteboard-foto's hebben vaak zwarte kaders)
    - Past morfologische dilatatie toe om woorden per regel samen te voegen
    - Geeft Y-coördinaten terug in het coördinatenstelsel van de ORIGINELE afbeelding
    """
    grijs = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape)==3 else img_bgr.copy()
    h_orig, w_orig = grijs.shape

    # Stap 1: snijd donkere randen weg
    ry0, ry1, rx0, rx1 = _trim_randen(grijs)
    roi = grijs[ry0:ry1, rx0:rx1]
    h, w = roi.shape
    if h < 10 or w < 10:
        return [(0, h_orig)]   # fallback: hele afbeelding

    # Stap 2: normaliseer verlichting
    bg   = cv2.GaussianBlur(roi.astype(np.float32), (0,0), 51)
    norm = cv2.divide(roi.astype(np.float32), bg, scale=255).astype(np.uint8)

    # Stap 3: binariseer (tekst = donker → inverteer)
    thr  = cv2.adaptiveThreshold(norm, 255,
                                  cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY_INV, 31, 8)

    # Stap 4: dilateer horizontaal zodat woorden op dezelfde regel samenklonteren
    kern_h  = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w//6), 1))
    dilated = cv2.dilate(thr, kern_h, iterations=3)

    # Stap 5: horizontale projectie → vind rijbanden met tekst
    proj   = np.sum(dilated > 0, axis=1).astype(np.float32)
    proj_s = cv2.GaussianBlur(proj.reshape(-1,1), (1,11), 0).flatten()
    drempel_v = max(w * 0.015, proj_s.max() * 0.04)
    min_h  = max(8,  h // 35)
    pad    = max(4,  h // 40)

    regels, in_r, y0 = [], False, 0
    for y, val in enumerate(proj_s):
        if not in_r and val >= drempel_v:
            in_r = True; y0 = y
        elif in_r and val < drempel_v:
            in_r = False
            if (y - y0) >= min_h:
                # Vertaal terug naar originele coördinaten
                regels.append((max(0, ry0 + y0 - pad),
                                min(h_orig, ry0 + y + pad)))
    if in_r and (h - y0) >= min_h:
        regels.append((max(0, ry0 + y0 - pad), min(h_orig, ry0 + h)))

    return regels if regels else [(ry0, ry1)]


def _enhance_whiteboard(img_bgr):
    """
    Detecteert inkt/marker op whiteboard/foto.
    Geeft clean zwart-op-wit beeld + mask terug.
    Overgenomen van werkende referentie-implementatie.
    """
    # Preprocessing: belichting egaliseren, contrast, ruis, sharpening
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    bg   = cv2.GaussianBlur(gray, (0, 0), sigmaX=45, sigmaY=45)
    gray = cv2.divide(gray, bg, scale=255)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.fastNlMeansDenoising(gray, None, h=12, templateWindowSize=7, searchWindowSize=21)
    kernel = np.array([[0,-1,0],[-1,4.5,-1],[0,-1,0]], dtype=np.float32)
    gray = cv2.filter2D(gray, -1, kernel)
    img_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Opschalen naar min. 2200px breed voor betere detectie
    h, w = img_bgr.shape[:2]
    if w < 2200:
        scale   = 2200 / w
        img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    lab     = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    bg2     = cv2.GaussianBlur(l, (0, 0), 45)
    l_norm  = cv2.divide(l, bg2, scale=255)
    clahe2  = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_norm  = clahe2.apply(l_norm)

    dark  = cv2.inRange(l_norm, 0, 190)
    hsv   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    blue  = cv2.inRange(hsv, (70, 8, 20),  (155, 255, 255))
    green = cv2.inRange(hsv, (30, 8, 20),  (100, 255, 255))
    mask  = cv2.bitwise_or(dark, blue)
    mask  = cv2.bitwise_or(mask, green)
    mask  = cv2.medianBlur(mask, 3)
    k     = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask  = cv2.dilate(mask, k, iterations=1)
    mask  = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=1)

    clean          = np.full_like(l_norm, 255)
    clean[mask > 0] = 0

    return clean, mask


def _ink_density(crop: np.ndarray) -> float:
    return float(np.count_nonzero(crop)) / crop.size if crop.size else 0.0

def _find_word_boxes(img_bgr):
    clean, mask = _enhance_whiteboard(img_bgr)
    h, w = mask.shape[:2]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (24, 10))
    joined = cv2.dilate(mask, kernel, iterations=1)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    raw_h = [cv2.boundingRect(c)[3] for c in contours]
    med_h = float(np.median(raw_h)) if raw_h else 20.0
    boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < max(8, med_h*.15) or bh < max(12, med_h*.30): continue
        if bw > w * 0.90 or bh > h * 0.45: continue
        if _ink_density(mask[y:y+bh, x:x+bw]) < 0.01: continue
        pad = 14
        boxes.append([max(0, x-pad), max(0, y-pad),
                       min(w, x+bw+pad), min(h, y+bh+pad)])

    if not boxes:
        return [], clean

    boxes.sort(key=lambda b: (b[1], b[0]))

    # Groepeer op regels via mediaan-hoogte als tolerantie
    heights  = [b[3] - b[1] for b in boxes]
    median_h = np.median(heights)
    line_tol = max(20, median_h * 0.75)

    lines = []
    for box in boxes:
        cy     = (box[1] + box[3]) / 2
        placed = False
        for line in lines:
            avg_y = np.mean([(b[1] + b[3]) / 2 for b in line])
            if abs(cy - avg_y) <= line_tol:
                line.append(box)
                placed = True
                break
        if not placed:
            lines.append([box])

    lines.sort(key=lambda line: np.mean([(b[1] + b[3]) / 2 for b in line]))
    for line in lines:
        line.sort(key=lambda b: b[0])

    ordered = []
    for line_idx, line in enumerate(lines):
        for box in line:
            ordered.append((line_idx, box))

    return ordered, clean


def _resize_for_trocr(word_gray):
    """Schaal woord-crop naar formaat dat TrOCR verwacht."""
    if len(word_gray.shape) == 2:
        word_bgr = cv2.cvtColor(word_gray, cv2.COLOR_GRAY2BGR)
    else:
        word_bgr = word_gray

    h, w = word_bgr.shape[:2]

    if h < 80:
        scale    = 80 / h
        word_bgr = cv2.resize(word_bgr, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_CUBIC)

    h, w = word_bgr.shape[:2]
    if w < 180:
        pad      = (180 - w) // 2
        word_bgr = cv2.copyMakeBorder(word_bgr, 10, 10, pad, pad,
                                       cv2.BORDER_CONSTANT, value=(255, 255, 255))
    if w > 900:
        scale    = 900 / w
        word_bgr = cv2.resize(word_bgr, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
    return word_bgr


def _is_printed_model(model_id: str) -> bool:
    """Printed modellen → per-regel pipeline. Handschrift → woord-voor-woord."""
    return "printed" in (model_id or "").lower()


def trocr_ocr_printed(img_bgr, model_id=None, status_cb=None, append_cb=None) -> str:
    """
    TrOCR gedrukt: per tekstRegel via horizontale projectie.
    Gebruikt OTSU-binarisatie + projectie (geen whiteboard-preprocessing).
    Merget overlappende detecties om dubbele regels te voorkomen.
    """
    import torch
    from PIL import Image as PILImage
    trocr_laden(model_id, status_cb)
    if status_cb: status_cb("⟳ TrOCR (gedrukt): regels detecteren...")

    grijs = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape)==3 else img_bgr.copy()
    h_img, w_img = grijs.shape

    # OTSU binarisatie — tekst is donker op lichte achtergrond
    _, bw = cv2.threshold(grijs, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Horizontale projectie: aantal donkere pixels per rij
    proj   = np.sum(bw > 0, axis=1).astype(np.float32)
    proj_s = cv2.GaussianBlur(proj.reshape(-1, 1), (1, 7), 0).flatten()
    drempel = max(w_img * 0.008, proj_s.max() * 0.04)
    min_rh  = max(6, h_img // 55)
    pad     = max(2, h_img // 90)

    regels_raw, in_r, y0 = [], False, 0
    for y, val in enumerate(proj_s):
        if not in_r and val >= drempel:
            in_r = True; y0 = y
        elif in_r and val < drempel:
            in_r = False
            if (y - y0) >= min_rh:
                regels_raw.append((max(0, y0 - pad), min(h_img, y + pad)))
    if in_r and (h_img - y0) >= min_rh:
        regels_raw.append((max(0, y0 - pad), h_img))

    # Merge overlappende/te-dicht-op-elkaar regels
    regels_yx: list = []
    for r0, r1 in regels_raw:
        if regels_yx and r0 < regels_yx[-1][1] + min_rh:
            regels_yx[-1] = (regels_yx[-1][0], max(regels_yx[-1][1], r1))
        else:
            regels_yx.append((r0, r1))
    if not regels_yx:
        regels_yx = [(0, h_img)]

    totaal = len(regels_yx)
    if status_cb: status_cb(f"⟳ TrOCR (gedrukt): {totaal} regels...")
    resultaten = []
    for i, (y0, y1) in enumerate(regels_yx):
        strip = img_bgr[y0:y1, :]
        if strip.shape[0] < 5 or strip.shape[1] < 10: continue
        h, w = strip.shape[:2]
        if h < 32:
            scale = 32 / h
            strip = cv2.resize(strip, (int(w * scale), 32), interpolation=cv2.INTER_CUBIC)
        pil = PILImage.fromarray(cv2.cvtColor(strip, cv2.COLOR_BGR2RGB))
        if status_cb: status_cb(f"⟳ TrOCR regel {i+1}/{totaal}...")
        pv = _trocr_processor(images=pil, return_tensors="pt").pixel_values
        with torch.no_grad():
            ids = _trocr_model.generate(pv, max_new_tokens=128,
                                         num_beams=4, early_stopping=True)
        t = _trocr_processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        if t:
            resultaten.append(t)
            if append_cb: append_cb(t + "\n")
    return "\n".join(resultaten)


def trocr_ocr(img_bgr: "np.ndarray", model_id=None, status_cb=None,
              is_crop: bool = False, append_cb=None) -> str:
    """Dispatcher: printed → per regel, handschrift → woord-voor-woord."""
    if _is_printed_model(model_id):
        return trocr_ocr_printed(img_bgr, model_id, status_cb, append_cb)

    # ── Handschrift: woord-voor-woord ─────────────────────────────────────────
    import torch
    from PIL import Image as PILImage
    trocr_laden(model_id, status_cb)
    if status_cb: status_cb("⟳ TrOCR (handschrift): woorden detecteren...")
    ordered, clean = _find_word_boxes(img_bgr)
    if not ordered:
        if status_cb: status_cb("⟳ TrOCR: geen woorden, verwerk volledig beeld...")
        pil = PILImage.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        pv  = _trocr_processor(images=pil, return_tensors="pt").pixel_values
        with torch.no_grad():
            ids = _trocr_model.generate(pv, max_new_tokens=128)
        return _trocr_processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    totaal = len(ordered)
    if status_cb: status_cb(f"⟳ TrOCR: {totaal} woorden gevonden, verwerken...")
    huidige_regel_idx = -1; huidige_woorden = []; regels = []
    _noise = set('.,;:!?-_\'"()[]{}0123456789')

    for i, (line_idx, box) in enumerate(ordered):
        x1, y1, x2, y2 = box
        if line_idx != huidige_regel_idx:
            if huidige_woorden:
                regels.append(" ".join(huidige_woorden))
                if append_cb: append_cb("\n")
            huidige_woorden = []; huidige_regel_idx = line_idx
        bw = x2 - x1; bh = y2 - y1
        if bw < 20 or bh < 15: continue
        word_gray = clean[y1:y2, x1:x2]
        if word_gray.size > 0 and float(np.count_nonzero(word_gray)) / word_gray.size < 0.015: continue
        word_bgr = _resize_for_trocr(word_gray)
        pil = PILImage.fromarray(cv2.cvtColor(word_bgr, cv2.COLOR_BGR2RGB))
        if status_cb: status_cb(f"⟳ TrOCR woord {i+1}/{totaal}...")
        pv = _trocr_processor(images=pil, return_tensors="pt").pixel_values
        with torch.no_grad():
            ids = _trocr_model.generate(pv, max_new_tokens=32, num_beams=3, early_stopping=True)
        t = _trocr_processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        if t and len(t) >= 2 and not all(c in _noise for c in t):
            huidige_woorden.append(t)
            if append_cb: append_cb(t + " ")

    if huidige_woorden: regels.append(" ".join(huidige_woorden))
    return "\n".join(regels)


# ═══════════════════════════════════════════════════════════════════════════════
# Export
# ═══════════════════════════════════════════════════════════════════════════════

def exp_txt(tekst, pad):
    Path(pad).write_text(tekst, encoding="utf-8")

def exp_docx(tekst, pad):
    try:
        from docx import Document
        from docx.shared import Pt
        doc = Document()
        doc.styles["Normal"].font.name = "Calibri"
        doc.styles["Normal"].font.size = Pt(11)
        for r in tekst.split("\n"):
            doc.add_paragraph(r)
        doc.save(str(pad))
    except ImportError:
        raise RuntimeError("pip install python-docx")

def exp_png(img, pad):
    cv2.imwrite(str(pad), img)


# ═══════════════════════════════════════════════════════════════════════════════
# Image Enhancer
# ═══════════════════════════════════════════════════════════════════════════════

class ImageEnhancer(tk.Toplevel):
    _MAX_UNDO=10; _THROTTLE_MS=80
    def __init__(self,parent,img_bgr,callback):
        super().__init__(parent)
        self._parent=parent; self._orig=img_bgr.copy(); self._base=img_bgr.copy()
        self._work=img_bgr.copy(); self._cropped=False; self._crop_box=None
        self._gray=False; self._inverted=False; self._callback=callback; self._alive=True
        self._undo_stack=[]; self._redo_stack=[]
        self._zoom=1.0; self._off=[0,0]; self._mode="pan"
        self._drag_s=None; self._sel_s=None; self._sel_id=None
        self._smudge_busy=False; self._smudge_pend=False; self._brush_pts=[]; self._last_sched=0
        self._cursor_id=None; self._cursor_xy=None; self._tk_img=None
        self.title(f"Afbeelding verbeteren — OCR v{APP_VERSION}")
        self.configure(bg=C_BG); self.resizable(True,True); self.grab_set()
        sw,sh=parent.winfo_screenwidth(),parent.winfo_screenheight()
        ww,wh=int(sw*.86),int(sh*.86)
        self.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")
        self._build_ui()
        self.after(120,self._fit_to_window); self.after(400,self._show_tip)
        self.bind("<Control-z>",lambda e:self._undo())
        self.bind("<Control-y>",lambda e:self._redo())
    def destroy(self):
        self._alive=False; super().destroy()
    def _build_ui(self):
        tip=tk.Frame(self,bg="#3a3a1e",padx=10,pady=4); tip.pack(fill="x")
        tk.Label(tip,text="💡  Sleep=pannen  •  Shift+sleep=crop  •  Ctrl+Z/Y=undo/redo  •  Smudge=vlekken",
                 font=("Segoe UI",9),bg="#3a3a1e",fg="#f9e2af",anchor="w").pack(side="left")
        r1=tk.Frame(self,bg=C_PAN,pady=4); r1.pack(fill="x")
        def _lbl(p,t): tk.Label(p,text=t,font=FS,bg=C_PAN,fg=C_MUT).pack(side="left",padx=(10,2))
        def _sep(p):   tk.Label(p,text="│",font=FS,bg=C_PAN,fg=C_MUT).pack(side="left",padx=5)
        _lbl(r1,"Contrast:")
        self._sv_con=tk.IntVar(value=0)
        tk.Scale(r1,from_=-100,to=100,orient="horizontal",variable=self._sv_con,command=self._on_adjust,
                 length=130,showvalue=True,bg=C_PAN,fg=C_TXT,highlightthickness=0,
                 troughcolor=C_BTN,activebackground=C_ACC,font=FS).pack(side="left",padx=2)
        tk.Button(r1,text="0",font=FS,bg=C_BTN,fg=C_MUT,relief="flat",padx=4,cursor="hand2",
                  command=lambda:(self._sv_con.set(0),self._on_adjust())).pack(side="left")
        _lbl(r1,"Belichting:")
        self._sv_bel=tk.IntVar(value=0)
        tk.Scale(r1,from_=-100,to=100,orient="horizontal",variable=self._sv_bel,command=self._on_adjust,
                 length=130,showvalue=True,bg=C_PAN,fg=C_TXT,highlightthickness=0,
                 troughcolor=C_BTN,activebackground=C_ACC,font=FS).pack(side="left",padx=2)
        tk.Button(r1,text="0",font=FS,bg=C_BTN,fg=C_MUT,relief="flat",padx=4,cursor="hand2",
                  command=lambda:(self._sv_bel.set(0),self._on_adjust())).pack(side="left")
        _sep(r1)
        self._gray_var=tk.BooleanVar(value=False)
        tk.Checkbutton(r1,text="⬛ Grijstint",variable=self._gray_var,command=self._toggle_gray,
                       font=FS,bg=C_PAN,fg=C_TXT,selectcolor=C_ACC,activebackground=C_PAN,
                       relief="flat",cursor="hand2",indicatoron=False,padx=6,pady=3).pack(side="left",padx=3)
        self._inv_var=tk.BooleanVar(value=False)
        tk.Checkbutton(r1,text="⬜ Invert",variable=self._inv_var,command=self._toggle_invert,
                       font=FS,bg=C_PAN,fg=C_TXT,selectcolor=C_ACC,activebackground=C_PAN,
                       relief="flat",cursor="hand2",indicatoron=False,padx=6,pady=3).pack(side="left",padx=3)
        _sep(r1)
        self._btn_undo=tk.Button(r1,text="↺",font=("Segoe UI",12),bg=C_BTN,fg=C_TXT,
                                  relief="flat",padx=6,cursor="hand2",state="disabled",command=self._undo)
        self._btn_undo.pack(side="left",padx=2)
        self._btn_redo=tk.Button(r1,text="↻",font=("Segoe UI",12),bg=C_BTN,fg=C_TXT,
                                  relief="flat",padx=6,cursor="hand2",state="disabled",command=self._redo)
        self._btn_redo.pack(side="left",padx=2)
        _sep(r1)
        tk.Button(r1,text="↩ Reset",font=FS,bg=C_BTN,fg=C_MUT,relief="flat",padx=8,
                  cursor="hand2",command=self._reset).pack(side="left",padx=3)
        tk.Button(r1,text="✗ Annuleer",font=FS,bg=C_BTN,fg=C_MUT,relief="flat",padx=10,
                  cursor="hand2",command=self._annuleer).pack(side="right",padx=6)
        tk.Button(r1,text="✓  Bevestig & verder",font=("Segoe UI",9,"bold"),bg=C_ACC,fg="white",
                  relief="flat",padx=14,cursor="hand2",command=self._bevestig).pack(side="right",padx=4)
        r2=tk.Frame(self,bg=C_PAN,pady=3,highlightbackground=C_MUT,highlightthickness=1); r2.pack(fill="x")
        self._smudge_var=tk.BooleanVar(value=False)
        tk.Checkbutton(r2,text="✏ Smudge",variable=self._smudge_var,command=self._toggle_smudge,
                       font=FS,bg=C_PAN,fg=C_TXT,selectcolor=C_ACC,activebackground=C_PAN,
                       relief="flat",cursor="hand2",indicatoron=False,padx=6,pady=3).pack(side="left",padx=(10,4))
        _lbl(r2,"Grootte:")
        self._sv_sz=tk.IntVar(value=20)
        tk.Scale(r2,from_=4,to=80,orient="horizontal",variable=self._sv_sz,length=100,showvalue=True,
                 bg=C_PAN,fg=C_TXT,highlightthickness=0,troughcolor=C_BTN,
                 activebackground=C_ACC,font=FS).pack(side="left",padx=2)
        _sep(r2)
        self._btn_wis=tk.Button(r2,text="✗ Wis selectie",font=FS,bg=C_BTN,fg=C_MUT,
                                 relief="flat",padx=8,cursor="hand2",
                                 command=self._wis_selectie,state="disabled")
        self._btn_wis.pack(side="left",padx=4)
        _sep(r2)
        _lbl(r2,"Zoom:")
        tk.Button(r2,text="−",font=("Segoe UI",11,"bold"),bg=C_BTN,fg=C_TXT,relief="flat",
                  padx=7,cursor="hand2",command=lambda:self._zoom_step(-1)).pack(side="left",padx=1)
        self._lbl_zoom=tk.Label(r2,text="fit",font=FS,bg=C_PAN,fg=C_TXT,width=5); self._lbl_zoom.pack(side="left")
        tk.Button(r2,text="+",font=("Segoe UI",11,"bold"),bg=C_BTN,fg=C_TXT,relief="flat",
                  padx=7,cursor="hand2",command=lambda:self._zoom_step(+1)).pack(side="left",padx=1)
        tk.Button(r2,text="Passend",font=FS,bg=C_BTN,fg=C_MUT,relief="flat",padx=6,
                  cursor="hand2",command=self._fit_to_window).pack(side="left",padx=4)
        tk.Button(r2,text="100%",font=FS,bg=C_BTN,fg=C_MUT,relief="flat",padx=6,
                  cursor="hand2",command=self._zoom_100).pack(side="left",padx=2)
        self._vs=tk.StringVar(value="Sleep=pannen  •  Shift+sleep=crop  •  Ctrl+Z=undo")
        tk.Label(self,textvariable=self._vs,font=FS,bg=C_BG,fg=C_MUT,anchor="w").pack(fill="x",padx=10,pady=1)
        self._cv=tk.Canvas(self,bg="#111118",highlightthickness=0,cursor="none"); self._cv.pack(fill="both",expand=True)
        self._cv.bind("<Configure>",self._redraw); self._cv.bind("<Motion>",self._on_motion)
        self._cv.bind("<Leave>",self._on_leave); self._cv.bind("<ButtonPress-1>",self._m_press)
        self._cv.bind("<B1-Motion>",self._m_drag); self._cv.bind("<ButtonRelease-1>",self._m_release)
        self._cv.bind("<MouseWheel>",self._scroll)
        self._cv.bind("<Button-4>",lambda e:self._scroll_delta(1,e.x,e.y))
        self._cv.bind("<Button-5>",lambda e:self._scroll_delta(-1,e.x,e.y))
    def _snapshot(self):
        s=dict(work=self._work.copy(),base=self._base.copy(),con=self._sv_con.get(),
               bel=self._sv_bel.get(),gray=self._gray,inv=self._inverted,
               crop=self._cropped,box=self._crop_box)
        self._undo_stack.append(s)
        if len(self._undo_stack)>self._MAX_UNDO: self._undo_stack.pop(0)
        self._redo_stack.clear(); self._update_ud_buttons()
    def _current_state(self):
        return dict(work=self._work.copy(),base=self._base.copy(),con=self._sv_con.get(),
                    bel=self._sv_bel.get(),gray=self._gray,inv=self._inverted,
                    crop=self._cropped,box=self._crop_box)
    def _restore(self,state):
        if not self._alive: return
        self._work=state["work"].copy(); self._base=state["base"].copy()
        self._sv_con.set(state["con"]); self._sv_bel.set(state["bel"])
        self._gray=state["gray"]; self._gray_var.set(self._gray)
        self._inverted=state["inv"]; self._inv_var.set(self._inverted)
        self._cropped=state["crop"]; self._crop_box=state["box"]
        try: self._btn_wis.config(state="normal" if self._cropped else "disabled")
        except tk.TclError: pass
        self._update_ud_buttons(); self._redraw()
    def _undo(self):
        if not self._alive or not self._undo_stack: return
        self._redo_stack.append(self._current_state()); self._restore(self._undo_stack.pop())
        self._vs.set(f"Undo — {len(self._undo_stack)} stap(pen) nog beschikbaar")
    def _redo(self):
        if not self._alive or not self._redo_stack: return
        self._undo_stack.append(self._current_state()); self._restore(self._redo_stack.pop())
        self._vs.set(f"Redo — {len(self._redo_stack)} stap(pen) vooruit")
    def _update_ud_buttons(self):
        if not self._alive: return
        try:
            self._btn_undo.config(state="normal" if self._undo_stack else "disabled")
            self._btn_redo.config(state="normal" if self._redo_stack else "disabled")
        except tk.TclError: pass
    def _on_adjust(self,_=None): self._snapshot(); self._apply_adjust()
    def _apply_adjust(self):
        con=self._sv_con.get(); bel=self._sv_bel.get()
        img=self._orig.copy().astype(np.float32)
        if bel!=0: img=img+bel*1.5
        if con!=0: img=(img-127)*(1.0+con/100.0)+127
        img=np.clip(img,0,255).astype(np.uint8)
        if self._gray: img=cv2.cvtColor(cv2.cvtColor(img,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        if self._inverted: img=cv2.bitwise_not(img)
        self._base=img
        if self._cropped and self._crop_box:
            x1,y1,x2,y2=self._crop_box; self._work=self._base[y1:y2,x1:x2].copy()
        else: self._work=self._base.copy()
        self._redraw()
    def _toggle_gray(self):
        self._snapshot(); self._gray=self._gray_var.get(); self._apply_adjust()
        self._vs.set("Grijstint AAN" if self._gray else "Grijstint UIT")
    def _toggle_invert(self):
        self._snapshot(); self._inverted=self._inv_var.get(); self._apply_adjust()
        self._vs.set("Invert AAN" if self._inverted else "Invert UIT")
    def _toggle_smudge(self):
        self._mode="smudge" if self._smudge_var.get() else "pan"
        self._vs.set("✏ Smudge AAN" if self._mode=="smudge" else "Sleep=pannen  •  Shift+sleep=crop")
        self._draw_cursor(self._cursor_xy)
    def _smudge_apply(self):
        if not self._brush_pts: self._smudge_busy=False; return
        pts,self._brush_pts=self._brush_pts[:],[]; r=self._sv_sz.get()
        img=self._work.copy(); h,w=img.shape[:2]
        mask=np.zeros((h,w),dtype=np.uint8)
        for bx,by in pts:
            if 0<=bx<w and 0<=by<h: cv2.circle(mask,(bx,by),r,255,-1)
        if mask.any(): self._work=cv2.inpaint(img,mask,inpaintRadius=max(3,r//2),flags=cv2.INPAINT_TELEA)
        self._smudge_busy=False
        if self._smudge_pend: self._smudge_pend=False; self._schedule_smudge()
        else: self.after(0,self._redraw)
    def _schedule_smudge(self):
        if self._smudge_busy: self._smudge_pend=True; return
        self._smudge_busy=True
        import threading as _th; _th.Thread(target=self._smudge_apply,daemon=True).start()
    def _add_smudge_pt(self,cx,cy):
        bx,by=self._canvas_to_img(cx,cy); self._brush_pts.append((bx,by))
        import time; now=int(time.monotonic()*1000)
        if now-self._last_sched>=self._THROTTLE_MS: self._last_sched=now; self._schedule_smudge()
    def _wis_selectie(self):
        self._snapshot(); self._cropped=False; self._crop_box=None; self._work=self._base.copy()
        if self._sel_id:
            try: self._cv.delete(self._sel_id)
            except tk.TclError: pass
            self._sel_id=None
        try: self._btn_wis.config(state="disabled")
        except tk.TclError: pass
        self._vs.set("Selectie gewist"); self._fit_to_window()
    def _do_crop(self,cx1,cy1,cx2,cy2):
        bx1,by1=self._canvas_to_img(min(cx1,cx2),min(cy1,cy2))
        bx2,by2=self._canvas_to_img(max(cx1,cx2),max(cy1,cy2))
        ih,iw=self._base.shape[:2]
        bx1,by1=max(0,bx1),max(0,by1); bx2,by2=min(iw,bx2),min(ih,by2)
        if (bx2-bx1)<10 or (by2-by1)<10: return
        self._snapshot(); self._crop_box=(bx1,by1,bx2,by2); self._cropped=True
        self._work=self._base[by1:by2,bx1:bx2].copy()
        try: self._btn_wis.config(state="normal")
        except tk.TclError: pass
        self._vs.set(f"Crop: {bx2-bx1}×{by2-by1}px — Ctrl+Z om terug"); self._fit_to_window()
    def _on_motion(self,e): self._cursor_xy=(e.x,e.y); self._draw_cursor((e.x,e.y))
    def _on_leave(self,e):
        self._cursor_xy=None
        if self._cursor_id:
            try: self._cv.delete(self._cursor_id)
            except tk.TclError: pass
            self._cursor_id=None
    def _m_press(self,e):
        if self._mode=="smudge":
            self._snapshot(); self._brush_pts=[]; self._add_smudge_pt(e.x,e.y)
        elif e.state&0x0001:
            self._mode_tmp="select"; self._sel_s=(e.x,e.y)
            if self._sel_id: self._cv.delete(self._sel_id)
            self._sel_id=self._cv.create_rectangle(e.x,e.y,e.x,e.y,outline=C_SEL,width=2,dash=(5,3),tags="sel")
        else:
            self._mode_tmp="pan"; self._drag_s=(e.x,e.y,self._off[0],self._off[1])
    def _m_drag(self,e):
        self._cursor_xy=(e.x,e.y)
        if self._mode=="smudge": self._add_smudge_pt(e.x,e.y); self._draw_cursor((e.x,e.y))
        elif getattr(self,"_mode_tmp","pan")=="select" and self._sel_s:
            x0,y0=self._sel_s; self._cv.coords(self._sel_id,x0,y0,e.x,e.y)
        elif getattr(self,"_mode_tmp","pan")=="pan" and self._drag_s:
            dx=e.x-self._drag_s[0]; dy=e.y-self._drag_s[1]
            ih,iw=self._work.shape[:2]; cw=max(self._cv.winfo_width(),1); ch=max(self._cv.winfo_height(),1)
            self._off[0]=int(max(0,min(max(0,iw-cw/self._zoom),self._drag_s[2]-dx/self._zoom)))
            self._off[1]=int(max(0,min(max(0,ih-ch/self._zoom),self._drag_s[3]-dy/self._zoom)))
            self._redraw()
    def _m_release(self,e):
        if self._mode=="smudge":
            if self._brush_pts: self._schedule_smudge()
        elif getattr(self,"_mode_tmp","pan")=="select" and self._sel_s:
            x0,y0=self._sel_s; self._sel_s=None; self._mode_tmp="pan"
            if self._sel_id: self._cv.delete(self._sel_id); self._sel_id=None
            self._do_crop(x0,y0,e.x,e.y)
        self._drag_s=None
    def _draw_cursor(self,xy):
        if self._cursor_id:
            try: self._cv.delete(self._cursor_id)
            except tk.TclError: pass
            self._cursor_id=None
        if xy is None or not self._alive: return
        cx,cy=xy; smudge=self._mode=="smudge"
        r=max(2.0,self._sv_sz.get()*self._zoom) if smudge else 5.0
        color=C_SEL if smudge else C_MUT; width=2 if smudge else 1
        try:
            self._cursor_id=self._cv.create_oval(cx-r,cy-r,cx+r,cy+r,
                outline=color,width=width,dash=(5,3),tags="cursor")
            self._cv.tag_raise("cursor")
        except tk.TclError: pass
    def _canvas_to_img(self,cx,cy): return int(cx/self._zoom+self._off[0]),int(cy/self._zoom+self._off[1])
    def _clamp_offset(self):
        ih,iw=self._work.shape[:2]; cw=max(self._cv.winfo_width(),1); ch=max(self._cv.winfo_height(),1)
        self._off[0]=max(0,min(max(0,iw-int(cw/self._zoom)),self._off[0]))
        self._off[1]=max(0,min(max(0,ih-int(ch/self._zoom)),self._off[1]))
    def _zoom_step(self,d):
        cw,ch=max(self._cv.winfo_width(),1)//2,max(self._cv.winfo_height(),1)//2; self._scroll_delta(d,cw,ch)
    def _zoom_100(self):
        cw,ch=max(self._cv.winfo_width(),1)//2,max(self._cv.winfo_height(),1)//2
        bx,by=self._canvas_to_img(cw,ch); self._zoom=1.0
        self._off=[max(0,bx-cw),max(0,by-ch)]; self._clamp_offset()
        self._lbl_zoom.config(text="100%"); self._redraw()
    def _fit_to_window(self):
        self.update_idletasks(); cw=max(self._cv.winfo_width(),400); ch=max(self._cv.winfo_height(),300)
        ih,iw=self._work.shape[:2]; self._zoom=min(cw/iw,ch/ih,1.0); self._off=[0,0]
        self._lbl_zoom.config(text=f"{int(self._zoom*100)}%"); self._redraw()
    def _scroll(self,e): self._scroll_delta(1 if e.delta>0 else -1,e.x,e.y)
    def _scroll_delta(self,d,cx,cy):
        old=self._zoom; step=0.15 if self._zoom<1.5 else 0.25
        self._zoom=max(0.1,min(8.0,self._zoom+d*step))
        bx=int(cx/old+self._off[0]); by=int(cy/old+self._off[1])
        self._off[0]=int(bx-cx/self._zoom); self._off[1]=int(by-cy/self._zoom)
        self._clamp_offset(); self._lbl_zoom.config(text=f"{int(self._zoom*100)}%")
        self._redraw(); self._draw_cursor(self._cursor_xy)
    def _redraw(self,_=None):
        if not self._alive or self._work is None: return
        cw=max(self._cv.winfo_width(),1); ch=max(self._cv.winfo_height(),1)
        ih,iw=self._work.shape[:2]
        x0=max(0,int(self._off[0])); y0=max(0,int(self._off[1]))
        x1=min(iw,x0+int(cw/self._zoom)+2); y1=min(ih,y0+int(ch/self._zoom)+2)
        if x1<=x0 or y1<=y0: return
        crop=self._work[y0:y1,x0:x1]
        out_w=min(cw,int((x1-x0)*self._zoom)); out_h=min(ch,int((y1-y0)*self._zoom))
        if out_w<1 or out_h<1: return
        interp=cv2.INTER_NEAREST if self._zoom>=2.0 else cv2.INTER_LINEAR
        disp=cv2.resize(crop,(out_w,out_h),interpolation=interp)
        pil=Image.fromarray(cv2.cvtColor(disp,cv2.COLOR_BGR2RGB))
        self._tk_img=ImageTk.PhotoImage(pil)
        try:
            self._cv.delete("img"); self._cv.create_image(0,0,anchor="nw",image=self._tk_img,tags="img")
        except tk.TclError: return
        self._draw_cursor(self._cursor_xy)
    def _reset(self):
        self._undo_stack.clear(); self._redo_stack.clear()
        self._work=self._orig.copy(); self._base=self._orig.copy()
        self._cropped=False; self._crop_box=None; self._sv_con.set(0); self._sv_bel.set(0)
        self._gray=False; self._gray_var.set(False); self._inverted=False; self._inv_var.set(False)
        self._smudge_var.set(False); self._mode="pan"
        try: self._btn_wis.config(state="disabled")
        except tk.TclError: pass
        self._update_ud_buttons(); self._vs.set("Reset — terug naar origineel"); self._fit_to_window()
    def _bevestig(self): self._callback(self._work.copy()); self.destroy()
    def _annuleer(self): self._callback(None); self.destroy()
    def _show_tip(self):
        if not self._alive: return
        messagebox.showinfo("Verbetertip",
            "Stap 1 — Sliders: contrast/belichting.\n"
            "Stap 2 — Grijstint of Invert indien nodig.\n"
            "Stap 3 — Smudge: penseel over vlekken.\n"
            "Stap 4 — Shift+sleep: selectie/autocrop.\n"
            "Stap 5 — Ctrl+Z / ↺ voor undo.\n"
            "Stap 6 — Bevestig & verder.",parent=self)

# ═══════════════════════════════════════════════════════════════════════════════
# Canvas met rubber-band selectie
# ═══════════════════════════════════════════════════════════════════════════════

class Canvas(tk.Canvas):
    def __init__(self, parent, on_crop, **kw):
        super().__init__(parent, bg=C_BG, highlightthickness=0, **kw)
        self._on_crop = on_crop
        self._orig  = None
        self._s     = 1.0
        self._off   = (0, 0)
        self._ss    = None   # sel start
        self._sr    = None   # sel rect id
        self._tk    = None   # tk image ref
        self.bind("<Configure>",       self._draw)
        self.bind("<ButtonPress-1>",   self._s1)
        self.bind("<B1-Motion>",       self._sm)
        self.bind("<ButtonRelease-1>", self._se)

    def set_img(self, img):
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self._orig = img
        self.clr_sel()
        self._draw()

    def clr(self):
        self._orig = None
        self.clr_sel()
        self.delete("all")
        w = max(self.winfo_width(), 300)
        h = max(self.winfo_height(), 100)
        self.create_text(w//2, h//2,
            text="Sleep een afbeelding hierheen\nof klik Openen",
            fill=C_MUT, font=FS, justify="center")

    def clr_sel(self):
        if self._sr:
            self.delete(self._sr)
            self._sr = None
        self._ss = None

    def _draw(self, e=None):
        if self._orig is None:
            return
        cw = max(self.winfo_width(), 1)
        ch = max(self.winfo_height(), 1)
        ih, iw = self._orig.shape[:2]
        s = min(cw/iw, ch/ih, 1.0)
        nw, nh = max(1,int(iw*s)), max(1,int(ih*s))
        self._s   = s
        self._off = ((cw-nw)//2, (ch-nh)//2)
        sm = cv2.resize(self._orig, (nw,nh), interpolation=cv2.INTER_AREA)
        tk = ImageTk.PhotoImage(Image.fromarray(sm))
        self.delete("img")
        ox, oy = self._off
        self.create_image(ox, oy, anchor="nw", image=tk, tags="img")
        self._tk = tk
        if self._sr:
            self.tag_raise(self._sr)

    def _s1(self, e):
        if self._orig is None:
            return
        self._ss = (e.x, e.y)
        if self._sr:
            self.delete(self._sr)
        self._sr = self.create_rectangle(e.x,e.y,e.x,e.y,
            outline=C_SEL, width=2, dash=(4,2))

    def _sm(self, e):
        if self._ss and self._sr:
            x0,y0 = self._ss
            self.coords(self._sr, x0,y0,e.x,e.y)

    def _se(self, e):
        if not self._ss:
            return
        x0,y0 = self._ss
        self._ss = None
        cx1,cx2 = min(x0,e.x), max(x0,e.x)
        cy1,cy2 = min(y0,e.y), max(y0,e.y)
        if (cx2-cx1)<10 or (cy2-cy1)<10:
            self.clr_sel()
            return
        ox,oy = self._off
        s = self._s
        ih,iw = self._orig.shape[:2]
        bx1 = max(0,  int((cx1-ox)/s))
        by1 = max(0,  int((cy1-oy)/s))
        bx2 = min(iw, int((cx2-ox)/s))
        by2 = min(ih, int((cy2-oy)/s))
        if bx2>bx1 and by2>by1:
            self._on_crop(bx1,by1,bx2,by2)


# ═══════════════════════════════════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════════════════════════════════

_BASE = TkinterDnD.Tk if _DND else tk.Tk

class App(_BASE):
    def __init__(self):
        super().__init__()
        self.title(f"OCR  v{APP_VERSION}")
        self.configure(bg=C_BG)
        self.geometry("1280x780")
        self.minsize(960, 620)

        self._pad      = None   # Path
        self._bgr      = None
        self._clean    = None
        self._crop_bgr = None
        self._crop_cln = None
        self._tekst    = ""
        self._sel_actief = False

        self._vm  = tk.StringVar(value="Whiteboard / Sauvola")
        self._vt  = tk.StringVar(value="NL + EN")
        self._vp  = tk.StringVar(value="11 — Sparse (handschrift/bord)")
        self._vs  = tk.StringVar(value="Sleep een afbeelding of klik Openen")
        self._ve  = tk.StringVar(value=ENGINE_TESSERACT)
        self._vo  = tk.StringVar(value="— selecteer Ollama model —")
        self._vtm = tk.StringVar(value=list(TROCR_MODELLEN.keys())[0])

        self._ui()
        if _DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._drop)


    def _btn(self, p, t, c, acc=False):
        bg = C_ACC if acc else C_BTN
        fg = "white" if acc else C_TXT
        return tk.Button(p, text=t, command=c, font=FS, bg=bg, fg=fg,
                         relief="flat", bd=0, padx=10, pady=5,
                         cursor="hand2", activebackground=bg)

    def _ui(self):
        # ── Rij 1: Acties ─────────────────────────────────────────────────────
        tb1 = tk.Frame(self, bg=C_PAN, pady=6)
        tb1.pack(fill="x")
        tk.Label(tb1, text="OCR", font=FT, bg=C_PAN, fg=C_ACC).pack(side="left", padx=12)
        self._btn(tb1,"📂 Openen",          self._open).pack(side="left", padx=3)
        self._btn(tb1,"↩ Verbeteraar",      self._heropenen_enhancer).pack(side="left", padx=3)
        self._btn_ocr_vol = self._btn(tb1,"🔍 OCR volledig", self._ocr_vol, True)
        self._btn_ocr_vol.pack(side="left", padx=3)
        self._btn_ocr_sel = self._btn(tb1,"✂ OCR selectie", self._ocr_sel)
        self._btn_ocr_sel.pack(side="left", padx=3)
        self._btn_reset_sel = self._btn(tb1,"✗ Reset selectie", self._reset_selectie)
        self._btn_reset_sel.pack(side="left", padx=3)
        self._btn(tb1,"👁 Toon preprocessed", self._toon_prep).pack(side="left", padx=3)
        self._btn(tb1,"💾 .txt",             lambda: self._exp("txt")).pack(side="left", padx=3)
        self._btn(tb1,"🖼 Sla verbeterd op", self._sla_verbeterd_op).pack(side="left", padx=3)
        tk.Label(tb1, textvariable=self._vs, font=FS,
                 bg=C_PAN, fg=C_MUT).pack(side="right", padx=12)

        # ── Rij 2: Engine + opties ────────────────────────────────────────────
        # Gebruik grid zodat pack_forget/pack niet zorgt voor verdwijnende widgets
        tb2 = tk.Frame(self, bg=C_PAN, pady=4,
                       highlightbackground=C_MUT, highlightthickness=1)
        tb2.pack(fill="x")
        tb2.columnconfigure(2, weight=1)   # opties-kolom mag groeien

        # Kolom 0+1: Engine label + dropdown
        tk.Label(tb2, text="Engine:", font=FS, bg=C_PAN,
                 fg=C_MUT).grid(row=0, column=0, padx=(12,2), pady=4)
        self._cb_engine = ttk.Combobox(tb2, textvariable=self._ve,
                                 values=ENGINES, state="readonly", width=32)
        self._cb_engine.grid(row=0, column=1, padx=(0,8), pady=4)
        self._cb_engine.bind("<<ComboboxSelected>>", self._on_engine_change)

        # Kolom 2: engine-specifieke opties frame (wordt gewisseld)
        self._opts_frame = tk.Frame(tb2, bg=C_PAN)
        self._opts_frame.grid(row=0, column=2, sticky="w")

        # Tesseract opties — in _opts_frame, altijd aangemaakt, tonen/verbergen via grid
        self._frame_tess = tk.Frame(self._opts_frame, bg=C_PAN)
        for lbl, var, vals, w in [
            ("Preprocessing:", self._vm, list(MODI.keys()),  22),
            ("Taal:",          self._vt, list(TALEN.keys()), 10),
            ("PSM:",           self._vp, list(PSM_OPTIES.keys()), 24),
        ]:
            tk.Label(self._frame_tess, text=lbl, font=FS,
                     bg=C_PAN, fg=C_MUT).pack(side="left", padx=(6,2))
            ttk.Combobox(self._frame_tess, textvariable=var, values=vals,
                         state="readonly", width=w).pack(side="left", padx=2)
        self._frame_tess.pack()   # standaard zichtbaar (Tesseract is default)

        # Ollama opties
        self._frame_ollama = tk.Frame(self._opts_frame, bg=C_PAN)
        self._lbl_ollama_lamp = tk.Label(self._frame_ollama, text="●",
                                          font=("Segoe UI", 14), bg=C_PAN, fg=C_MUT)
        self._lbl_ollama_lamp.pack(side="left", padx=(6,2))
        tk.Label(self._frame_ollama, text="Model:", font=FS,
                 bg=C_PAN, fg=C_MUT).pack(side="left", padx=(0,2))
        self._cb_ollama = ttk.Combobox(self._frame_ollama, textvariable=self._vo,
                                       values=[], state="normal", width=26)
        self._cb_ollama.pack(side="left", padx=2)
        tk.Button(self._frame_ollama, text="🔄", font=FS,
                  bg=C_BTN, fg=C_TXT, relief="flat", padx=5, cursor="hand2",
                  command=self._ollama_refresh).pack(side="left", padx=2)
        tk.Button(self._frame_ollama, text="▶ Start Ollama", font=FS,
                  bg=C_BTN, fg=C_TXT, relief="flat", padx=6, cursor="hand2",
                  command=self._ollama_auto_start).pack(side="left", padx=2)
        self._ollama_pct  = tk.IntVar(value=0)
        self._ollama_prog = ttk.Progressbar(self._frame_ollama, variable=self._ollama_pct,
                                             maximum=100, length=80, mode="determinate")
        self._ollama_prog.pack(side="left", padx=4)
        self._lbl_ollama_status = tk.Label(self._frame_ollama, font=FS,
                                            bg=C_PAN, fg=C_MUT, text="", width=28, anchor="w")
        self._lbl_ollama_status.pack(side="left", padx=4)
        # frame_ollama niet getoond bij start

        # EasyOCR opties
        self._frame_easyocr = tk.Frame(self._opts_frame, bg=C_PAN)
        tk.Label(self._frame_easyocr, text="Talen:", font=FS,
                 bg=C_PAN, fg=C_MUT).pack(side="left", padx=(6,2))
        self._veasy = tk.StringVar(value="nl, en")
        tk.Entry(self._frame_easyocr, textvariable=self._veasy,
                 width=12, font=FS, bg=C_BTN, fg=C_TXT,
                 insertbackground=C_TXT, relief="flat").pack(side="left", padx=2)
        self._lbl_easyocr_info = tk.Label(self._frame_easyocr, font=FS,
                                           bg=C_PAN, fg=C_MUT, text="")
        self._lbl_easyocr_info.pack(side="left", padx=8)
        # frame_easyocr niet getoond bij start

        # TrOCR opties
        self._frame_trocr = tk.Frame(self._opts_frame, bg=C_PAN)
        tk.Label(self._frame_trocr, text="Model:", font=FS,
                 bg=C_PAN, fg=C_MUT).pack(side="left", padx=(6,2))
        self._cb_trocr_model = ttk.Combobox(
                     self._frame_trocr, textvariable=self._vtm,
                     values=list(TROCR_MODELLEN.keys()),
                     state="readonly", width=24)
        self._cb_trocr_model.pack(side="left", padx=2)
        self._lbl_trocr_info = tk.Label(self._frame_trocr, font=FS,
                                         bg=C_PAN, fg=C_MUT, text="")
        self._lbl_trocr_info.pack(side="left", padx=8)
        # frame_trocr niet getoond bij start

        # Kolom 3: status
        self._ve_status = tk.StringVar(value="")
        tk.Label(tb2, textvariable=self._ve_status, font=FS,
                 bg=C_PAN, fg=C_GRN).grid(row=0, column=3, padx=12, sticky="e")
        tb2.columnconfigure(3, weight=0)

        # ── Content ───────────────────────────────────────────────────────────
        ct = tk.Frame(self, bg=C_BG)
        ct.pack(fill="both", expand=True, padx=8, pady=8)
        ct.columnconfigure(0, weight=3); ct.columnconfigure(1, weight=2)
        ct.rowconfigure(0, weight=1)

        # Links: canvas
        lf = tk.Frame(ct, bg=C_PAN)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0,4))
        lf.rowconfigure(1, weight=1); lf.columnconfigure(0, weight=1)
        lh = tk.Frame(lf, bg=C_PAN)
        lh.grid(row=0, column=0, sticky="ew", padx=8, pady=(6,2))
        tk.Label(lh, text="Preview — klik+sleep = crop",
                 font=FS, bg=C_PAN, fg=C_MUT).pack(side="left")
        self._btn(lh,"Wis selectie",self._wis_sel).pack(side="right")
        self._cv = Canvas(lf, on_crop=self._on_crop)
        self._cv.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        # Rechts: tekst
        rf = tk.Frame(ct, bg=C_PAN)
        rf.grid(row=0, column=1, sticky="nsew", padx=(4,0))
        rf.rowconfigure(1, weight=1); rf.columnconfigure(0, weight=1)
        rh = tk.Frame(rf, bg=C_PAN)
        rh.grid(row=0, column=0, sticky="ew", padx=8, pady=(6,2))
        tk.Label(rh, text="Herkende tekst",
                 font=FS, bg=C_PAN, fg=C_MUT).pack(side="left")
        self._btn(rh,"Alles selecteren",self._sel_all).pack(side="right")
        sb = tk.Scrollbar(rf, orient="vertical")
        self._tw = tk.Text(rf, font=FM, bg=C_BG, fg=C_TXT,
                           insertbackground=C_TXT, relief="flat", bd=0,
                           padx=12, pady=8, wrap="word", yscrollcommand=sb.set)
        sb.config(command=self._tw.yview)
        self._tw.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

    # ── Engine wissel ─────────────────────────────────────────────────────────
    def _on_engine_change(self, e=None):
        engine = self._ve.get()
        # Verberg alle engine-frames
        for f in (self._frame_tess, self._frame_ollama,
                  self._frame_easyocr, self._frame_trocr):
            f.pack_forget()
        self._ve_status.set("")

        if engine == ENGINE_TESSERACT:
            self._frame_tess.pack(anchor="w")

        elif engine == ENGINE_EASYOCR:
            self._frame_easyocr.pack(anchor="w")
            if easyocr_beschikbaar():
                self._lbl_easyocr_info.config(text="✓ EasyOCR beschikbaar")
                self._ve_status.set("Talen: komma-gescheiden codes, bijv. 'nl, en'")
            else:
                self._lbl_easyocr_info.config(text="⚠ pip install easyocr")
                self._ve_status.set("⚠ pip install easyocr")

        elif engine == ENGINE_OLLAMA:
            self._frame_ollama.pack(anchor="w")
            self._ollama_lamp_set(False)
            self._lbl_ollama_status.config(text="⟳ controleren...", fg=C_MUT)
            self._ollama_pct.set(0)
            import threading as _t
            _t.Thread(target=self._ollama_check_async, daemon=True).start()

        elif engine == ENGINE_TROCR:
            self._frame_trocr.pack(anchor="w")
            ok = trocr_beschikbaar()
            if ok:
                # Check welke modellen al in cache staan
                cached_labels = []
                cached_ids    = {}
                niet_cached   = []
                for label, mid in TROCR_MODELLEN.items():
                    if trocr_in_cache(mid):
                        cached_labels.append(label)
                        cached_ids[label] = mid
                    else:
                        niet_cached.append(label.split()[0])

                # Toon alle modellen — markeer gecachte met ✓
                display_labels = []
                for label, mid in TROCR_MODELLEN.items():
                    prefix = "✓ " if trocr_in_cache(mid) else "↓ "
                    display_labels.append(prefix + label)

                self._cb_trocr_model.config(values=display_labels)
                # Herstel huidige selectie met prefix
                huidig = self._vtm.get().lstrip("✓↓ ")
                for dl in display_labels:
                    if huidig in dl:
                        self._vtm.set(dl)
                        break
                else:
                    self._vtm.set(display_labels[0])

                n_cached = len(cached_labels)
                self._ve_status.set(
                    f"✓ {n_cached}/{len(TROCR_MODELLEN)} in cache  — ↓ = wordt gedownload bij gebruik")

                self._lbl_trocr_info.config(
                    text="⚠ Gebruik 'OCR selectie' met crop voor beste resultaat")
            else:
                self._ve_status.set("⚠ pip install transformers torch")
                self._lbl_trocr_info.config(text="")

    def _voer_ocr_uit(self, img_bgr):
        """Centrale OCR dispatcher — kiest engine op basis van dropdown."""
        engine = self._ve.get()
        if engine == ENGINE_TESSERACT:
            modus = MODI.get(self._vm.get(), "sauvola")
            taal  = TALEN.get(self._vt.get(), "nld+eng")
            psm   = PSM_OPTIES.get(self._vp.get(), 11)
            cln   = preprocess(img_bgr, modus)
            # Toon preprocessed in canvas
            self.after(0, lambda c=cln: self._cv.set_img(c))
            if img_bgr is self._bgr:
                self._clean = cln
            else:
                self._crop_cln = cln
            return ocr(cln, taal, psm), f"Tesseract | {self._vm.get()} | PSM {psm}"

        elif engine == ENGINE_EASYOCR:
            if not easyocr_beschikbaar():
                raise RuntimeError("pip install easyocr")
            talen = [t.strip() for t in self._veasy.get().split(",") if t.strip()]
            if not talen:
                talen = ["nl", "en"]
            def _status(s): self.after(0, lambda: self._vs.set(s))
            tekst = easyocr_ocr(img_bgr, talen, _status)
            return tekst, f"EasyOCR | {', '.join(talen)}"

        elif engine == ENGINE_OLLAMA:
            model = self._vo.get().strip()
            if not model or model.startswith("—"):
                raise RuntimeError(
                    "Geen Ollama model geselecteerd.\n\n"
                    "Klik 🔄 om beschikbare vision modellen te zoeken,\n"
                    "of typ een modelnaam handmatig (bijv: llava).\n\n"
                    "Installeer: ollama pull llava"
                )
            def _st(s): self.after(0, lambda: self._vs.set(s))
            return ollama_ocr(img_bgr, model), f"Ollama | {model}"

        elif engine == ENGINE_TROCR:
            if not trocr_beschikbaar():
                raise RuntimeError("pip install transformers torch")
            # Strip ✓/↓ prefix uit display label
            model_label_raw = self._vtm.get().lstrip("✓↓ ")
            model_label     = next(
                (l for l in TROCR_MODELLEN if model_label_raw in l), 
                list(TROCR_MODELLEN.keys())[0])
            model_id = TROCR_MODELLEN[model_label]
            is_crop  = self._sel_actief
            # Bij volledig beeld met groot formaat: waarschuw
            h, w = img_bgr.shape[:2]
            if not is_crop and (w > 1500 or h > 1000):
                if not messagebox.askyesno(
                    "TrOCR tip",
                    "TrOCR is getraind op tekstregels, niet op volledige foto's.\n\n"
                    "Beste resultaat: teken een selectie (crop) rondom alleen de tekst,\n"
                    "gebruik dan 'OCR selectie'.\n\n"
                    "Toch doorgaan met volledig beeld?",
                    icon="warning"
                ):
                    raise RuntimeError("Geannuleerd — gebruik 'OCR selectie' met een crop")
            def _status(s): self.after(0, lambda: self._vs.set(s))
            def _append(s):
                def _do(s=s):
                    self._tw.config(state="normal")
                    self._tw.insert("end", s)
                    self._tw.see("end")
                    self.update_idletasks()
                self.after(0, _do)
            self._tw.config(state="normal")
            self._tw.delete("1.0", "end")
            tekst = trocr_ocr(img_bgr, model_id, _status,
                               is_crop=is_crop, append_cb=_append)
            self._tekst = tekst
            return tekst, f"TrOCR | {model_label.split('(')[0].strip()}"

        raise RuntimeError(f"Onbekende engine: {engine}")

    # ── Laden ─────────────────────────────────────────────────────────────────
    def _open(self):
        p = filedialog.askopenfilename(filetypes=[
            ("Afbeeldingen","*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
            ("Alle","*.*")])
        if p: self._load(Path(p))

    def _drop(self, e):
        raw = e.data.strip()
        if raw.startswith("{") and raw.endswith("}"): raw = raw[1:-1]
        p = Path(raw.split("} {")[0])
        if p.suffix.lower() in {".png",".jpg",".jpeg",".bmp",
                                  ".tif",".tiff",".webp"}:
            self._load(p)
        else:
            self._vs.set(f"⚠ Niet ondersteund: {p.suffix}")

    def _load(self, p):
        try:
            img = laad(p)
            self._orig_bgr = img; self._pad = p; self._sel_actief = False
            self._vs.set(f"Laden: {p.name} — verbetervenster opent...")
            self.update_idletasks()
            ImageEnhancer(self, img, lambda r: self._na_enhancer(r, img, p))
        except Exception as ex:
            messagebox.showerror("Fout", str(ex))

    def _na_enhancer(self, result, origineel, p):
        img = result if result is not None else origineel
        self._bgr=img; self._clean=None; self._crop_bgr=None
        self._crop_cln=None; self._sel_actief=False
        self._cv.set_img(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        label = "verbeterd" if result is not None else "origineel"
        self._vs.set(f"Geladen [{label}]: {p.name}  {img.shape[1]}×{img.shape[0]}px")

    def _heropenen_enhancer(self):
        if not hasattr(self, "_orig_bgr") or self._orig_bgr is None:
            messagebox.showwarning("", "Open eerst een afbeelding."); return
        ImageEnhancer(self, self._orig_bgr,
                      lambda r: self._na_enhancer(r, self._orig_bgr, self._pad))

    def _ollama_lamp_set(self, actief: bool):
        try: self._lbl_ollama_lamp.config(fg=C_GRN if actief else C_MUT)
        except Exception: pass

    def _ollama_check_async(self):
        ok, modellen = ollama_beschikbaar()
        def _ui():
            self._ollama_pct.set(100 if ok and modellen else (50 if ok else 0))
            if not ok:
                self._ollama_lamp_set(False)
                self._lbl_ollama_status.config(text="⚠ Niet bereikbaar — klik Start Ollama", fg=C_SEL)
                self._ve_status.set("Ollama niet actief"); return
            if not modellen:
                self._ollama_lamp_set(False)
                self._cb_ollama.config(values=[])
                self._lbl_ollama_status.config(text="⚠ Geen vision model", fg=C_SEL)
                self._ve_status.set("ollama pull llava  —  of typ modelnaam handmatig"); return
            self._cb_ollama.config(values=modellen)
            huidig = self._vo.get().strip()
            if not huidig or huidig.startswith("—"): self._vo.set(modellen[0])
            self._ollama_lamp_set(True)
            self._lbl_ollama_status.config(text=f"✓ {len(modellen)} vision model(len)", fg=C_GRN)
            self._ve_status.set("Klaar — klik OCR selectie")
        self.after(0, _ui)

    def _ollama_refresh(self):
        self._ollama_lamp_set(False)
        self._lbl_ollama_status.config(text="⟳ zoeken...", fg=C_MUT)
        self._ollama_pct.set(0)
        import threading as _t
        _t.Thread(target=self._ollama_check_async, daemon=True).start()

    def _ollama_auto_start(self):
        self._ollama_lamp_set(False); self._ollama_pct.set(0)
        self._lbl_ollama_status.config(text="⟳ starten...", fg=C_MUT)
        self._btn_ocr_vol.config(state="disabled"); self._btn_ocr_sel.config(state="disabled")
        def _run():
            def _cb(pct, tekst):
                self.after(0, lambda p=pct, t=tekst: (
                    self._ollama_pct.set(p),
                    self._lbl_ollama_status.config(text=t, fg=C_GRN if p==100 else C_MUT),
                ))
            ok, msg = ollama_start_en_wacht(_cb, timeout=40)
            def _klaar():
                self._btn_ocr_vol.config(state="normal"); self._btn_ocr_sel.config(state="normal")
                if ok: self._ollama_check_async()
                else:
                    self._ollama_lamp_set(False)
                    self._lbl_ollama_status.config(text=f"✗ {msg}", fg=C_SEL)
            self.after(0, _klaar)
        import threading as _t
        _t.Thread(target=_run, daemon=True).start()

    # ── Crop ──────────────────────────────────────────────────────────────────
    def _on_crop(self, x1, y1, x2, y2):
        if self._bgr is None: return
        self._crop_bgr   = self._bgr[y1:y2, x1:x2].copy()
        self._crop_cln   = None
        self._sel_actief = True
        self._vs.set(f"✂ Selectie: {x2-x1}×{y2-y1}px — klik OCR selectie of wissel engine")
        self._kies_engine_voor_selectie()

    def _kies_engine_voor_selectie(self):
        dlg = tk.Toplevel(self)
        dlg.title("Suggestie: type tekst")
        dlg.resizable(False, False); dlg.grab_set(); dlg.configure(bg=C_PAN)
        self.update_idletasks()
        x = self.winfo_x() + self.winfo_width()  // 2 - 210
        y = self.winfo_y() + self.winfo_height() // 2 - 130
        dlg.geometry(f"420x260+{x}+{y}")
        tk.Label(dlg, text="Kies type tekst — engine altijd te wisselen via dropdown:",
                 font=FS, bg=C_PAN, fg=C_TXT).pack(pady=(18, 8))
        keuzes = [
            ("✍  Handschrift / whiteboard",           ENGINE_EASYOCR),
            ("🖥  Schermpresentatie / digitale tekst", ENGINE_TESSERACT),
            ("📄  Gedrukte tekst (pdf, foto, scan)",   ENGINE_TESSERACT),
        ]
        def _kies(engine):
            self._cb_engine.config(values=ENGINES)
            self._ve.set(engine); self._on_engine_change()
            self._vs.set(f"Engine: {engine} — klik OCR selectie"); dlg.destroy()
        for label, engine in keuzes:
            self._btn(dlg, label, lambda e=engine: _kies(e)).pack(fill="x", padx=24, pady=4)
        tk.Button(dlg, text="Sluiten (engine ongewijzigd)", command=dlg.destroy,
                  font=FS, bg=C_PAN, fg=C_MUT, relief="flat").pack(pady=(8, 0))

    def _reset_selectie(self):
        self._cv.clr_sel()
        self._crop_bgr = None; self._crop_cln = None; self._sel_actief = False
        self._vs.set("Selectie vrijgegeven — OCR volledig of nieuwe selectie maken")

    def _wis_sel(self):
        self._reset_selectie()


    # ── Preprocessed preview ──────────────────────────────────────────────────
    def _toon_prep(self):
        src = self._crop_bgr if self._crop_bgr is not None else self._bgr
        if src is None: return
        cln = preprocess(src, MODI.get(self._vm.get(), "sauvola"))
        self._cv.set_img(cln)
        self._vs.set(f"Preview preprocessed — modus: {self._vm.get()}")

    # ── OCR ───────────────────────────────────────────────────────────────────
    def _ocr_vol(self):
        if self._bgr is None:
            messagebox.showwarning("", "Open eerst een afbeelding."); return
        self._start_ocr(self._bgr, is_sel=False)

    def _ocr_sel(self):
        if not self._sel_actief or self._crop_bgr is None:
            messagebox.showwarning("", "Teken eerst een selectie."); return
        self._start_ocr(self._crop_bgr, is_sel=True)

    def _start_ocr(self, img_bgr, is_sel: bool):
        """Start OCR — TrOCR in aparte thread voor live output, rest synchroon."""
        engine = self._ve.get()
        self._vs.set(f"⟳ {engine} bezig..."); self.update()

        if engine == ENGINE_TROCR:
            # Knopjes uitschakelen tijdens verwerking
            self._btn_ocr_vol.config(state="disabled")
            self._btn_ocr_sel.config(state="disabled")
            # Tekstvak leegmaken
            self._tw.config(state="normal")
            self._tw.delete("1.0", "end")

            def _run():
                try:
                    t, info = self._voer_ocr_uit(img_bgr)
                    def _klaar():
                        self._tekst = t
                        extra = f"  |  {img_bgr.shape[1]}×{img_bgr.shape[0]}px" if is_sel else ""
                        self._vs.set(f"✓ {len(t.split())} woorden  |  {info}{extra}")
                        self._btn_ocr_vol.config(state="normal")
                        self._btn_ocr_sel.config(state="normal")
                    self.after(0, _klaar)
                except Exception as ex:
                    def _fout(ex=ex):
                        messagebox.showerror("OCR fout", str(ex))
                        self._vs.set(f"✗ {ex}")
                        self._btn_ocr_vol.config(state="normal")
                        self._btn_ocr_sel.config(state="normal")
                    self.after(0, _fout)

            threading.Thread(target=_run, daemon=True).start()

        else:
            # Alle andere engines: synchroon
            try:
                t, info = self._voer_ocr_uit(img_bgr)
                self._set_txt(t)
                extra = f"  |  {img_bgr.shape[1]}×{img_bgr.shape[0]}px" if is_sel else ""
                self._vs.set(f"✓ {len(t.split())} woorden  |  {info}{extra}")
            except Exception as ex:
                messagebox.showerror("OCR fout", str(ex))
                self._vs.set(f"✗ {ex}")

    def _set_txt(self, t):
        self._tekst = t
        self._tw.config(state="normal")
        self._tw.delete("1.0", "end")
        self._tw.insert("1.0", t)

    # ── Export ────────────────────────────────────────────────────────────────
    def _exp(self, fmt="txt"):
        if not self._tekst:
            messagebox.showwarning("", "Voer eerst OCR uit."); return
        naam = self._pad.stem if self._pad else "ocr"
        p = filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[("Tekstbestand", "*.txt")], initialfile=f"{naam}_ocr.txt")
        if not p: return
        try:
            exp_txt(self._tekst, p); self._vs.set(f"✓ Opgeslagen: {Path(p).name}")
        except Exception as ex:
            messagebox.showerror("Export fout", str(ex))

    def _sla_verbeterd_op(self):
        if self._bgr is None:
            messagebox.showwarning("", "Open eerst een afbeelding."); return
        naam = self._pad.stem if self._pad else "verbeterd"
        p = filedialog.asksaveasfilename(defaultextension=".png",
            filetypes=[("PNG", "*.png")], initialfile=f"{naam}_verbeterd.png")
        if p:
            cv2.imwrite(str(p), self._bgr)
            self._vs.set(f"✓ Verbeterd beeld opgeslagen: {Path(p).name}")

    def _sel_all(self):
        self._tw.tag_add("sel","1.0","end"); self._tw.focus()




if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception:
        traceback.print_exc()
        input("\nDruk ENTER...")
