"""auto_rig.solve on a synthetic humanoid (boxes in a T pose, facing -Y, Z up, character's left = +X), no Blender.
python -m pytest tests  (or: python tests/test_auto_rig.py)"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "rig"))
import auto_rig

H = 1.8
CROTCH, ARM_LO, ARM_HI = 0.85, 1.33, 1.43


def box(lo, hi, step=0.02):
    """Closed surface of an axis-aligned box as a triangle grid (vertices every ~2 cm, like a decimated scan)."""
    lo, hi = np.array(lo, float), np.array(hi, float); V, T = [], []
    for ax in range(3):
        u, v = [a for a in range(3) if a != ax]
        nu, nv = (max(1, int(np.ceil((hi[k] - lo[k]) / step))) for k in (u, v))
        for side in (lo[ax], hi[ax]):
            g = np.zeros(((nu + 1) * (nv + 1), 3)); g[:, ax] = side
            uu, vv = np.meshgrid(np.linspace(lo[u], hi[u], nu + 1), np.linspace(lo[v], hi[v], nv + 1), indexing="ij")
            g[:, u], g[:, v] = uu.ravel(), vv.ravel()
            i = np.arange(nu * (nv + 1)).reshape(nu, nv + 1)[:, :nv].ravel() + sum(len(x) for x in V)
            T += [np.stack([i, i + nv + 1, i + 1], 1), np.stack([i + 1, i + nv + 1, i + nv + 2], 1)]
            V.append(g)
    return np.vstack(V), np.vstack(T)


def mesh(parts):
    V, T, n = [], [], 0
    for lo, hi in parts:
        v, t = box(lo, hi); V.append(v); T.append(t + n); n += len(v)
    return np.vstack(V), np.vstack(T)


def humanoid(robe=False, kneecap=None, palm=False, extra=(), arm_end=0.85):
    parts = list(extra) + [((-0.20, -0.10, CROTCH), (0.20, 0.10, 1.45)),            # torso
             ((-0.05, -0.05, 1.45), (0.05, 0.05, 1.55)),              # neck
             ((-0.10, -0.12, 1.55), (0.10, 0.10, H))]                 # head
    for s in (1, -1):
        x = sorted((s * 0.20, s * arm_end)); parts.append(((x[0], -0.05, ARM_LO), (x[1], 0.05, ARM_HI)))   # arm
        x = sorted((s * 0.85, s * 0.95))
        z = (1.30, 1.46) if palm else (1.35, 1.41)
        parts.append(((x[0], -0.04, z[0]), (x[1], 0.04, z[1])))                                          # hand
        if palm:
            x = sorted((s * 0.95, s * 1.02)); parts.append(((x[0], -0.01, 1.37), (x[1], 0.01, 1.39)))    # finger
        x = sorted((s * 0.06, s * 0.18))
        if not robe: parts.append(((x[0], -0.07, 0.0), (x[1], 0.07, CROTCH)))                         # leg
        if kneecap: parts.append(((x[0] + 0.03, -0.12, kneecap - 0.01), (x[1] - 0.03, -0.07, kneecap + 0.01)))
        parts.append(((x[0], -0.20, 0.0), (x[1], 0.07, 0.08)))                                          # foot
    if robe: parts.append(((-0.25, -0.12, 0.08), (0.25, 0.12, CROTCH)))                                 # robe to the feet
    return mesh(parts)


def mirrored(j, name, tol=0.02 * H):
    l, r = j["Left" + name], j["Right" + name]
    return abs(l[0] + r[0]) < tol and abs(l[2] - r[2]) < tol and l[0] > 0 > r[0]


def test_legs_apart():
    j, f = auto_rig.solve(*humanoid())
    assert not f["robe"] and abs(f["crotch_z"] - CROTCH) < 0.02 * H
    for n in ("Arm", "ForeArm", "Hand", "Shoulder", "UpLeg", "Leg", "Foot", "ToeBase"):
        assert mirrored(j, n), n
    hips = j["Hips"][2]
    assert CROTCH < hips < ARM_LO and abs(j["Hips"][0]) < 1e-6
    assert j["Hips"][2] < j["Spine"][2] < j["Spine1"][2] < j["Spine2"][2] < j["Neck"][2] < j["Head"][2] < j["HeadTop_End"][2]
    for s in ("Left", "Right"):
        sgn = 1 if s == "Left" else -1
        foot, knee = j[s + "Foot"], j[s + "Leg"]
        assert foot[2] < knee[2] < hips and 0.06 <= sgn * knee[0] <= 0.18      # knee inside its own leg
        arm, elbow, hand, tip = j[s + "Arm"], j[s + "ForeArm"], j[s + "Hand"], j[s + "Tip"]
        assert ARM_LO <= arm[2] <= ARM_HI and ARM_LO <= hand[2] <= ARM_HI
        assert sgn * arm[0] < sgn * elbow[0] < sgn * hand[0] < sgn * tip[0]
        assert np.linalg.norm(tip - hand) < 0.2 * H and abs(tip[0]) > 0.94    # wrist towards the fingertip


def test_knee_from_contour():
    j, f = auto_rig.solve(*humanoid())          # a straight column: no kneecap, SOMA's fraction
    assert f["knee_from"] == "SOMA"
    soma = j["LeftLeg"][2]
    j, f = auto_rig.solve(*humanoid(kneecap=0.58))
    assert f["knee_from"] == "contour" and abs(soma - 0.58) > 0.03 * H
    for s in ("Left", "Right"):
        assert abs(j[s + "Leg"][2] - 0.58) < 0.01 * H, j[s + "Leg"]


def test_knee_among_bulges_behind_a_tabard():
    """Armour: a bulge at the greave's top under the poleyn, and a tabard hanging in front of both thighs whose hem the
    leg gap ends at. The knee is the poleyn: the bulge nearest SOMA's knee, at its apex, above the hem."""
    j, _ = auto_rig.solve(*humanoid())
    soma = j["LeftLeg"][2]
    poleyn, greave, hem = soma + 0.04, soma - 0.12, soma - 0.03
    extra = []
    for s in (1, -1):
        x = sorted((s * 0.09, s * 0.15))
        extra += [((x[0], -0.12, poleyn - 0.01), (x[1], -0.07, poleyn + 0.01)),
                  ((x[0], -0.11, greave - 0.01), (x[1], -0.07, greave + 0.01))]
    extra.append(((-0.20, -0.20, hem), (0.20, -0.17, CROTCH)))          # tabard, 5 cm in front of the poleyns
    j, f = auto_rig.solve(*humanoid(extra=extra))
    for s in ("Left", "Right"):
        assert abs(j[s + "Leg"][2] - poleyn) < 0.01 * H, (j[s + "Leg"], poleyn)
        assert 0.06 <= abs(j[s + "Leg"][0]) <= 0.18                      # inside its leg, not on the tabard
    assert f["knee_from"] == "contour" and f["crotch_z"] < poleyn and not f["crotch_real"]


