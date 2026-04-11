"""
OCR Pro - MVP
=============
Architectuur (lagen):
  Layer 1 - config.py    : constanten, paden, instellingen (hier inline)
  Layer 2 - smoketest    : dependency check bij opstart
  Layer 3 - preprocessor : beeldverbetering per inputtype
  Layer 4 - ocr_engine   : Tesseract wrapper
  Layer 5 - exporter     : output naar txt / docx / xlsx / pptx (stubs voor fase 2+)
  Layer 6 - app (GUI)    : tkinter hoofd-applicatie

Smoke tests (bij --test of via CI):
  ST-01  pytesseract importeerbaar
  ST-02  Pillow importeerbaar
  ST-03  opencv importeerbaar
  ST-04  python-docx importeerbaar
  ST-05  openpyxl importeerbaar
  ST-06  python-pptx importeerbaar
  ST-07  Tesseract executable vindbaar
  ST-08  preprocess() retourneert PIL Image
  ST-09  export_txt() schrijft bestand
  ST-10  export_docx() schrijft bestand (stub controle)
"""

# ─────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────
import json
import os
import sys
import threading
import tempfile
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import tkinterdnd2 as _dnd
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

_AppBase = _dnd.Tk if _DND_AVAILABLE else tk.Tk

# ─────────────────────────────────────────────
# LAYER 1 — CONFIG
# ─────────────────────────────────────────────
APP_NAME    = "OCR Pro"
APP_VERSION = "1.1.1"

ONEDRIVE_DESKTOP = Path.home() / "OneDrive" / "Bureaublad"
NORMAL_DESKTOP   = Path.home() / "Desktop"
DEFAULT_OUTPUT   = str(ONEDRIVE_DESKTOP if ONEDRIVE_DESKTOP.exists() else NORMAL_DESKTOP)

SETTINGS_FILE = Path.home() / "AppData" / "Local" / "OCRPro" / "settings.json"

TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# Input types (dropdown 1)
INPUT_TYPES = [
    "Document (scan / PDF)",
    "Foto document (mobiel)",
    "Screenshot / scherm",
    "Tabel / spreadsheet",
    "Formulier",
    "Poster / flyer",
    "Handschrift",
    "Stroomschema",
]

# Talen (dropdown 2)
LANGUAGES = {
    "Nederlands":       "nld",
    "Engels":           "eng",
    "Nederlands+Engels":"nld+eng",
    "Arabisch":         "ara",
    "Arabisch+Engels":  "ara+eng",
    "Mixed":            "nld+eng+ara",
}

# Output formaten (dropdown 3)
OUTPUT_FORMATS = [
    "Platte tekst (.txt)",
    "Word document (.docx)",
    "Excel tabel (.xlsx)",
    "PowerPoint (.pptx)",
]

# Kwaliteit (dropdown 4)
QUALITY_LEVELS = {
    "Snel (ruw)":       "--oem 1 --psm 6",
    "Gebalanceerd":     "--oem 3 --psm 6",
    "Nauwkeurig":       "--oem 3 --psm 4",
}

# Layout gedrag (dropdown 5)
LAYOUT_MODES = [
    "Geen layout (alleen tekst)",
    "Basis layout (koppen + alinea)",
    "Tabel layout",
    "Volledige layout reconstructie",
]

