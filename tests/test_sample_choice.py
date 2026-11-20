"""Choosing a sample: hand activity from a Kimodo BVH (bvh.py) and the automatic pick (stages.pick)."""
import os, sys, tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
import bvh  # noqa: E402
from stages import pick  # noqa: E402

# Root -> Hips (6 channels, position replaces OFFSET) -> LeftHand / RightHand 50 cm to each side; 3 frames at 30 fps.
# Frame 1 turns the hips 90 deg about Y (the hands swing to the front/back), frame 2 lifts the hips by 10 cm.
BVH = """HIERARCHY
ROOT Root
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
  JOINT Hips
  {
    OFFSET 0 100 0
    CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
    JOINT LeftHand
    {
      OFFSET 50 0 0
      CHANNELS 3 Zrotation Yrotation Xrotation
      End Site
      {
        OFFSET 0 0 1
      }
    }
    JOINT RightHand
    {
      OFFSET -50 0 0
      CHANNELS 3 Zrotation Yrotation Xrotation
      End Site
      {
        OFFSET 0 0 1
      }
    }
  }
}
MOTION
Frames: 3
Frame Time: 0.0333333
0 0 0 0 0 0  0 90 0 0 0 0  0 0 0  0 0 0
0 0 0 0 0 0  0 90 0 0 90 0  0 0 0  0 0 0
0 0 0 0 0 0  0 100 0 0 0 0  0 0 0  0 0 0
"""


def _joints():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.bvh"); open(p, "w").write(BVH)
        return bvh.joints(p)


def test_joints_forward_kinematics():
    J, names, ft = _joints()
    assert names == ["Root", "Hips", "LeftHand", "RightHand"] and abs(ft - 1 / 30) < 1e-6
    np.testing.assert_allclose(J[0, 1], [0, 0, 0.9], atol=1e-9)          # Y up -> Z up; position channels replace OFFSET
    np.testing.assert_allclose(J[0, 2], [0.5, 0, 0.9], atol=1e-9)
    # +90 deg about BVH Y takes +X to -Z (BVH), which is +Y in Blender's frame
    np.testing.assert_allclose(J[1, 2], [0, 0.5, 0.9], atol=1e-9)
    np.testing.assert_allclose(J[2, 2], [0.5, 0, 1.0], atol=1e-9)


def test_activity_measures_hands_against_the_hips():
    J, names, ft = _joints()
    a = bvh.activity(J, names, ft, {"phases": [{"duration": 0.05}, {"duration": 0.05}]})
    assert abs(a["range"]["L"] - np.sqrt(0.5)) < 1e-3        # swung from +X to +Y: 0.71 m; lifting the hips moves nothing
    assert len(a["phase_moves"]) == 2


def test_pick_skips_samples_that_did_nothing():
    # Padlinozerca round 1: s0 held the hands at the head (score 1.18), s1 did the rake (17.31)
    assert pick([(1.18, 0.37), (17.31, 1.18), (38.09, 0.21), (13.13, 0.56)]) == 3
    # Wybuchacz run: s0 and s2 stood still; the clean audit of s2 (0) does not win
    assert pick([(22.6, 0.08), (0.13, 0.44), (0.0, 0.10), (0.0, 0.19)]) == 3
    # approved choices keep their sample: Wybuchacz attack through the poses (kf s1), run (kf s0)
    assert pick([(14.2, 0.67), (6.21, 0.65), (27.34, 0.73), (14.59, 0.57)]) == 1
    assert pick([(1.06, 0.23), (12.51, 0.46), (6.26, 0.36), (12.81, 0.36)]) == 0
    assert pick([(1.18, 0.36), (1.47, 0.43), (1.18, 0.31), (1.18, 0.31)]) == 0      # a tie goes to the more active one
