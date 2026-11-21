"""Pelvis and knee shake (pipeline/lib/shake.py) on synthetic tracks."""
import os, sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
import shake  # noqa: E402


def hips(yaw_deg):
    a = np.radians(yaw_deg); r = np.stack([np.cos(a), np.sin(a), np.zeros_like(a)], 1) * 0.1
    return r, -r


def test_steady_turn_and_step_leave_no_shake():
    y = np.linspace(-23, 30, 40)                                   # a 53 deg turn at a steady rate
    assert np.abs(shake.residual(y)).max() < 1e-9
    knee = np.stack([np.linspace(0, 0.3, 40), np.zeros(40), np.full(40, 0.5)], 1)
    assert shake.residual(knee).max() < 1e-9


def test_pelvis_snapping_to_keys_is_caught():
    """Round 7 pattern: the pelvis reaches the posed yaw only on the key frame and falls back."""
    y = np.zeros(40); y[[10, 15, 18]] = [-10, -17, -19]
    py, _ = shake.rows(*hips(y), np.zeros((40, 3)), np.zeros((40, 3)))
    assert py.max() > 12 and py[:8].max() == 0


def test_yaw_unwraps_across_180():
    y = np.linspace(170, 190, 21)
    assert np.allclose(shake.yaw_deg(*hips(y)), y)
    assert shake.residual(shake.yaw_deg(*hips(y))).max() < 1e-9


def test_edges_and_short_clips_are_zero():
    assert shake.residual(np.arange(4.0)).tolist() == [0, 0, 0, 0]
    r = shake.residual(np.array([0, 0, 5.0, 0, 0, 0, 0]))
    assert r[0] == r[1] == r[-1] == r[-2] == 0 and r[2] == pytest.approx(4.0)
