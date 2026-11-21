"""One-handed weapon carried rigidly in one hand: sword, axe, mace, torch.
Use when: one hand holds the weapon by its grip through the whole action and the other hand never touches it; the
    approved pose scene already shows where the weapon sits in that hand.
Not for: two-handed grips, a weapon that changes hands or is drawn, thrown or sheathed, a shield strapped to the forearm,
    a grip that slides along the shaft.
Inputs: motion file `recipe`: `weapon` (GLB with one mesh, path relative to the motion file), `hand` (right/left),
    `in_hand` (4x4: the weapon mesh object in the hand bone's frame), `grip` (both ends of the part the fist closes on,
    weapon mesh coordinates), `fingers` ({finger bone: pose quaternion wxyz} of the closed fist). `--read-scene` prints
    `in_hand` and `fingers` from the approved pose scene.
Output: the clip GLB with the weapon as a mesh parented to the hand bone and the fist on every frame of the action;
    `<out>_recipe.json`. No other bone is touched: body joints and the hand's rotation stay as the clip has them.
Checks: per whole frame, reported and not scored: how deep the weapon is in the body outside the holding hand and wrist
    (by region), and the share of the grip the fist covers. Points are the weapon's vertices and its edges every 2 cm:
    a body part thinner than that between two points is missed, as is anything between whole frames.

blender -b --python pipeline/recipes/one_hand_weapon.py -- --glb merged.glb --motion <motion>.json --out out.glb [--skeleton X]
blender -b <pose scene>.blend --python pipeline/recipes/one_hand_weapon.py -- --read-scene <weapon object> [--hand right]
    [--frame 0] [--skeleton X]     prints {"in_hand": ..., "fingers": ...} for the motion file
Run again on its own output it replaces the weapon instead of adding a second one (character.py runs it per action)."""
import json
import os
import sys

import numpy as np

NAME = "one_hand_weapon"
STEP = 0.02    # m: spacing of the check points along the weapon's edges
TOUCH = 0.01   # m: a grip point this close to the holding hand's skin is covered by the fist
HERE = os.path.dirname(os.path.abspath(__file__))


def edge_points(co, edges, step=STEP):
    """The vertices plus points along every edge longer than `step`, at most `step` apart (a low-poly blade has its
    vertices only at the guard and the tip)."""
    co = np.asarray(co, float); out = [co]
    for a, b in edges:
        n = int(np.ceil(np.linalg.norm(co[b] - co[a]) / step))
        if n > 1: out.append(co[a] + np.outer(np.arange(1, n) / n, co[b] - co[a]))
    return np.concatenate(out)


def grip_mask(pts, a, b):
    """Points of the grip section: between the planes through `a` and `b` across the grip axis."""
    a, b = np.asarray(a, float), np.asarray(b, float); t = (np.asarray(pts, float) - a) @ (b - a) / ((b - a) @ (b - a))
    return (t >= 0) & (t <= 1)


def summary(rows):
    """Per-frame rows [{"frame", "in_body_cm": {region: cm}, "grip_covered"}] -> the report's numbers and its one line."""
    bad = [r for r in rows if r["in_body_cm"]]
    worst = sorted(((max(r["in_body_cm"].values()), r["frame"], max(r["in_body_cm"], key=r["in_body_cm"].get)) for r in bad), reverse=True)[:5]
    cov = [r["grip_covered"] for r in rows]
    out = {"frames": len(rows), "in_body_frames": len(bad), "worst": [list(w) for w in worst],
           "grip_covered": {"min": min(cov), "mean": round(sum(cov) / len(cov), 2)}}
    out["line"] = "weapon in the body on %d of %d frames%s; the fist covers %.0f-%.0f%% of the grip" % (
        len(bad), len(rows), " (worst %.1f cm on fr. %d, %s)" % tuple(worst[0]) if worst else "", 100 * min(cov), 100 * max(cov))
    return out


