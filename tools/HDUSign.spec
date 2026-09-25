# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
BROWSERS = ROOT / 'build' / 'portable-runtime' / 'browsers'
FFMPEG = ROOT / 'build' / 'portable-runtime' / 'ffmpeg'
if not BROWSERS.is_dir():
    raise RuntimeError('Use tools/release.py build --ffmpeg-bundle <audio ZIP> to prepare the portable runtime.')
if not all((FFMPEG / name).is_file() for name in (
        'ffmpeg.exe', 'LICENSE', 'README.txt', 'SOURCE.json', 'version.txt',
        'buildconf.txt', 'license-notice.txt')):
    raise RuntimeError('The complete FFmpeg runtime and notices are missing. '
                       'Use tools/release.py build --ffmpeg-bundle <audio ZIP> to prepare them.')

datas = [(str(ROOT / 'config.example.yaml'), '.'),
         (str(ROOT / 'assets' / 'hdusign.ico'), 'assets'),
         (str(ROOT / 'hdusign' / 'qml'), 'hdusign/qml'),
         (str(BROWSERS), 'browsers'),
         (str(FFMPEG), 'ffmpeg')]
binaries = []
hiddenimports = ['soundcard.mediafoundation']
for package in ('sherpa_onnx', 'soundcard', 'fastembed', 'onnxruntime',
                'tokenizers', 'huggingface_hub'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports


a = Analysis(
    [str(ROOT / 'hdusign' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / 'tools' / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'hdusign.gui', 'hdusign.ui',
              'PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HDUSign',
    icon=str(ROOT / 'assets' / 'hdusign.ico'),
    version=str(ROOT / 'build' / 'windows-version.txt'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['ffmpeg.exe'],
    name='HDUSign',
)
