"""Upper body from the key poses and the head on the facing direction (pipeline/lib/pose_track.py): the rules on plain
numbers, the motion file keys in the schema, and the playbook index (docs/motions/).
python -m pytest tests  (or: python tests/test_pose_track.py)"""
import json, os, sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for d in ("tools", os.path.join("pipeline", "lib")): sys.path.insert(0, os.path.join(ROOT, d))
import motions_index as MI
import pose_track as PT
import schema_check

EXAMPLE = os.path.join(ROOT, "examples", "one_handed_attack.example.json")
FACING = np.array([0.0, -1.0, 0.0])


def quat(axis, deg):
    a = np.radians(deg) / 2; return np.concatenate([[np.cos(a)], np.sin(a) * np.asarray(axis, float)])


def test_hermite_passes_through_the_keys_with_flat_ends():
    x, y = [0, 8, 14, 20, 38], [0.0, 1.0, 3.0, -2.0, 0.5]
    assert np.allclose(PT.hermite(x, y, x), y)
    assert abs(PT.hermite(x, y, [0.01])[0] - y[0]) < 1e-4 and abs(PT.hermite(x, y, [37.99])[0] - y[-1]) < 1e-4   # no speed at the ends
    two = PT.hermite(x, np.stack([y, y], 1), [3.0, 11.0])
    assert two.shape == (2, 2) and np.allclose(two[:, 0], two[:, 1])


def test_hermite_does_not_brake_at_a_key_and_tangents_scale_it():
    x, y = [0, 10, 20, 30], [0.0, 1.0, 2.0, 3.0]                      # a steady move through the keys 10 and 20
    v = lambda sc: (PT.hermite(x, y, [20.5], sc)[0] - PT.hermite(x, y, [19.5], sc)[0])   # noqa: E731  speed through key 20
    assert abs(v(None) - 0.1) < 5e-3                                  # Catmull-Rom: the keys' own speed, not zero
    assert v({20: 1.6}) > 1.4 * v(None) and v({20: 0.25}) < 0.4 * v(None)
    assert abs(PT.hermite(x, y, [20.0], {20: 0.25})[0] - 2.0) < 1e-12  # the key itself stays


def test_track_closes_a_loop_on_the_first_pose_or_holds_the_last():
    keys = [0, 8, 14]; qs = [quat([0, 1, 0], 0), quat([0, 1, 0], 60), quat([0, 1, 0], 120)]; t = PT.key_times(0, 20.0)
    loop = PT.track(keys, qs, 20.0, t)
    assert np.allclose(np.linalg.norm(loop, axis=1), 1) and np.allclose(loop[[0, 8, 14]], qs) and np.allclose(loop[20], qs[0])
    held = PT.track(keys, qs, 20.0, t, loop=False)
    assert np.allclose(held[14:], qs[2]) and np.allclose(held[[0, 8]], qs[:2])                 # no way back to the first pose
    assert np.allclose(PT.track(keys, qs, 14.0, PT.key_times(0, 14.0))[-1], qs[2])       # a last key on the last frame: nothing added


def test_track_keeps_neighbours_in_one_hemisphere():
    qs = [quat([0, 1, 0], 10), -quat([0, 1, 0], 20), quat([0, 1, 0], 30)]               # the same turn stored with the other sign
    mid = PT.track([0, 10, 20], qs, 20.0, [5.0, 15.0], loop=False)
    ang = np.degrees(2 * np.arccos(np.abs(mid[:, 0])))
    assert 10 < ang[0] < 20 < ang[1] < 30                                               # not through the far side of the sphere


def test_key_times_end_on_the_clips_own_last_key():
    assert PT.key_times(0, 55.0) == list(range(56))
    assert PT.key_times(0, 55.2) == list(range(56)) + [55.2]                            # 30 fps keys in a 24 fps scene


def test_head_direction_and_target():
    f, u = PT.direction(0, 0, FACING); assert np.allclose(f, FACING) and np.allclose(u, [0, 0, 1])
    f, u = PT.direction(90, 0, FACING); assert np.allclose(f, [1, 0, 0])                # yaw + = the character's left
    f, u = PT.direction(0, 30, FACING); assert abs(f[2] + 0.5) < 1e-9 and abs(f @ u) < 1e-12 and u[2] > 0   # pitch + = down, no roll
    assert PT.head_target("lock", 38, -4, 38, -4, 10) == (0.0, 3.0, False)
    assert PT.head_target("keep", 65, 9, 33, 0, 10, keep=0.35)[:2] == (0.35 * 32, 3.0 + 0.35 * 9)
    assert PT.head_target("keep", 33, 0, 33, 0, 10, keep=0.35) == (0.0, 3.0, False)     # the first frame faces forward
    assert PT.head_target("lock", 0, 0, 0, 0, -80) == (-10.0, 3.0, True)                # the chest turned 80: the head lags 70 behind
    assert PT.head_target("lock", 0, 0, 0, 0, 75, chest_max=60) == (15.0, 3.0, True)


def test_motion_file_marks_the_action():
    M = json.load(open(EXAMPLE, encoding="utf-8"))
    assert schema_check.problems(M, "motion") == [] and "upper_body" in M and M["head"]["mode"] == "lock"
    assert set(map(int, M["upper_body"]["tangents"])) <= set(M["key_poses"].values())   # tangents sit on key frames
    assert not set(map(int, M["upper_body"]["breakdowns"])) & set(M["key_poses"].values())
    M["upper_body"]["tangents"]["x"] = 1; M["upper_body"]["breakdowns"]["17"] = {}; M["head"] = {"mode": "forward", "keep": 2}
    p = "\n".join(schema_check.problems(M, "motion"))
    for bit in ("$.upper_body.tangents", "$.upper_body.breakdowns.17", "$.head.mode", "$.head.keep"): assert bit in p, (bit, p)


def test_playbook_index_is_fresh_and_every_playbook_has_its_header():
    P = MI.playbooks()
    assert "one_handed_weapon_attack" in P
    for n, h in P.items(): assert all(h[f] for f in MI.FIELDS), n
    assert open(MI.INDEX, encoding="utf-8").read() == MI.index(), "run python tools/motions_index.py"
    for p in [MI.INDEX] + [os.path.join(MI.MOTIONS, n + ".md") for n in P]:
        assert len(open(p, encoding="utf-8").read().splitlines()) <= 350, p


def test_playbook_header_problems_are_named(tmp_path):
    def problem(text):
        p = tmp_path / "x.md"; p.write_text(text, encoding="utf-8")
        try: MI.header(str(p))
        except ValueError as e: return str(e)
        return None
    good = "# A motion\n\nUse when: a\nNot for: n\nRoute: b\n  more of b\n\n## Body\n"
    assert problem(good) is None and MI.header(str(tmp_path / "x.md"))["Route"] == "b more of b"
    assert "needs, in this order" in problem(good.replace("Route: b\n  more of b\n", ""))
    assert "title" in problem("Use when: a\n")


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(Path(tempfile.mkdtemp())) if f.__code__.co_argcount else f(); print("ok", n)
