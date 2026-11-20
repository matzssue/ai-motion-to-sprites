"""Key-pose hips carried to Kimodo (pipeline/lib/keypose_root.py) on synthetic poses."""
import math, os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
import keypose_root as K  # noqa: E402

# imported BVH in cm (Blender Z up), rig in metres; the rig faces another way (C turns 90 deg about Z)
SRC_REST = np.array([0.0, 0.0, 95.0])
TGT_REST = np.array([0.0, 0.0, 1.10])
C = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
k = 1.10 / 95.0


def test_source_is_the_inverse_of_the_retarget():
    src = np.array([4.0, -7.0, 88.0])
    tgt = K.retarget(src, SRC_REST, TGT_REST, C, k)
    assert np.allclose(K.source(tgt, SRC_REST, TGT_REST, C, k), src)


def test_crouch_set_by_hand_lowers_the_kimodo_root():
    # the author lowers the rig's hips 33 cm and pushes them 10 cm forward (rig -Y) from standing
    standing = TGT_REST
    crouch = TGT_REST + np.array([0.0, -0.10, -0.33])
    a = K.to_kimodo(K.source(standing, SRC_REST, TGT_REST, C, k))
    b = K.to_kimodo(K.source(crouch, SRC_REST, TGT_REST, C, k))
    assert math.isclose(a[1], 0.95, abs_tol=1e-9)                      # Kimodo Y = hip height above the ground
    assert math.isclose(a[1] - b[1], 0.33 / 1.10 * 0.95, abs_tol=1e-9)  # lowered in source proportion
    assert math.isclose(float(np.linalg.norm(b - a)), math.hypot(0.10, 0.33) / 1.10 * 0.95, abs_tol=1e-9)


def test_to_kimodo_axes_and_units():
    # Blender (x, y, z) in cm = Kimodo (x, -z, y) in m, as the axis check of kimodo_keyposes.py prints it
    assert np.allclose(K.to_kimodo([10.0, 20.0, 90.0]), [0.10, 0.90, -0.20])
    assert np.allclose(K.to_kimodo([10.0, 20.0, 90.0], src_scale=0.5), [0.20, 1.80, -0.40])
    assert np.allclose(K.KIMODO_TO_BLENDER @ K.to_kimodo([1.0, 2.0, 3.0]) * K.BVH_UNITS, [1.0, 2.0, 3.0])
