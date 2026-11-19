"""Machine-specific paths, all overridable by environment variables (see README, "Setup").
BLENDER      Blender executable (default: `blender` on PATH)
KIMODO_DIR   folder with Kimodo: venv/, repo/ (Kimodo source), hf/ (HF_HOME with weights); also holds the GPU lock
KIMODO_MODEL Kimodo checkpoint name (default Kimodo-SOMA-RP-v1.1); only commercial-use checkpoints pass (LICENSES.md)"""
import os
import shutil
import sys

PIPELINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = ("", "rig", "motion", "checks", "review", "lib")
BLENDER = os.environ.get("BLENDER") or shutil.which("blender") or "blender"
KIMODO_DIR = os.environ.get("KIMODO_DIR", os.path.join(os.path.expanduser("~"), "kimodo"))
KIMODO_MODEL = os.environ.get("KIMODO_MODEL", "Kimodo-SOMA-RP-v1.1")
# checkpoint families whose license allows commercial use (LICENSES.md); anything else is refused
COMMERCIAL_CHECKPOINTS = ("Kimodo-SOMA-", "Kimodo-G1-")


def check_model_license(name):
    """Raises ValueError unless the Kimodo checkpoint is on the commercial-use allowlist."""
    if name.startswith(COMMERCIAL_CHECKPOINTS): return
    if name.startswith("Kimodo-SMPLX-"):
        raise ValueError("KIMODO_MODEL=%s is under the NVIDIA R&D Model License (no commercial use); use a Kimodo-SOMA-* "
                         "checkpoint" % name)
    raise ValueError("KIMODO_MODEL=%s is not on the license allowlist: check its license and, if it allows commercial use, "
                     "add its prefix to COMMERCIAL_CHECKPOINTS in pipeline/lib/config.py and to LICENSES.md" % name)


try: check_model_license(KIMODO_MODEL)
except ValueError as e: raise SystemExit(str(e))
KIMODO_PYTHON = os.environ.get("KIMODO_PYTHON") or os.path.join(
    KIMODO_DIR, "venv", "Scripts" if sys.platform == "win32" else "bin", "python.exe" if sys.platform == "win32" else "python")


def script_path(name):
    """Full path of a pipeline script by file name (scripts live in subfolders by stage)."""
    for g in GROUPS:
        p = os.path.join(PIPELINE, g, name)
        if os.path.exists(p): return p
    raise FileNotFoundError("no pipeline script " + name)
