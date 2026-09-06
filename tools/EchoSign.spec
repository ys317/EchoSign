# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
BROWSERS = ROOT / 'build' / 'portable-runtime' / 'browsers'
if not BROWSERS.is_dir():
    raise RuntimeError('Use python tools/release.py build to prepare the portable runtime.')

datas = [(str(ROOT / 'config.example.yaml'), '.'),
         (str(ROOT / 'assets' / 'echosign.ico'), 'assets'),
         (str(BROWSERS), 'browsers')]
binaries = []
hiddenimports = ['soundcard.mediafoundation']
for package in ('sherpa_onnx', 'soundcard', 'fastembed', 'onnxruntime',
                'tokenizers', 'huggingface_hub', 'customtkinter'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports


a = Analysis(
    [str(ROOT / 'echosign' / '__main__.py')],
    pathex=[str(ROOT)],
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
    [],
    exclude_binaries=True,
    name='EchoSign',
    icon=str(ROOT / 'assets' / 'echosign.ico'),
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
    upx_exclude=[],
    name='EchoSign',
)
