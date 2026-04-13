# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [('transcribt.ico', '.')]
binaries = []
hiddenimports = ['tkinterdnd2']

# faster-whisper: ONNX assets (silero_vad_v6.onnx e.a.) meepakken
datas += collect_data_files('faster_whisper', includes=['assets/*'])

# tkinterdnd2
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pyannote — volledige collectie (code + data + binaries)
# collect_all pikt ook submodules op zoals pyannote.audio.models
for pkg in ['pyannote.audio', 'pyannote.core', 'pyannote.database', 'pyannote.metrics']:
    tmp = collect_all(pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

a = Analysis(
    ['transcribe.py'],
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
    name='transcribe',
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
    icon=['transcribt.ico'],
)
