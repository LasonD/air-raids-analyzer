"""Repository paths, independent of the working directory (works the same on Windows/macOS/Linux)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
ASSETS = ROOT / "airraid" / "assets"
