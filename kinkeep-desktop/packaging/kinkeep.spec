# PyInstaller spec for Windows (.exe) and macOS (.app). Run from kinkeep-desktop/:  pyinstaller packaging/kinkeep.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
IS_MAC, IS_WIN = sys.platform == "darwin", sys.platform == "win32"
icon = str(ROOT / "packaging" / ("KinKeep.icns" if IS_MAC else "KinKeep.ico"))
if not Path(icon).exists():
    icon = None

a = Analysis(
    [str(ROOT / "run_kinkeep.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "kinkeep_desktop" / "ui"), "kinkeep_desktop/ui")],
    hiddenimports=["keyring.backends.Windows", "keyring.backends.macOS"] if (IS_WIN or IS_MAC) else [],
    excludes=["tkinter", "unittest", "pydoc", "test"],   # smaller, fewer moving parts
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="KinKeep", console=False, icon=icon, disable_windowed_traceback=True)
coll = COLLECT(exe, a.binaries, a.datas, name="KinKeep")
if IS_MAC:
    app = BUNDLE(coll, name="KinKeep.app", icon=icon, bundle_identifier="app.kinkeep.desktop",
                 info_plist={"CFBundleShortVersionString": "2.0.0", "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "11.0", "NSDocumentsFolderUsageDescription": "KinKeep keeps your encrypted records in your Documents folder."})
