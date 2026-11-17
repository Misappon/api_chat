# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("markdown.extensions") + [
    "pymysql",
    "cryptography",
    "httpx",
    "bs4",
    "soupsieve",
    "pypdf",
]

# Conda keeps libffi/libexpat in Library/bin, outside the DLL search path used
# by PyInstaller's dependency resolver. _ctypes and pyexpat need them.
conda_bin = os.path.join(sys.prefix, "Library", "bin")
binaries = []
for dll_name in ("ffi.dll", "libexpat.dll"):
    dll_path = os.path.join(conda_bin, dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, "."))

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=[("assets", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml"],
    noarchive=False,
)
# Conda's base environment can leak an old ICU 58 into the bundle through
# PATH. Qt 6 on Windows uses the OS-provided ICU; shipping the old DLL causes
# "specified procedure not found" when importing QtCore.
a.binaries = [
    entry
    for entry in a.binaries
    if not os.path.basename(entry[0]).lower().startswith("icu")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="APIChat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="APIChat",
)
