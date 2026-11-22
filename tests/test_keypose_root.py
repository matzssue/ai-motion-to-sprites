"""Key-pose hips carried to Kimodo (pipeline/lib/keypose_root.py) on synthetic poses."""
import math, os, sys

import numpy as np
import pytest

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


def hips(yaw_deg, width=0.2):
    """Right and left hip joints (Kimodo, Y up) of a pelvis turned by yaw about Y (0 = facing +Z, right hip at -x)."""
    a = math.radians(yaw_deg); half = np.array([-math.cos(a), 0.0, math.sin(a)]) * width / 2
    return half, -half


def test_heading_is_kimodos_hip_line_angle():
    for y in (0.0, 23.0, -30.0, 170.0):
        assert math.degrees(K.heading(*hips(y))) == pytest.approx(y, abs=1e-9)


def test_keys_forward_on_the_track_give_the_old_payload_bit_for_bit():
    yaw, xz = K.root_between([0, 10, 25, 69], [K.heading(*hips(0.0))] * 4, [[0.0, 0.0]] * 4, 85)
    head = np.stack([np.cos(yaw), np.sin(yaw) + 0.0], 1).astype(np.float32)   # as kimodo_keyposes.py builds it
    old = np.tile(np.array([[1.0, 0.0]], np.float32), (85, 1))
    assert head.tobytes() == old.tobytes() and (xz + 0.0).tobytes() == np.zeros((85, 2)).tobytes()


def test_path_runs_through_the_keys_without_stopping_mid_turn():
    f, y = [0, 10, 15, 18, 25], np.radians([0.0, -10.0, -17.0, -23.0, 25.0])
    yaw, _ = K.root_between(f, y, [[0.0, 0.0]] * 5, 30)
    assert np.allclose(yaw[f], y)
    assert yaw[10] - yaw[9] < 0 and yaw[11] - yaw[10] < 0            # still turning on key 10 (a smoothstep would stop there)
    assert np.all(np.diff(yaw[:18]) <= 1e-12)                         # monotone run: no overshoot past a key
    assert yaw[18] == pytest.approx(y[3]) and yaw[17] >= y[3] and yaw[19] >= y[3]   # reversal key: the extreme, not passed
    assert np.allclose(yaw[25:], y[4])                                 # held after the last key


def test_turn_takes_the_short_way_across_180():
    yaw, _ = K.root_between([0, 10], np.radians([170.0, -170.0]), [[0.0, 0.0]] * 2, 11)
    assert math.degrees(yaw[5]) == pytest.approx(180.0) and math.degrees(yaw[10]) == pytest.approx(190.0)


def test_root_offset_follows_the_keys_hips():
    _, xz = K.root_between([0, 20, 40], [0.0] * 3, [[0.0, 0.0], [0.04, -0.03], [0.0, 0.0]], 41)
    assert np.allclose(xz[20], [0.04, -0.03]) and np.allclose(xz[[0, 40]], 0.0)
    assert 0 < xz[10, 0] < 0.04 and np.all(xz[:, 0] <= 0.04 + 1e-12)   # between: on the way, never past the key


def test_loop_keys_close_on_the_first_pose():
    yaw, xz = K.root_between([0, 30, 69], np.radians([-2.0, 28.0, -2.0]), [[-0.02, 0.01], [0.03, 0.02], [-0.02, 0.01]], 85)
    assert yaw[69] == pytest.approx(yaw[0]) and np.allclose(xz[69], xz[0]) and np.allclose(yaw[69:], yaw[69])
