"""Auto-rig: skeleton + skin weights from the mesh silhouette.
python pipeline/rig/auto_rig.py --src=<x>_for_rig.fbx --out=rig_base.fbx      # own skeleton (skeletons/amts.json)
python pipeline/rig/auto_rig.py --src=... --out=... --template=<any Mixamo FBX with the standard skeleton>
    # Mixamo-compatible `mixamorig:*` names; hierarchy, rest orientations and finger bones come from that FBX
Joints (numpy/scipy/PIL) -> skeleton and weights in Blender (`auto_rig_blender.py`). Joints land in `<out>_joints.json`
(editable by hand; an existing file is reused). Before Blender the mirrored L/R joints are checked (`symmetry_gate`).

Joints file: {key: [x, y, z]} in world metres, keys of `solve` (Hips, Spine..Spine2, Neck, Head, HeadTop_End, <Side>Shoulder,
Arm, ForeArm, Hand, Tip, UpLeg, Leg, Foot, ToeBase, Toe_End). The own skeleton also reads <Side>Hand<Finger>1..4 (knuckle ..
tip, Finger = Thumb, Index, Middle, Ring, Pinky); keys starting with `_` are comments. Another detector plugs in by writing
this file before the run: missing finger keys are then placed from the mesh (hand_fingers.py), nothing else is changed.
Sources of every number (no Mixamo rig is used as a source or a check): body proportions of the SOMA77 skeleton
(`SOMA`), joint-to-surface relations from ANSUR II (`HIPS_ABOVE_CROTCH`, `ARM_UP`), the rest from the mesh itself. The
spine split and the clavicle start come from SOMA (own_skeleton.own_joints); with --template from that template's own
layout (`template_layout`), so a `mixamorig:*` rig keeps the skeleton the user's file defines."""
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

# Proportions of the SOMA77 skeleton (`kimodo/assets/skeletons/somaskel77/somaskel77_standard_tpose.bvh`, Kimodo
# repository, Apache-2.0; the skeleton the motion is generated on). Recompute: tools/soma_proportions.py <bvh>.
# H = SOMA's head top (HeadEnd) above the floor; both sides averaged.
SOMA = {
    "hips_z": 0.5685,          # Hips above the floor, fraction of H
    "hips_t": 0.686,           # Hips on ankle -> Arm, by height
    "upleg_down": 0.162,       # UpLeg below Hips, fraction of Hips -> knee
    "knee_t": 0.449,           # knee: fraction of ankle -> Hips (from the ankle)
    "wrist_t": 0.746,          # Hand: fraction of Arm -> middle fingertip
    "arm_len": 0.317,          # Arm -> Hand (upper arm + forearm), fraction of H
    "elbow_t": 0.515,          # ForeArm: fraction of Arm -> Hand
    "neck_above_arm": 0.018,   # Neck (SOMA Neck1, the base of the neck) above Arm, fraction of H
    "head_above_neck": 0.079,  # Head (skull base) above Neck
    "head_forward": 0.024,     # Head in front of Neck (Neck stands at the shoulders' depth: SOMA 0.1% H apart)
    "toe_base_t": 0.672,       # ToeBase: fraction of ankle -> toe tip (in Y)
}
# Joint-to-surface relations: SOMA joint heights against landmarks of ANSUR II (Gordon et al. 2014, "2012 Anthropometric
# Survey of U.S. Army Personnel: Methods and Summary Statistics", NATICK/TR-15/007; summary statistics, printed page numbers; mean of the
# female and male means over stature 162.85 / 175.62 cm, p. 194). The surveyed body is a real adult: a generated character's
# boots, pauldrons or hump are not in it.
# crotch height 78.23 / 84.59 cm (p. 98) = 0.481 of stature: Hips this far above the crotch
HIPS_ABOVE_CROTCH = SOMA["hips_z"] - 0.481
# UpLeg.x: SOMA's hip joints 0.114 H apart over hip breadth (35.38 / 34.57 cm, p. 144) = 0.552 of the body's half-width at
# the hip joints (the thigh does not stand vertical over a generated character's knee: Wybuchacz's knees stand wide)
HIP_PER_BREADTH = 0.552
# Ankle above the floor: lateral malleolus height (6.27 / 7.29 cm, p. 162) over foot length (24.63 / 27.12 cm, p. 116)
ANKLE_PER_FOOT = 0.262
# Arm above the armpit when the shoulder top cannot be measured: half of acromial height (133.51 / 144.07 cm, p. 48) minus
# axilla height (123.90 / 132.91 cm, p. 54) = 0.5 x 0.061 of stature, the middle of the arm's root as with a measured top
ARM_UP = 0.5 * 0.061
# Arm.z: the middle of the arm's root between the armpit and the shoulder top above it (the joint on the limb's axis, as
# the elbow and the wrist are centred across the silhouette). SOMA's joint height against ANSUR's landmarks would give
# 0.88: the pivot at the top of the deltoid, and on a pauldron above it.
ARM_T = 0.5
# Arm.y: fraction of the torso's depth at armpit height from the front - its middle, the mid-axillary line
ARM_DEPTH_T = 0.5
# SOMA's hand, wrist -> middle fingertip: arm_len x (1 / wrist_t - 1), fraction of H
HAND = SOMA["arm_len"] * (1 / SOMA["wrist_t"] - 1)


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


