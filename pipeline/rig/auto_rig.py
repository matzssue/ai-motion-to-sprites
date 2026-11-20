"""Auto-rig: skeleton + skin weights from the mesh silhouette.
python pipeline/rig/auto_rig.py --src=<x>_for_rig.fbx --out=rig_base.fbx      # own skeleton (skeletons/amts.json)
python pipeline/rig/auto_rig.py --src=... --out=... --template=<any Mixamo FBX with the standard skeleton>
    # Mixamo-compatible `mixamorig:*` names; hierarchy, rest orientations and finger bones come from that FBX
python pipeline/rig/auto_rig.py --bench --mesh-dir=<npz> --gt-dir=<json>   # against rigs made by Mixamo
Joints (numpy/scipy/PIL) -> skeleton and weights in Blender (`auto_rig_blender.py`). Joints land in `<out>_joints.json`
(editable by hand; an existing file is reused).

Joints file: {key: [x, y, z]} in world metres, keys of `solve` (Hips, Spine..Spine2, Neck, Head, HeadTop_End, <Side>Shoulder,
Arm, ForeArm, Hand, Tip, UpLeg, Leg, Foot, ToeBase, Toe_End). The own skeleton also reads <Side>Hand<Finger>1..4 (knuckle ..
tip, Finger = Thumb, Index, Middle, Ring, Pinky); keys starting with `_` are comments. Another detector plugs in by writing
this file before the run: missing finger keys are then placed from the mesh (hand_fingers.py), nothing else is changed.
Without a template the spine split and the clavicle start of a fresh detection come from SOMA proportions
(own_skeleton.own_joints), not from the Mixamo-measured SPINE_T / Shoulder rule below."""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from config import BLENDER, script_path
import hand_fingers
import own_skeleton

RES = 512  # pixels per character height

# Mixamo proportions measured on 18 rigs (--bench prints them). Mixamo places the spine and clavicle RIGIDLY:
# Spine/Spine1/Spine2 = 0.2/0.433/0.7 of Hips->Neck, Shoulder.x = Arm.x/3 - identical to a thousandth on all of them.
SPINE_T = (0.2, 0.433, 0.7)
CAL = {
    "hips_above_crotch": 0.172,  # Hips.z - crotch, fraction of H
    "hips_t": 0.666,             # Hips on ankle->Arm (when the crotch is hidden: robe, loincloth)
    "upleg_x": 0.834,            # UpLeg.x / Leg.x
    "upleg_down": 0.13,          # UpLeg below Hips, fraction of Hips->knee
    "knee_t": 0.448,             # knee: fraction of ankle->Hips (from the ankle)
    "ankle_z": 0.072,            # Foot.z above the floor, fraction of H
    "arm_in": 0.0,               # Arm.x relative to the armpit, fraction of H
    "arm_t": 0.65,               # Arm.z: fraction of armpit->shoulder top
    "arm_up": 0.139,             # Arm.z above the armpit when the shoulder top cannot be measured
    "arm_depth": 0.61,           # Arm.y: fraction of torso depth from the front, at armpit height
    "wrist_t": 0.678,            # Hand: fraction of Arm->fingertip
    "elbow_t": 0.477,            # ForeArm: fraction of Arm->Hand
    "neck_above_arm": 0.043,     # Neck.z above Arm.z, fraction of H
    "head_above_neck": 0.037,
    "head_to_snout": 0.06,       # Head.y: fraction of the way neck -> snout tip
    "toe_base_t": 0.639,         # ToeBase: fraction of ankle->toe tip (in Y)
}


