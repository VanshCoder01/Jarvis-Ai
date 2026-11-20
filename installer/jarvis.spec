# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Jarvis.  Built by build.bat -- run that, not this.
#
# One-folder build (dist\Jarvis\Jarvis.exe + dist\Jarvis\_internal\...), not
# one-file: it starts in a second instead of unpacking ~100 MB to %TEMP% on
# every launch, and antivirus flags it far less often. The installer ships
# the whole folder.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

hidden = (
    collect_submodules("google.genai")
    + collect_submodules("edge_tts")
    + ["openai", "anthropic", "pyscreeze", "pymsgbox", "pytweening", "pygetwindow",
       "mouseinfo", "win32timezone", "screen_brightness_control", "wmi",
       "googleapiclient.discovery", "google_auth_oauthlib.flow"]
)

datas = [
    (os.path.join(ROOT, "index.html"), "."),
    (os.path.join(ROOT, "jarvis.ico"), "."),
]
datas += collect_data_files("certifi")
datas += collect_data_files("googleapiclient")   # discovery documents for Gmail

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests", "pytest", "IPython"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jarvis",
    icon=os.path.join(ROOT, "jarvis.ico"),
    console=False,
    upx=False,                  # UPX-packed exes are a classic antivirus false positive
    version=os.path.join(SPECPATH, "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="Jarvis",
)
