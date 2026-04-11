# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['ocr.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pytesseract',
        'PIL', 'PIL.Image', 'PIL.ImageOps', 'PIL.ImageFilter', 'PIL.ImageEnhance',
        'cv2',
        'docx',
        'openpyxl',
        'pptx',
        'tkinterdnd2',
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchaudio', 'torchvision',
        'scipy', 'sklearn', 'matplotlib',
        'numba', 'llvmlite',
        'tensorflow', 'transformers', 'pyarrow',
        'sqlalchemy', 'psycopg2', 'grpc',
        'nltk', 'sympy', 'av',
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