# ---------------------------------------------------------------- 2D silhouettes
class Silhouette:
    """Silhouette of the mesh projected on a plane (axis a = horizontal, axis b = vertical Z)."""

    def __init__(self, verts, tris, a, b, px):
        self.a, self.b, self.px = a, b, px
        lo = verts[:, [a, b]].min(0) - 4 * px
        hi = verts[:, [a, b]].max(0) + 4 * px
        self.lo = lo
        w, h = np.ceil((hi - lo) / px).astype(int) + 1
        img = Image.new("1", (w, h), 0)
        draw = ImageDraw.Draw(img)
        uv = (verts[:, [a, b]] - lo) / px
        uv[:, 1] = h - 1 - uv[:, 1]
        for t in tris:
            draw.polygon([tuple(uv[i]) for i in t], fill=1, outline=1)
        mask = np.array(img, dtype=bool)
        self.mask = ndimage.binary_fill_holes(ndimage.binary_closing(mask, iterations=2))
        self.h = h

    def to_px(self, u, z):
        return int(round((u - self.lo[0]) / self.px)), int(round(self.h - 1 - (z - self.lo[1]) / self.px))

    def to_world(self, col, row):
        return self.lo[0] + col * self.px, self.lo[1] + (self.h - 1 - row) * self.px

    def runs(self, z):
        """Filled spans in the row at height z -> [(u0, u1), ...] in world units."""
        _, row = self.to_px(0.0, z)
        line = self.mask[min(max(row, 0), self.mask.shape[0] - 1)]
        edges = np.diff(np.concatenate([[0], line.astype(np.int8), [0]]))
        starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0] - 1
        return [(self.to_world(s, row)[0], self.to_world(e, row)[0]) for s, e in zip(starts, ends)]

    def outside(self):
        """Background connected to the image border (holes inside the silhouette drop out)."""
        lab, _ = ndimage.label(~self.mask)
        border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
        return np.isin(lab, list(border - {0}))


def run_at(runs, u):
    for r in runs:
        if r[0] <= u <= r[1]:
            return r
    return None


def slab_center(verts, x, z, radius, axis_y=1):
    """Middle of body thickness in Y around the point (x, z) of the front projection."""
    near = verts[(np.abs(verts[:, 0] - x) < radius) & (np.abs(verts[:, 2] - z) < radius)]
    if len(near) < 4:
        return None
    return 0.5 * (near[:, axis_y].min() + near[:, axis_y].max())


# ---------------------------------------------------------------- detection
def detect(verts, tris):
    """Features from geometry (crotch, armpits, fingertips, feet, neck) -> joints."""
    zmin, zmax = verts[:, 2].min(), verts[:, 2].max()
    H = zmax - zmin
    px = H / RES
    front = Silhouette(verts, tris, 0, 2, px)
    feat = {"zmin": zmin, "zmax": zmax, "H": H}
    out = front.outside()
    rows_n, cols_n = out.shape

    # --- crotch: the highest "outside" background pixel in a narrow central band. A loincloth between the legs
    # does not fool it: the gaps on its sides reach up to the crotch.
    c0, _ = front.to_px(-0.04 * H, 0)
    c1, _ = front.to_px(0.04 * H, 0)
    r_mid = front.to_px(0, zmin + 0.75 * H)[1]
    band = out[r_mid:, c0:c1 + 1]
    hit = np.argwhere(band)
    crotch_z, robe = None, False
    if len(hit):
        crotch_z = front.to_world(0, r_mid + hit[:, 0].min())[1]
        below = front.runs(crotch_z - 3 * px)
        above = run_at(front.runs(crotch_z + 3 * px), 0.0) or run_at(front.runs(crotch_z + 6 * px), 0.0)
        legs = [r for r in below if abs(0.5 * (r[0] + r[1])) < 0.35 * H]
        if above and len(legs) >= 2:
            extent = max(r[1] for r in legs) - min(r[0] for r in legs)
            robe = (above[1] - above[0]) > 1.25 * extent
        if crotch_z < zmin + 0.25 * H:
            robe = True  # a gap barely above the ankles = the hem of a robe
    else:
        robe = True
    feat["crotch_z"], feat["robe"] = crotch_z, robe

    # --- fingertips: extreme vertices in X (auto-riggers require an A/T pose)
    tipL = verts[verts[:, 0].argmax()]
    tipR = verts[verts[:, 0].argmin()]
    # A prop on the back (crossbow) sticks out sideways higher than the hand. When the tips differ in height by >10% H,
    # the higher one is the prop: look for the hand on that side at the height of the lower tip.
    if abs(tipL[2] - tipR[2]) > 0.10 * H:
        good, sgn = (tipR, 1) if tipL[2] > tipR[2] else (tipL, -1)
        band = verts[(np.abs(verts[:, 2] - good[2]) < 0.10 * H) & (sgn * verts[:, 0] > 0)]
        alt = band[(sgn * band[:, 0]).argmax()]
        if sgn > 0:
            tipL = alt
        else:
            tipR = alt
        feat["prop_tip"] = "Left" if sgn > 0 else "Right"

    # --- armpits: a "pocket" of background under the arm (window from the centre to the tip, from 0.12 H below the tip up),
    # the component containing a point just under the hand. Armpit = its top. Gaps between fingers/claws connect the pocket
    # to the background ABOVE the arm, so search in a silhouette closed by ~1.5% H, and the window ends at 85% of hand reach.
    closed = ndimage.binary_closing(front.mask, structure=np.ones((3, 3)), iterations=max(1, int(0.015 * RES)))
    lab_o, _ = ndimage.label(~closed)
    border = set(np.unique(np.concatenate([lab_o[0], lab_o[-1], lab_o[:, 0], lab_o[:, -1]])))
    out_c = np.isin(lab_o, list(border - {0}))
    arm_pits = {}
    for side, tip in (("Left", tipL), ("Right", tipR)):
        sgn = 1 if side == "Left" else -1
        ca, _ = front.to_px(0.0, 0)
        cb, _ = front.to_px(0.85 * tip[0], 0)
        lo_c, hi_c = sorted((ca, cb))
        r_cut = front.to_px(0, tip[2] - 0.12 * H)[1]
        win = np.zeros_like(out_c)
        win[:r_cut + 1, lo_c:hi_c + 1] = out_c[:r_cut + 1, lo_c:hi_c + 1]
        lab, _ = ndimage.label(win)
        sc, sr = front.to_px(0.85 * tip[0] - sgn * 2 * px, tip[2])
        sr = min(max(sr, 0), rows_n - 1)
        while sr < r_cut and not win[sr, sc]:
            sr += 1
        label = lab[sr, sc] if sr <= r_cut else 0
        if not label:
            arm_pits[side] = None
            continue
        # Underside of the arm column by column; armpit = the INNERMOST column whose underside is within 3% H of the highest.
        # In a T-pose the underside is flat along its whole length and the plain top landed at the wrist.
        pocket = np.argwhere(lab == label)
        cols = np.unique(pocket[:, 1])
        tops = np.array([pocket[pocket[:, 1] == c][:, 0].min() for c in cols])
        near = cols[tops <= tops.min() + 0.03 * RES]
        c = near[np.abs(near - ca).argmin()]
        r = tops[cols == c][0]
        x, z = front.to_world(c, r)
        # shoulder top: up from the armpit, across gaps shorter than 4% H
        column = closed[:r, c]
        filled = np.where(column)[0]
        top_r = r
        for rr in filled[::-1]:
            if top_r - rr > 0.04 * RES:
                break
            top_r = rr
        arm_pits[side] = np.array([x, z, front.to_world(c, top_r)[1]])
    feat["armpits"] = arm_pits
    feat["tips"] = {"Left": tipL, "Right": tipR}
    feat["front"] = front
    return feat