# ─────────────────────────────────────────────
# LAYER 2 — SMOKE TESTS
# ─────────────────────────────────────────────
def run_smoke_tests(verbose=True):
    """
    Voert alle smoke tests uit. Retourneert (passed, failed, log).
    Wordt aangeroepen via: python ocr.py --test
    Ook gebruikt door CI pipeline.
    """
    results = []

    def check(test_id, description, fn):
        try:
            fn()
            results.append((test_id, "OK", description))
            if verbose:
                print(f"  {test_id} OK  — {description}")
        except Exception as e:
            results.append((test_id, f"FAIL: {e}", description))
            if verbose:
                print(f"  {test_id} FAIL — {description}: {e}")

    if verbose:
        print(f"\n{'='*50}")
        print(f"  OCR Pro {APP_VERSION} — Smoke Tests")
        print(f"{'='*50}")

    # ST-01 pytesseract
    def t01():
        import pytesseract
    check("ST-01", "pytesseract importeerbaar", t01)

    # ST-02 Pillow
    def t02():
        from PIL import Image
    check("ST-02", "Pillow (PIL) importeerbaar", t02)

    # ST-03 OpenCV
    def t03():
        import cv2
    check("ST-03", "OpenCV (cv2) importeerbaar", t03)

    # ST-04 python-docx
    def t04():
        import docx
    check("ST-04", "python-docx importeerbaar", t04)

    # ST-05 openpyxl
    def t05():
        import openpyxl
    check("ST-05", "openpyxl importeerbaar", t05)

    # ST-06 python-pptx
    def t06():
        import pptx
    check("ST-06", "python-pptx importeerbaar", t06)

    # ST-07 Tesseract executable
    def t07():
        import pytesseract
        _set_tesseract_path()
        pytesseract.get_tesseract_version()
    check("ST-07", "Tesseract executable vindbaar", t07)

    # ST-08 preprocess() retourneert PIL Image
    def t08():
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=(200, 200, 200))
        result = preprocess(img, "screen")
        assert result is not None
        assert hasattr(result, "size")
    check("ST-08", "preprocess() retourneert PIL Image", t08)

    # ST-09 export_txt() schrijft bestand
    def t09():
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_txt("testtekst OCR Pro", tmpdir, "smoke_test")
            assert os.path.exists(path), f"Bestand niet gevonden: {path}"
            content = open(path, encoding="utf-8").read()
            assert "testtekst" in content
    check("ST-09", "export_txt() schrijft en leest correct", t09)

    # ST-10 export_docx() stub aanwezig en aanroepbaar
    def t10():
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_docx("testtekst OCR Pro", tmpdir, "smoke_test")
            assert os.path.exists(path), f"Bestand niet gevonden: {path}"
    check("ST-10", "export_docx() schrijft .docx bestand", t10)

    passed = sum(1 for _, s, _ in results if s == "OK")
    failed = len(results) - passed

    if verbose:
        print(f"\n  Resultaat: {passed}/{len(results)} geslaagd", end="")
        if failed:
            print(f"  ({failed} mislukt)")
        else:
            print("  — alles OK")
        print(f"{'='*50}\n")

    return passed, failed, results


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _set_tesseract_path():
    import pytesseract
    for p in TESSERACT_PATHS:
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return
    # Niet gevonden — pytesseract zoekt zelf in PATH

def is_tesseract_available():
    try:
        import pytesseract
        _set_tesseract_path()
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False

def load_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "output":          DEFAULT_OUTPUT,
        "language":        "Nederlands+Engels",
        "input_type":      "Document (scan / PDF)",
        "output_format":   "Platte tekst (.txt)",
        "quality":         "Gebalanceerd",
        "layout":          "Geen layout (alleen tekst)",
        "keep_spaces":     True,
        "save_preprocess": False,
    }

def save_settings(data):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────
# LAYER 3 — PREPROCESSOR
# ─────────────────────────────────────────────
def preprocess(img, input_type: str):
    """
    Verwerkt een PIL Image op basis van het gekozen inputtype.
    Retourneert altijd een PIL Image (grayscale, geoptimaliseerd).
    """
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    img = img.convert("RGB")
    g   = ImageOps.grayscale(img)
    g   = ImageOps.autocontrast(g)

    t = input_type.lower()

    if "screenshot" in t or "scherm" in t:
        g = ImageEnhance.Contrast(g).enhance(1.2)
        g = ImageEnhance.Sharpness(g).enhance(2.0)

    elif "foto" in t or "mobiel" in t:
        g = g.filter(ImageFilter.MedianFilter(3))
        g = ImageEnhance.Contrast(g).enhance(1.5)
        g = ImageEnhance.Sharpness(g).enhance(1.7)

    elif "tabel" in t or "spreadsheet" in t:
        g = g.filter(ImageFilter.MedianFilter(3))
        g = ImageEnhance.Contrast(g).enhance(1.6)
        g = ImageEnhance.Sharpness(g).enhance(1.5)

    elif "handschrift" in t:
        g = g.filter(ImageFilter.MedianFilter(3))
        g = ImageEnhance.Contrast(g).enhance(1.8)
        g = ImageEnhance.Sharpness(g).enhance(2.0)

    elif "poster" in t or "flyer" in t:
        g = ImageEnhance.Contrast(g).enhance(1.4)
        g = ImageEnhance.Sharpness(g).enhance(1.8)

    else:  # document (default)
        g = g.filter(ImageFilter.MedianFilter(3))
        g = ImageEnhance.Contrast(g).enhance(1.3)

    return g


