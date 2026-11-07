#!/usr/bin/env python3
"""Build the desktop app on the machine you are on (PyInstaller cannot cross-compile):
     Windows:  py -3 packaging/build.py     ->  dist/KinKeep/KinKeep.exe   (+ dist/KinKeep-windows.zip)
     macOS:    python3 packaging/build.py   ->  dist/KinKeep.app           (+ dist/KinKeep-macos.zip)
Steps: build the UI page, run the tests, make icons, run PyInstaller, zip the result."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
run = lambda *a, **k: subprocess.run(a, cwd=ROOT, check=True, **k)

run(sys.executable, "tools/build_ui.py")
if "--skip-tests" not in sys.argv:
    run(sys.executable, "-m", "pytest", "-q", "-x", "--ignore=tests/test_ui_e2e.py")
png, ico = ROOT / "ui_src" / "KinKeep-logo.png", ROOT / "ui_src" / "KinKeep.ico"
try:
    from PIL import Image
    if sys.platform == "darwin":
        Image.open(png).convert("RGBA").resize((1024, 1024)).save(ROOT / "packaging" / "KinKeep.icns")
except ImportError:
    print("Pillow not installed: building without a macOS icon")
if ico.exists():
    shutil.copy(ico, ROOT / "packaging" / "KinKeep.ico")
shutil.rmtree(ROOT / "dist", ignore_errors=True)
run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "packaging/kinkeep.spec")
name = "KinKeep-macos" if sys.platform == "darwin" else "KinKeep-windows" if sys.platform == "win32" else "KinKeep-linux"
target = ROOT / "dist" / ("KinKeep.app" if sys.platform == "darwin" else "KinKeep")
if sys.platform == "darwin":
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(target), str(ROOT / "dist" / f"{name}.zip")], check=True)  # keeps the bundle intact
else:
    shutil.make_archive(str(ROOT / "dist" / name), "zip", ROOT / "dist", "KinKeep")
print("Built:", target)