def centerline_point(front, verts, a, b, t, H):
    """Point on the arm axis: fraction t of a->b, centred across the silhouette."""
    p = a + t * (b - a)
    d = (b - a) / (np.linalg.norm(b - a) + 1e-9)
    n = np.array([-d[1], d[0]])
    lo = hi = 0.0
    step = front.px

    def filled(q):
        c, r = front.to_px(q[0], q[1])
        return 0 <= r < front.mask.shape[0] and 0 <= c < front.mask.shape[1] and front.mask[r, c]
    if filled(p):
        while filled(p + (hi + step) * n) and hi < 0.3 * H:
            hi += step
        while filled(p - (lo + step) * n) and lo < 0.3 * H:
            lo += step
        p = p + 0.5 * (hi - lo) * n
    return p


def solve(verts, tris):
    f = detect(verts, tris)
    H, zmin = f["H"], f["zmin"]
    j = {}

    def at_y(x, z, r=0.03):
        y = slab_center(verts, x, z, r * H)
        return y if y is not None else 0.0

    # ---- arms
    for side in ("Left", "Right"):
        sgn = 1 if side == "Left" else -1
        tip = f["tips"][side]
        pit = f["armpits"][side]
        if pit is None:
            pit = np.array([sgn * 0.12 * H, zmin + 0.7 * H])
        thick = pit[2] - pit[1] if len(pit) > 2 else 0.0
        up = CAL["arm_t"] * thick if 0.04 * H < thick < 0.4 * H else CAL["arm_up"] * H
        arm = np.array([pit[0] - sgn * CAL["arm_in"] * H, pit[1] + up])
        tip2 = np.array([tip[0], tip[2]])
        hand = centerline_point(f["front"], verts, arm, tip2, CAL["wrist_t"], H)
        elbow = centerline_point(f["front"], verts, arm, hand, CAL["elbow_t"], H)
        for name, p in (("Arm", arm), ("ForeArm", elbow), ("Hand", hand)):
            j[side + name] = np.array([p[0], at_y(p[0], p[1]), p[1]])
        # Shoulder: torso depth at ARMPIT height (lower than the head of a hunchback, which hangs in front of the chest
        # and pulled the slab middle ~8% H forward). Mixamo places the joint at 61% of the depth from the front (median of 18).
        torso = verts[(np.abs(verts[:, 0]) < abs(pit[0])) & (np.abs(verts[:, 2] - pit[1]) < 0.02 * H)]
        if len(torso) > 8:
            yf, yb = torso[:, 1].min(), torso[:, 1].max()
            j[side + "Arm"][1] = yf + CAL["arm_depth"] * (yb - yf)
        j[side + "Tip"] = tip

    # A prop above a shoulder pulls that shoulder top up on one side. The body is not made crooked: when the sides
    # differ by >4% H, both come from the clean side (without the prop; without prop knowledge, the lower one).
    la, ra = j["LeftArm"], j["RightArm"]
    if abs(la[2] - ra[2]) > 0.04 * H or abs(la[0] + ra[0]) > 0.04 * H:
        if "prop_tip" in f:
            lo = "Right" if f["prop_tip"] == "Left" else "Left"
        else:
            lo = "Left" if la[2] < ra[2] else "Right"
        hi = "Right" if lo == "Left" else "Left"
        src = j[lo + "Arm"]
        f["prop_arm"] = hi
        j[hi + "Arm"] = np.array([-src[0], src[1], src[2]])
        tip = j[hi + "Tip"]
        tip2 = np.array([tip[0], tip[2]])
        arm2 = np.array([-src[0], src[2]])
        hand = centerline_point(f["front"], verts, arm2, tip2, CAL["wrist_t"], H)
        elbow = centerline_point(f["front"], verts, arm2, hand, CAL["elbow_t"], H)
        for name, p in (("ForeArm", elbow), ("Hand", hand)):
            j[hi + name] = np.array([p[0], at_y(p[0], p[1]), p[1]])

    # ---- torso
    arm_z = 0.5 * (j["LeftArm"][2] + j["RightArm"][2])
    ank_z = zmin + CAL["ankle_z"] * H
    by_arm = ank_z + CAL["hips_t"] * (arm_z - ank_z)
    by_crotch = None
    if f["crotch_z"] is not None and not f["robe"]:
        by_crotch = f["crotch_z"] + CAL["hips_above_crotch"] * H
    f["hips_by_arm"], f["hips_by_crotch"] = by_arm, by_crotch
    if by_crotch is None or by_crotch < by_arm - 0.08 * H:
        hips_z = by_arm  # the gap between the legs ends at the hem of a robe/loincloth
    else:
        hips_z = 0.5 * (by_arm + by_crotch)
    neck_z = arm_z + CAL["neck_above_arm"] * H
    j["Hips"] = np.array([0.0, at_y(0.0, hips_z, 0.06), hips_z])
    # Mixamo runs the spine at shoulder depth (Spine2.y = Shoulder.y = Arm.y on 18 rigs); the slab middle moved
    # a hunchback's neck ~6% H forward.
    arm_y = 0.5 * (j["LeftArm"][1] + j["RightArm"][1])
    j["Neck"] = np.array([0.0, arm_y, neck_z])
    # Head: Mixamo places it almost vertically ABOVE the neck (3.7% H higher, 6% of the way to the snout tip) - the slab
    # middle at that height caught a hunchback's head.
    head_z = neck_z + CAL["head_above_neck"] * H
    face = verts[(np.abs(verts[:, 0]) < 0.08 * H) & (verts[:, 2] > arm_z - 0.12 * H)]
    snout_y = face[:, 1].min() if len(face) else arm_y
    j["Head"] = np.array([0.0, arm_y + CAL["head_to_snout"] * (snout_y - arm_y), head_z])
    j["HeadTop_End"] = np.array([0.0, j["Head"][1], f["zmax"]])
    for name, t in zip(("Spine", "Spine1", "Spine2"), SPINE_T):
        j[name] = j["Hips"] + t * (j["Neck"] - j["Hips"])
    for side in ("Left", "Right"):
        arm = j[side + "Arm"]
        j[side + "Shoulder"] = np.array([arm[0] / 3.0, j["Spine2"][1], arm[2] + 0.015 * H])

    # ---- legs
    for side in ("Left", "Right"):
        sgn = 1 if side == "Left" else -1
        foot_v = verts[(verts[:, 2] < zmin + 0.05 * H) & (sgn * verts[:, 0] > 0)]
        ank_z = zmin + CAL["ankle_z"] * H
        ring = verts[(np.abs(verts[:, 2] - ank_z) < 0.01 * H) & (sgn * verts[:, 0] > 0.01 * H)]
        if len(ring) < 4:
            ring = foot_v
        ax = 0.5 * (ring[:, 0].min() + ring[:, 0].max())
        ay = 0.5 * (ring[:, 1].min() + ring[:, 1].max())
        j[side + "Foot"] = np.array([ax, ay, ank_z])
        tip_y = foot_v[:, 1].min()
        j[side + "Toe_End"] = np.array([ax, tip_y, zmin + 0.01 * H])
        j[side + "ToeBase"] = np.array([ax, ay + CAL["toe_base_t"] * (tip_y - ay), zmin + 0.01 * H])
        knee_z = ank_z + CAL["knee_t"] * (hips_z - ank_z)
        runs = f["front"].runs(knee_z)
        leg = [r for r in runs if sgn * 0.5 * (r[0] + r[1]) > 0]
        kx = ax
        if leg and not f["robe"]:
            r = min(leg, key=lambda r: abs(0.5 * (r[0] + r[1]) - ax))
            kx = 0.5 * (r[0] + r[1])
        j[side + "Leg"] = np.array([kx, at_y(kx, knee_z), knee_z])
        ul_z = hips_z - CAL["upleg_down"] * (hips_z - knee_z)
        j[side + "UpLeg"] = np.array([CAL["upleg_x"] * kx, j["Hips"][1], ul_z])
    return j, f