def test_wrist_at_the_neck_after_a_cuff():
    """A gauntlet: the forearm ends in a cuff 1.4x the arm, a short neck half the cuff, then a mitten 1.4x the neck (not
    the 1.5x of a bare hand). The wrist is at the start of the neck, not inside the cuff or in the mitten."""
    extra = []
    for s in (1, -1):
        for a, b, h, w in ((0.62, 0.72, 0.07, 0.07), (0.72, 0.75, 0.035, 0.03), (0.75, 0.95, 0.048, 0.04)):
            x = sorted((s * a, s * b)); extra.append(((x[0], -w, 1.38 - h), (x[1], w, 1.38 + h)))
    j, _ = auto_rig.solve(*humanoid(extra=extra, arm_end=0.62))
    for s in ("Left", "Right"):
        assert 0.715 <= abs(j[s + "Hand"][0]) <= 0.75, j[s + "Hand"]      # SOMA's fraction: 0.76, in the mitten


def test_wrist_where_the_hand_widens():
    j, _ = auto_rig.solve(*humanoid(palm=True))     # palm 16 cm tall on an arm 10 cm thick
    for s in ("Left", "Right"):
        assert abs(abs(j[s + "Hand"][0]) - 0.85) < 0.02, j[s + "Hand"]
        assert abs(j[s + "Arm"][0]) < abs(j[s + "ForeArm"][0]) < abs(j[s + "Hand"][0])


