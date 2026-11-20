"""Rig for AI motion (once per character): the prop is cut out of the mesh onto its own bone (parented to the back),
finger bones are grown out of the claws with weights, debris left by the cut is removed. Output = base for
soma_to_mixamo / merge_actions (--base) and the audit. Next to it `<out>_data.json` for prop_in_hands.
blender -b --python pipeline/rig/prepare_rig.py -- --rig rig_base.fbx --config <character>/rig.json --out rig_ai.glb [--preview]
    [--skeleton mixamo|profile.json]
Paths inside the config are relative to the config file. `prop.parent` is a bone name without the skeleton prefix.
The joints file comes from auto_rig.py and keeps its Mixamo keys (RightHand, LeftTip, Head).
A rig with its own weighted finger chains below a hand (the own skeleton of auto_rig) keeps them: no finger_* bones are grown
on that hand, the config's `fingers` block is not needed there (its `thumb` override still applies).
A separate prop (character.json `prop_model`, mesh objects `amts_prop*` from prepare_for_rigging) is joined in and selected
whole: its `select` and `debris` are not needed."""
import bpy, bmesh, sys, os, math, json, argparse
import numpy as np
from mathutils import Matrix, Vector, geometry as mgeo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, rig_of, FINGER_PREFIX
import own_skeleton
from stages import PROP_MESH

ap = argparse.ArgumentParser(description="Cut the prop onto its own bone and grow finger bones out of the claws.")
ap.add_argument("--rig", required=True); ap.add_argument("--config", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--preview", action="store_true", help="control render: prop red, fingers coloured, thumb red")
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
A.out = os.path.abspath(A.out)  # Blender saves relative render paths against C:\, not the cwd
CF = json.load(open(A.config, encoding="utf-8"))
JOINTS_PATH = os.path.join(os.path.dirname(os.path.abspath(A.config)), CF["joints"])
JOINTS = json.load(open(JOINTS_PATH, encoding="utf-8"))

bpy.ops.wm.read_factory_settings(use_empty=True)
if A.rig.lower().endswith(".fbx"): bpy.ops.import_scene.fbx(filepath=A.rig)
else: bpy.ops.import_scene.gltf(filepath=A.rig)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
if arm.animation_data: arm.animation_data.action = None
for b in arm.pose.bones: b.matrix_basis = Matrix()
bpy.context.view_layer.update()
PROP_OBJ = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(PROP_MESH)]
body = max((o for o in bpy.data.objects if o.type == "MESH" and o not in PROP_OBJ), key=lambda o: len(o.data.vertices))
PROF = rig_of(arm, A.skeleton).prof; P = PROF.prefix
HAND = {s: PROF.bone("hand", s) for s in ("Left", "Right")}
AW = arm.matrix_world; AWi = AW.inverted(); mw = body.matrix_world


def coords(): return np.array([tuple(mw @ v.co) for v in body.data.vertices])


# check: joints from auto_rig must sit on the bones (otherwise the import uses a different frame than the config)
for n, b in (("RightHand", HAND["Right"]), ("LeftHand", HAND["Left"]), ("Head", PROF.bone("head"))):
    d = ((AW @ arm.data.bones[b].head_local) - Vector(JOINTS[n])).length
    if d > 0.02: raise SystemExit("prepare_rig: %s is %.1f cm from the joint in %s - different coordinate frame" % (n, d * 100, CF["joints"]))


# ---------- 1. prop vertex selection ----------
def in_box(co, bx):
    lo, hi = np.array(bx[0]), np.array(bx[1]); return ((co >= lo) & (co <= hi)).all(1)


def dist_segment(co, a, b):
    a, b = np.array(a), np.array(b); ab = b - a
    t = np.clip(((co - a) @ ab) / (ab @ ab), 0, 1); return np.linalg.norm(co - (a + t[:, None] * ab), axis=1)


def dist_line(co, a, b):
    a, b = np.array(a), np.array(b); d = (b - a) / np.linalg.norm(b - a); r = co - a
    return np.linalg.norm(r - np.outer(r @ d, d), axis=1)


def select(co, rules):
    sel = np.zeros(len(co), bool)
    for r in rules:
        m = np.ones(len(co), bool)
        if "tube" in r: m &= dist_line(co, *r["tube"]) < r["r"]
        if "segment" in r: m &= dist_segment(co, *r["segment"]) < r["r"]
        if "box" in r: m &= in_box(co, r["box"])
        for bx in r.get("exclude", []): m &= ~in_box(co, bx)
        sel |= m
    return sel


PC = CF.get("prop")
prop = None
if PROP_OBJ and not PC:
    raise SystemExit("prepare_rig: the rig has a separate prop mesh (character.json prop_model) but %s has no `prop` block "
                     "(name, parent, frame)" % A.config)
