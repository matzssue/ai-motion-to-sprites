"""config.check_model_license: only Kimodo checkpoints that allow commercial use pass.
python -m pytest tests  (or: python tests/test_config.py)"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
from config import check_model_license


def refused(name):
    try: check_model_license(name)
    except ValueError as e: return str(e)
    return None


def test_soma_and_g1_pass():
    for name in ("Kimodo-SOMA-RP-v1.1", "Kimodo-SOMA-RP-v1", "Kimodo-G1-RP-v1"):
        assert refused(name) is None, name


def test_smplx_refused_with_license_name():
    msg = refused("Kimodo-SMPLX-RP-v1")
    assert msg and "NVIDIA R&D Model License" in msg


def test_unknown_refused_with_allowlist_hint():
    for name in ("my-finetune", "kimodo-soma-rp-v1.1", "SOMA-Kimodo-x"):
        msg = refused(name)
        assert msg and "allowlist" in msg and "COMMERCIAL_CHECKPOINTS" in msg, name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
