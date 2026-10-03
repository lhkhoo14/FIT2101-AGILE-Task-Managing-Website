from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

if DIST.exists():
    shutil.rmtree(DIST)

DIST.mkdir()
shutil.copy2(ROOT / "index.html", DIST / "index.html")
shutil.copy2(ROOT / "settings.json", DIST / "settings.json")
shutil.copytree(ROOT / "src", DIST / "src")

print(f"Frontend built in {DIST}")
