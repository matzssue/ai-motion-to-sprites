"""Review preview: every action from 8 directions (game camera: 30 deg down), 8 frames per row -> <action>.png.
blender -b --python pipeline/review/preview_8.py -- --glb X.glb --actions walk,attack --out dir [--count 8] [--px 320]
Not a replacement for your sprite-sheet renderer: just an eye on the motion before review."""
import bpy, sys, os, math, json, argparse
import numpy as np
from mathutils import Matrix, Vector

ap = argparse.ArgumentParser(description="Render each action from 8 isometric directions.")
ap.add_argument("--glb", required=True); ap.add_argument("--actions", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--count", type=int, default=8); ap.add_argument("--px", type=int, default=320)
ap.add_argument("--frames", default=None, help="exactly these frames, e.g. key poses: 0,44")
ap.add_argument("--all", action="store_true", help="every frame separately to out/<action>/<dir>_NNN.png (for review pages)")
ap.add_argument("--directions", default=None, help="only these directions, e.g. s (front to the game camera)")
ap.add_argument("--every", type=int, default=1, help="with --all: every n-th frame")
ap.add_argument("--pitch", type=float, default=30.0, help="game camera pitch (deg)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")); import gpu_queue; gpu_queue.acquire("preview_8.py", None)  # Eevee on the GPU
# relative paths are the caller's (Blender keeps the shell's cwd); a cwd at a drive root or in Blender's own folder means the
# caller is a launcher, and a relative --out landed on C:\ without a word once: refuse instead of guessing
_cwd = os.getcwd()
if not (os.path.isabs(A.out) and os.path.isabs(A.glb)) and (
        os.path.splitdrive(_cwd)[1] in ("", os.sep, "/") or os.path.normcase(_cwd).startswith(os.path.normcase(os.path.dirname(bpy.app.binary_path)))):
    raise SystemExit("preview_8: Blender runs in %s; give --glb and --out as absolute paths" % _cwd)
A.out, A.glb = os.path.abspath(A.out), os.path.abspath(A.glb)
print("preview_8: writing to", A.out, flush=True)
os.makedirs(A.out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=A.glb)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x = sc.render.resolution_y = A.px
sc.render.film_transparent = False; sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.33, 0.35, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 1.6
for rot, e in (((50, 0, 30), 3.5), ((60, 0, 210), 1.5)):
    s = bpy.data.objects.new("s", bpy.data.lights.new("s", "SUN")); s.data.energy = e
    s.rotation_euler = [math.radians(v) for v in rot]; sc.collection.objects.link(s)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"
DIRS = [("s", 0), ("sw", 45), ("w", 90), ("nw", 135), ("n", 180), ("ne", 225), ("e", 270), ("se", 315)]
if A.directions: DIRS = [k for k in DIRS if k[0] in A.directions.split(",")]


def bbox():
    dg = bpy.context.evaluated_depsgraph_get(); pts = []
    for o in meshes:
        e = o.evaluated_get(dg); m = e.to_mesh()
        pts += [tuple(o.matrix_world @ m.vertices[i].co) for i in range(0, len(m.vertices), 25)]; e.to_mesh_clear()
    p = np.array(pts); return p.min(0), p.max(0)


result = {}
for action in A.actions.split(","):
    arm.animation_data.action = bpy.data.actions[action]
    for pb in arm.pose.bones: pb.matrix_basis = Matrix()   # bones without curves: rest, not a pose from another action
    f0, f1 = arm.animation_data.action.frame_range
    frames = [f0 + (f1 - f0) * i / (A.count - 1) for i in range(A.count)]
    if A.frames: frames = [float(x) for x in A.frames.split(",")]
    if A.all: frames = [float(f) for f in range(int(f0), int(f1) + 1, A.every)]; os.makedirs(os.path.join(A.out, action), exist_ok=True)
    lo, hi = np.full(3, 9e9), np.full(3, -9e9)
    for f in frames:
        sc.frame_set(int(f)); a, b = bbox(); lo, hi = np.minimum(lo, a), np.maximum(hi, b)
    center = Vector((lo + hi) / 2); cam.data.ortho_scale = float((hi - lo).max()) * 1.15
    grid = np.zeros((A.px * len(DIRS), A.px * len(frames), 4), np.float32)
    for wi, (kn, yaw) in enumerate(DIRS):
        d = Vector((math.sin(math.radians(yaw)), -math.cos(math.radians(yaw)), math.tan(math.radians(A.pitch)))).normalized()
        cam.location = center + d * 6; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        for ki, f in enumerate(frames):
            sc.frame_set(int(f), subframe=f - int(f))
            p = os.path.join(A.out, action, "%s_%03d.png" % (kn, ki)) if A.all else os.path.join(A.out, "_tmp.png")
            sc.render.filepath = p; bpy.ops.render.render(write_still=True)
            if A.all: continue
            im = bpy.data.images.load(p); px = np.array(im.pixels[:], np.float32).reshape(A.px, A.px, 4)
            bpy.data.images.remove(im)
            y0 = (len(DIRS) - 1 - wi) * A.px   # Blender images grow from the bottom
            grid[y0:y0 + A.px, ki * A.px:(ki + 1) * A.px] = px
    if A.all: print("action", action, len(frames), "frames x", len(DIRS)); continue
    out = bpy.data.images.new(action, A.px * len(frames), A.px * len(DIRS), alpha=True)
    out.pixels = grid.ravel(); out.filepath_raw = os.path.join(A.out, action + ".png"); out.file_format = "PNG"; out.save()
    result[action] = {"file": action + ".png", "rows": [k for k, _ in DIRS], "frames": [round(f, 2) for f in frames]}
    print("action", action, "->", out.filepath_raw)
if os.path.exists(os.path.join(A.out, "_tmp.png")): os.remove(os.path.join(A.out, "_tmp.png"))
json.dump(result, open(os.path.join(A.out, "done.json"), "w"), indent=1)
print("PREVIEW OK", A.out)
