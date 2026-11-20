"""Hip position of a hand-set key pose carried back to Kimodo (plain numpy; keyposes_to_kimodo.py and kimodo_keyposes.py use
it, tests run it). The retarget (soma_to_mixamo.py) moves the rig's hips by the source's hip travel turned by C and scaled
by k = rig hip height / source hip height (above the lowest foot, rest pose). Key poses passed rotations only, so a crouch
posed by hand reached Kimodo at the base sample's standing hip height and floated (Padlinozerca: lowest joint 34 cm up)."""
import numpy as np

KIMODO_TO_BLENDER = np.array([[1.0, 0, 0], [0, 0, -1], [0, 1, 0]])   # Kimodo (Y up) -> Blender (Z up)
BVH_UNITS = 100.0   # Kimodo writes its BVH in cm (kimodo/exports/bvh.py); Blender imports 1 BVH unit = 1 unit


def retarget(src, src_rest, tgt_rest, C, k):
    """soma_to_mixamo.py: rig hips for source hips `src` (both Blender world)."""
    return np.asarray(tgt_rest) + np.asarray(C) @ (np.asarray(src) - src_rest) * k


def source(tgt, src_rest, tgt_rest, C, k):
    """The inverse: source hips (Blender world of the imported BVH) that the retarget turns into rig hips `tgt`."""
    return np.asarray(src_rest) + np.asarray(C).T @ (np.asarray(tgt) - tgt_rest) / k


def to_kimodo(v, src_scale=1.0):
    """Blender world point of the imported BVH -> Kimodo metres (Y up)."""
    return KIMODO_TO_BLENDER.T @ np.asarray(v, float) / (BVH_UNITS * src_scale)
