"""Compatibility entry point; the main app uses explicit top navigation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from views import ranking

ranking()
