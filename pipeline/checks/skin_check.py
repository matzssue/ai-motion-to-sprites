"""Arm skin check before review: "candy wrapper" twist of upper arm/forearm (skin.py) on every frame,
on failure a close-up of the worst spot from the game camera (textured, and with stripes along the arm that spiral when twisted).
Motion from GLB:  blender -b --python pipeline/checks/skin_check.py -- --glb X.glb --action attack --out dir [--step 1] [--skeleton X]
Posing script:    blender -b --python pipeline/checks/skin_check.py -- --script anim.py --pose-expr "pose(nr / 20)" --frames 130-170:2 --out dir -- <script args>
The script is run once (as __main__); then for every frame `nr` is set in its globals and --pose-expr is evaluated there.
Limits and measurements: README, "Skin twist". Alpha (a mask cutting the body): alpha_check.py."""
import bpy, sys, os, math, json, argparse, runpy
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import skin
from collisions import dominant, vertices, rig_of
from audit_metrics import height

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
rest_args = argv[argv.index("--") + 1:] if "--" in argv else []; argv = argv[:argv.index("--")] if "--" in argv else argv
ap = argparse.ArgumentParser(description="Measure arm skin twist on every frame of a GLB action or a posing script.")
ap.add_argument("--glb"); ap.add_argument("--action"); ap.add_argument("--step", type=float, default=1.0)
ap.add_argument("--script"); ap.add_argument("--pose-expr", help="expression in the script globals, `nr` = frame number")
ap.add_argument("--frames", default="", help="10,20 or 130-170:2")
ap.add_argument("--out", required=True); ap.add_argument("--yaw", type=float, default=0.0, help="game camera: rotation around vertical (deg)")
ap.add_argument("--pitch", type=float, default=30.0); ap.add_argument("--no-closeups", action="store_true")
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
A = ap.parse_args(argv); A.out = os.path.abspath(A.out); os.makedirs(A.out, exist_ok=True)  # Blender saves relative render paths against C:\, not the cwd
if not A.glb and not A.script: ap.error("give --glb with --action, or --script with --pose-expr")


def frame_list(s):
    out = []
    for part in filter(None, s.split(",")):
        if "-" in part[1:]:
            rng, _, step = part.partition(":"); a, b = rng.split("-"); out += list(np.arange(float(a), float(b) + 1e-6, float(step or 1)))
        else: out.append(float(part))
    return out


if A.script:
    sys.argv = [sys.argv[0], "--"] + rest_args
    G = runpy.run_path(A.script, run_name="__main__")
    nrs = frame_list(A.frames)
    def set_frame(nr): G["nr"] = int(nr) if float(nr).is_integer() else nr; eval(A.pose_expr, G); bpy.context.view_layer.update()
else:
    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=A.glb)
    _arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); _arm.animation_data.action = bpy.data.actions[A.action]
    for _pb in _arm.pose.bones: _pb.matrix_basis = Matrix()
    f0, f1 = (int(v) for v in _arm.animation_data.action.frame_range)
    nrs = frame_list(A.frames) or list(np.arange(f0, f1 + 1e-6, A.step))
    def set_frame(nr): bpy.context.scene.frame_set(int(nr), subframe=float(nr) - int(nr)); bpy.context.view_layer.update()

arm = max((o for o in bpy.data.objects if o.type == "ARMATURE"), key=lambda o: len(o.pose.bones))
body = max((o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)),
           key=lambda o: len(o.data.vertices))
PROF = rig_of(arm, A.skeleton).prof
AW = arm.matrix_world
dom = np.array([str(d) for d in dominant(body)])
TORSO = PROF.spine[-1]
arm.data.pose_position = "REST"; bpy.context.view_layer.update(); rest = vertices(body, bpy.context.evaluated_depsgraph_get())
arm.data.pose_position = "POSE"; bpy.context.view_layer.update()
heads0 = {b.name: np.array(AW @ b.head_local) for b in arm.data.bones}
SEGS = {s: skin.segments(PROF, s) for s in ("Left", "Right")}
SEL = {s: skin.select(dom, rest, heads0, SEGS[s]) for s in ("Left", "Right")}
SEG_OF = {PROF.short(a): (s, a, b, vb) for s in SEGS for a, b, vb in SEGS[s]}   # report region (bone without prefix) -> segment
H = height(rest[:, 2])


def torso():
    b = arm.data.bones[TORSO]; return np.array((AW @ arm.pose.bones[TORSO].matrix @ b.matrix_local.inverted() @ AW.inverted()).to_3x3())


def head(n): return np.array(AW @ arm.pose.bones[n].head)


rows = []
for nr in nrs:
    set_frame(nr); co = vertices(body, bpy.context.evaluated_depsgraph_get()); Rt = torso(); row = {"frame": float(nr)}
    for s, seg in SEL.items():
        for a, end, _ in SEGS[s]:
            if a not in seg: continue
            b, r = skin.twist(rest, co, seg[a], heads0[a], heads0[end], head(a), head(end), Rt)
            row[PROF.short(a)] = {"twist": round(b), "spread": round(r, 2)}
    rows.append(row)
    print("SKIN fr. %6.1f  " % nr + "  ".join("%s twist %4d deg spread %.2f" % (k, v["twist"], v["spread"]) for k, v in row.items() if k != "frame"), flush=True)