# ---------------------------------------------------------------- bench
def load_mesh(npz):
    z = np.load(npz)
    return z["verts"], z["tris"]


MAIN = ["Hips", "Spine2", "Neck", "Head", "LeftArm", "LeftForeArm", "LeftHand", "RightArm",
        "RightForeArm", "RightHand", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg",
        "RightLeg", "RightFoot", "LeftToeBase", "RightToeBase"]


def bench(mesh_dir, gt_dir, only=None):
    """Joint error vs Mixamo-made rigs: gt_dir/<name>.json {"rest": {"mixamorig:Bone": [x,y,z]}}, mesh_dir/<name>.npz."""
    errs, report = {}, {}
    for name in sorted(os.listdir(gt_dir)):
        if not name.endswith(".json"):
            continue
        n = name[:-5]
        if only and n not in only:
            continue
        gt = {k.split(":")[1]: np.array(v) for k, v in json.load(open(os.path.join(gt_dir, name)))["rest"].items()}
        verts, tris = load_mesh(os.path.join(mesh_dir, n + ".npz"))
        j, f = solve(verts, tris)
        H = f["H"]
        row = {b: float(np.linalg.norm(j[b] - gt[b]) / H) for b in MAIN}
        report[n] = {"pred": {b: j[b].tolist() for b in j}, "feat": {
            "crotch_z": f["crotch_z"], "robe": bool(f["robe"]),
            "hips_by_arm": f["hips_by_arm"], "hips_by_crotch": f["hips_by_crotch"],
            "armpits": {k: (v.tolist() if v is not None else None) for k, v in f["armpits"].items()}}}
        for b, e in row.items():
            errs.setdefault(b, []).append(e)
        worst = sorted(row.items(), key=lambda kv: -kv[1])[:3]
        print("%-18s mean %4.1f%% H  robe=%d  worst: %s" % (
            n, 100 * np.mean(list(row.values())), f["robe"], ", ".join("%s %.1f%%" % (b, 100 * e) for b, e in worst)))
    print("\nJOINT             median  max   (%% of character height)")
    for b in MAIN:
        print("%-17s %6.1f %6.1f" % (b, 100 * np.median(errs[b]), 100 * np.max(errs[b])))
    print("TOTAL median %.1f%%" % (100 * np.median([e for v in errs.values() for e in v])))
    return report


