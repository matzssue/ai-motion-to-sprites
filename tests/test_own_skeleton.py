"""Own skeleton (no Blender): the definition against its profile, the rest-frame rule, SOMA proportions, fingers placed on
a synthetic hand and the template-less joints file of auto_rig.
python -m pytest tests  (or: python tests/test_own_skeleton.py)"""
import json, os, sys
import numpy as np
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline", "lib")); sys.path.insert(0, os.path.join(ROOT, "pipeline", "rig"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_rig, hand_fingers, own_skeleton as OS, schema_check, skeleton
from test_auto_rig import H, box, mesh

WRIST_X, PALM_END, TIP_X, HAND_Z = 0.85, 0.95, 1.03, (1.35, 1.41)
# index .. pinky lanes in y (index in front: the model faces -Y), thumb in front of the palm
LANES = (-0.04, -0.015, 0.01, 0.035)


def hand_parts(side=1, mitten=False):
    """Boxes of one hand in a T-pose (palm down), wrist at |x| = 0.85."""
    def bx(x0, x1, y0, y1):
        xs = sorted((side * x0, side * x1)); return ((xs[0], y0, HAND_Z[0]), (xs[1], y1, HAND_Z[1]))
    if mitten: return [bx(WRIST_X, TIP_X, -0.05, 0.05)]
    parts = [bx(WRIST_X, PALM_END, -0.05, 0.05), bx(0.90, 0.96, -0.10, -0.05)]
    parts += [bx(PALM_END, TIP_X - (0.012 if k == 3 else 0.0), y - 0.0075, y + 0.0075) for k, y in enumerate(LANES)]
    return parts


def fine(parts, step=0.005):
    """Boxes as one mesh with ~5 mm vertices (finger-sized parts; the 2 cm grid of test_auto_rig leaves 7 mm gaps)."""
    V, T, n = [], [], 0
    for lo, hi in parts:
        v, t = box(lo, hi, step); V.append(v); T.append(t + n); n += len(v)
    return np.vstack(V), np.vstack(T)


def test_definition_matches_profile():
    P = skeleton.load(OS.NAME)
    R = P.bind(OS.PARENT)
    assert len(OS.BONES) == 65 and sum(OS.deforming(b[0]) for b in OS.BONES) == 52
    assert sum(OS.deforming(b[0], fingers=False) for b in OS.BONES) == 52 - 30
    seen = set()
    for name, parent, *_ in OS.BONES:
        assert parent is None or parent in seen, name; seen.add(name)
        assert "mixamorig" not in name and ":" not in name
    assert P.spine == ["spine.1", "spine.2", "spine.3"] and P.aim("hand.L") == "middle.1.L" and P.aim("spine.3") == "neck"
    assert len(R.fingers) == 2 * 5 * 4 and R.bone_side("pinky_end.R") == "R" and R.region["thigh.L"] == "legs"
    pairs = dict(skeleton.load("soma").pairs(P))
    assert pairs["Chest"] == "spine.3" and pairs["LeftLeg"] == "thigh.L" and pairs["RightShin"] == "shin.R"
    assert dict(P.same_roles(skeleton.load("soma")))["middle.1.L"] == "LeftHandMiddle1"
    for s in ("L", "R"):   # the profile's finger chains are the skeleton's finger bones, knuckle first
        assert P.finger_chains(s) == {f: ["%s.%d.%s" % (f, i, s) for i in (1, 2, 3)] for f in OS.FINGERS}
        assert all(OS.PARENT[c[0]] == "hand." + s for c in P.finger_chains(s).values())


def test_soma_proportions_are_fractions():
    assert 0 < OS.SPINE_SPLIT[0] < OS.SPINE_SPLIT[1] < OS.SPINE_SPLIT[2] < 1
    for f, p in OS.PHALANX.items():
        assert abs(sum(p) - 1) < 0.002, f
    assert all(0.3 < k < 0.7 for k in OS.KNUCKLE.values())


def joints_with_fingers():
    v0, t0 = mesh(humanoid_parts()); v1, t1 = fine([*hand_parts(1), *hand_parts(-1)])
    v, t = np.vstack([v0, v1]), np.vstack([t0, t1 + len(v0)])
    j, f = auto_rig.solve(v, t)
    return v, t, OS.own_joints(j)


def humanoid_parts():
    """test_auto_rig's humanoid boxes without its box hands."""
    import test_auto_rig as T
    parts = [((-0.20, -0.10, T.CROTCH), (0.20, 0.10, 1.45)), ((-0.05, -0.05, 1.45), (0.05, 0.05, 1.55)),
             ((-0.10, -0.12, 1.55), (0.10, 0.10, H))]
    for s in (1, -1):
        x = sorted((s * 0.20, s * 0.85)); parts.append(((x[0], -0.05, T.ARM_LO), (x[1], 0.05, T.ARM_HI)))
        x = sorted((s * 0.06, s * 0.18))
        parts += [((x[0], -0.07, 0.0), (x[1], 0.07, T.CROTCH)), ((x[0], -0.20, 0.0), (x[1], 0.07, 0.08))]
    return parts


def test_own_joints_spine_and_clavicle():
    _, _, j = joints_with_fingers()
    hips, neck = j["Hips"], j["Neck"]
    for k, t in zip(("Spine", "Spine1", "Spine2"), OS.SPINE_SPLIT):
        assert np.allclose(j[k], hips + t * (neck - hips))
    assert abs(j["LeftShoulder"][0] - OS.CLAVICLE_X * j["LeftArm"][0]) < 1e-9 and j["LeftShoulder"][2] == j["LeftArm"][2]


