"""The pipeline's own helpers (pipeline/lib), imported the way character.py imports them, so the service judges
freshness and validity with the same code."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(REPO, "pipeline", "lib")
if LIB not in sys.path: sys.path.insert(0, LIB)

from config import script_path  # noqa: E402
from schema_check import load_character, problems  # noqa: E402
from stages import NOISE, STAGES, fresh, rig_review  # noqa: E402

CHARACTER_PY = os.path.join(REPO, "pipeline", "character.py")
__all__ = ["CHARACTER_PY", "NOISE", "REPO", "STAGES", "fresh", "load_character", "problems", "rig_review", "script_path"]
