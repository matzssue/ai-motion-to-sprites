"""grip_words: a grip written in words -> vectors in the prop frame -> back to the same words (no Blender).
python -m pytest tests  (or: python tests/test_grip_words.py)"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
from grip_words import AXES, PALM_SIDE, nearest, grip_from_words, grip_in_words


def test_readme_example():
    g = grip_from_words({"x": 0.08, "palm": "from below", "fingers": "left", "fingers_tilt": ["forward", 45]})
    assert g["palm_normal"] == [0, 0, 1]
    assert np.allclose(g["direction"], [np.sqrt(0.5), np.sqrt(0.5), 0])
    # 45 deg is a tie between two axes: which one is named depends on float rounding (the README line, printed in Blender, says "left")
    assert grip_in_words(g, -0.25) in ("palm from below, fingers %s, 33 cm in front of the butt" % w
                                       for w in ("left and 45 deg forward", "forward and 45 deg left"))


def test_nearest():
    assert nearest(AXES, (0.9, 0.1, 0)) == "forward" and nearest(AXES, (0, -3, 0.5)) == "right"
    assert nearest(PALM_SIDE, (0, 0, 1)) == "from below"


def test_words_round_trip():
    for palm in PALM_SIDE:
        for fingers in AXES:
            for toward in AXES:
                if np.dot(AXES[fingers], AXES[toward]) != 0: continue
                g = grip_from_words({"x": 0.3, "palm": palm, "fingers": fingers, "fingers_tilt": [toward, 30]})
                assert grip_in_words(g, 0.1) == "palm %s, fingers %s and 30 deg %s, 20 cm in front of the butt" % (palm, fingers, toward)


def test_small_tilt_is_not_spoken_and_vectors_pass_through():
    g = grip_from_words({"x": 0.0, "palm": "from above", "fingers": "back", "fingers_tilt": ["up", 2]})
    assert grip_in_words(g, 0.0) == "palm from above, fingers back, 0 cm in front of the butt"
    v = {"x": 0.33, "direction": [0.35, -0.94, 0], "palm_normal": [0, 0, 1]}     # a grip given as vectors stays as it is
    assert grip_from_words(dict(v)) == v
    assert grip_in_words(v, 0.0).startswith("palm from below, fingers right and 20 deg forward")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
