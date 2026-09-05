# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

# Centreer de statustekst van PyInstaller's splash-scherm (modulenamen
# tijdens het uitpakken van de onefile-exe, en onze eigen boodschap
# daarna -- zie de Splash(...) call verderop). PyInstaller tekent die
# tekst met een hardcoded "-anchor sw" (linksonder) in zijn eigen
# Tcl-template, waardoor langere teksten aan de rechterkant afgekapt
# worden. Er is geen ingebouwde instelling om dit te centreren
# (gecontroleerd t/m de develop-branch op GitHub), dus we patchen de
# geinstalleerde template hier naar "-anchor s" (onder-midden). Draait
# bij elke build opnieuw (idempotent) omdat een upgrade van PyInstaller
# de ongepatchte template kan terugzetten. Dit .spec-bestand is zelf
# gewoon Python -- geen los patch-scriptje nodig.
import pathlib
import PyInstaller.building.splash_templates as _splash_templates

_splash_tpl_path = pathlib.Path(_splash_templates.__file__)
_splash_tpl_src = _splash_tpl_path.read_text(encoding='utf-8')
_splash_tpl_patched = _splash_tpl_src.replace('-anchor sw', '-anchor s')
if _splash_tpl_patched != _splash_tpl_src:
    _splash_tpl_path.write_text(_splash_tpl_patched, encoding='utf-8')
    print(f"Splash-statustekst gecentreerd (patch toegepast): {_splash_tpl_path}")
else:
    print("Splash-statustekst was al gecentreerd.")

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

# Splash screen: de exe is bewust single-file (onefile) gebleven, en dat
# betekent dat PyInstaller bij elke start eerst alles naar een tijdelijke
# map moet uitpakken (~1-2 GB aan torch/ctranslate2/pyannote) voordat
# Python opstart. Dat kost 10-15s waarin de gebruiker niets ziet gebeuren.
# Deze splash wordt door de bootloader zelf getoond, al tijdens het
# uitpakken, dus vrijwel meteen na de dubbelklik — dat lost het "lijkt
# vastgelopen"-probleem op zonder dat we naar een map-installatie hoeven
# over te stappen. transcribe.py sluit de splash vlak voor het
# hoofdvenster verschijnt (zie pyi_splash in main()).
#
# text_pos staat aan: dat toont tijdens het uitpakken automatisch de
# bestandsnaam van elk uitgepakt bestand (bv. "torch\cuda\amp\__init__.py")
# -- bewust gewenst, zodat zichtbaar is dat er iets gebeurt. PyInstaller
# tekent die tekst standaard met een linksonder-ankerpunt (-anchor sw),
# waardoor langere namen aan de rechterkant afgekapt werden -- vandaar de
# center-anchor patch bovenaan dit bestand. Zodra Python opstart,
# overschrijft transcribe.py de tekst met een vriendelijke boodschap (zie
# pyi_splash in main()) en sluit de splash vlak voor het hoofdvenster
# verschijnt.
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(220, 220),
    text_size=12,
    text_color='#666666',
    text_default='Bezig met opstarten...',
    text_align='center',
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    a.binaries,
    a.datas,
    splash.binaries,
    [],
    name='transcribe-nlen',
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