def slab_center_near(verts, x, z, radius, y_ref, gap):
    """slab_center of the one layer in Y nearest y_ref: the slab is split where Y jumps by more than `gap`. Behind
    Kusznik's left elbow lay the crossbow carried on his back; the middle of both put the elbow 8 cm behind the arm."""
    near = verts[(np.abs(verts[:, 0] - x) < radius) & (np.abs(verts[:, 2] - z) < radius)]
    if len(near) < 4:
        return None
    ys = np.sort(near[:, 1]); layers = np.split(ys, np.where(np.diff(ys) > gap)[0] + 1)
    lay = min(layers, key=lambda g: 0.0 if g[0] <= y_ref <= g[-1] else min(abs(g[0] - y_ref), abs(g[-1] - y_ref)))
    return 0.5 * (lay[0] + lay[-1])


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


def across(front, p, d, H):
    """Width of the silhouette across direction d at p, and p centred across it (None, p when p is outside)."""
    n = np.array([-d[1], d[0]])
    lo = hi = 0.0
    step = front.px

    def filled(q):
        c, r = front.to_px(q[0], q[1])
        return 0 <= r < front.mask.shape[0] and 0 <= c < front.mask.shape[1] and front.mask[r, c]
    if not filled(p):
        return None, p
    while filled(p + (hi + step) * n) and hi < 0.3 * H:
        hi += step
    while filled(p - (lo + step) * n) and lo < 0.3 * H:
        lo += step
    return lo + hi, p + 0.5 * (hi - lo) * n


def centerline_point(front, verts, a, b, t, H):
    """Point on the arm axis: fraction t of a->b, centred across the silhouette."""
    d = (b - a) / (np.linalg.norm(b - a) + 1e-9)
    return across(front, a + t * (b - a), d, H)[1]


def wrist_t(arm, tip, H):
    """Wrist as a fraction of Arm -> fingertip: SOMA's, or SOMA's arm length (upper arm + forearm) over the height when that
    ends nearer. A claw or an oversized hand lengthens Arm -> tip, not the arm: Padlinozerca's claws put the wrist at 0.746
    of it inside the hand, the depth of one wrist on a claw layer (sides 7.1 cm apart)."""
    return min(SOMA["wrist_t"], SOMA["arm_len"] * H / max(float(np.linalg.norm(np.asarray(tip) - np.asarray(arm))), 1e-6))