def rig(src, out, template, joints_path=None, no_fingers=False):
    """FBX for rigging -> rig_base.fbx. Joints land in `joints_path` (JSON, for manual fixes). No template = own skeleton."""
    work = os.path.splitext(out)[0]
    npz = work + "_mesh.npz"
    joints_path = joints_path or work + "_joints.json"
    blend = script_path("auto_rig_blender.py")
    run([BLENDER, "--background", "--python-exit-code", "1", "--python", blend, "--", "export", "--src=" + src, "--out=" + npz])
    verts, tris = load_mesh(npz)
    os.remove(npz)
    if template:
        if os.path.exists(joints_path):
            print("auto_rig: using EXISTING joints from %s (delete the file to detect again)" % joints_path)
        else:
            j, f = solve(verts, tris)
            json.dump({k: [round(float(c), 5) for c in v] for k, v in j.items()}, open(joints_path, "w"), indent=1)
            print("auto_rig: crotch %s, robe=%s" % (f["crotch_z"], f["robe"]))
    else:
        own_joints_file(verts, tris, joints_path)
    cmd = [BLENDER, "--background", "--python-exit-code", "1", "--python", blend, "--",
           "build", "--src=" + src, "--joints=" + joints_path, "--out=" + out]
    if template:
        cmd.insert(-1, "--template=" + template)
    if no_fingers:
        cmd.append("--no-fingers")
    run(cmd)