def main():
    import argparse

    import bpy
    from mathutils import Matrix, Quaternion, Vector
    sys.path.insert(0, os.path.join(HERE, "..", "lib"))
    from collisions import dominant, labels_all, prop_in_body, rig_of, skin_tree, vertices

    ap = argparse.ArgumentParser(description="One-handed weapon rigid in one hand, a fist on every frame, weapon-in-body report.")
    ap.add_argument("--glb"); ap.add_argument("--motion"); ap.add_argument("--out"); ap.add_argument("--skeleton", default=None)
    ap.add_argument("--read-scene", default=None, metavar="OBJECT", help="print in_hand and fingers of this weapon object in the open scene")
    ap.add_argument("--hand", default="right", choices=["right", "left"]); ap.add_argument("--frame", type=int, default=None)
    A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    def hand_bones(arm, side):
        """(profile rig, hand bone, every bone below it): only those are finger bones of this hand."""
        rig = rig_of(arm, A.skeleton); hand = rig.prof.bone("hand", side)
        return rig, hand, {b.name for b in arm.data.bones[hand].children_recursive}

    if A.read_scene:
        arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE"); w = bpy.data.objects[A.read_scene]
        if A.frame is not None: bpy.context.scene.frame_set(A.frame)
        bpy.context.view_layer.update(); _, hand, fing = hand_bones(arm, A.hand.capitalize())
        M = (arm.matrix_world @ arm.pose.bones[hand].matrix).inverted() @ w.matrix_world
        print("READ SCENE " + json.dumps({"hand": A.hand, "in_hand": [[round(x, 6) for x in r] for r in M], "fingers": {
            b: [round(x, 6) for x in arm.pose.bones[b].matrix_basis.to_quaternion()] for b in sorted(fing)}}))
        return
    if not (A.glb and A.motion and A.out): ap.error("--glb, --motion and --out are required")
    R = json.load(open(A.motion, encoding="utf-8")); P = R["recipe"]; side = P.get("hand", "right").capitalize()
    weapon = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(A.motion)), P["weapon"]))
    if not os.path.exists(weapon): raise SystemExit("%s: recipe.weapon: no file %s" % (A.motion, weapon))
    wname = os.path.splitext(os.path.basename(weapon))[0]

    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb)); sc = bpy.context.scene
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); act = bpy.data.actions.get(R["action"])
    if act is None: raise SystemExit("%s: no action %s (there are: %s)" % (A.glb, R["action"], ", ".join(sorted(a.name for a in bpy.data.actions))))
    arm.animation_data.action = act
    try: arm.animation_data.action_slot = act.slots[0]
    except (AttributeError, IndexError): pass
    for pb in arm.pose.bones: pb.matrix_basis = Matrix()   # bones without curves here keep another action's pose
    skinned = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
    body = max(skinned, key=lambda o: len(o.data.vertices))
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in skinned and o.name.split(".")[0] == wname]:
        bpy.data.objects.remove(o, do_unlink=True)   # this recipe's weapon from an earlier run on the same file
    RIG, hand, fing = hand_bones(arm, side); PROF = RIG.prof; AW = arm.matrix_world; f0, f1 = (int(round(x)) for x in act.frame_range)

    # 1. the weapon: one mesh, parented to the hand bone at the approved placement
    before = set(bpy.data.objects); bpy.ops.import_scene.gltf(filepath=weapon); new = set(bpy.data.objects) - before
    meshes = [o for o in new if o.type == "MESH"]
    if len(meshes) != 1: raise SystemExit("%s: one mesh expected, found %d (join them: `in_hand` places one mesh object)" % (weapon, len(meshes)))
    w = meshes[0]; w.parent = None
    for o in new - {w}: bpy.data.objects.remove(o, do_unlink=True)
    w.name = wname; IN = Matrix(P["in_hand"]); sc.frame_set(f0)
    w.parent = arm; w.parent_type = "BONE"; w.parent_bone = hand; w.matrix_parent_inverse = Matrix(); bpy.context.view_layer.update()
    w.matrix_world = AW @ arm.pose.bones[hand].matrix @ IN

    # 2. the fist: the finger curves of this action replaced by one pose (Kimodo has no fingers, the clip leaves them straight)
    F = P.get("fingers") or {}
    stray = sorted(set(F) - fing)
    if stray: raise SystemExit("%s: recipe.fingers: %s %s not below the %s hand bone %s (this recipe moves fingers only)" % (
        A.motion, ", ".join(stray), "is" if len(stray) == 1 else "are", side.lower(), hand))
    bags = [act] if hasattr(act, "fcurves") else [b for la in act.layers for st in la.strips for b in st.channelbags]
    for bag in bags:
        for fc in [c for c in bag.fcurves if c.data_path.startswith('pose.bones["') and c.data_path.split('"')[1] in F
                   and "rotation" in c.data_path]:
            bag.fcurves.remove(fc)
    for b, q in F.items():
        pb = arm.pose.bones[b]; pb.rotation_mode = "QUATERNION"; pb.rotation_quaternion = Quaternion(q)
        for f in (f0, f1): pb.keyframe_insert("rotation_quaternion", frame=f)
    print("recipe %s: %s in the %s hand (%s)%s" % (NAME, wname, side.lower(), hand, ", fist on %d finger bones" % len(F) if F else
          ", no `fingers` given: the hand stays as the clip has it"))

    # 3. per frame: the weapon against the whole skin, and the grip against the holding hand
    dom = dominant(body); LAB = labels_all(dom, RIG); SIDE = np.array([RIG.bone_side(d) for d in dom])
    tris = np.array([p.vertices[:3] for p in body.data.polygons]); fore = PROF.bone("forearm", side); s1 = side[0]
    LOC = edge_points([v.co for v in w.data.vertices], [e.vertices for e in w.data.edges]); G = grip_mask(LOC, *P["grip"])
    if not G.any(): raise SystemExit("%s: recipe.grip: no weapon point lies between its two ends (weapon mesh coordinates)" % A.motion)
    rows = []
    for f in range(f0, f1 + 1):
        sc.frame_set(f); bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
        if f in (f0, f1):   # rigid: the weapon sits in the hand as given, on the first and the last frame
            now = (AW @ arm.pose.bones[hand].matrix).inverted() @ w.matrix_world
            if max(abs(now[i][j] - IN[i][j]) for i in range(4) for j in range(4)) > 1e-4: raise SystemExit("fr. %d: the weapon left its place in the hand" % f)
        MW = np.array(w.matrix_world); pts = LOC @ MW[:3, :3].T + MW[:3, 3]
        TA, RA, SA = skin_tree(vertices(body, dg), tris, LAB, SIDE)
        hd, fa = (AW @ arm.pose.bones[b].matrix.translation for b in (hand, fore))
        hits = prop_in_body(TA, RA, SA, pts[~G], {s1: (hd, (hd - fa).length)})
        cov = 0
        for p in pts[G]:
            v = Vector(p); loc, nor, fi, d = TA.find_nearest(v, 0.05)
            cov += loc is not None and RA[fi] in ("hands", "fingers") and SA[fi] == s1 and (d <= TOUCH or (v - loc).dot(nor) < 0)
        rows.append({"frame": f, "in_body_cm": {k: round(v[0] * 100, 1) for k, v in hits.items() if round(v[0] * 100, 1) > 0},
                     "grip_covered": round(cov / int(G.sum()), 2)})
    rep = dict({"recipe": NAME, "action": R["action"], "weapon": wname, "hand": s1}, **summary(rows))
    rep["limits"] = "whole frames; weapon vertices and edges every %d cm; holding hand, fingers and wrist left out" % round(STEP * 100)
    rep["per_frame"] = rows
    out = os.path.abspath(A.out); json.dump(rep, open(out.replace(".glb", "_recipe.json"), "w", encoding="utf-8"), indent=1)
    sc.frame_set(f0)
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_animations=True)
    print("recipe %s: %s" % (NAME, rep["line"]))
    print("RECIPE OK", out)


if __name__ == "__main__":
    main()