def wrist_on_mesh(front, elbow, tip, H):
    """Wrist at the neck between the forearm and the hand, walking from the elbow to the fingertip:
    - a bare arm widens 1.5x into the hand (palm, spread fingers): the last point of the forearm's narrowest stretch
      before it. SOMA's fraction put the wrist in the palm of Kusznik and Wybuchacz, 5-7 cm past it;
    - a flared cuff (a gauntlet) is 1.5x wider than the neck within 3/4 of SOMA's hand before it, narrows into the
      neck, and the hand widens behind it: the start of the neck. The neck is short (<= 4% H to where the hand
      widens). Flisak's thick forearm tapers 1.2x over that reach and gives none; a neck nearer the fingertip than
      that reach is a gap between fingers (Flisak's, 6% H from the tip).
    None without either: SOMA's fraction stays."""
    L = float(np.linalg.norm(tip - elbow))
    d = (tip - elbow) / max(L, 1e-9)
    prof = [(t, *across(front, elbow + t * L * d, d, H)) for t in np.arange(0.15, 0.95, front.px / max(L, 1e-9))]
    prof = [(t, w, p) for t, w, p in prof if w is not None]
    best, at = None, None
    for t, w, p in prof:                                   # widening into the hand
        if best is not None and w > 1.5 * best:
            if t > 0.2:
                return at
            break
        if best is None or w < best:
            best = w
        if w <= 1.3 * best:
            at = p
    ws, ts = np.array([w for _, w, _ in prof]), np.array([t for t, _, _ in prof])
    reach = 0.75 * HAND * H / L                            # the cuff, and the hand, each about a hand long
    for k in range(1, len(ws)):                            # narrowing out of a cuff
        rise = np.where(ws[k + 1:] > 1.15 * ws[k])[0]
        cuff = ws[:k][ts[:k] >= ts[k] - reach]
        if not len(cuff) or cuff.max() < 1.5 * ws[k] or not len(rise) or ws[k:k + 1 + rise[0]].min() < ws[k] or \
                1 - ts[k] < reach:
            continue
        j = k
        while j > 0 and ws[j - 1] <= 1.1 * ws[k]:
            j -= 1
        return prof[j][2] if (prof[k + 1 + rise[0]][0] - prof[j][0]) * L <= 0.04 * H else None
    return None


def arm_line(front, verts, arm, tip, H):
    """Hand and elbow on the arm in the front view: the wrist from the mesh (SOMA's fraction without a clear hand),
    the elbow at SOMA's fraction of Arm -> wrist."""
    hand = centerline_point(front, verts, arm, tip, wrist_t(arm, tip, H), H)
    elbow = centerline_point(front, verts, arm, hand, SOMA["elbow_t"], H)
    seen = wrist_on_mesh(front, elbow, tip, H)
    if seen is not None:
        hand = seen
        elbow = centerline_point(front, verts, arm, hand, SOMA["elbow_t"], H)
    return hand, elbow


def leg_side(verts, tris, f, foot, hi, sgn):
    """Side silhouette (Y, Z) of one leg: triangles over the x-range of the leg's front-view runs from the ankle up
    to hi. A run that crosses the midline is not a leg (a tabard or a loincloth joins the legs) and is left out."""
    H = f["H"]
    xs = []
    for z in np.arange(foot[2], hi, 0.01 * H):
        leg = [r for r in f["front"].runs(z) if sgn * (r[0] + r[1]) > 0 and r[0] * r[1] > 0]
        if leg:
            xs += min(leg, key=lambda r: abs(0.5 * (r[0] + r[1]) - foot[0]))
    if not xs:
        return None
    c = verts[tris].mean(1)
    keep = (c[:, 0] >= min(xs)) & (c[:, 0] <= max(xs)) & (c[:, 2] < hi + 0.1 * H)
    return Silhouette(verts, tris[keep], 1, 2, f["front"].px) if keep.any() else None


