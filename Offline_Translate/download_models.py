"""
download_models.py — Modellen downloaden voor Offline_Translate.

NLLB-200 (aanbevolen, ~1.3GB):
    python download_models.py --nllb

MarianMT (alternatief, ~300MB per richting):
    python download_models.py --marian --talen nl en
    python download_models.py --marian --alles

Beide:
    python download_models.py --nllb --marian --talen nl en
"""

import argparse
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_models")

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

LANGUAGE_DISPLAY = {
    "nl": "Nederlands", "en": "Engels", "fr": "Frans", "de": "Duits",
    "es": "Spaans", "ru": "Russisch", "uk": "Oekraiens", "zh": "Chinees", "ar": "Arabisch",
}

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


def download_nllb():
    """Download NLLB-200 distilled 600M (~1.3GB) — beste offline vertaalmodel."""
    model_name = "facebook/nllb-200-distilled-600M"
    local_path = os.path.join(MODELS_DIR, model_name.replace("/", "--"))

    if os.path.exists(local_path):
        print(f"NLLB-200 al aanwezig: {local_path}")
        return True

    print("=" * 50)
    print("NLLB-200 downloaden (~1.3GB)")
    print("Ondersteunt alle 9 talen direct, geen pivot nodig")
    print("=" * 50)

    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError:
        logger.error("transformers niet geinstalleerd. Voer uit: pip install -r requirements.txt")
        return False

    os.makedirs(local_path, exist_ok=True)
    try:
        print("Tokenizer downloaden...")
        tok = AutoTokenizer.from_pretrained(model_name)
        tok.save_pretrained(local_path)

        print("Model downloaden (~1.3GB, even geduld)...")
        mdl = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        mdl.save_pretrained(local_path)

        print(f"NLLB-200 opgeslagen: {local_path}")
        return True
    except Exception as e:
        logger.error(f"NLLB download mislukt: {e}")
        return False


def download_marian(talen, force=False):
    """Download MarianMT modellen als fallback."""
    try:
        from transformers import MarianMTModel, MarianTokenizer
    except ImportError:
        logger.error("transformers niet geinstalleerd.")
        return

    os.makedirs(MODELS_DIR, exist_ok=True)
    te_downloaden = [(src, tgt, naam) for (src, tgt), naam in MARIAN_MODELS.items()
                     if src in talen and tgt in talen]

    if not te_downloaden:
        print(f"Geen MarianMT modellen voor talen: {talen}")
        return

    print(f"\nMarianMT: {len(te_downloaden)} modellen te downloaden")
    geslaagd, mislukt = [], []

    for i, (src, tgt, model_name) in enumerate(te_downloaden, 1):
        local_path = os.path.join(MODELS_DIR, model_name.replace("/", "--"))
        print(f"[{i}/{len(te_downloaden)}] {LANGUAGE_DISPLAY.get(src)} -> {LANGUAGE_DISPLAY.get(tgt)}")

        if os.path.exists(local_path) and not force:
            print(f"  Al aanwezig")
            geslaagd.append(model_name)
            continue

        try:
            tok = MarianTokenizer.from_pretrained(model_name)
            mdl = MarianMTModel.from_pretrained(model_name)
            tok.save_pretrained(local_path)
            mdl.save_pretrained(local_path)
            print(f"  Opgeslagen")
            geslaagd.append(model_name)
        except Exception as e:
            print(f"  MISLUKT: {e}")
            mislukt.append(model_name)

    print(f"\nGeslaagd: {len(geslaagd)}  |  Mislukt: {len(mislukt)}")


def main():
    parser = argparse.ArgumentParser(description="Offline_Translate modellen downloaden")
    parser.add_argument("--nllb",   action="store_true", help="Download NLLB-200 (aanbevolen, ~1.3GB)")
    parser.add_argument("--marian", action="store_true", help="Download MarianMT modellen (fallback)")
    parser.add_argument("--talen",  nargs="+", default=["nl", "en"],
                        choices=list(LANGUAGE_DISPLAY.keys()), metavar="TAAL")
    parser.add_argument("--alles",  action="store_true", help="Alle MarianMT talen")
    parser.add_argument("--force",  action="store_true", help="Overschrijf bestaande modellen")
    args = parser.parse_args()

    # Default: als niets opgegeven, download NLLB
    if not args.nllb and not args.marian:
        args.nllb = True

    print("Offline_Translate — Model Downloader")
    print("=" * 50)
    os.makedirs(MODELS_DIR, exist_ok=True)

    if args.nllb:
        ok = download_nllb()
        if ok:
            print("\nNLLB-200 gereed — alle 9 talen ondersteund zonder extra downloads.")

    if args.marian:
        talen = list(LANGUAGE_DISPLAY.keys()) if args.alles else args.talen
        print(f"\nMarianMT talen: {', '.join(LANGUAGE_DISPLAY.get(t, t) for t in talen)}")
        download_marian(talen, args.force)

    print("\nOffline_Translate is gereed voor gebruik.")


if __name__ == "__main__":
    main()