if PC and not PROP_OBJ and not PC.get("select"):
    raise SystemExit("prepare_rig: %s: prop.select is needed when the prop is part of the model's mesh" % A.config)
if PC:
    n_body = len(body.data.vertices)
    if PROP_OBJ:   # joined after the body's vertices: the separation below works as for a modelled-in prop
        bpy.ops.object.select_all(action="DESELECT")
        for o in [body, *PROP_OBJ]: o.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.join()
    sel = select(coords(), PC.get("select", []))
    sel[n_body:] = True
    if PROP_OBJ: print("separate prop mesh: %d vertices" % (len(sel) - n_body))
    # closure: an island (after welding UV seams) that is mostly selected goes in whole - string ends, fittings
    co_ = coords()
    _, wl = np.unique(np.round(co_ * 2e4).astype(np.int64), axis=0, return_inverse=True); wl = wl.ravel()
    par = np.arange(wl.max() + 1)

    def fw(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    for e in body.data.edges:
        i, j = fw(wl[e.vertices[0]]), fw(wl[e.vertices[1]])
        if i != j: par[i] = j
    isl = np.array([fw(x) for x in wl])
    count = np.bincount(isl, minlength=len(par)); chosen = np.bincount(isl, weights=sel, minlength=len(par))
    frac = np.divide(chosen, count, out=np.zeros(len(par)), where=count > 0)
    thr = PC.get("close_islands", 0.5)
    for w_ in np.where((frac > 0) & (frac < 1))[0]:
        print("  island %6d verts: %.0f%% selected -> %s" % (count[w_], 100 * frac[w_], "whole" if frac[w_] >= thr else "unchanged"))
    sel = sel | (frac[isl] >= thr)
    # growth along thin parts (bow strings are long-edged cylinders: an end outside the rule stays with the body
    # and draws a line on the back). A neighbour joins when the mesh under it is thinner than the limit and near the prop.
    GR = PC.get("grow")
    if GR:
        from mathutils.bvhtree import BVHTree
        tris_ = [p.vertices[:] for p in body.data.polygons]
        tree = BVHTree.FromPolygons([Vector(c) for c in co_], tris_)
        nor = [(mw.to_3x3() @ v.normal).normalized() for v in body.data.vertices]
        lo_, hi_ = co_[sel].min(0) - GR["margin"], co_[sel].max(0) + GR["margin"]
        nb = [[] for _ in range(len(co_))]
        for e in body.data.edges:
            a_, b_ = e.vertices; nb[a_].append(b_); nb[b_].append(a_)

        def thickness(i):
            hit = tree.ray_cast(Vector(co_[i]) - nor[i] * 1e-4, -nor[i], 0.2)
            return hit[3] if hit[0] is not None else 0.2
        front = list(np.where(sel)[0]); added = 0
        for _ in range(GR["steps"]):
            new = []
            for i in front:
                for j in nb[i]:
                    if sel[j] or not ((co_[j] >= lo_) & (co_[j] <= hi_)).all(): continue
                    if thickness(j) < GR["thickness"]: sel[j] = True; new.append(j)
            added += len(new); front = new
            if not new: break
        print("  growth along thin parts: +%d vertices" % added)
    print("prop %s: %d vertices" % (PC["name"], sel.sum()))
    bpy.context.view_layer.objects.active = body
    for o in bpy.data.objects: o.select_set(o is body)
    # face selections from the import stay in the mesh: without a deselect `separate` takes half the body
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="DESELECT"); bpy.ops.object.mode_set(mode="OBJECT")
    for v, s_ in zip(body.data.vertices, sel): v.select = bool(s_)
    before = set(bpy.data.objects)
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.separate(type="SELECTED"); bpy.ops.object.mode_set(mode="OBJECT")
    prop = next(iter(set(bpy.data.objects) - before)); prop.name = PC["name"]; prop.data.name = PC["name"]

    # debris: small body islands in the prop zone. Connectivity after welding positions - the mesh is split at UV seams
    bm = bmesh.new(); bm.from_mesh(body.data); bm.verts.ensure_lookup_table()
    par = list(range(len(bm.verts)))

    def fnd(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    key = {}
    for v in bm.verts:
        k = tuple(round(c * 2e4) for c in v.co)
        if k in key: par[fnd(v.index)] = fnd(key[k])
        else: key[k] = v.index
    for e in bm.edges:
        i, j = fnd(e.verts[0].index), fnd(e.verts[1].index)
        if i != j: par[i] = j
    islands = {}
    for v in bm.verts: islands.setdefault(fnd(v.index), []).append(v)
    DB = PC.get("debris")
    kill = [q for c in islands.values() if DB and len(c) < DB["max_vertices"]
            and in_box(np.array([tuple(mw @ q.co) for q in c]), DB["box"]).all() for q in c]
    print("debris: %d vertices in %d islands" % (len(kill), sum(1 for c in islands.values() if c[0] in kill)))
    bmesh.ops.delete(bm, geom=kill, context="VERTS"); bm.to_mesh(body.data); bm.free()

    # cap check: the share of cap faces turned more than 60 deg from the stock's outward direction, and how far an interior
    # vertex sits off the stock radius. The fan cap: 400 faces; the cylinder-domain cap: see the log
    CAP_STEP, CAP_OFF, CAP_ERR, SHARD = 0.008, 0.10, 0.004, 0.05

    def cap_quality(faces, mw_, radial, centre, added):
        """(share of faces facing > 60 deg off the stock's outward direction, max distance of a new vertex from the stock radius)
        around the stock's fitted centre line."""
        off, err = 0, 0.0
        for f in faces:
            p = mw_ @ f.calc_center_median(); c, r = centre(radial(p)[0]); rv = p - c
            if rv.length > 1e-6 and (mw_.to_3x3() @ f.normal).normalized().dot(rv.normalized()) < 0.5: off += 1
            for v in f.verts:
                if v not in added: continue   # the loop's own vertices stay where the model has them
                p = mw_ @ v.co; c, r = centre(radial(p)[0]); err = max(err, abs((p - c).length - r))
        return off / max(len(faces), 1), err

    # cap the cut: where the prop was fused with the body the separation leaves matching open loops in both meshes
    # (Kusznik: the stock went through the quiver in the model; seen as a hole in the stock by the right hand and in the
    # quiver). Only loops whose vertices lie on the other mesh's open edges are filled; other open edges stay.
    # The mesh is split at UV seams: it is welded first, or a loop crossing a seam is not closed and stays open.
    # The stock's surface inside the quiver never existed: what it kept there (a concave piece of the quiver wall) stays.
    key = lambda v: tuple(round(c * 2e4) for c in v.co)
    bms = {}
    for o in (body, prop):
        bms[o] = bmesh.new(); bms[o].from_mesh(o.data)
    rim = {o: {key(v) for e in bms[o].edges if e.is_boundary for v in e.verts} for o in bms}
    for o, other in ((body, prop), (prop, body)):
        b_ = bms[o]
        # the prop is small and welded whole (its seam edges ending on the rim kept the loop from closing); the body only
        # at the rim
        bmesh.ops.remove_doubles(b_, verts=list(b_.verts) if o is prop else [v for v in b_.verts if key(v) in rim[other]], dist=1e-5)
        cut = [e for e in b_.edges if e.is_boundary and all(key(v) in rim[other] for v in e.verts)]
        # each simple loop (every vertex on two cut edges) becomes one face; bmesh.ops.holes_fill left Kusznik's 49-edge
        # loop on the stock open
        cs, seen_, new = set(cut), set(), []
        for e in cut:
            if e in seen_: continue
            ring, v, prev = [e.verts[0]], e.verts[1], e; seen_.add(e)
            while v is not ring[0]:
                nxt = [y for y in v.link_edges if y in cs and y is not prev]
                if len(nxt) != 1: ring = None; break
                ring.append(v); prev = nxt[0]; seen_.add(prev); v = prev.other_vert(v)
            if ring and len(ring) >= 3:
                try: new.append(b_.faces.new(ring))
                except ValueError: pass   # a face over these vertices exists already
        nf = len(new)
        if new and o is prop and PC.get("frame"):
            # on the prop the cap bulges onto the stock radius around the prop axis: a flat cap of a loop wrapping half the
            # stock ran through its inside, the grip read the stock surface as inside and lifted the right thumb off it
            U_ = PC["frame"]; mw_ = o.matrix_world; mwi_ = mw_.inverted()
            A_ = Vector(U_["axis"][0]); fa = (Vector(U_["axis"][1]) - A_).normalized()

            def radial(p):   # world point -> (along the axis, radial vector)
                x = (p - A_).dot(fa); return x, p - (A_ + fa * x)
            prof = []
            for f in b_.faces:
                if f in new: continue
                x, rv = radial(mw_ @ f.calc_center_median())
                if rv.length > 1e-6 and (mw_.to_3x3() @ f.normal).normalized().dot(rv.normalized()) > 0.7: prof.append((x, rv.length))
            prof = np.array(prof)

            def r_at(x):   # stock radius at x from its outward-facing surface
                m = np.abs(prof[:, 0] - x) < 0.03
                return float(np.median(prof[m, 1])) if len(prof) and m.any() else None
            # the stock's centre line across the cut: circles fitted to intact cross-sections (points all round) on both
            # sides of the loops (a low-poly ring: >= 5 of 12 angle bins, fit error < 2 mm), a straight line through their
            # centres and radii. The prop axis from the config runs 1-3.4 cm off Kusznik's stock there (radius 2.3 cm behind
            # the cut, 3.5 cm in front), and a cap on radii about it bulged out to one side
            u0 = fa.orthogonal().normalized(); v0 = fa.cross(u0)
            rimv = {v for f in new for v in f.verts}
            xs_ = [radial(mw_ @ v.co)[0] for v in rimv]; x_lo, x_hi = min(xs_) - 0.01, max(xs_) + 0.01
            pv = np.array([(x, rv.dot(u0), rv.dot(v0)) for x, rv in (radial(mw_ @ v.co) for v in b_.verts if v not in rimv)
                           if rv.length < 0.08])
            fits = []
            for xc in np.arange(x_lo - 0.10, x_hi + 0.10, 0.01):
                if x_lo - 0.005 < xc < x_hi + 0.005: continue
                q = pv[np.abs(pv[:, 0] - xc) < 0.01]
                if len(q) < 6: continue
                Am = np.c_[q[:, 1], q[:, 2], np.ones(len(q))]; D, E, F = np.linalg.lstsq(Am, -(q[:, 1] ** 2 + q[:, 2] ** 2), rcond=None)[0]
                cu, cv = -D / 2, -E / 2; rr = cu * cu + cv * cv - F
                if rr <= 0: continue
                rad = np.hypot(q[:, 1] - cu, q[:, 2] - cv); bins = np.unique(((np.arctan2(q[:, 2] - cv, q[:, 1] - cu) + math.pi) / (2 * math.pi) * 12).astype(int) % 12)
                if np.sqrt(np.mean((rad - math.sqrt(rr)) ** 2)) < 0.002 and len(bins) >= 5 and 0.015 < math.sqrt(rr) < 0.07:
                    fits.append((xc, cu, cv, math.sqrt(rr)))
            fits = np.array(fits)
            if len(fits) >= 2 and (fits[:, 0] < x_lo).any() and (fits[:, 0] > x_hi).any():
                LN = [np.polyfit(fits[:, 0], fits[:, k], 1) for k in (1, 2, 3)]

                def centre(x):   # (point on the stock's centre line, stock radius) at x
                    cu, cv, r = (float(np.polyval(c, x)) for c in LN); return A_ + fa * x + u0 * cu + v0 * cv, r
            else:
                def centre(x):
                    return A_ + fa * x, r_at(x) or 0.03
            print("stock centre line on %s: %d intact sections%s" % (o.name, len(fits), " at x %s" % np.round(fits[:, 0], 2).tolist() if len(fits) else ""))

            def to_stock(p, x):   # point -> onto the stock surface at x, keeping its direction from the centre line
                c, r = centre(x); d = p - c; d -= fa * d.dot(fa); return c + d.normalized() * r if d.length > 1e-6 else p
            # the loop's rim lies on the quiver wall, up to 5 cm off the stock: the rim goes onto the stock surface, and so do
            # two rings of faces next to it where they stand off it (out or in) by less than SHARD. Left as they were, the cap bulged out to the rim and the wall pieces stood out as shards
            ring_, front_ = set(rimv), set(rimv)
            for _ in range(2):
                front_ = {w for v in front_ for e in v.link_edges for w in e.verts} - ring_; ring_ |= front_
            moved = 0
            for v in ring_:
                p = mw_ @ v.co; x = radial(p)[0]; c, r = centre(x); d = (p - c) - fa * (p - c).dot(fa)
                if v in rimv or (x_lo <= x <= x_hi and 0.002 < abs(d.length - r) < SHARD): v.co = mwi_ @ to_stock(p, x); moved += 1
            print("cut rim on %s: %d vertices onto the stock surface" % (o.name, moved))
            # each loop is triangulated in the unrolled stock surface (along the axis x angle) with interior points every
            # CAP_STEP, and every new vertex is set on the stock radius: a fan from one centre pushed onto the radius gave
            # a spiky, faceted patch by the right hand (author: "the fill did not work") and the middle finger stood up on it
            R0 = float(np.mean([centre(x)[1] for x in np.linspace(x_lo, x_hi, 5)]))

            def ang(p):
                rv = p - centre(radial(p)[0])[0]; return math.atan2(rv.dot(v0), rv.dot(u0))

            def on_stock(x, th):
                c, r = centre(x); return c + (u0 * math.cos(th) + v0 * math.sin(th)) * r
            caps, added = [], set()
            for f in list(new):
                ring = list(f.verts); P_ = [mw_ @ v.co for v in ring]
                th = [ang(P_[0])]
                for p_ in P_[1:]: th.append(th[-1] + (ang(p_) - th[-1] + math.pi) % (2 * math.pi) - math.pi)
                if abs(th[-1] + (th[0] - th[-1] + math.pi) % (2 * math.pi) - math.pi - th[0]) > math.pi:
                    caps.append(f); continue   # the loop goes round the stock: no patch on its surface, the plain face stays
                xy = [(radial(p_)[0], t_ * R0) for p_, t_ in zip(P_, th)]
                poly = np.array(xy); lo_, hi_ = poly.min(0), poly.max(0); pts = []
                for gx in np.arange(lo_[0] + CAP_STEP / 2, hi_[0], CAP_STEP):
                    for gy in np.arange(lo_[1] + CAP_STEP / 2, hi_[1], CAP_STEP):
                        q = np.array((gx, gy)); a2, b2 = poly, np.roll(poly, -1, 0)
                        cross = ((a2[:, 1] > gy) != (b2[:, 1] > gy)) & (gx < (b2[:, 0] - a2[:, 0]) * (gy - a2[:, 1]) / (b2[:, 1] - a2[:, 1] + 1e-12) + a2[:, 0])
                        ab2 = b2 - a2; t2 = np.clip(((q - a2) * ab2).sum(1) / np.maximum((ab2 * ab2).sum(1), 1e-12), 0, 1)
                        if cross.sum() % 2 and np.linalg.norm(a2 + t2[:, None] * ab2 - q, axis=1).min() > CAP_STEP / 2: pts.append((gx, gy))
                n_ = len(ring); V2 = [Vector(c) for c in xy + pts]
                out = mgeo.delaunay_2d_cdt(V2, [(i, (i + 1) % n_) for i in range(n_)], [list(range(n_))], 1, 1e-7)
                if not out[2]: caps.append(f); continue
                vmap = []
                for k, (co2, orig) in enumerate(zip(out[0], out[3])):
                    i0 = min(orig) if orig else None
                    if i0 is not None and i0 < n_: vmap.append(ring[i0])
                    else: vmap.append(b_.verts.new(mwi_ @ on_stock(co2.x, co2.y / R0))); added.add(vmap[-1])
                b_.faces.remove(f)
                for tri in out[2]:
                    try: caps.append(b_.faces.new([vmap[i] for i in tri]))
                    except ValueError: pass
            new = caps
        if new:
            new = bmesh.ops.triangulate(b_, faces=new)["faces"]
            bmesh.ops.recalc_face_normals(b_, faces=new)
        print("cut capped on %s: %d open edges, %d loops filled, %d new faces" % (o.name, len(cut), nf, len(new)))
        if new and o is prop and PC.get("frame"):
            off, err = cap_quality(new, mw_, radial, centre, added)
            print("cap quality on %s: %d faces, %.0f%% facing off the stock (> 60 deg), interior radius error max %.1f cm"
                  % (o.name, len(new), 100 * off, 100 * err))
            if off > CAP_OFF or err > CAP_ERR:
                raise SystemExit("prepare_rig: the cap on %s is spiky (%.0f%% of its faces off the stock surface, limit %.0f%%; radius "
                                 "error %.1f cm, limit %.1f): a torn-looking patch by the grip" % (o.name, 100 * off, 100 * CAP_OFF, 100 * err, 100 * CAP_ERR))
        b_.to_mesh(o.data); b_.free()

# ---------- 2. fingers out of the claws ----------
dom = dominant(body)
co0 = coords()
edges = np.array([e.vertices[:] for e in body.data.edges])
_, weld = np.unique(np.round(co0 * 2e4).astype(np.int64), axis=0, return_inverse=True); weld = weld.ravel()
FC = CF.get("fingers")
FING = {}


def rig_chains(side):
    """[[bone 1, 2, 3], ...] of the rig's own fingers below the hand: chains of 3 bones that own skin (a Mixamo template's
    finger bones own none)."""
    out = []
    for c in arm.data.bones[HAND[side]].children:
        ch = [c]
        while len(ch) < 3 and ch[-1].children: ch.append(ch[-1].children[0])
        if len(ch) == 3 and np.isin(dom, [b.name for b in ch]).any(): out.append([b.name for b in ch])
    return out


OWN = {s: c for s in ("Right", "Left") for c in [rig_chains(s)] if c}
for side, chains in OWN.items():
    w0 = np.array(JOINTS[side + "Hand"]); ax = np.array(JOINTS[side + "Tip"]) - w0; ax /= np.linalg.norm(ax)
    fl = []
    for names in chains:
        bs = [arm.data.bones[n] for n in names]
        end = bs[-1].children[0].head_local if bs[-1].children else bs[-1].tail_local
        fl.append(([AW @ b.head_local for b in bs] + [AW @ end], np.where(np.isin(dom, names))[0], None, None, False))
    FING[side] = (fl, ax, w0)
    print(side, "fingers: %d chains of the rig itself" % len(chains))
if FC:
    for side in ("Right", "Left"):
        if side in OWN: continue
        w0 = np.array(JOINTS[side + "Hand"]); ax = np.array(JOINTS[side + "Tip"]) - w0; ax /= np.linalg.norm(ax)
        hm = np.where(dom == HAND[side])[0]
        t = (co0[hm] - w0) @ ax

        def components(thr):
            slab = hm[t > thr]; sset = set(slab.tolist()); p2 = {i: i for i in slab}

            def f2(i):
                while p2[i] != i: p2[i] = p2[p2[i]]; i = p2[i]
                return i

            def join(x, y):
                x, y = f2(x), f2(y)
                if x != y: p2[x] = y
            wid = {}
            for i in slab: wid.setdefault(weld[i], []).append(i)
            for lst in wid.values():
                for j in lst[1:]: join(j, lst[0])
            for e0, e1 in edges:
                if e0 in sset and e1 in sset: join(e0, e1)
            cs = {}
            for i in slab: cs.setdefault(f2(i), []).append(i)
            return [set(c) for c in cs.values() if len(c) >= FC["min_vertices"]]
        thresholds = FC["claw_thresholds"]
        main = components(thresholds[0]); fingers = [list(c) for c in main]
        n_main = len(fingers)
        for thr in thresholds[1:]:
            for c in components(thr):
                if not any(c & m for m in main): fingers.append(list(c))
        fingers = [np.array(c) for c in fingers]
        print(side, "fingers (vertices):", sorted(len(c) for c in fingers))
        if not fingers: continue
        inf = set(np.concatenate(fingers).tolist())
        a0, a1 = FC["base_band"]
        base = np.array([i for i, tt in zip(hm, t) if a0 < tt < a1 and i not in inf], dtype=int)

        def perp(p): return p - np.outer((p - w0) @ ax, ax)
        bc = [perp(co0[c][np.argsort((co0[c] - w0) @ ax)[:20]]).mean(0) for c in fingers]
        near = np.argmin(np.stack([np.linalg.norm(perp(co0[base]) - b, axis=1) for b in bc]), axis=0) if len(base) else []
        out_f = []
        for k, c in enumerate(fingers):
            verts = np.concatenate([c, base[near == k]]) if len(base) else c
            tv = (co0[verts] - w0) @ ax
            tip = co0[verts[np.argsort(tv)[-6:]]].mean(0); tt = (tip - w0) @ ax
            n0 = max(FC["base"], float(tv.min()) + 0.006)   # a finger selected without base vertices starts higher

            def at(x):
                m = np.abs(tv - x) < 0.012
                if m.sum() <= 2: m = np.argsort(np.abs(tv - x))[:4]   # gap between the base and the claw
                return co0[verts[m]].mean(0)
            J = [at(n0), at(n0 + (tt - n0) / 3), at(n0 + 2 * (tt - n0) / 3), tip]
            if any(j is None for j in J): print("  finger %d skipped (too short)" % k); continue
            print("  finger %d: base t=%.3f, tip t=%.3f, %d verts" % (k, n0, tt, len(verts)))
            s_ = np.zeros(len(verts))
            for vi, p in enumerate(co0[verts]):
                best = (1e9, 0)
                for b in range(3):
                    ab = J[b + 1] - J[b]; u_ = np.clip((p - J[b]) @ ab / (ab @ ab), 0, 1)
                    d = np.linalg.norm(p - (J[b] + u_ * ab))
                    if d < best[0]: best = (d, b + u_)
                s_[vi] = best[1]
            out_f.append(([Vector(j) for j in J], verts, s_, tv, k >= n_main))
        FING[side] = (out_f, ax, w0)

# ---------- 3. bones ----------
bpy.context.view_layer.objects.active = arm
for o in bpy.data.objects: o.select_set(o is arm)
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
if PC:
    U = PC["frame"]; A_, B_ = Vector(U["axis"][0]), Vector(U["axis"][1]); fa = (B_ - A_).normalized()
    Or = A_ + fa * (Vector(U["origin"]) - A_).dot(fa)
    up = Vector(U["up"]); up = (up - fa * up.dot(fa)).normalized()
    Cr = Matrix((fa, up.cross(fa), up)).transposed().to_4x4(); Cr.translation = Or
    kb = eb.new(PC["name"]); kb.head = AWi @ Or; kb.tail = AWi @ (Or + fa * 0.2)
    kb.align_roll(AWi.to_3x3() @ up); kb.parent = eb[P + PC["parent"] if P + PC["parent"] in eb else PC["parent"]]; kb.use_deform = True
NAMES = {}
for side, (fl, ax, w0) in FING.items():
    if side in OWN: NAMES[side] = OWN[side]; continue
    for k, (J, verts, s_, tv, kc) in enumerate(fl):
        prev = eb[HAND[side]]; nn = []
        for b in range(3):
            e = eb.new("%s%s%d_%d" % (FINGER_PREFIX, side[0], k, b + 1))
            e.head = AWi @ J[b]; e.tail = AWi @ J[b + 1]; e.parent = prev; e.use_connect = b > 0; e.use_deform = True
            prev = e; nn.append(e.name)
        NAMES.setdefault(side, []).append(nn)
bpy.ops.object.mode_set(mode="OBJECT")
for b in arm.pose.bones: b.rotation_mode = "QUATERNION"

# ---------- 4. weights ----------
p0, pw = FC["weight_blend"] if FC else (0, 1)
for side, (fl, ax, w0) in FING.items():
    if side in OWN: continue
    hg = body.vertex_groups[HAND[side]]
    for k, (J, verts, s_, tv, kc) in enumerate(fl):
        gs = [body.vertex_groups.new(name=n) for n in NAMES[side][k]]
        for vi, sv, t_ in zip(verts, s_, tv):
            wf = float(np.clip((t_ - p0) / pw, 0, 1)); wf = wf * wf * (3 - 2 * wf)
            ws = np.zeros(3); b = min(int(sv), 2); fr = sv - b; ws[b] = 1.0
            if fr > 0.85 and b < 2: x = (fr - 0.85) / 0.3; ws[b] = 1 - x; ws[b + 1] = x
            if fr < 0.15 and b > 0: x = (0.15 - fr) / 0.3; ws[b] = 1 - x; ws[b - 1] = x
            for g, w in zip(gs, ws):
                if w * wf > 1e-3: g.add([int(vi)], float(w * wf), "REPLACE")
            hg.add([int(vi)], float(1 - wf), "REPLACE")
if prop:
    for vg in list(prop.vertex_groups): prop.vertex_groups.remove(vg)
    prop.vertex_groups.new(name=PC["name"]).add(list(range(len(prop.data.vertices))), 1.0, "REPLACE")

# ---------- 5. data for prop_in_hands: palm normal (sign from the thumb) ----------
data = {"fingers": NAMES, "thumbs": {}, "palm": {}}
if PC:
    KB = AW @ arm.data.bones[PC["name"]].matrix_local
    data["prop"] = {"name": PC["name"], "frame_in_bone": [list(r) for r in (KB.inverted() @ Cr)],
                    "frame_world": [list(r) for r in Cr]}
for side, (fl, ax, w0) in FING.items():
    hm = np.where(dom == HAND[side])[0]; t = (co0[hm] - w0) @ ax
    # own fingers: the palm ends at the first knuckle that is not the thumb's base (the thumb starts next to the wrist)
    knuckles = FC["base"] if side not in OWN else sorted(float((np.array(J[0]) - w0) @ ax) for J, *_ in fl)[1]
    c = co0[hm[(t > 0.03) & (t < knuckles)]]; c = c - c.mean(0); c = c - np.outer(c @ ax, ax)
    n = np.linalg.svd(c, full_matrices=False)[2][1]; n = n - ax * (n @ ax); n /= np.linalg.norm(n)
    curl = np.zeros(3)
    for J, *_ in fl:
        line = np.array(J[3] - J[0]); mid = np.array((J[1] + J[2]) / 2 - J[0]); curl += mid - line * (mid @ line) / (line @ line)
    if n @ curl < 0: n = -n
    # thumb: in the rest pose (A-pose, palms facing the body) it lies furthest forward (-Y). The angle from the hand axis
    # pointed at the middle finger. Always confirm on the preview (--preview, thumb in red); "thumb" in the config overrides.
    # The rig's own fingers: the chain starting closest to the wrist, its base is the CMC joint (forward-most picked the
    # index on Kusznik: 14.4 vs 14.0 cm).
    fwd = [round(-float(np.array(J[1] + J[2])[1] / 2 - w0[1]), 3) for J, *_ in fl]
    guess = int(np.argmax(fwd))
    if side in OWN:
        guess = int(np.argmin([float((np.array(J[0]) - w0) @ ax) for J, *_ in fl]))
    k_ = ((FC or {}).get("thumb") or {}).get(side, guess)
    data["thumbs"][side] = [k_]
    print(side, "fingers forward (m):", fwd, "-> thumb", k_)
    # palm side from hand anatomy: fingers along the axis, palm n -> thumb on the axis x n side (right) / n x axis (left).
    # The claw curl (above) gave the BACK of the hand: fingers bent backwards and stuck out from the stock.
    # thumb side from its base; the rig's own thumb starts at the CMC next to the wrist, almost on the hand axis (Kusznik: the
    # palm came out flipped on one hand only), so there from its second joint (MCP), where it leaves the hand
    tk = np.array(fl[k_][0][1 if side in OWN else 0]) - w0; tk = tk - ax * (tk @ ax)
    ch_ = np.cross(ax, n) if side == "Right" else np.cross(n, ax)
    if ch_ @ tk < 0:
        n = -n; print(side, "palm flipped (claw curl pointed at the back of the hand)")
    # the rig's own fingers: the palm normal from the knuckles in the joints file, the rule the own skeleton rolls its hand
    # with (own_skeleton.palm_normal). The point cloud above saw the wrist cloth and the thumb's offset towards the palm
    # (Kusznik: 127 and 150 deg off, the back of the hand on the stock, fingers bent backwards out of the crossbow)
    try: kn = own_skeleton.palm_normal(JOINTS, side) if side in OWN else None
    except KeyError: kn = None   # a joints file without finger keys (fingers from another source)
    if kn is not None:
        print(side, "palm from the knuckles: %.0f deg from the point-cloud estimate" % math.degrees(math.acos(max(-1, min(1, float(kn @ n))))))
        n = kn
    R = (AW @ arm.data.bones[HAND[side]].matrix_local).to_3x3().normalized()
    data["palm"][side] = {"local_normal": list((R.transposed() @ Vector(n)).normalized()),
                          "axis_vs_bone_deg": round(math.degrees(Vector((0, 1, 0)).angle(R.transposed() @ Vector(ax))), 1)}
    print(side, "hand axis vs bone Y: %.1f deg" % data["palm"][side]["axis_vs_bone_deg"])
json.dump(data, open(A.out.replace(".glb", "_data.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------- 6. export ----------
for o in bpy.data.objects: o.select_set(o in (arm, body) or o is prop)
bpy.ops.export_scene.gltf(filepath=A.out, export_format="GLB", use_selection=True, export_animations=False)
print("RIG OK", A.out, "bones:", len(arm.data.bones))

if A.preview:
    import gpu_queue; gpu_queue.acquire("prepare_rig.py", None)  # Eevee on the GPU
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x, sc.render.resolution_y = 900, 900
    sc.render.film_transparent = True; sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True; w.node_tree.nodes["Background"].inputs[1].default_value = 2.5
    for o in (body, prop):
        if o is None: continue
        mat = bpy.data.materials.new(o.name + "_preview"); mat.diffuse_color = (0.85, 0.15, 0.1, 1) if o is prop else (0.7, 0.7, 0.7, 1)
        o.data.materials.clear(); o.data.materials.append(mat)
    cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
    sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "MATERIAL"
    cam.data.type = "ORTHO"
    lo, hi = co0.min(0), co0.max(0)
    views = [("back", 180, (lo + hi) / 2, (hi - lo).max() * 1.1), ("side", 90, (lo + hi) / 2, (hi - lo).max() * 1.1)]
    if prop:
        pc = np.array([tuple(prop.matrix_world @ v.co) for v in prop.data.vertices])
        views.append(("back_closeup", 180, (pc.min(0) + pc.max(0)) / 2, (pc.max(0) - pc.min(0)).max() * 1.15))
    COL = [(0.2, 0.5, 0.95, 1), (0.2, 0.8, 0.3, 1), (0.95, 0.8, 0.1, 1), (0.7, 0.3, 0.9, 1), (0.1, 0.8, 0.8, 1)]
    mats = []
    for i, c in enumerate(COL + [(0.9, 0.1, 0.1, 1)]):
        m_ = bpy.data.materials.new("finger%d" % i); m_.diffuse_color = c; body.data.materials.append(m_); mats.append(len(body.data.materials) - 1)
    for side, (fl, ax, w0) in FING.items():
        for k, (J, verts, s_, tv, kc) in enumerate(fl):
            vs = set(verts.tolist()); mi = mats[-1] if k in data["thumbs"][side] else mats[k % len(COL)]
            for poly in body.data.polygons:
                if sum(v in vs for v in poly.vertices) >= 2: poly.material_index = mi
        hc = np.array(JOINTS[side + "Hand"]) + ax * 0.17
        views += [("hand_%s_%s" % (side, nm), yaw, hc, 0.4) for nm, yaw in (("front", 0), ("side", 90 if side == "Left" else -90), ("back", 180))]
    for nm, yaw, center, size in views:
        cam.data.ortho_scale = float(size)
        d = Vector((math.sin(math.radians(yaw)), -math.cos(math.radians(yaw)), 0.15)).normalized()
        cam.location = Vector(center) + d * 5; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = A.out.replace(".glb", "_preview_%s.png" % nm); bpy.ops.render.render(write_still=True)