def knee_z(verts, tris, f, foot, hips_z, sgn):
    """Knee height from the leg's side silhouette: where the front edge stands furthest in front of the edge 4% H
    above and below it - the kneecap, a poleyn, or the corner of a bent leg (Padlinozerca's digitigrade leg).
    - The edge is the run that continues the shin row by row from the ankle up, so a tabard or a hem hanging in
      front of the thigh is another run and is not followed.
    - Searched from 0.25 to 0.62 of ankle -> Hips (SOMA's knee is at 0.449), and 2% H under a real crotch (above
      hang Kusznik's loincloth flaps, Flisak's hands on his thighs). A crotch that is a hem (Hips from the arms) caps
      nothing: the knee can be above it.
    - Each bulge of at least 1.5% H is a candidate (the kneecap is 1.8-2.4% H on Kusznik, Wybuchacz, Padlinozerca and
      the knight; Flisak's padded knee is 0.8-1.4% H and lands 1-3 cm under it); bulges closer than 2% H are one;
      the one nearest SOMA's knee wins (armour has a bulge at the greave's top, the poleyn and the cuisse). The knee
      is its apex, the most forward rows within 2% H: the bulge's own peak sits on its lower slope (2-3 cm under the
      knight's poleyn, whose greave recedes sharply below it).
    None (SOMA's fraction) under a robe, without a crotch or without a bulge; `solve` also drops both sides when they
    disagree by more than 1.5% H."""
    if f["robe"] or f["crotch_z"] is None:
        return None
    H = f["H"]
    lo = foot[2] + 0.25 * (hips_z - foot[2])
    hi = foot[2] + 0.62 * (hips_z - foot[2])
    if f["crotch_real"]:
        hi = min(hi, f["crotch_z"] - 0.02 * H)
    side = leg_side(verts, tris, f, foot, hi + 0.05 * H, sgn)
    if side is None:
        return None
    step = side.px
    n, m = int(round(0.04 * H / step)), int(round(0.02 * H / step))
    zs = np.arange(lo - n * step, hi + n * step + 1e-9, step)
    if len(zs) < 2 * n + 3:
        return None
    front, prev = np.full(len(zs), np.nan), None
    for i, z in enumerate(zs):
        runs = side.runs(z)
        if prev is not None:
            runs = [r for r in runs if r[0] <= prev[1] and r[1] >= prev[0]]
        if not runs:
            continue
        if prev is None:
            r = min(runs, key=lambda r: abs(0.5 * (r[0] + r[1]) - foot[1]))
        else:
            r = max(runs, key=lambda r: min(r[1], prev[1]) - max(r[0], prev[0]))
        prev, front[i] = r, r[0]     # the model faces -Y
    ahead = 0.5 * (front[:-2 * n] + front[2 * n:]) - front[n:-n]
    peaks = [k for k in range(1, len(ahead) - 1) if ahead[k] >= 0.015 * H and
             ahead[k] >= np.nanmax(ahead[max(0, k - m):k + m + 1])]
    if not peaks:
        return None
    groups = [[peaks[0]]]
    for k in peaks[1:]:
        if k - groups[-1][-1] <= m:
            groups[-1].append(k)
        else:
            groups.append([k])
    knees = []
    for g in groups:     # the bulge's apex: the most forward rows of the edge within 2% H of it
        c = n + (g[0] + g[-1]) // 2
        w = front[c - m:c + m + 1]
        top = np.where(w <= np.nanmin(w) + 0.5 * step)[0]
        knees.append(float(zs[c - m] + 0.5 * (top[0] + top[-1]) * step))
    soma = foot[2] + SOMA["knee_t"] * (hips_z - foot[2])
    return min(knees, key=lambda z: abs(z - soma))


