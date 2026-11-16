"""alpha_check.measure on synthetic layers: a palm with three fingers, a mask band cutting the fingers in the middle."""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "checks"))
from alpha_check import measure, ISLANDS_LIMIT


def hand():
    a = np.zeros((200, 200), np.float32)
    a[120:190, 40:160] = 1.0                       # palm
    for x in (50, 90, 130):
        a[30:120, x:x + 18] = 1.0                  # fingers
    return a


def test_clean_mask_passes():
    raw = hand(); final = raw.copy(); final[0:60, :] = 0        # mask hides the fingertips: the rest stays one piece
    islands, _, _ = measure(raw, final)
    assert sum(w["px"] for w in islands) == 0


def test_mask_cutting_fingers_fails():
    raw = hand(); final = raw.copy(); final[70:90, :] = 0       # band across the middle of the fingers: tips float
    islands, _, _ = measure(raw, final)
    assert len(islands) == 3 and sum(w["px"] for w in islands) > ISLANDS_LIMIT


if __name__ == "__main__":
    test_clean_mask_passes(); test_mask_cutting_fingers_fails(); print("ok alpha")
