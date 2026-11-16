"""Machine-specific paths, all overridable by environment variables (see README, "Setup").
BLENDER      Blender executable (default: `blender` on PATH)
KIMODO_DIR   folder with Kimodo: venv/, repo/ (Kimodo source), hf/ (HF_HOME with weights); also holds the GPU lock
KIMODO_MODEL Kimodo checkpoint name (default Kimodo-SOMA-RP-v1.1)"""
import os
import shutil
import sys

PIPELINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = ("", "rig", "motion", "checks", "review", "lib")
BLENDER = os.environ.get("BLENDER") or shutil.which("blender") or "blender"
KIMODO_DIR = os.environ.get("KIMODO_DIR", os.path.join(os.path.expanduser("~"), "kimodo"))
KIMODO_MODEL = os.environ.get("KIMODO_MODEL", "Kimodo-SOMA-RP-v1.1")
KIMODO_PYTHON = os.environ.get("KIMODO_PYTHON") or os.path.join(
    KIMODO_DIR, "venv", "Scripts" if sys.platform == "win32" else "bin", "python.exe" if sys.platform == "win32" else "python")


def script_path(name):
    """Full path of a pipeline script by file name (scripts live in subfolders by stage)."""
    for g in GROUPS:
        p = os.path.join(PIPELINE, g, name)
        if os.path.exists(p): return p
    raise FileNotFoundError("no pipeline script " + name)