def solve(verts, tris):
    f = detect(verts, tris)
    H, zmin = f["H"], f["zmin"]
    j = {}

    def at_y(x, z, r=0.03):
        y = slab_center(verts, x, z, r * H)
        return y if y is not None else 0.0

    def limb_y(x, z, y_ref, r=0.03):
        """Depth of an elbow or wrist: the layer of the slab nearest the previous joint (a prop or a strap behind
        or in front of the arm is another layer)."""
        y = slab_center_near(verts, x, z, r * H, y_ref, 0.01 * H)
        return y if y is not None else 0.0

    def arm_depths(side, elbow, hand, tip):
        """Wrist in the layer of the fingertips, elbow in the layer on the shoulder-wrist line: the arm of a hunchback
        hangs 15 cm in front of the shoulder joint, so the layer nearest the shoulder was the crossbow on the back."""
        hy = limb_y(hand[0], hand[1], tip[1])
        sy = j[side + "Arm"][1]
        ey = limb_y(elbow[0], elbow[1], sy + SOMA["elbow_t"] * (hy - sy))
        j[side + "ForeArm"] = np.array([elbow[0], ey, elbow[1]]); j[side + "Hand"] = np.array([hand[0], hy, hand[1]])

    # ---- arms
    for side in ("Left", "Right"):
        sgn = 1 if side == "Left" else -1
        tip = f["tips"][side]
        pit = f["armpits"][side]
        if pit is None:
            pit = np.array([sgn * 0.12 * H, zmin + 0.7 * H])
        thick = pit[2] - pit[1] if len(pit) > 2 else 0.0
        up = ARM_T * thick if 0.04 * H < thick < 0.4 * H else ARM_UP * H
        arm = np.array([pit[0], pit[1] + up])     # straight above the top of the armpit
        tip2 = np.array([tip[0], tip[2]])
        hand, elbow = arm_line(f["front"], verts, arm, tip2, H)
        j[side + "Arm"] = np.array([arm[0], at_y(arm[0], arm[1]), arm[1]])
        # Depth: from the torso at ARMPIT height. The slab middle on the joint itself caught the head of a hunchback
        # hanging in front of the chest (~8% H forward).
        torso = verts[(np.abs(verts[:, 0]) < abs(pit[0])) & (np.abs(verts[:, 2] - pit[1]) < 0.02 * H)]
        if len(torso) > 8:
            yf, yb = torso[:, 1].min(), torso[:, 1].max()
            j[side + "Arm"][1] = yf + ARM_DEPTH_T * (yb - yf)
        arm_depths(side, elbow, hand, tip)
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
        hand, elbow = arm_line(f["front"], verts, arm2, tip2, H)
        arm_depths(hi, elbow, hand, tip)

    # ---- ankles: height from the foot's length (generated boots and big feet stand higher than a body's 3.5% H)
    feet = {}
    for side in ("Left", "Right"):
        sgn = 1 if side == "Left" else -1
        foot_v = verts[(verts[:, 2] < zmin + 0.05 * H) & (sgn * verts[:, 0] > 0)]
        feet[side] = (foot_v, zmin + ANKLE_PER_FOOT * float(foot_v[:, 1].max() - foot_v[:, 1].min()))

    # ---- torso
    arm_z = 0.5 * (j["LeftArm"][2] + j["RightArm"][2])
    ank_z = 0.5 * (feet["Left"][1] + feet["Right"][1])
    by_arm = ank_z + SOMA["hips_t"] * (arm_z - ank_z)
    by_crotch = None
    if f["crotch_z"] is not None and not f["robe"]:
        by_crotch = f["crotch_z"] + HIPS_ABOVE_CROTCH * H
    f["hips_by_arm"], f["hips_by_crotch"] = by_arm, by_crotch
    f["crotch_real"] = by_crotch is not None and by_crotch >= by_arm - 0.08 * H
    if not f["crotch_real"]:
        hips_z = by_arm  # the gap between the legs ends at the hem of a robe/loincloth
    else:
        hips_z = 0.5 * (by_arm + by_crotch)
    neck_z = arm_z + SOMA["neck_above_arm"] * H
    j["Hips"] = np.array([0.0, at_y(0.0, hips_z, 0.06), hips_z])
    # Neck and head from the shoulders, not from the slab middle: that moved a hunchback's neck ~6% H forward and caught
    # the head hanging in front of the chest.
    arm_y = 0.5 * (j["LeftArm"][1] + j["RightArm"][1])
    j["Neck"] = np.array([0.0, arm_y, neck_z])
    head_z = neck_z + SOMA["head_above_neck"] * H
    j["Head"] = np.array([0.0, arm_y - SOMA["head_forward"] * H, head_z])     # the model faces -Y
    j["HeadTop_End"] = np.array([0.0, j["Head"][1], f["zmax"]])
    j.update(own_skeleton.own_joints(j))     # Spine..Spine2 and the clavicles (SOMA); a template replaces them

    # ---- legs
    for side in ("Left", "Right"):
        sgn = 1 if side == "Left" else -1
        foot_v, ank_z = feet[side]
        ring = verts[(np.abs(verts[:, 2] - ank_z) < 0.01 * H) & (sgn * verts[:, 0] > 0.01 * H)]
        if len(ring) < 4:
            ring = foot_v
        ax = 0.5 * (ring[:, 0].min() + ring[:, 0].max())
        ay = 0.5 * (ring[:, 1].min() + ring[:, 1].max())
        j[side + "Foot"] = np.array([ax, ay, ank_z])
        tip_y = foot_v[:, 1].min()
        j[side + "Toe_End"] = np.array([ax, tip_y, zmin + 0.01 * H])
        j[side + "ToeBase"] = np.array([ax, ay + SOMA["toe_base_t"] * (tip_y - ay), zmin + 0.01 * H])
    # one height for both knees (the body is symmetric; a hand on one thigh moves one side's peak)
    seen = [knee_z(verts, tris, f, j[s + "Foot"], hips_z, 1 if s == "Left" else -1) for s in ("Left", "Right")]
    seen = [z for z in seen if z is not None]
    if len(seen) == 2 and abs(seen[0] - seen[1]) > 0.015 * H:
        seen = []
    f["knee_from"] = "contour" if seen else "SOMA"
    for side in ("Left", "Right"):
        sgn = 1 if side == "Left" else -1
        ax, ank_z = j[side + "Foot"][0], j[side + "Foot"][2]
        kz = float(np.mean(seen)) if seen else ank_z + SOMA["knee_t"] * (hips_z - ank_z)
        runs = f["front"].runs(kz)
        leg = [r for r in runs if sgn * 0.5 * (r[0] + r[1]) > 0 and r[0] * r[1] > 0]     # not a tabard over both legs
        kx = ax
        if leg and not f["robe"]:
            r = min(leg, key=lambda r: abs(0.5 * (r[0] + r[1]) - ax))
            kx = 0.5 * (r[0] + r[1])
        j[side + "Leg"] = np.array([kx, at_y(kx, kz), kz])
        ul_z = hips_z - SOMA["upleg_down"] * (hips_z - kz)
        body = run_at(f["front"].runs(ul_z), 0.0)   # the narrower side: a pouch or a quiver at one hip widens the other
        ux = sgn * HIP_PER_BREADTH * min(-body[0], body[1]) if body and body[0] < 0 < body[1] else kx
        j[side + "UpLeg"] = np.array([ux, j["Hips"][1], ul_z])
    return j, f


