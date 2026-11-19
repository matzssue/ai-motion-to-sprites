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


def humanoid(robe=False):
    parts = [((-0.20, -0.10, CROTCH), (0.20, 0.10, 1.45)),            # torso
             ((-0.05, -0.05, 1.45), (0.05, 0.05, 1.55)),              # neck
             ((-0.10, -0.12, 1.55), (0.10, 0.10, H))]                 # head
    for s in (1, -1):
        x = sorted((s * 0.20, s * 0.85)); parts.append(((x[0], -0.05, ARM_LO), (x[1], 0.05, ARM_HI)))   # arm
        x = sorted((s * 0.85, s * 0.95)); parts.append(((x[0], -0.04, 1.35), (x[1], 0.04, 1.41)))       # hand
        x = sorted((s * 0.06, s * 0.18))
        if not robe: parts.append(((x[0], -0.07, 0.0), (x[1], 0.07, CROTCH)))                         # leg
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


def test_robe_without_leg_gap():
    j, f = auto_rig.solve(*humanoid(robe=True))
    assert f["robe"]
    assert f["hips_by_crotch"] is None and abs(j["Hips"][2] - f["hips_by_arm"]) < 1e-9
    for n in ("Arm", "Hand", "UpLeg", "Leg", "Foot"):
        assert mirrored(j, n), n


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
