# -*- mode: python ; coding: utf-8 -*-
# ocr.spec — PyInstaller build config voor OCR Pro v3.9
# torch/transformers/easyocr worden NIET gebundeld (te groot).
# hook_sitepkg.py zorgt dat de exe ze vindt in de systeem Python-installatie.

a = Analysis(
    ['ocr.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pytesseract',
        'PIL', 'PIL.Image', 'PIL.ImageOps', 'PIL.ImageFilter', 'PIL.ImageEnhance',
        'cv2',
        'tkinterdnd2',
        'numpy',
        'urllib.request', 'urllib.error',
        'json', 'base64', 'subprocess', 'threading', 'shutil',
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=['hook_sitepkg.py'],
    excludes=[
        'torch', 'torchaudio', 'torchvision',
        'transformers', 'tokenizers', 'huggingface_hub',
        'easyocr', 'jamo', 'unidecode',
        'scipy', 'sklearn', 'matplotlib', 'pandas',
        'numba', 'llvmlite',
        'tensorflow', 'pyarrow',
        'sqlalchemy', 'psycopg2', 'grpc',
        'nltk', 'sympy', 'av',
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ocr.ico'],
)