# ---------------------------------------------------------------- template layout
def template_layout(heads):
    """Spine split and clavicle placement of the template the user supplies ({short bone name: rest head, world}), so a
    `mixamorig:*` rig keeps the layout that file defines: Spine..Spine2 as fractions of Hips -> Neck, each clavicle's
    x as a fraction of its Arm's x from the midline and its y/z offsets from Spine2/Arm in units of Hips -> Neck."""
    h = {k: np.asarray(v, float) for k, v in heads.items()}
    hips, neck = h["Hips"], h["Neck"]
    d = neck - hips; L = float(np.linalg.norm(d))
    out = {"spine": [float((h[k] - hips) @ d) / L ** 2 for k in ("Spine", "Spine1", "Spine2")]}
    mid = hips[0]
    out["clavicle_x"] = float(np.mean([(h[s + "Shoulder"][0] - mid) / (h[s + "Arm"][0] - mid) for s in ("Left", "Right")]))
    out["clavicle_dy"] = float(np.mean([h[s + "Shoulder"][1] - h["Spine2"][1] for s in ("Left", "Right")])) / L
    out["clavicle_dz"] = float(np.mean([h[s + "Shoulder"][2] - h[s + "Arm"][2] for s in ("Left", "Right")])) / L
    return out


def apply_layout(j, lay):
    """Spine..Spine2 and the clavicles of joints `j` placed by a template layout (`template_layout`); returns a new dict."""
    out = {k: np.asarray(v, float) for k, v in j.items()}
    hips, neck = out["Hips"], out["Neck"]
    L = float(np.linalg.norm(neck - hips))
    for k, t in zip(("Spine", "Spine1", "Spine2"), lay["spine"]):
        out[k] = hips + t * (neck - hips)
    for s in ("Left", "Right"):
        arm = out[s + "Arm"]
        out[s + "Shoulder"] = np.array([lay["clavicle_x"] * arm[0], out["Spine2"][1] + lay["clavicle_dy"] * L,
                                        arm[2] + lay["clavicle_dz"] * L])
    return out