def own_joints_file(verts, tris, joints_path):
    """Joints of the own skeleton: a fresh detection (`solve` + SOMA spine/clavicle) or an existing file; fingers missing
    in it are placed from the mesh. Written back to `joints_path`."""
    H = float(verts[:, 2].max() - verts[:, 2].min())
    if os.path.exists(joints_path):
        j = {k: v for k, v in json.load(open(joints_path)).items()}
        print("auto_rig: using EXISTING joints from %s (delete the file to detect again)" % joints_path)
    else:
        j, f = solve(verts, tris)
        j = own_skeleton.own_joints(j)
        print("auto_rig: crotch %s, robe=%s" % (f["crotch_z"], f["robe"]))
    fingers = [k for k in own_skeleton.JOINT_KEYS if "Hand" in k and k[-1].isdigit()]
    if any(k not in j for k in fingers):
        fj, rep = hand_fingers.finger_joints(verts, tris, {k: np.asarray(v, float) for k, v in j.items() if not k.startswith("_")}, H)
        for side, r in rep.items():
            print("auto_rig: fingers %s - %s" % (side, r))
        j.update({k: v for k, v in fj.items() if k not in j})
    lost = own_skeleton.missing(j)
    if lost:
        raise SystemExit("auto_rig: %s lacks joints of the own skeleton: %s" % (joints_path, ", ".join(lost)))
    json.dump({k: (v if k.startswith("_") else [round(float(c), 5) for c in v]) for k, v in j.items()},
              open(joints_path, "w"), indent=1)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in r.stdout.splitlines():
        if line.startswith("auto_rig") or "Error" in line or "Traceback" in line:
            print(line)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("auto_rig: Blender returned %d" % r.returncode)


def main():
    ap = argparse.ArgumentParser(description="Auto-rig a generated mesh: own skeleton, or a Mixamo-compatible one from --template.")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--mesh-dir"); ap.add_argument("--gt-dir"); ap.add_argument("--only"); ap.add_argument("--report")
    ap.add_argument("--src", help="FBX prepared for rigging (prepare_for_rigging.py)")
    ap.add_argument("--out", help="output rig_base.fbx")
    ap.add_argument("--joints", help="joints JSON (default next to --out)")
    # The template is the CLIP DUMMY (any Mixamo FBX with the standard skeleton): every bone = its orientation rotated
    # the shortest way onto the new direction (the same relation Mixamo rigs have).
    ap.add_argument("--template", help="Mixamo FBX with the standard 65-bone skeleton (not distributed with this repo); "
                    "without it: the own skeleton (skeletons/amts.json)")
    # With a template fingers do NOT deform by default: finger bones stand from the template, not from the mesh, and when a
    # clip closes the hand they tore the claws (hand 5-11% of edges, without fingers 0.1-0.5%). The own skeleton places
    # them on the mesh, so there they deform unless --no-fingers.
    ap.add_argument("--fingers", action=argparse.BooleanOptionalAction, default=None,
                    help="finger bones deform the mesh (default: yes for the own skeleton, no with --template)")
    a = ap.parse_args()
    if a.bench:
        rep = bench(a.mesh_dir, a.gt_dir, a.only.split(",") if a.only else None)
        if a.report:
            json.dump(rep, open(a.report, "w"))
    elif a.src and a.out:
        fingers = a.fingers if a.fingers is not None else not a.template
        rig(a.src, a.out, a.template, a.joints, not fingers)
    else:
        ap.error("give --src and --out (and --template for a Mixamo skeleton), or --bench")


if __name__ == "__main__":
    main()
