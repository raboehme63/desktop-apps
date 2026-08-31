# PyInstaller spec for the Windows onedir bundle. Run via packaging/build.ps1.
# Application sources under apps/ and packages/ are not modified.

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPECPATH).resolve()
ROOT = SPECDIR.parent
SRC_CORE = ROOT / "packages" / "travelcore" / "src"
SRC_APP = ROOT / "apps" / "traveljournal" / "src"
_VERSION = os.environ.get("TRAVELJOURNAL_VERSION", "3.1.0")  # kept for EXE metadata later

datas: list = []
binaries: list = []
hiddenimports: list = []

# Collect data-file packages only. PySide6/WebEngine come from PyInstaller hooks
# plus the hiddenimports below so unused Qt modules stay out of the bundle.
for package in (
    "folium",
    "branca",
    "jinja2",
    "xyzservices",
    "alembic",
    "mako",
):
    collected_datas, collected_binaries, collected_hidden = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hidden

hiddenimports += collect_submodules("travelcore")
hiddenimports += collect_submodules("traveljournal")
hiddenimports += [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "sqlalchemy.dialects.sqlite",
]

datas += [
    (
        str(SRC_CORE / "travelcore" / "database" / "migrations"),
        "travelcore/database/migrations",
    ),
    (str(ROOT / "LICENSE"), "."),
    (str(SPECDIR / "NOTICE.txt"), "."),
]

a = Analysis(
    [str(SPECDIR / "entry.py")],
    pathex=[str(SRC_CORE), str(SRC_APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Reisetagebuch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Reisetagebuch",
)