# ---------------------------------------------------------------- symmetry
SYM_JOINTS = ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase", "Toe_End") + tuple(
    "Hand%s1" % f.capitalize() for f in own_skeleton.FINGERS)


def asymmetry(j):
    """([(distance m, joint name without the side)] worst first, midline x): left joints against the right ones mirrored in
    the median midline of the pairs (a model 0.9 cm off x = 0 put every Kusznik pair 1.9 cm apart; one broken pair does not
    move the median). Body joints and finger knuckles; fingertips and outer finger joints follow each hand's own pose."""
    pairs = [(n, np.asarray(j["Left" + n], float), np.asarray(j["Right" + n], float))
             for n in SYM_JOINTS if "Left" + n in j and "Right" + n in j]
    if not pairs: return [], 0.0
    mid = float(np.median([0.5 * (L[0] + R[0]) for _, L, R in pairs]))
    out = [(float(np.linalg.norm(L - np.array([2 * mid - R[0], R[1], R[2]]))), n) for n, L, R in pairs]
    return sorted(out, reverse=True), mid


# limits as fractions of the character height (derivation: .claude/skills/ai-motion/AUDIT.md, "Rig symmetry")
ASYM_BODY, ASYM_KNUCKLE = 0.03, 0.05


def symmetry_gate(j, H, where, allow=False):
    """Stops the rig when a mirrored joint pair is further apart than its limit: one side was detected on a prop, a strap
    or a wrong layer (Kusznik's left elbow 9.1 cm off) and no later audit sees it. `allow`: the model is posed asymmetrically."""
    a, mid = asymmetry(j)
    if not a: return
    knuckle = lambda n: n.startswith("Hand") and n != "Hand"
    groups = (("body", [x for x in a if not knuckle(x[1])], ASYM_BODY), ("knuckles", [x for x in a if knuckle(x[1])], ASYM_KNUCKLE))
    print("auto_rig: symmetry (midline x %+.1f cm) %s" % (100 * mid, ", ".join(
        "%s worst %s %.1f cm (limit %.1f)" % (g, x[0][1], 100 * x[0][0], 100 * lim * H) for g, x, lim in groups if x)))
    bad = [(d, n, lim) for _, x, lim in groups for d, n in x if d > lim * H]
    if not bad: return
    text = ", ".join("Left/Right%s %.1f cm (limit %.1f)" % (n, 100 * d, 100 * lim * H) for d, n, lim in bad)
    if allow:
        print("auto_rig: asymmetric pose allowed - %s" % text); return
    raise SystemExit("auto_rig: the rig is lopsided - mirrored joints too far apart: %s. One side was detected on a prop, a strap "
                     "or the wrong body layer. Look at %s; fix the joint by hand (the file is reused) or delete it to detect again, "
                     "give a separate prop as its own mesh (character.json prop_model), or for a model posed asymmetrically pass "
                     "--allow-asymmetry (character.json rig_asymmetric)" % (text, where))


# ---------------------------------------------------------------- run
def load_mesh(npz):
    with np.load(npz) as z:
        return z["verts"], z["tris"]