def test_five_fingers_follow_the_digits():
    v, t = fine(hand_parts(1))
    tip = v[v[:, 0].argmax()]
    chains, rep = hand_fingers.place(v, t, np.array([WRIST_X, 0.0, 1.38]), tip, H, np.array([0.5, 0.0, 1.38]))
    assert rep.startswith("5 digits") and set(chains) == set(OS.FINGERS)
    assert chains["thumb"][3][1] < -0.05 and 0.9 < chains["thumb"][3][0] < 0.97            # thumb on the thumb box
    for f, y in zip(OS.FINGERS[1:], LANES):
        J = np.array(chains[f])
        assert np.all(np.abs(J[1:, 1] - y) < 0.006), (f, J)                                  # on its own finger
        assert np.all(np.diff(J[:, 0]) > 0) and J[3, 0] > PALM_END + 0.04                    # knuckle -> tip outwards
        assert np.all((J[:, 2] > HAND_Z[0]) & (J[:, 2] < HAND_Z[1]))                         # inside the hand
        assert WRIST_X + 0.05 < J[0, 0] <= PALM_END + 0.005                                  # knuckle in the palm


def test_mitten_gets_five_spread_chains():
    v, t = fine(hand_parts(-1, mitten=True))
    tip = v[v[:, 0].argmin()]
    chains, rep = hand_fingers.place(v, t, np.array([-WRIST_X, 0.0, 1.38]), tip, H, np.array([-0.5, 0.0, 1.38]))
    assert rep.startswith("1 digit") and set(chains) == set(OS.FINGERS)
    ys = [np.mean([p[1] for p in chains[f]]) for f in OS.FINGERS]
    assert all(a < b for a, b in zip(ys, ys[1:])) and ys[0] < -0.03 and ys[-1] > 0.03      # thumb in front, evenly back
    assert all(chains[f][3][0] < -TIP_X + 0.02 for f in OS.FINGERS)                         # every chain reaches the end


def test_bone_frames_rule():
    v, t, j = joints_with_fingers()
    fj, _ = hand_fingers.finger_joints(v, t, j, H)
    j.update(fj)
    F = OS.bone_frames(j)
    assert set(F) == {b[0] for b in OS.BONES}
    for name, (head, tail, z) in F.items():
        y = (tail - head) / np.linalg.norm(tail - head)
        assert abs(np.linalg.norm(z) - 1) < 1e-9 and abs(z @ y) < 1e-9, name
    for s, S in OS.SIDES:
        n = OS.palm_normal(j, S)
        assert n[2] < -0.9                                                  # T-pose: palms face down
        assert F["index.1." + s][2] @ n > 0.99 and F["hand." + s][2] @ n > 0.99
        assert F["foot." + s][2][2] > 0.5 and F["upper_arm." + s][2][1] < -0.99
    assert F["spine.2"][2][1] < -0.99 and np.allclose(F["head_end"][0], j["HeadTop_End"])
    del j["LeftHandRing3"]
    with pytest.raises(KeyError, match="LeftHandRing3"):
        OS.bone_frames(j)


def test_joints_file_old_format_readable(tmp_path):
    """A joints file in today's format (no finger keys, from another detector or a template run) gets fingers from the
    mesh; every other key stays as it was."""
    v, t, j = joints_with_fingers()
    old = {k: [round(float(c), 5) for c in x] for k, x in auto_rig.solve(v, t)[0].items()}
    p = tmp_path / "x_joints.json"; p.write_text(json.dumps(dict(old, _note="hand-fixed")))
    auto_rig.own_joints_file(v, t, str(p))
    new = json.loads(p.read_text())
    assert all(new[k] == x for k, x in old.items()) and new["_note"] == "hand-fixed"
    assert not OS.missing(new)
    p.unlink(); auto_rig.own_joints_file(v, t, str(p))                         # fresh detection: SOMA spine split
    fresh = json.loads(p.read_text())
    assert not OS.missing(fresh) and abs(fresh["Spine"][2] - (j["Hips"][2] + OS.SPINE_SPLIT[0] * (j["Neck"][2] - j["Hips"][2]))) < 1e-4


def test_character_without_template_or_walk(tmp_path):
    """A character with only Kimodo actions and no Mixamo file is valid now (character.py builds the own skeleton)."""
    C = json.load(open(os.path.join(ROOT, "examples", "character.example.json"), encoding="utf-8"))
    C["rig_config"] = os.path.join(ROOT, "examples", C["rig_config"])
    for k in ("walk_clip", "auto_rig_template"): del C[k]
    C["actions"] = {"attack": {"ai": "attack.json"}}
    (tmp_path / "character.json").write_text(json.dumps(C))
    assert "skeleton" not in schema_check.load_character(str(tmp_path / "character.json"))
    C["skeleton"] = "amts"; (tmp_path / "character.json").write_text(json.dumps(C))
    assert schema_check.load_character(str(tmp_path / "character.json"))["skeleton"] == "amts"


if __name__ == "__main__":
    import tempfile, pathlib
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(pathlib.Path(tempfile.mkdtemp())) if "tmp_path" in fn.__code__.co_varnames else fn(); print("ok", name)