errors = []
for metric, limit, f in (("twist", skin.TWIST_MAX, abs), ("spread", skin.SPREAD_MAX, float)):
    for reg in sorted({k for r in rows for k in r if k != "frame"}):
        bad = [r for r in rows if reg in r and f(r[reg][metric]) > limit]
        if bad:
            worst = max(bad, key=lambda r: f(r[reg][metric]))
            errors.append({"region": reg, "metric": metric, "value": worst[reg][metric], "limit": limit, "frame": worst["frame"],
                           "frames": [r["frame"] for r in bad], "share": round(len(bad) / len(rows), 2)})
report = {"result": "OK" if not errors else "FAIL", "limits": {"twist_deg": skin.TWIST_MAX, "spread": skin.SPREAD_MAX},
          "errors": errors, "frames": rows, "source": A.glb or A.script}
json.dump(report, open(os.path.join(A.out, "skin.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("SKIN %s (%d frames)" % (report["result"], len(rows)))
for e in sorted(errors, key=lambda e: -abs(e["value"]) / e["limit"]):
    print("  FAIL %-14s %-7s %s (limit %s) at fr. %.1f, %d%% of frames: %s" % (
        e["region"], e["metric"], e["value"], e["limit"], e["frame"], round(100 * e["share"]), ",".join("%g" % k for k in e["frames"][:12])))


def closeup(e):
    """game-camera frame on the segment middle: texture + stripes of angle around the arm axis (spiral = twist)"""
    import gpu_queue; gpu_queue.acquire("skin_check.py", None)
    sc = bpy.context.scene; set_frame(e["frame"])
    dg = bpy.context.evaluated_depsgraph_get(); me = bpy.data.meshes.new_from_object(body.evaluated_get(dg), depsgraph=dg)
    me.transform(body.matrix_world); cp = bpy.data.objects.new("skin_copy", me); sc.collection.objects.link(cp)
    hidden = {o: o.hide_render for o in sc.objects}
    for o in sc.objects:
        if o is not cp and o.type in ("MESH", "CURVE"): o.hide_render = True
    s, a, end, _ = SEG_OF[e["region"]]; ii = SEL[s][a]
    a0, b0 = heads0[a], heads0[end]; d0 = (b0 - a0) / np.linalg.norm(b0 - a0)
    ref = np.cross(d0, [0, 0, 1.0]); ref = ref / np.linalg.norm(ref) if np.linalg.norm(ref) > 1e-6 else np.array([1.0, 0, 0]); ref2 = np.cross(d0, ref)
    col = np.tile(np.array([0.55, 0.55, 0.55, 1.0]), (len(me.vertices), 1))
    bones = {x for _, _, xs in SEGS[s] for x in xs}
    m = np.isin(dom, list(bones)); p = rest[m] - a0; ang = np.arctan2(p @ ref2, p @ ref)
    col[m] = np.where((np.floor(ang / (np.pi / 4)) % 2 == 0)[:, None], [0.85, 0.15, 0.1, 1.0], [0.95, 0.9, 0.8, 1.0])
    ca = me.color_attributes.new("stripes", "FLOAT_COLOR", "POINT"); ca.data.foreach_set("color", col.astype(np.float32).ravel())
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); center = Vector(co.reshape(-1, 3)[ii].mean(0))
    cam = bpy.data.objects.new("skin_cam", bpy.data.cameras.new("skin_cam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = "ORTHO"; cam.data.ortho_scale = 1.4 * H          # whole torso with both arms: at 0.75 H a foreshortened arm said nothing
    sc.render.engine = "BLENDER_WORKBENCH"; sc.render.film_transparent = False; sc.render.resolution_x = sc.render.resolution_y = 640
    sc.render.resolution_percentage = 100; sc.display.shading.light = "STUDIO"; sc.view_settings.view_transform = "Standard"
    files = []
    for name, yaw, pitch in (("game", A.yaw, A.pitch), ("front", A.yaw, 5.0)):
        y, pt = math.radians(yaw), math.radians(pitch); d = Vector((math.sin(y) * math.cos(pt), -math.cos(y) * math.cos(pt), math.sin(pt)))
        cam.location = center + d * 10 * H; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler(); cam.data.clip_end = 30 * H
        for colour in ("TEXTURE", "VERTEX"):
            sc.display.shading.color_type = colour
            if colour == "VERTEX": me.color_attributes.active_color = ca
            sc.render.filepath = os.path.join(A.out, "closeups", "%s_%s_fr%g_%s_%s.png" % (e["region"], e["metric"], e["frame"], name, "stripes" if colour == "VERTEX" else "texture"))
            bpy.ops.render.render(write_still=True); files.append(sc.render.filepath)
    for o, h in hidden.items():
        if o is not cp: o.hide_render = h
    bpy.data.objects.remove(cp); bpy.data.meshes.remove(me); bpy.data.objects.remove(cam)
    return files


if errors and not A.no_closeups:
    done = set()
    for e in sorted(errors, key=lambda e: -abs(e["value"]) / e["limit"]):
        if (e["region"], e["frame"]) in done: continue
        done.add((e["region"], e["frame"])); e["closeups"] = closeup(e)
    json.dump(report, open(os.path.join(A.out, "skin.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("closeups:", os.path.join(A.out, "closeups"))