def rig(src, out, template, joints_path=None, no_fingers=False, allow_asymmetry=False):
    """FBX for rigging -> rig_base.fbx. Joints land in `joints_path` (JSON, for manual fixes). No template = own skeleton."""
    work = os.path.splitext(out)[0]
    npz = work + "_mesh.npz"
    joints_path = joints_path or work + "_joints.json"
    blend = script_path("auto_rig_blender.py")
    cmd = [BLENDER, "--background", "--python-exit-code", "1", "--python", blend, "--", "export", "--src=" + src, "--out=" + npz]
    run(cmd + (["--template=" + template] if template else []))
    verts, tris = load_mesh(npz)
    z = np.load(npz)
    heads = dict(zip([str(n) for n in z["tmpl_names"]], z["tmpl_heads"])) if "tmpl_names" in z.files else None
    z.close(); os.remove(npz)
    if template:
        if os.path.exists(joints_path):
            print("auto_rig: using EXISTING joints from %s (delete the file to detect again)" % joints_path)
        else:
            j, f = solve(verts, tris)
            lay = template_layout(heads)
            j = apply_layout(j, lay)
            print("auto_rig: template layout - spine %s of hips->neck, clavicle x %.3f of the arm's" % (
                "/".join("%.3f" % t for t in lay["spine"]), lay["clavicle_x"]))
            json.dump({k: [round(float(c), 5) for c in v] for k, v in j.items()}, open(joints_path, "w"), indent=1)
            print("auto_rig: crotch %s, robe=%s, knees from the %s" % (f["crotch_z"], f["robe"], f["knee_from"]))
    else:
        own_joints_file(verts, tris, joints_path)
    symmetry_gate({k: v for k, v in json.load(open(joints_path)).items() if not k.startswith("_")},
                  float(verts[:, 2].max() - verts[:, 2].min()), joints_path, allow_asymmetry)
    cmd = [BLENDER, "--background", "--python-exit-code", "1", "--python", blend, "--",
           "build", "--src=" + src, "--joints=" + joints_path, "--out=" + out]
    if template:
        cmd.insert(-1, "--template=" + template)
    if no_fingers:
        cmd.append("--no-fingers")
    run(cmd)


def own_joints_file(verts, tris, joints_path):
    """Joints of the own skeleton: a fresh detection (`solve`) or an existing file; fingers missing
    in it are placed from the mesh. Written back to `joints_path`."""
    H = float(verts[:, 2].max() - verts[:, 2].min())
    if os.path.exists(joints_path):
        j = {k: v for k, v in json.load(open(joints_path)).items()}
        print("auto_rig: using EXISTING joints from %s (delete the file to detect again)" % joints_path)
    else:
        j, f = solve(verts, tris)    # spine and clavicles already from SOMA (own_skeleton.own_joints)
        print("auto_rig: crotch %s, robe=%s, knees from the %s" % (f["crotch_z"], f["robe"], f["knee_from"]))
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
    try:
        own_skeleton.bone_frames(j)   # before Blender: a zero-length bone named with its file
    except ValueError as e:
        raise SystemExit("auto_rig: %s - %s" % (joints_path, e))


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
    ap.add_argument("--src", help="FBX prepared for rigging (prepare_for_rigging.py)")
    ap.add_argument("--out", help="output rig_base.fbx")
    ap.add_argument("--joints", help="joints JSON (default next to --out)")
    # The template is the CLIP DUMMY (any Mixamo FBX with the standard skeleton): every bone = its orientation rotated
    # the shortest way onto the new direction; the spine split and the clavicles keep the template's own layout.
    ap.add_argument("--template", help="Mixamo FBX with the standard 65-bone skeleton (not distributed with this repo); "
                    "without it: the own skeleton (skeletons/amts.json)")
    # With a template fingers do NOT deform by default: finger bones stand from the template, not from the mesh, and when a
    # clip closes the hand they tore the claws (hand 5-11% of edges, without fingers 0.1-0.5%). The own skeleton places
    # them on the mesh, so there they deform unless --no-fingers.
    ap.add_argument("--fingers", action=argparse.BooleanOptionalAction, default=None,
                    help="finger bones deform the mesh (default: yes for the own skeleton, no with --template)")
    ap.add_argument("--allow-asymmetry", action="store_true",
                    help="the model is posed asymmetrically: the symmetry gate reports, but does not stop the rig")
    a = ap.parse_args()
    if a.src and a.out:
        fingers = a.fingers if a.fingers is not None else not a.template
        rig(a.src, a.out, a.template, a.joints, not fingers, a.allow_asymmetry)
    else:
        ap.error("give --src and --out (and --template for a Mixamo skeleton)")


if __name__ == "__main__":
    main()
