# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


SOURCE_ROOT = Path(SPECPATH).parent
VERSION = os.environ.get("BLE_STT_APP_VERSION", "0.0.0")
SIGNING_IDENTITY = os.environ.get("BLE_STT_CODESIGN_IDENTITY") or None

datas = []
for package in (
    "bleak",
    "huggingface_hub",
    "mlx",
    "mlx_whisper",
    "opencc",
    "tiktoken",
):
    datas += collect_data_files(package, include_py_files=False)

for distribution in (
    "bleak",
    "hf-xet",
    "huggingface-hub",
    "mlx",
    "mlx-whisper",
    "numpy",
    "opencc-python-reimplemented",
    "tiktoken",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

binaries = collect_dynamic_libs("mlx")
hiddenimports = []
for package in (
    "bleak.backends.corebluetooth",
    "huggingface_hub",
    "mlx",
    "tiktoken",
):
    hiddenimports += collect_submodules(package)

# These are imported through PyObjC at runtime and are easy for static analysis
# to miss when the corresponding branch is not executed during collection.
hiddenimports += [
    "AppKit",
    "CoreBluetooth",
    "Foundation",
    "Quartz",
    "hf_xet",
    "mlx_whisper",
    "objc",
]

a = Analysis(
    [str(Path(SPECPATH) / "entrypoint.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[str(Path(SPECPATH) / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "ctranslate2",
        "faster_whisper",
        "torch",
        "torchaudio",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="M5StopWatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=SIGNING_IDENTITY,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="M5StopWatch",
)

app = BUNDLE(
    coll,
    name="M5StopWatch.app",
    bundle_identifier="com.aporicho.m5stopwatch-ble-stt",
    version=VERSION,
    target_arch="arm64",
    codesign_identity=SIGNING_IDENTITY,
    info_plist={
        "CFBundleDisplayName": "M5StopWatch",
        "CFBundleName": "M5StopWatch",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "15.0",
        "LSUIElement": True,
        "NSBluetoothAlwaysUsageDescription": "用于连接 M5StopWatch 并接收手表上的语音数据。",
        "NSHighResolutionCapable": True,
    },
)
