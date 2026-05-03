# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [('offlinetranslate.ico', '.')]
binaries = []
hiddenimports = []

# transformers + tokenizers + safetensors + huggingface_hub
for pkg in ['transformers', 'tokenizers', 'huggingface_hub', 'safetensors']:
    tmp = collect_all(pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# sentencepiece + sacremoses
for pkg in ['sentencepiece', 'sacremoses']:
    tmp = collect_all(pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# langdetect
tmp = collect_all('langdetect')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# torch (vereist door transformers)
tmp = collect_all('torch')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# Extra hiddenimports
hiddenimports += [
    'transformers.models.nllb',
    'transformers.models.marian',
    'transformers.models.auto',
    'langdetect',
    'sentencepiece',
    'sacremoses',
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
]

a = Analysis(
    ['Offline_Translate.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Offline_Translate',
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
    icon=['offlinetranslate.ico'],
)
