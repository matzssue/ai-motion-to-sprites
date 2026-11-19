"""Rig for AI motion (once per character): the prop is cut out of the mesh onto its own bone (parented to the back),
finger bones are grown out of the claws with weights, debris left by the cut is removed. Output = base for
soma_to_mixamo / merge_actions (--base) and the audit. Next to it `<out>_data.json` for prop_in_hands.
blender -b --python pipeline/rig/prepare_rig.py -- --rig rig_base.fbx --config <character>/rig.json --out rig_ai.glb [--preview]
    [--skeleton mixamo|profile.json]
Paths inside the config are relative to the config file. `prop.parent` is a bone name without the skeleton prefix.
The joints file comes from auto_rig.py and keeps its Mixamo keys (RightHand, LeftTip, Head).
A rig with its own weighted finger chains below a hand (the own skeleton of auto_rig) keeps them: no finger_* bones are grown
on that hand, the config's `fingers` block is not needed there (its `thumb` override still applies)."""
import bpy, bmesh, sys, os, math, json, argparse
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, rig_of, FINGER_PREFIX
import own_skeleton

ap = argparse.ArgumentParser(description="Cut the prop onto its own bone and grow finger bones out of the claws.")
ap.add_argument("--rig", required=True); ap.add_argument("--config", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--preview", action="store_true", help="control render: prop red, fingers coloured, thumb red")
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
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
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
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
if PC:
    sel = select(coords(), PC["select"])
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
    DB = PC["debris"]
    kill = [q for c in islands.values() if len(c) < DB["max_vertices"]
            and in_box(np.array([tuple(mw @ q.co) for q in c]), DB["box"]).all() for q in c]
    print("debris: %d vertices in %d islands" % (len(kill), sum(1 for c in islands.values() if c[0] in kill)))
    bmesh.ops.delete(bm, geom=kill, context="VERTS"); bm.to_mesh(body.data); bm.free()

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
