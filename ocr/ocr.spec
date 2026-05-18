# -*- mode: python ; coding: utf-8 -*-
# ocr.spec — PyInstaller build config voor OCR Pro
# torch/transformers/easyocr worden NIET gebundeld in de exe
# (te groot, ~4GB+) — ze worden gedownload bij eerste gebruik.

a = Analysis(
    ['ocr.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Tesseract wrapper
        'pytesseract',
        # Imaging
        'PIL', 'PIL.Image', 'PIL.ImageOps', 'PIL.ImageFilter', 'PIL.ImageEnhance',
        # OpenCV
        'cv2',
        # Tkinter drag-and-drop
        'tkinterdnd2',
        # Numeriek
        'numpy',
        # Netwerk (Ollama)
        'urllib.request', 'urllib.error', 'json', 'base64',
        # Threading / OS
        'subprocess', 'threading', 'shutil',
    ],
    hookspath=['.'],       # hook-tkinterdnd2.py staat naast ocr.py
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ML-frameworks — niet gebundeld (te groot, optioneel)
        'torch', 'torchaudio', 'torchvision',
        'transformers', 'tokenizers', 'huggingface_hub',
        'easyocr', 'jamo', 'unidecode',
        # Wetenschappelijk
        'scipy', 'sklearn', 'matplotlib', 'pandas',
        'numba', 'llvmlite',
        # Overig groot
        'tensorflow', 'pyarrow',
        'sqlalchemy', 'psycopg2', 'grpc',
        'nltk', 'sympy', 'av',
        # Office-formaten (niet gebruikt in UI)
        'docx', 'openpyxl', 'pptx',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ocr',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # geen CMD-venster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ocr.ico'],
)
