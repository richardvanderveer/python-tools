# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [('transcribt.ico', '.')]
binaries = []
hiddenimports = ['tkinterdnd2']

# faster-whisper: volledige collectie inclusief ONNX assets
for pkg in ['faster_whisper', 'ctranslate2']:
    tmp = collect_all(pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# ONNX assets expliciet meepakken (silero_vad_v6.onnx e.a.)
datas += collect_data_files('faster_whisper', includes=['assets/*'])

# tkinterdnd2
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pyannote — volledige collectie (code + data + binaries)
for pkg in ['pyannote.audio', 'pyannote.core', 'pyannote.database', 'pyannote.metrics', 'pyannote.pipeline']:
    tmp = collect_all(pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# Extra hiddenimports die PyInstaller mist
hiddenimports += [
    'faster_whisper',
    'faster_whisper.transcribe',
    'faster_whisper.audio',
    'faster_whisper.feature_extractor',
    'faster_whisper.tokenizer',
    'faster_whisper.vad',
    'ctranslate2',
    'huggingface_hub',
    'tokenizers',
    'onnxruntime',
    'av',
    'torch',
    'torchaudio',
    'lightning',
    'pyannote.audio.pipelines',
    'pyannote.audio.pipelines.speaker_diarization',
    'pyannote.audio.models.segmentation',
]

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
