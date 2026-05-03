"""
Offline_Translate — Offline vertaaltool voor defensie-analisten.
Eén enkel Python-bestand. Geen submodules nodig.
"""

__author__    = "Richard van der Veer"
__version__   = "1.4.1"
__build__     = "20260430"
__copyright__ = "© 2026 Richard van der Veer"
__watermark__ = "Offline_Translate | Offline vertaaltool | Defensie gebruik"

import json
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Offline_Translate")


# ---------------------------------------------------------------------------
# Netwerk veiligheidscheck
# ---------------------------------------------------------------------------
def _check_network_safety() -> list[str]:
    """
    Controleert bij opstarten of omgevingsvariabelen correct zijn gezet
    om HuggingFace/transformers netwerktoegang te blokkeren.
    Geeft lijst van waarschuwingen terug (leeg = veilig).
    """
    warnings = []
    vereist = {
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_OFFLINE":       "1",
        "HF_DATASETS_OFFLINE":  "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    for var, gewenst in vereist.items():
        waarde = os.environ.get(var, "")
        if waarde != gewenst:
            warnings.append(f"{var} = '{waarde}' (verwacht: '{gewenst}')")

    return warnings


def _log_network_status():
    """Log netwerk veiligheidsstatus bij opstarten."""
    waarschuwingen = _check_network_safety()
    if not waarschuwingen:
        logger.info("Netwerk lockdown: ACTIEF — HuggingFace offline geblokkeerd")
    else:
        logger.warning("Netwerk lockdown: NIET VOLLEDIG ACTIEF")
        for w in waarschuwingen:
            logger.warning(f"  Ontbrekend: {w}")
        logger.warning("Start de app via start.bat voor volledige offline beveiliging")


def _vraag_online_toestemming(model_naam: str, grootte: str = "~1.3GB") -> bool:
    """
    Toont een waarschuwingsdialoog voordat de app online gaat om een model te downloaden.
    Geeft True terug als gebruiker akkoord gaat, False als geannuleerd.
    Werkt ook vanuit een achtergrondthread via Tk-safe aanroep.
    """
    import tkinter as tk
    from tkinter import messagebox

    # Maak tijdelijk root-venster als er nog geen Tk loop actief is
    _eigen_root = False
    try:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
            _eigen_root = True
    except Exception:
        root = tk.Tk()
        root.withdraw()
        _eigen_root = True

    antwoord = messagebox.askyesno(
        "Model niet gevonden — online download vereist",
        f"Het model '{model_naam}' staat niet lokaal op deze computer.\n\n"
        f"Grootte: {grootte}\n\n"
        f"Om door te gaan moet de app EENMALIG verbinding maken met internet "
        f"(HuggingFace) om het model te downloaden.\n\n"
        f"Na het downloaden werkt de app volledig offline.\n\n"
        f"Wil je nu online gaan om het model te downloaden?",
        icon="warning",
    )

    if _eigen_root:
        try:
            root.destroy()
        except Exception:
            pass

    if antwoord:
        logger.info(f"Gebruiker akkoord: online download gestart voor {model_naam}")
    else:
        logger.info(f"Gebruiker geannuleerd: download {model_naam} afgebroken")

    return antwoord


def _melding_download_gereed(model_naam: str) -> None:
    """Toont melding dat download geslaagd is en app weer offline werkt."""
    import tkinter as tk
    from tkinter import messagebox

    _eigen_root = False
    try:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
            _eigen_root = True
    except Exception:
        root = tk.Tk()
        root.withdraw()
        _eigen_root = True

    messagebox.showinfo(
        "Download geslaagd — app werkt weer offline",
        f"Het model '{model_naam}' is succesvol gedownload en lokaal opgeslagen.\n\n"
        f"De app werkt vanaf nu volledig offline voor dit model.\n"
        f"Je hoeft nooit meer online te gaan voor dit model.",
    )

    if _eigen_root:
        try:
            root.destroy()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Taalconfiguratie
# ---------------------------------------------------------------------------
LANGUAGE_DISPLAY = {
    "nl": "Nederlands", "en": "Engels",  "fr": "Frans",
    "de": "Duits",      "es": "Spaans",  "ru": "Russisch",
    "uk": "Oekraïens",  "zh": "Chinees", "ar": "Arabisch",
}

AUTO_DETECT = "Automatisch"
SRC_OPTIONS = [AUTO_DETECT] + list(LANGUAGE_DISPLAY.values())

MARIAN_MODELS = {
    ("nl", "en"): "Helsinki-NLP/opus-mt-nl-en",
    ("en", "nl"): "Helsinki-NLP/opus-mt-en-nl",
    ("fr", "en"): "Helsinki-NLP/opus-mt-fr-en",
    ("en", "fr"): "Helsinki-NLP/opus-mt-en-fr",
    ("nl", "fr"): "Helsinki-NLP/opus-mt-nl-fr",
    ("de", "en"): "Helsinki-NLP/opus-mt-de-en",
    ("en", "de"): "Helsinki-NLP/opus-mt-en-de",
    ("de", "nl"): "Helsinki-NLP/opus-mt-de-nl",
    ("es", "en"): "Helsinki-NLP/opus-mt-es-en",
    ("en", "es"): "Helsinki-NLP/opus-mt-en-es",
    ("ru", "en"): "Helsinki-NLP/opus-mt-ru-en",
    ("en", "ru"): "Helsinki-NLP/opus-mt-en-ru",
    ("uk", "en"): "Helsinki-NLP/opus-mt-uk-en",
    ("en", "uk"): "Helsinki-NLP/opus-mt-en-uk",
    ("zh", "en"): "Helsinki-NLP/opus-mt-zh-en",
    ("en", "zh"): "Helsinki-NLP/opus-mt-en-zh",
    ("ar", "en"): "Helsinki-NLP/opus-mt-ar-en",
    ("en", "ar"): "Helsinki-NLP/opus-mt-en-ar",
}

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

# ---------------------------------------------------------------------------
# Taalherkenning
# ---------------------------------------------------------------------------
def detect_language(text: str) -> Optional[str]:
    """
    Detecteer taal. Probeert langdetect, valt terug op tekenset-heuristiek.
    Geeft taalcode (nl/en/fr/...) of None terug.
    """
    if not text or len(text.strip()) < 10:
        return None

    try:
        from langdetect import detect
        code = detect(text)
        mapping = {
            "nl": "nl", "en": "en", "fr": "fr", "de": "de",
            "es": "es", "ru": "ru", "uk": "uk",
            "zh-cn": "zh", "zh-tw": "zh", "ar": "ar",
        }
        result = mapping.get(code)
        if result:
            logger.info(f"Taal gedetecteerd via langdetect: {code} -> {result}")
        return result
    except Exception:
        pass

    # Fallback: tekenset-heuristiek
    sample = text[:300]
    total  = max(len([c for c in sample if not c.isspace()]), 1)
    arabic   = sum(1 for c in sample if '\u0600' <= c <= '\u06ff') / total
    chinese  = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff') / total
    cyrillic = sum(1 for c in sample if '\u0400' <= c <= '\u04ff') / total

    if arabic   > 0.25: return "ar"
    if chinese  > 0.25: return "zh"
    if cyrillic > 0.25:
        ukr = sum(1 for c in sample if c in "іїєґІЇЄҐ")
        return "uk" if ukr > 2 else "ru"

    return None  # Latijns schrift, taal onbekend



# NLLB-200 taalcodes (Facebook/Meta formaat)
NLLB_CODES = {
    "nl": "nld_Latn", "en": "eng_Latn", "fr": "fra_Latn",
    "de": "deu_Latn", "es": "spa_Latn", "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl", "zh": "zho_Hans", "ar": "arb_Arab",
}

NLLB_MODEL_NAME  = "facebook/nllb-200-distilled-600M"
NLLB_MODEL_DIR   = os.path.join(MODELS_DIR, "facebook--nllb-200-distilled-600M")

# ---------------------------------------------------------------------------
# NLLB-200 engine (primair — beste kwaliteit)
# ---------------------------------------------------------------------------
_nllb_model     = None
_nllb_tokenizer = None
_nllb_ok        = None


def _load_nllb() -> bool:
    global _nllb_ok, _nllb_model, _nllb_tokenizer
    if _nllb_ok is None:
        try:
            from transformers import AutoModelForSeq2SeqLM, NllbTokenizer, NllbTokenizerFast
            is_local = os.path.exists(NLLB_MODEL_DIR)

            # Model niet lokaal — vraag toestemming voor online download
            if not is_local:
                if not _vraag_online_toestemming("NLLB-200 (facebook/nllb-200-distilled-600M)", "~1.3GB"):
                    _nllb_ok = False
                    logger.info("NLLB-200 download geannuleerd door gebruiker")
                    return False
                logger.info("NLLB-200 online download gestart...")

            src_path = NLLB_MODEL_DIR if is_local else NLLB_MODEL_NAME
            logger.info(f"NLLB-200 laden: {src_path}")

            # Probeer NllbTokenizerFast eerst (gebruikt tokenizer.json)
            try:
                _nllb_tokenizer = NllbTokenizerFast.from_pretrained(
                    src_path, local_files_only=is_local
                )
                logger.info("NllbTokenizerFast geladen")
            except Exception as e1:
                logger.warning(f"NllbTokenizerFast mislukt ({e1}), probeer NllbTokenizer")
                try:
                    _nllb_tokenizer = NllbTokenizer.from_pretrained(
                        src_path, local_files_only=is_local
                    )
                    logger.info("NllbTokenizer geladen")
                except Exception as e2:
                    logger.warning(f"NllbTokenizer mislukt ({e2}), probeer AutoTokenizer")
                    from transformers import AutoTokenizer
                    _nllb_tokenizer = AutoTokenizer.from_pretrained(
                        src_path, local_files_only=is_local
                    )
                    logger.info("AutoTokenizer geladen")

            _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(
                src_path, local_files_only=is_local
            )
            _nllb_ok = True
            logger.info("NLLB-200 volledig geladen")

            # Toon melding als model zojuist gedownload is
            if not is_local:
                _melding_download_gereed("NLLB-200 (facebook/nllb-200-distilled-600M)")

        except Exception as e:
            _nllb_ok = False
            logger.error(f"NLLB-200 laden mislukt: {type(e).__name__}: {e}")
    return _nllb_ok



def _split_voor_nllb(text: str, max_chars: int = 800) -> list:
    """
    Splits tekst in segmenten die NLLB-200 aankan.
    Splitst op zinsgrenzen (. ! ?) om afkap te voorkomen.
    Behoudt alinea-structuur waar mogelijk.
    """
    if len(text) <= max_chars:
        return [text]

    segmenten = []
    # Splits eerst op alinea's
    alineas = [a for a in text.split("\n\n") if a.strip()]

    huidig = ""
    for alinea in alineas:
        if len(huidig) + len(alinea) <= max_chars:
            huidig += ("\n\n" if huidig else "") + alinea
        else:
            # Alinea te groot — splits op zinnen
            if huidig:
                segmenten.append(huidig)
                huidig = ""
            # Splits alinea op zinsgrenzen
            zinnen = []
            voor = ""
            for char in alinea:
                voor += char
                if char in ".!?" and len(voor.strip()) > 10:
                    zinnen.append(voor.strip())
                    voor = ""
            if voor.strip():
                zinnen.append(voor.strip())

            zin_blok = ""
            for zin in zinnen:
                if len(zin_blok) + len(zin) <= max_chars:
                    zin_blok += (" " if zin_blok else "") + zin
                else:
                    if zin_blok:
                        segmenten.append(zin_blok)
                    zin_blok = zin
            if zin_blok:
                huidig = zin_blok

    if huidig:
        segmenten.append(huidig)

    return segmenten if segmenten else [text]


def translate_nllb(text: str, src: str, tgt: str,
                   progress_cb=None) -> Optional[str]:
    """Vertaal met NLLB-200 — ondersteunt alle 9 talen direct."""
    if not text.strip():
        return ""
    src_code = NLLB_CODES.get(src)
    tgt_code = NLLB_CODES.get(tgt)
    if not src_code or not tgt_code:
        logger.warning(f"NLLB: taalcode ontbreekt voor {src} of {tgt}")
        return None
    if not _load_nllb():
        return None
    if progress_cb:
        progress_cb(f"NLLB-200: {LANGUAGE_DISPLAY.get(src, src)} -> {LANGUAGE_DISPLAY.get(tgt, tgt)}")
    try:
        # Zet brontaal op de tokenizer
        _nllb_tokenizer.src_lang = src_code

        # Bepaal doeltaal token ID
        try:
            tgt_lang_id = _nllb_tokenizer.lang_code_to_id[tgt_code]
        except (AttributeError, KeyError):
            tgt_lang_id = _nllb_tokenizer.convert_tokens_to_ids(tgt_code)

        # Splits tekst in segmenten van max ~400 tokens
        # Splits op zinsgrenzen om context te behouden
        segmenten = _split_voor_nllb(text)
        results = []
        for segment in segmenten:
            if not segment.strip():
                results.append(segment)
                continue
            inputs = _nllb_tokenizer(
                segment, return_tensors="pt",
                padding=True, truncation=True, max_length=400
            )
            out = _nllb_model.generate(
                **inputs,
                forced_bos_token_id=tgt_lang_id,
                max_length=600,
                num_beams=4,
                no_repeat_ngram_size=3,
            )
            results.append(_nllb_tokenizer.batch_decode(out, skip_special_tokens=True)[0])
        return " ".join(r for r in results if r.strip())
    except Exception as e:
        logger.error(f"NLLB vertaalfout: {type(e).__name__}: {e}")
        return None

# ---------------------------------------------------------------------------
# MarianMT engine (fallback voor NLLB)
# ---------------------------------------------------------------------------
_model_cache: dict   = {}
_transformers_ok     = None
_MarianModel         = None
_MarianTokenizer     = None


def _load_transformers() -> bool:
    global _transformers_ok, _MarianModel, _MarianTokenizer
    if _transformers_ok is None:
        try:
            from transformers import MarianMTModel, MarianTokenizer
            _MarianModel     = MarianMTModel
            _MarianTokenizer = MarianTokenizer
            _transformers_ok = True
            logger.info("transformers geladen")
        except ImportError:
            _transformers_ok = False
            logger.warning("transformers niet beschikbaar")
    return _transformers_ok


def _get_model(model_name: str):
    if model_name in _model_cache:
        return _model_cache[model_name]
    if not _load_transformers():
        return None
    local = os.path.join(MODELS_DIR, model_name.replace("/", "--"))
    try:
        if os.path.exists(local):
            logger.info(f"Model laden: {local}")
            tok = _MarianTokenizer.from_pretrained(local)
            mdl = _MarianModel.from_pretrained(local)
        else:
            # Model niet lokaal — vraag toestemming voor online download
            if not _vraag_online_toestemming(model_name, "~300MB"):
                logger.info(f"MarianMT download geannuleerd door gebruiker: {model_name}")
                return None
            logger.info(f"MarianMT online download gestart: {model_name}")
            tok = _MarianTokenizer.from_pretrained(model_name)
            mdl = _MarianModel.from_pretrained(model_name)
            # Sla lokaal op zodat volgende keer offline werkt
            tok.save_pretrained(local)
            mdl.save_pretrained(local)
            logger.info(f"MarianMT model opgeslagen: {local}")
            _melding_download_gereed(model_name)
        _model_cache[model_name] = (mdl, tok)
        logger.info(f"Model gereed: {model_name}")
        return (mdl, tok)
    except Exception as e:
        logger.error(f"Model laden mislukt ({model_name}): {e}")
        return None



def _split_voor_marian(text: str, max_chars: int = 600) -> list:
    """Splits tekst voor MarianMT op zinsgrenzen."""
    if len(text) <= max_chars:
        return [text]
    segmenten = []
    huidig = ""
    for char in text:
        huidig += char
        if char in ".!?\n" and len(huidig.strip()) > 20:
            segmenten.append(huidig.strip())
            huidig = ""
    if huidig.strip():
        segmenten.append(huidig.strip())
    return segmenten if segmenten else [text]



# ---------------------------------------------------------------------------
# Chunk-vertaler — voor lange teksten met tussentijdse opslag
# ---------------------------------------------------------------------------
import tempfile
import time

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")


def _get_temp_path(src: str, tgt: str) -> str:
    """Geeft pad naar tijdelijk vertaalbestand."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    return os.path.join(TEMP_DIR, f"vertaling_{src}_{tgt}_lopend.txt")


def _save_progress(temp_path, segmenten, resultaten, src, tgt, engine):
    """Sla tussentijdse voortgang op naar temp-bestand."""
    try:
        tijdstip = time.strftime("%Y-%m-%d %H:%M:%S")
        vertaald = " ".join(r for r in resultaten if r.strip())
        header = [
            "# Offline_Translate - Lopende vertaling",
            "# Van: " + src + " | Naar: " + tgt + " | Engine: " + engine,
            "# Gestart: " + tijdstip,
            "# Segmenten: " + str(len(segmenten)) + " | Klaar: " + str(len(resultaten)),
            "#" + "=" * 60,
            "",
        ]
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("\n".join(header) + vertaald)
    except Exception as e:
        logger.warning("Tussentijdse opslag mislukt: " + str(e))

def _cleanup_temp(temp_path: str):
    """Verwijder temp-bestand na succesvolle vertaling."""
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info(f"Temp-bestand verwijderd: {temp_path}")
    except Exception as e:
        logger.warning(f"Temp-bestand verwijderen mislukt: {e}")


def translate_lang(text: str, src: str, tgt: str,
                   engine: str = "AUTO",
                   ollama_host: str = "http://localhost:11434",
                   ollama_model: str = "mistral:7b",
                   progress_cb=None,
                   cancel_flag=None) -> tuple:
    """
    Vertaal lange teksten in segmenten met tussentijdse opslag.
    Geeft (vertaling, engine_naam, voltooid_pct) terug.
    cancel_flag: threading.Event — zet op True om te stoppen.
    """
    temp_path = _get_temp_path(src, tgt)

    # Bepaal segmentgrootte op basis van engine
    if engine in ("AUTO", "NLLB"):
        segmenten = _split_voor_nllb(text, max_chars=600)
    else:
        segmenten = _split_voor_marian(text, max_chars=500)

    totaal = len(segmenten)
    logger.info(f"Lange tekst: {len(text)} tekens → {totaal} segmenten")

    resultaten = []
    gebruikte_engine = "-"

    for i, segment in enumerate(segmenten):
        # Annulering controleren
        if cancel_flag and cancel_flag.is_set():
            logger.info(f"Vertaling geannuleerd na {i}/{totaal} segmenten")
            _save_progress(temp_path, segmenten, resultaten, src, tgt, gebruikte_engine)
            return " ".join(r for r in resultaten if r.strip()), gebruikte_engine, False

        if progress_cb:
            pct = int((i / totaal) * 100)
            progress_cb(f"Vertalen segment {i+1}/{totaal} ({pct}%)...")

        # Vertaal dit segment
        resultaat, engine_naam = translate_auto(
            segment, src, tgt,
            engine=engine,
            ollama_host=ollama_host,
            ollama_model=ollama_model,
        )
        gebruikte_engine = engine_naam

        if resultaat:
            resultaten.append(resultaat)
        else:
            logger.warning(f"Segment {i+1} mislukt, wordt overgeslagen")
            resultaten.append(f"[VERTALING MISLUKT: {segment[:50]}...]")

        # Tussentijdse opslag elke 3 segmenten
        if (i + 1) % 3 == 0 or i == totaal - 1:
            _save_progress(temp_path, segmenten, resultaten, src, tgt, gebruikte_engine)

    # Volledig — verwijder temp-bestand
    _cleanup_temp(temp_path)

    vertaling = " ".join(r for r in resultaten if r.strip())
    return vertaling, gebruikte_engine, True


def check_lopende_vertaling(src: str, tgt: str) -> Optional[str]:
    """Controleer of er een onderbroken vertaling is voor deze taalrichting."""
    temp_path = _get_temp_path(src, tgt)
    if os.path.exists(temp_path):
        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    return None


def _run_model(text: str, model_name: str) -> Optional[str]:
    loaded = _get_model(model_name)
    if not loaded:
        return None
    mdl, tok = loaded
    try:
        # Splits op zinsgrenzen voor betere kwaliteit en geen afkap
        segmenten = _split_voor_marian(text)
        results = []
        for seg in segmenten:
            if not seg.strip():
                continue
            inp = tok(seg, return_tensors="pt", padding=True,
                      truncation=True, max_length=450)
            out = mdl.generate(**inp, max_length=600)
            results.append(tok.batch_decode(out, skip_special_tokens=True)[0])
        return " ".join(r for r in results if r.strip())
    except Exception as e:
        logger.error(f"Vertaalfout: {e}")
        return None


def translate_marian(text: str, src: str, tgt: str,
                     progress_cb=None) -> Optional[str]:
    if not text.strip():
        return ""
    direct = MARIAN_MODELS.get((src, tgt))
    if direct:
        if progress_cb:
            progress_cb(f"MarianMT: {LANGUAGE_DISPLAY.get(src, src)} -> {LANGUAGE_DISPLAY.get(tgt, tgt)}")
        result = _run_model(text, direct)
        if result is not None:
            return result
        logger.warning(f"Direct model mislukt ({src}->{tgt}), probeer pivot")

    src_en = MARIAN_MODELS.get((src, "en"))
    en_tgt = MARIAN_MODELS.get(("en", tgt))
    if src_en and en_tgt and src != "en" and tgt != "en":
        if progress_cb:
            progress_cb(f"MarianMT pivot: {LANGUAGE_DISPLAY.get(src, src)} -> Engels -> {LANGUAGE_DISPLAY.get(tgt, tgt)}")
        stap1 = _run_model(text, src_en)
        if stap1:
            stap2 = _run_model(stap1, en_tgt)
            if stap2:
                return stap2
    return None


# ---------------------------------------------------------------------------
# Ollama engine
# ---------------------------------------------------------------------------
def ollama_check(host: str = "http://localhost:11434") -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def translate_ollama(text: str, src: str, tgt: str,
                     host: str = "http://localhost:11434",
                     model: str = "mistral:7b",
                     progress_cb=None) -> Optional[str]:
    import urllib.request
    import urllib.error
    src_n = LANGUAGE_DISPLAY.get(src, src)
    tgt_n = LANGUAGE_DISPLAY.get(tgt, tgt)
    if progress_cb:
        progress_cb(f"Ollama ({model}): {src_n} -> {tgt_n}")

    # Controleer eerst welke modellen beschikbaar zijn
    try:
        req_tags = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req_tags, timeout=5) as r:
            tags_data = json.loads(r.read())
            beschikbaar = [m["name"] for m in tags_data.get("models", [])]
            logger.info(f"Ollama modellen beschikbaar: {beschikbaar}")
            # Gebruik eerste beschikbaar model als gevraagde niet bestaat
            gebruik_model = model
            if model not in beschikbaar and beschikbaar:
                # Probeer zonder :tag suffix
                model_basis = model.split(":")[0]
                match = next((m for m in beschikbaar if m.startswith(model_basis)), None)
                if match:
                    gebruik_model = match
                    logger.info(f"Model {model} niet gevonden, gebruik {gebruik_model}")
                else:
                    gebruik_model = beschikbaar[0]
                    logger.info(f"Model {model} niet gevonden, gebruik eerste: {gebruik_model}")
    except Exception as e:
        logger.warning(f"Ollama model check mislukt: {e}")
        gebruik_model = model

    prompt = (
        f"Translate the following text from {src_n} to {tgt_n}.\n"
        f"Return ONLY the translation, no explanation or comments.\n\n"
        f"Text:\n{text}\n\nTranslation:"
    )
    payload = json.dumps({
        "model": gebruik_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2048}
    }).encode()
    try:
        req = urllib.request.Request(
            f"{host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=180) as r:
            result = json.loads(r.read())
            response = result.get("response", "").strip()
            if not response:
                logger.error(f"Ollama lege response. Volledig resultaat: {result}")
                return None
            return response
    except urllib.error.HTTPError as e:
        logger.error(f"Ollama HTTP fout {e.code}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        logger.error(f"Ollama verbindingsfout: {e.reason}")
        return None
    except Exception as e:
        logger.error(f"Ollama fout: {type(e).__name__}: {e}")
        return None


def translate_auto(text: str, src: str, tgt: str,
                   engine: str = "AUTO",
                   ollama_host: str = "http://localhost:11434",
                   ollama_model: str = "mistral:7b",
                   progress_cb=None) -> tuple:
    """
    Vertaal — engine prioriteit: NLLB-200 > MarianMT > Ollama
    engine: AUTO | NLLB | MARIAN | OLLAMA
    """
    if src == tgt:
        return text, "-"
    # NLLB-200 — beste kwaliteit, alle taalrichtingen direct
    if engine in ("AUTO", "NLLB"):
        r = translate_nllb(text, src, tgt, progress_cb)
        if r is not None:
            return r, "NLLB-200"
    # MarianMT — fallback als NLLB niet geladen
    if engine in ("AUTO", "MARIAN"):
        r = translate_marian(text, src, tgt, progress_cb)
        if r is not None:
            return r, "MarianMT"
    # Ollama — laatste optie
    if engine in ("AUTO", "OLLAMA"):
        r = translate_ollama(text, src, tgt, ollama_host, ollama_model, progress_cb)
        if r is not None:
            return r, f"Ollama ({ollama_model})"
    return None, "-"


# ---------------------------------------------------------------------------
# Thema's
# ---------------------------------------------------------------------------
THEMES = {
    "donker": {
        "BG":       "#1a2332", "PANEL":  "#243044", "ACCENT": "#2e86ab",
        "ACC2":     "#1d6a8a", "TEXT":   "#e8edf2", "MUTED":  "#8899aa",
        "BORDER":   "#2e4060", "INPUT":  "#0f1923", "OK":     "#2ecc71",
        "WARN":     "#f39c12", "ERR":    "#e74c3c",
        "BTN_LBL":  "☀️  Licht",
    },
    "licht": {
        "BG":       "#f0f4f8", "PANEL":  "#dce3ec", "ACCENT": "#2e86ab",
        "ACC2":     "#1d6a8a", "TEXT":   "#1a2332", "MUTED":  "#5a6a7a",
        "BORDER":   "#b0bec8", "INPUT":  "#ffffff", "OK":     "#27ae60",
        "WARN":     "#e67e22", "ERR":    "#c0392b",
        "BTN_LBL":  "🌙  Donker",
    },
}


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self._translating    = False
        self._cancel         = threading.Event()
        self._theme_name     = "donker"
        self._detected_src: Optional[str] = None

        self._setup_window()
        self._apply_styles()
        self._build_header()
        self._build_toolbar()
        self._build_panels()
        self._build_statusbar()
        self._check_engines()

    @property
    def T(self):
        return THEMES[self._theme_name]

    # ------------------------------------------------------------------ setup

    def _setup_window(self):
        self.title(f"Offline_Translate  v{__version__}")
        self.geometry("1100x700")
        self.minsize(900, 580)
        self.configure(bg=self.T["BG"])
        self.protocol("WM_DELETE_WINDOW", lambda: (self._cancel.set(), self.destroy()))

    def _apply_styles(self):
        T = self.T
        self.configure(bg=T["BG"])
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",        background=T["BG"])
        s.configure("TLabel",        background=T["BG"],    foreground=T["TEXT"],  font=("Segoe UI", 10))
        s.configure("Muted.TLabel",  background=T["BG"],    foreground=T["MUTED"], font=("Segoe UI", 9))
        s.configure("TRadiobutton",  background=T["BG"],    foreground=T["TEXT"],  font=("Segoe UI", 9))
        s.map("TRadiobutton",        background=[("active", T["BG"])])
        s.configure("TCombobox",     fieldbackground=T["PANEL"], foreground=T["TEXT"],
                    selectbackground=T["ACCENT"])
        s.map("TCombobox",
              fieldbackground=[("readonly", T["PANEL"])],
              foreground=[("readonly", T["TEXT"])])
        s.configure("Accent.TButton", background=T["ACCENT"], foreground="white",
                    font=("Segoe UI", 10, "bold"), padding=(16, 8), borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", T["ACC2"]), ("pressed", T["ACC2"])])
        s.configure("Ghost.TButton", background=T["PANEL"], foreground=T["MUTED"],
                    font=("Segoe UI", 9), padding=(8, 4), borderwidth=0)
        s.map("Ghost.TButton",
              background=[("active", T["BORDER"])],
              foreground=[("active", T["TEXT"])])

    # ------------------------------------------------------------------ header

    def _build_header(self):
        T = self.T
        self._hdr = tk.Frame(self, bg=T["PANEL"], height=48)
        self._hdr.pack(fill=tk.X)
        self._hdr.pack_propagate(False)

        tk.Label(self._hdr, text="OFFLINE TRANSLATE", bg=T["PANEL"], fg=T["TEXT"],
                 font=("Segoe UI", 13, "bold"), padx=16).pack(side=tk.LEFT, pady=10)
        tk.Label(self._hdr, text="Offline vertaaltool  |  Classificatie: INTERN",
                 bg=T["PANEL"], fg=T["MUTED"], font=("Segoe UI", 9)).pack(side=tk.LEFT)

        # Thema-knop
        self._btn_theme = tk.Button(
            self._hdr, text=T["BTN_LBL"], bg=T["PANEL"], fg=T["MUTED"],
            font=("Segoe UI", 9), relief=tk.FLAT, bd=0, padx=8, cursor="hand2",
            activebackground=T["BORDER"], activeforeground=T["TEXT"],
            command=self._toggle_theme
        )
        self._btn_theme.pack(side=tk.RIGHT, padx=12)

        self._ind_ollama = tk.Label(self._hdr, text="● Ollama",   bg=T["PANEL"], fg=T["MUTED"], font=("Segoe UI", 9), padx=6)
        self._ind_marian = tk.Label(self._hdr, text="● MarianMT", bg=T["PANEL"], fg=T["MUTED"], font=("Segoe UI", 9), padx=6)
        self._ind_nllb   = tk.Label(self._hdr, text="● NLLB-200", bg=T["PANEL"], fg=T["MUTED"], font=("Segoe UI", 9), padx=6)
        self._ind_ollama.pack(side=tk.RIGHT)
        self._ind_marian.pack(side=tk.RIGHT)
        self._ind_nllb.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ toolbar

    def _build_toolbar(self):
        T = self.T
        self._toolbar = tk.Frame(self, bg=T["BG"], pady=10, padx=12)
        self._toolbar.pack(fill=tk.X)

        tk.Label(self._toolbar, text="Van:", bg=T["BG"], fg=T["MUTED"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self._src = tk.StringVar(value=AUTO_DETECT)
        self._src_cb = ttk.Combobox(self._toolbar, textvariable=self._src,
                                     values=SRC_OPTIONS, state="readonly", width=14)
        self._src_cb.pack(side=tk.LEFT)

        ttk.Button(self._toolbar, text="=", style="Ghost.TButton",
                   command=self._swap, width=3).pack(side=tk.LEFT, padx=6)

        tk.Label(self._toolbar, text="Naar:", bg=T["BG"], fg=T["MUTED"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self._tgt = tk.StringVar(value="Engels")
        ttk.Combobox(self._toolbar, textvariable=self._tgt,
                     values=list(LANGUAGE_DISPLAY.values()),
                     state="readonly", width=14).pack(side=tk.LEFT)

        tk.Label(self._toolbar, text="Engine:", bg=T["BG"], fg=T["MUTED"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(16, 4))
        self._engine = tk.StringVar(value="AUTO")
        for v, l in [("AUTO", "Automatisch"), ("NLLB", "NLLB-200"), ("MARIAN", "MarianMT"), ("OLLAMA", "Ollama")]:
            ttk.Radiobutton(self._toolbar, text=l, variable=self._engine,
                            value=v).pack(side=tk.LEFT, padx=4)

        self._btn_go   = ttk.Button(self._toolbar, text="Vertaal (F5)",
                                     style="Accent.TButton", command=self._go)
        self._btn_go.pack(side=tk.RIGHT, padx=4)
        self._btn_stop = ttk.Button(self._toolbar, text="Annuleer",
                                     style="Ghost.TButton", command=self._stop)
        self._btn_stop.pack(side=tk.RIGHT, padx=2)
        self._btn_stop.state(["disabled"])

        self.bind("<F5>", lambda e: self._go())
        self.bind("<Control-Return>", lambda e: self._go())
        self._src.trace_add("write", self._update_labels)
        self._tgt.trace_add("write", self._update_labels)

    # ------------------------------------------------------------------ panels

    def _build_panels(self):
        T = self.T
        self._cont = tk.Frame(self, bg=T["BG"])
        self._cont.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))
        self._cont.columnconfigure(0, weight=1)
        self._cont.columnconfigure(1, weight=1)
        self._cont.rowconfigure(1, weight=1)

        self._lbl_src = tk.Label(self._cont, text="Brontekst (automatisch)",
                                  bg=T["BG"], fg=T["MUTED"], font=("Segoe UI", 9))
        self._lbl_src.grid(row=0, column=0, sticky=tk.W, pady=(0, 3))
        self._lbl_tgt = tk.Label(self._cont, text="Vertaling (Engels)",
                                  bg=T["BG"], fg=T["MUTED"], font=("Segoe UI", 9))
        self._lbl_tgt.grid(row=0, column=1, sticky=tk.W, pady=(0, 3), padx=(8, 0))

        self._frame_src = self._make_textbox()
        self._frame_src.grid(row=1, column=0, sticky=tk.NSEW, in_=self._cont)
        self._txt_src = self._frame_src._txt

        self._frame_tgt = self._make_textbox()
        self._frame_tgt.grid(row=1, column=1, sticky=tk.NSEW, padx=(8, 0), in_=self._cont)
        self._txt_tgt = self._frame_tgt._txt

        self._btns = tk.Frame(self._cont, bg=T["BG"])
        self._btns.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0))
        ttk.Button(self._btns, text="Kopieer brontekst", style="Ghost.TButton",
                   command=lambda: self._copy(self._txt_src)).pack(side=tk.LEFT)
        ttk.Button(self._btns, text="Wis alles", style="Ghost.TButton",
                   command=self._clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(self._btns, text="Kopieer vertaling", style="Ghost.TButton",
                   command=lambda: self._copy(self._txt_tgt)).pack(side=tk.RIGHT)
        ttk.Button(self._btns, text="Gebruik als brontekst", style="Ghost.TButton",
                   command=self._flip).pack(side=tk.RIGHT, padx=4)

    def _make_textbox(self) -> tk.Frame:
        T = self.T
        frame = tk.Frame(self, bg=T["BORDER"], bd=1)
        txt = tk.Text(frame, bg=T["INPUT"], fg=T["TEXT"], insertbackground=T["TEXT"],
                      font=("Segoe UI", 11), wrap=tk.WORD, relief=tk.FLAT,
                      padx=10, pady=10, undo=True,
                      selectbackground=T["ACCENT"], selectforeground="white")
        scr = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)
        frame._txt = txt
        return frame

    # ------------------------------------------------------------------ statusbar

    def _build_statusbar(self):
        T = self.T
        self._statusbar = tk.Frame(self, bg=T["PANEL"], bd=1, relief=tk.SUNKEN)
        self._statusbar.pack(fill=tk.X, side=tk.BOTTOM)
        self._lbl_status = tk.Label(self._statusbar, text="Gereed", anchor=tk.W,
                                     bg=T["PANEL"], fg=T["TEXT"],
                                     font=("Segoe UI", 9), padx=6)
        self._lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._lbl_engine_used = tk.Label(self._statusbar, text="", anchor=tk.E,
                                          bg=T["PANEL"], fg=T["MUTED"],
                                          font=("Segoe UI", 9), padx=6)
        self._lbl_engine_used.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ thema

    def _toggle_theme(self):
        self._theme_name = "licht" if self._theme_name == "donker" else "donker"
        self._apply_styles()
        T = self.T
        # Header
        self._hdr.config(bg=T["PANEL"])
        for w in self._hdr.winfo_children():
            if isinstance(w, tk.Label):
                w.config(bg=T["PANEL"])
            elif isinstance(w, tk.Button):
                w.config(bg=T["PANEL"], fg=T["MUTED"],
                         activebackground=T["BORDER"], activeforeground=T["TEXT"],
                         text=T["BTN_LBL"])
        self._ind_nllb.config(bg=T["PANEL"])
        self._ind_marian.config(bg=T["PANEL"])
        self._ind_ollama.config(bg=T["PANEL"])
        # Toolbar
        self._toolbar.config(bg=T["BG"])
        for w in self._toolbar.winfo_children():
            if isinstance(w, tk.Label):
                w.config(bg=T["BG"])
        # Panels
        self._cont.config(bg=T["BG"])
        self._lbl_src.config(bg=T["BG"], fg=T["MUTED"])
        self._lbl_tgt.config(bg=T["BG"], fg=T["MUTED"])
        self._btns.config(bg=T["BG"])
        for f, txt in [(self._frame_src, self._txt_src), (self._frame_tgt, self._txt_tgt)]:
            f.config(bg=T["BORDER"])
            txt.config(bg=T["INPUT"], fg=T["TEXT"], insertbackground=T["TEXT"])
        # Statusbar
        self._statusbar.config(bg=T["PANEL"])
        self._lbl_status.config(bg=T["PANEL"])
        self._lbl_engine_used.config(bg=T["PANEL"])

    # ------------------------------------------------------------------ engines

    def _check_engines(self):
        def check():
            # Netwerk veiligheidscheck
            warnings = _check_network_safety()
            n = _load_nllb()
            m = _load_transformers()
            o = ollama_check()
            self.after(0, lambda: self._set_indicators(n, m, o, warnings))
        threading.Thread(target=check, daemon=True).start()

    def _set_indicators(self, nllb_ok: bool, marian_ok: bool, ollama_ok: bool,
                         netwerk_warnings: list = None):
        T = self.T
        self._ind_nllb.config(fg=T["OK"] if nllb_ok else T["ERR"])
        self._ind_marian.config(fg=T["MUTED"] if nllb_ok else (T["OK"] if marian_ok else T["ERR"]))
        self._ind_ollama.config(fg=T["OK"] if ollama_ok else T["WARN"])

        # Netwerk waarschuwing heeft hoogste prioriteit
        if netwerk_warnings:
            self._status(
                "LET OP: Netwerk lockdown niet actief — start via start.bat",
                T["ERR"]
            )
            self._ind_nllb.config(text="⚠ NLLB-200")
            return

        if nllb_ok:
            self._status("Gereed - NLLB-200 actief | Netwerk: geblokkeerd")
        elif marian_ok:
            self._status("NLLB-200 niet geladen - MarianMT actief", T["WARN"])
        elif ollama_ok:
            self._status("Alleen Ollama beschikbaar", T["WARN"])
        else:
            self._status("Geen engine beschikbaar", T["ERR"])

    # ------------------------------------------------------------------ vertalen

    def _go(self):
        if self._translating:
            return
        text = self._txt_src.get("1.0", tk.END).strip()
        if not text:
            self._status("Voer tekst in", self.T["WARN"])
            return

        src_display = self._src.get()
        if src_display == AUTO_DETECT:
            self._status("Taal detecteren...", self.T["MUTED"])
            detected = detect_language(text)
            if detected:
                self._detected_src = detected
                src = detected
                naam = LANGUAGE_DISPLAY.get(detected, detected)
                self._lbl_src.config(text=f"Brontekst (gedetecteerd: {naam})")
            else:
                self._status(
                    "Taal niet herkend - stel brontaal handmatig in via 'Van:'",
                    self.T["WARN"]
                )
                messagebox.showwarning(
                    "Taal niet herkend",
                    "De brontaal kon niet automatisch worden bepaald.\n\n"
                    "Selecteer de brontaal handmatig in het 'Van:' dropdown.",
                    parent=self
                )
                return
        else:
            src = self._to_code(src_display)
            self._detected_src = None

        tgt = self._to_code(self._tgt.get())
        if src == tgt:
            self._status("Bron en doel zijn gelijk", self.T["WARN"])
            return

        self._translating = True
        self._cancel.clear()
        self._btn_go.state(["disabled"])
        self._btn_stop.state(["!disabled"])
        self._txt_tgt.delete("1.0", tk.END)
        self._status("Vertaling starten...", self.T["MUTED"])

        # Controleer op onderbroken vertaling
        lopend = check_lopende_vertaling(src, tgt)
        if lopend:
            # Strip commentaarregels
            vorige = "\n".join(
                r for r in lopend.splitlines()
                if not r.startswith("#")
            ).strip()
            if vorige:
                antw = messagebox.askyesno(
                    "Onderbroken vertaling gevonden",
                    f"Er is een eerdere vertaling gevonden voor {LANGUAGE_DISPLAY.get(src)} → {LANGUAGE_DISPLAY.get(tgt)}.\n\n"
                    f"Wil je deze laden?\n\n"
                    f"(Klik Nee om opnieuw te vertalen)",
                    parent=self
                )
                if antw:
                    self._txt_tgt.delete("1.0", tk.END)
                    self._txt_tgt.insert("1.0", vorige)
                    self._translating = False
                    self._btn_go.state(["!disabled"])
                    self._btn_stop.state(["disabled"])
                    self._status("Onderbroken vertaling geladen", self.T["OK"])
                    return

        def worker():
            # Gebruik chunk-vertaler voor alle teksten
            result, used, voltooid = translate_lang(
                text, src, tgt,
                engine=self._engine.get(),
                ollama_host="http://localhost:11434",
                progress_cb=lambda m: self.after(0, lambda msg=m: self._status(msg, self.T["MUTED"])),
                cancel_flag=self._cancel,
            )
            self.after(0, lambda: self._finish(result, used, src))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, result: Optional[str], used: str, src: str):
        self._translating = False
        self._btn_go.state(["!disabled"])
        self._btn_stop.state(["disabled"])
        T = self.T
        if result:
            self._txt_tgt.delete("1.0", tk.END)
            self._txt_tgt.insert("1.0", result)
            naam = LANGUAGE_DISPLAY.get(src, src)
            self._lbl_src.config(text=f"Brontekst ({naam})")
            self._status("Vertaling gereed", T["OK"])
            self._lbl_engine_used.config(text=f"Engine: {used}")
        else:
            self._status("Vertaling mislukt", T["ERR"])
            messagebox.showerror(
                "Vertaalfout",
                "Vertaling mislukt.\n\n"
                "Controleer:\n"
                "- Zijn de modellen gedownload? (download_models.py)\n"
                "- Is Ollama actief? (ollama serve)\n"
                "- Wordt de taalcombinatie ondersteund?",
                parent=self
            )

    def _stop(self):
        self._cancel.set()
        self._translating = False
        self._btn_go.state(["!disabled"])
        self._btn_stop.state(["disabled"])
        self._status("Geannuleerd", self.T["WARN"])

    # ------------------------------------------------------------------ helpers

    def _to_code(self, display: str) -> str:
        for k, v in LANGUAGE_DISPLAY.items():
            if v == display:
                return k
        return "en"

    def _swap(self):
        s, t = self._src.get(), self._tgt.get()
        new_src = t if t in SRC_OPTIONS else AUTO_DETECT
        if s == AUTO_DETECT and self._detected_src:
            new_tgt = LANGUAGE_DISPLAY.get(self._detected_src, "Nederlands")
        elif s != AUTO_DETECT:
            new_tgt = s
        else:
            new_tgt = "Nederlands"
        self._src.set(new_src)
        self._tgt.set(new_tgt)
        st = self._txt_src.get("1.0", tk.END).strip()
        tt = self._txt_tgt.get("1.0", tk.END).strip()
        self._txt_src.delete("1.0", tk.END)
        self._txt_tgt.delete("1.0", tk.END)
        if tt: self._txt_src.insert("1.0", tt)
        if st: self._txt_tgt.insert("1.0", st)

    def _copy(self, w: tk.Text):
        t = w.get("1.0", tk.END).strip()
        if t:
            self.clipboard_clear()
            self.clipboard_append(t)
            self._status("Gekopieerd naar klembord", self.T["OK"])
        else:
            self._status("Geen tekst om te kopiëren", self.T["WARN"])

    def _clear(self):
        self._txt_src.delete("1.0", tk.END)
        self._txt_tgt.delete("1.0", tk.END)
        self._detected_src = None
        self._lbl_src.config(text="Brontekst (automatisch)")
        self._status("Geleegd")

    def _flip(self):
        t = self._txt_tgt.get("1.0", tk.END).strip()
        if not t:
            return
        s, tg = self._src.get(), self._tgt.get()
        new_src = tg if tg in SRC_OPTIONS else AUTO_DETECT
        new_tgt = s if s != AUTO_DETECT else LANGUAGE_DISPLAY.get(self._detected_src, "Nederlands")
        self._src.set(new_src)
        self._tgt.set(new_tgt)
        self._txt_src.delete("1.0", tk.END)
        self._txt_src.insert("1.0", t)
        self._txt_tgt.delete("1.0", tk.END)
        self._status("Vertaling verplaatst naar bronveld")

    def _update_labels(self, *_):
        src = self._src.get()
        tgt = self._tgt.get()
        if src == AUTO_DETECT:
            src_lbl = f"gedetecteerd: {LANGUAGE_DISPLAY.get(self._detected_src, '')}" \
                      if self._detected_src else "automatisch"
        else:
            src_lbl = src
        self._lbl_src.config(text=f"Brontekst ({src_lbl})")
        self._lbl_tgt.config(text=f"Vertaling ({tgt})")

    def _status(self, msg: str, color: str = None):
        self._lbl_status.config(text=msg, fg=color or self.T["TEXT"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Offline_Translate v{__version__} starten")
    logger.info(__watermark__)
    _log_network_status()
    app = App()
    app.update_idletasks()
    w, h = app.winfo_width(), app.winfo_height()
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    app.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    app.mainloop()
