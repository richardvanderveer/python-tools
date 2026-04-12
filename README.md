# python-tools

Verzameling van Python desktop tools voor Windows 11.

## Apps

| App | Omschrijving | Versie |
|-----|-------------|--------|
| AudioForge | Audio converter en editor met waveform visualisatie | v2.1.2 |
| Transcribe | Lokale audio/video transcriptie met AI (faster-whisper + pyannote) | v2.0.1 |
| OCR Pro | OCR tool voor afbeeldingen en PDF naar tekst/docx/xlsx/pptx | v1.3.0 |

## Releases

Collega's downloaden de kant-en-klare `.exe` via GitHub Releases.
Geen Python-installatie vereist.

## Vereisten per app

### OCR Pro
OCR Pro vereist twee externe tools die eenmalig geïnstalleerd moeten worden:

**1. Tesseract OCR**
Download en installeer via de officiële installer:
https://github.com/UB-Mannheim/tesseract/wiki

Standaard installatiepad: `C:\Program Files\Tesseract-OCR\tesseract.exe`

Taalbestanden installeren (kies bij installatie):
- Nederlands (nld)
- Engels (eng)
- Arabisch (ara) — optioneel

**2. Poppler (voor PDF-ondersteuning)**
Eenmalig installeren via winget:
```
winget install oschwartz10612.poppler
pip install pdf2image
```

Zonder poppler werkt OCR Pro alleen op afbeeldingen (png, jpg, etc.).
Met poppler ook op PDF bestanden (alle pagina's worden verwerkt).

## Nieuwe release bouwen

Elke app heeft een eigen release bat in de werkmap:

| App | Werkmap | Bat |
|-----|---------|-----|
| AudioForge | `C:\github_cicd\audioforge\` | `audioforge_release.bat` |
| Transcribe | `C:\github_cicd\transcribe\` | `transcribe_release.bat` |
| OCR Pro | `C:\github_cicd\ocr\` | `ocr_release.bat` |

Dubbelklik de bat, voer versienummer en commit bericht in.
De bat bouwt lokaal, pusht naar GitHub en maakt een tag aan.
GitHub Actions bouwt automatisch de release exe.

## Monorepo structuur

```
python-tools/
  audioforge/       ← AudioForge broncode + spec + ico
  transcribe/       ← Transcribe broncode + spec + ico
  ocr/              ← OCR Pro broncode + spec + ico + hook
  .github/
    workflows/
      ci.yml        ← Smoke tests per app (path-triggered)
      release.yml   ← Exe bouwen + GitHub Release (tag-triggered)
```

## GitHub links

- Repo: https://github.com/richardvanderveer/python-tools
- Releases: https://github.com/richardvanderveer/python-tools/releases
- Actions: https://github.com/richardvanderveer/python-tools/actions