def test_robe_without_leg_gap():
    j, f = auto_rig.solve(*humanoid(robe=True))
    assert f["robe"]
    assert f["hips_by_crotch"] is None and abs(j["Hips"][2] - f["hips_by_arm"]) < 1e-9
    for n in ("Arm", "Hand", "UpLeg", "Leg", "Foot"):
        assert mirrored(j, n), n


def test_symmetry_gate():
    """Mirrored L/R joints: the body within 3% of the height, knuckles within 5%; a model off x = 0 is not lopsided."""
    import pytest
    j, _ = auto_rig.solve(*humanoid())
    j = {k: np.asarray(v, float) for k, v in j.items()}
    j.update(LeftHandIndex1=np.array([0.97, -0.03, 1.38]), RightHandIndex1=np.array([-0.97, -0.03, 1.38]))
    a, mid = auto_rig.asymmetry(j)
    assert a[0][0] < 0.01 and abs(mid) < 1e-3
    auto_rig.symmetry_gate(j, H, "x.json")
    moved = {k: v + np.array([0.03, 0.0, 0.0]) for k, v in j.items()}
    assert auto_rig.asymmetry(moved)[0][0][0] < 0.01 and abs(auto_rig.asymmetry(moved)[1] - 0.03) < 1e-3
    elbow = dict(j, LeftForeArm=j["LeftForeArm"] + np.array([0.0, 0.09, 0.0]))     # Kusznik: elbow on the crossbow's layer
    with pytest.raises(SystemExit, match=r"Left/RightForeArm 9\.\d cm \(limit 5\.4\).*x\.json"):
        auto_rig.symmetry_gate(elbow, H, "x.json")
    auto_rig.symmetry_gate(elbow, H, "x.json", allow=True)
    auto_rig.symmetry_gate(dict(j, LeftHandIndex1=j["LeftHandIndex1"] + np.array([0.0, 0.08, 0.0])), H, "x.json")
    with pytest.raises(SystemExit, match="Left/RightHandIndex1"):
        auto_rig.symmetry_gate(dict(j, LeftHandIndex1=j["LeftHandIndex1"] + np.array([0.0, 0.1, 0.0])), H, "x.json")


def test_template_layout():
    """Without a template the spine split and the clavicles are SOMA's (own_skeleton); with one they come from that
    template's own joints, scaled onto the detected body, and nothing else moves."""
    import own_skeleton as OS
    j, _ = auto_rig.solve(*humanoid())
    hips, neck = j["Hips"], j["Neck"]
    for k, t in zip(("Spine", "Spine1", "Spine2"), OS.SPINE_SPLIT):
        assert np.allclose(j[k], hips + t * (neck - hips))
    T = {k: np.array(v, float) for k, v in {
        "Hips": [0, 0, 1.0], "Neck": [0, 0.02, 1.5], "Spine": [0, 0, 1.1], "Spine1": [0, 0.01, 1.2], "Spine2": [0, 0.01, 1.35],
        "LeftArm": [0.18, 0.02, 1.42], "RightArm": [-0.18, 0.02, 1.42],
        "LeftShoulder": [0.06, 0.01, 1.43], "RightShoulder": [-0.06, 0.01, 1.43]}.items()}
    lay = auto_rig.template_layout(T)
    d = T["Neck"] - T["Hips"]
    assert np.allclose(lay["spine"], [(T[k] - T["Hips"]) @ d / (d @ d) for k in ("Spine", "Spine1", "Spine2")])
    assert abs(lay["clavicle_x"] - 1 / 3) < 1e-9
    k = auto_rig.apply_layout(j, lay)
    L = np.linalg.norm(neck - hips)
    assert np.allclose(k["Spine1"], hips + lay["spine"][1] * (neck - hips))
    for s in ("Left", "Right"):
        assert abs(k[s + "Shoulder"][0] - j[s + "Arm"][0] / 3) < 1e-9
        assert abs(k[s + "Shoulder"][2] - (j[s + "Arm"][2] + 0.01 / np.linalg.norm(d) * L)) < 1e-9
        assert abs(k[s + "Shoulder"][1] - k["Spine2"][1]) < 1e-9
    assert all(np.allclose(k[n], j[n]) for n in j if "Spine" not in n and "Shoulder" not in n)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