# ─────────────────────────────────────────────
# LAYER 4 — OCR ENGINE
# ─────────────────────────────────────────────
def run_ocr(image, lang: str, config: str, keep_spaces: bool) -> str:
    """
    Voert Tesseract OCR uit op een preprocessed PIL Image.
    Retourneert de herkende tekst als string.
    """
    import pytesseract
    _set_tesseract_path()
    cfg = config
    cfg += " -c preserve_interword_spaces=1" if keep_spaces else " -c preserve_interword_spaces=0"
    return pytesseract.image_to_string(image, lang=lang, config=cfg)


# ─────────────────────────────────────────────
# LAYER 5 — EXPORTERS
# ─────────────────────────────────────────────
def export_txt(text: str, output_dir: str, stem: str) -> str:
    """Exporteert tekst naar .txt bestand. Retourneert het pad."""
    path = os.path.join(output_dir, f"{stem}_ocr.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def export_docx(text: str, output_dir: str, stem: str) -> str:
    """
    Exporteert tekst naar .docx met basis structuurherkenning.
    Korte regels (< 60 tekens, hoofdletters) → Heading 1
    Overige regels → Normal paragraaf
    """
    from docx import Document
    from docx.shared import Pt

    doc  = Document()
    path = os.path.join(output_dir, f"{stem}_ocr.docx")

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Simpele heuristiek: kop detecteren
        if len(line) < 60 and line.isupper():
            doc.add_heading(line, level=1)
        elif len(line) < 80 and line.endswith(":"):
            doc.add_heading(line, level=2)
        else:
            doc.add_paragraph(line)

    doc.save(path)
    return path


def export_xlsx(text: str, output_dir: str, stem: str) -> str:
    """
    Exporteert tabelachtige tekst naar .xlsx.
    Splitst op tab of meerdere spaties → kolommen.
    Fase 2: vervangen door OpenCV tabeldetectie.
    """
    import openpyxl, re
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "OCR output"
    path = os.path.join(output_dir, f"{stem}_ocr.xlsx")

    for row_idx, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        # Splits op tab of 2+ spaties
        cells = re.split(r'\t|  +', line)
        for col_idx, cell in enumerate(cells, start=1):
            ws.cell(row=row_idx, column=col_idx, value=cell.strip())

    wb.save(path)
    return path


def export_pptx(text: str, output_dir: str, stem: str) -> str:
    """
    Exporteert tekst naar .pptx — één slide per sectie.
    Fase 2: layout reconstructie toevoegen.
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs  = Presentation()
    path = os.path.join(output_dir, f"{stem}_ocr.pptx")

    slide_layout = prs.slide_layouts[1]  # titel + inhoud
    lines  = [l.strip() for l in text.splitlines() if l.strip()]
    chunks = []
    current = []

    for line in lines:
        if len(line) < 60 and line.isupper():
            if current:
                chunks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append(current)

    if not chunks:
        chunks = [lines]

    for chunk in chunks:
        slide = prs.slides.add_slide(slide_layout)
        title = slide.shapes.title
        body  = slide.placeholders[1]
        title.text = chunk[0] if chunk else "OCR Output"
        body.text  = "\n".join(chunk[1:]) if len(chunk) > 1 else ""

    prs.save(path)
    return path


def run_export(text: str, output_format: str, output_dir: str, stem: str) -> str:
    """Router: stuurt naar de juiste exporter op basis van gekozen formaat."""
    fmt = output_format.lower()
    if ".docx" in fmt:
        return export_docx(text, output_dir, stem)
    elif ".xlsx" in fmt:
        return export_xlsx(text, output_dir, stem)
    elif ".pptx" in fmt:
        return export_pptx(text, output_dir, stem)
    else:
        return export_txt(text, output_dir, stem)


# ─────────────────────────────────────────────
# LAYER 6 — GUI (tkinter)
# ─────────────────────────────────────────────
class App(_AppBase):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1200x820")
        self.minsize(1000, 680)

        s = load_settings()
        self.input_var         = tk.StringVar(value="")
        self.output_var        = tk.StringVar(value=s.get("output", DEFAULT_OUTPUT))
        self.input_type_var    = tk.StringVar(value=s.get("input_type", INPUT_TYPES[0]))
        self.language_var      = tk.StringVar(value=s.get("language", "Nederlands+Engels"))
        self.output_format_var = tk.StringVar(value=s.get("output_format", OUTPUT_FORMATS[0]))
        self.quality_var       = tk.StringVar(value=s.get("quality", "Gebalanceerd"))
        self.layout_var        = tk.StringVar(value=s.get("layout", LAYOUT_MODES[0]))
        self.keep_spaces_var   = tk.BooleanVar(value=s.get("keep_spaces", True))
        self.save_pre_var      = tk.BooleanVar(value=s.get("save_preprocess", False))

        self._build_ui()
        self.log(f"{APP_NAME} {APP_VERSION} gestart.")

        if not is_tesseract_available():
            self.log("WAARSCHUWING: Tesseract niet gevonden — OCR werkt niet.")
            messagebox.showwarning(
                "Tesseract niet gevonden",
                "Tesseract OCR is niet gevonden.\n"
                r"Verwacht: C:\Program Files\Tesseract-OCR\tesseract.exe"
            )

    # ── UI opbouw ──────────────────────────────
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # ── Instellingen frame ──
        frm = ttk.LabelFrame(self, text="Instellingen")
        frm.pack(fill="x", padx=10, pady=8)

        # Rij 0: inputbestand (+ drag-and-drop)
        lbl_input = "Inputbestand (of sleep hierheen)" if _DND_AVAILABLE else "Inputbestand"
        ttk.Label(frm, text=lbl_input).grid(row=0, column=0, sticky="w", **pad)
        self._input_entry = ttk.Entry(frm, textvariable=self.input_var, width=100)
        self._input_entry.grid(row=0, column=1, sticky="ew", **pad)
        if _DND_AVAILABLE:
            self._input_entry.drop_target_register(_dnd.DND_FILES)
            self._input_entry.dnd_bind("<<Drop>>", self._on_drop)
        ttk.Button(frm, text="Selecteer", command=self._select_input).grid(row=0, column=2, **pad)

        # Rij 1: outputmap
        ttk.Label(frm, text="Outputmap").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.output_var, width=100).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Selecteer", command=self._select_output).grid(row=1, column=2, **pad)

        # Rij 2-4: dropdowns
        dropdowns = [
            ("Input type",     self.input_type_var,    INPUT_TYPES),
            ("Taal",           self.language_var,       list(LANGUAGES.keys())),
            ("Output formaat", self.output_format_var,  OUTPUT_FORMATS),
            ("Kwaliteit",      self.quality_var,        list(QUALITY_LEVELS.keys())),
            ("Layout",         self.layout_var,         LAYOUT_MODES),
        ]
        for i, (label, var, values) in enumerate(dropdowns):
            ttk.Label(frm, text=label).grid(row=2+i, column=0, sticky="w", **pad)
            ttk.Combobox(frm, textvariable=var, values=values, state="readonly", width=50
                         ).grid(row=2+i, column=1, sticky="w", **pad)

        # Rij 7: checkboxes
        opt_row = ttk.Frame(frm)
        opt_row.grid(row=7, column=1, sticky="w", **pad)
        ttk.Checkbutton(opt_row, text="Spaties behouden", variable=self.keep_spaces_var).pack(side="left", padx=(0,20))
        ttk.Checkbutton(opt_row, text="Preprocessed opslaan", variable=self.save_pre_var).pack(side="left")

        frm.columnconfigure(1, weight=1)

        # ── Knoppen ──
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=4)
        self.start_btn = ttk.Button(btn_row, text="▶  Start OCR", command=self._start_ocr)
        self.start_btn.pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Smoke tests uitvoeren", command=self._run_smoke_ui).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Open outputmap", command=self._open_output).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Sluiten", command=self.destroy).pack(side="right")

        # ── Progress ──
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=4)

        # ── Log + Preview ──
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=6)

        log_frm     = ttk.LabelFrame(paned, text="Log")
        preview_frm = ttk.LabelFrame(paned, text="Preview output")
        paned.add(log_frm, weight=1)
        paned.add(preview_frm, weight=1)

        self.log_text = tk.Text(log_frm, wrap="word", height=20, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self.preview_text = tk.Text(preview_frm, wrap="word", height=20)
        self.preview_text.pack(fill="both", expand=True, padx=4, pady=4)

    # ── Logging ────────────────────────────────
    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.update_idletasks()

    # ── Drag-and-drop ──────────────────────────
    def _on_drop(self, event):
        path = event.data.strip()
        # tkinterdnd2 omsluiting bij paden met spaties: {C:\pad met spaties\bestand.png}
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        self.input_var.set(path)
        self.log(f"Input (drag-and-drop): {os.path.basename(path)}")

    # ── Bestandskeuze ──────────────────────────
    def _select_input(self):
        path = filedialog.askopenfilename(
            title="Selecteer inputbestand",
            filetypes=[
                ("Afbeeldingen", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("Alle bestanden", "*.*"),
            ]
        )
        if path:
            self.input_var.set(path)
            self.log(f"Input: {os.path.basename(path)}")

    def _select_output(self):
        folder = filedialog.askdirectory(title="Selecteer outputmap")
        if folder:
            self.output_var.set(folder)
            self.log(f"Outputmap: {folder}")

    def _open_output(self):
        d = self.output_var.get().strip()
        if os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showwarning("Outputmap", "Map bestaat niet.")

    # ── Smoke tests via UI ─────────────────────
    def _run_smoke_ui(self):
        self.log("Smoke tests starten...")
        self.start_btn.configure(state="disabled")
        self.progress.start(10)

        def worker():
            passed, failed, results = run_smoke_tests(verbose=False)
            def done():
                self.progress.stop()
                self.start_btn.configure(state="normal")
                for tid, status, desc in results:
                    self.log(f"  {tid} {'✓' if status == 'OK' else '✗'} {desc}" +
                             (f" — {status}" if status != "OK" else ""))
                self.log(f"Smoke tests klaar: {passed}/{len(results)} geslaagd.")
                if failed:
                    messagebox.showwarning("Smoke tests", f"{failed} test(s) mislukt — zie log.")
                else:
                    messagebox.showinfo("Smoke tests", "Alle tests geslaagd.")
            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    # ── OCR uitvoeren ──────────────────────────
    def _start_ocr(self):
        if not is_tesseract_available():
            messagebox.showerror("Tesseract ontbreekt", "Tesseract is niet beschikbaar.")
            return

        input_file  = self.input_var.get().strip()
        output_dir  = self.output_var.get().strip()

        if not input_file or not os.path.isfile(input_file):
            messagebox.showwarning("Input", "Selecteer eerst een geldig inputbestand.")
            return
        if not output_dir:
            messagebox.showwarning("Output", "Selecteer een outputmap.")
            return

        os.makedirs(output_dir, exist_ok=True)
        self._save_settings()
        self.preview_text.delete("1.0", "end")
        self.start_btn.configure(state="disabled")
        self.progress.start(10)
        self.log("OCR gestart...")

        threading.Thread(target=self._ocr_worker,
                         args=(input_file, output_dir),
                         daemon=True).start()

    def _ocr_worker(self, input_file: str, output_dir: str):
        try:
            from PIL import Image

            # Instellingen ophalen
            input_type    = self.input_type_var.get()
            lang_key      = self.language_var.get()
            lang          = LANGUAGES.get(lang_key, "nld+eng")
            config        = QUALITY_LEVELS.get(self.quality_var.get(), "--oem 3 --psm 6")
            output_format = self.output_format_var.get()
            keep_spaces   = self.keep_spaces_var.get()
            stem          = Path(input_file).stem

            self.after(0, lambda: self.log(f"Bestand: {os.path.basename(input_file)}"))
            self.after(0, lambda: self.log(f"Type: {input_type} | Taal: {lang} | Formaat: {output_format}"))

            # Layer 3: preprocess
            img           = Image.open(input_file)
            preprocessed  = preprocess(img, input_type)

            # Preprocessed opslaan indien gewenst
            if self.save_pre_var.get():
                pre_path = os.path.join(output_dir, f"{stem}_preprocessed.png")
                preprocessed.save(pre_path)
                self.after(0, lambda: self.log(f"Preprocessed opgeslagen: {pre_path}"))

            # Layer 4: OCR
            text = run_ocr(preprocessed, lang, config, keep_spaces)

            # Layer 5: export
            out_path = run_export(text, output_format, output_dir, stem)

            self.after(0, lambda: self.preview_text.insert("1.0", text))
            self.after(0, lambda: self.log(f"Klaar → {out_path}"))

        except Exception as e:
            self.after(0, lambda: self.log(f"FOUT: {e}"))
            self.after(0, lambda: messagebox.showerror("Fout", str(e)))
        finally:
            self.after(0, self._ocr_done)

    def _ocr_done(self):
        self.progress.stop()
        self.start_btn.configure(state="normal")

    def _save_settings(self):
        save_settings({
            "output":          self.output_var.get(),
            "input_type":      self.input_type_var.get(),
            "language":        self.language_var.get(),
            "output_format":   self.output_format_var.get(),
            "quality":         self.quality_var.get(),
            "layout":          self.layout_var.get(),
            "keep_spaces":     self.keep_spaces_var.get(),
            "save_preprocess": self.save_pre_var.get(),
        })


# ─────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        # CI / command-line smoke test mode
        passed, failed, _ = run_smoke_tests(verbose=True)
        sys.exit(0 if failed == 0 else 1)
    else:
        App().mainloop()
