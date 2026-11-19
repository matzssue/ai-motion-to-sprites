"""Close-ups of both hands on the prop at chosen frames, 3 sides (the audit cannot see "unnatural").
blender -b --python pipeline/review/hand_closeups.py -- --glb X.glb --action attack --frames 10,45,56,85 --out dir [--skeleton X]"""
import bpy, sys, os, math, argparse
from mathutils import Matrix, Vector

ap = argparse.ArgumentParser(description="Render front/side/below close-ups of both hands at given frames.")
ap.add_argument("--glb", required=True); ap.add_argument("--action", required=True)
ap.add_argument("--frames", required=True); ap.add_argument("--out", required=True); ap.add_argument("--px", type=int, default=480)
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")); import gpu_queue; gpu_queue.acquire("hand_closeups.py", None)  # Eevee on the GPU
from collisions import rig_of  # noqa: E402
os.makedirs(A.out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=A.glb)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); arm.animation_data.action = bpy.data.actions[A.action]
# bones without curves in this action keep the pose of another action in the file: start from rest
for _pb in arm.pose.bones: _pb.matrix_basis = Matrix()
PROF = rig_of(arm, A.skeleton).prof
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x = sc.render.resolution_y = A.px
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.33, 0.35, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 2.5
for rot, e in (((50, 0, 30), 4), ((60, 0, 200), 2)):
    s = bpy.data.objects.new("s", bpy.data.lights.new("s", "SUN")); s.data.energy = e
    s.rotation_euler = [math.radians(v) for v in rot]; sc.collection.objects.link(s)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; cam.data.ortho_scale = 0.42
for f in [float(x) for x in A.frames.split(",")]:
    sc.frame_set(int(f), subframe=f - int(f))
    for side in ("Right", "Left"):
        b = arm.pose.bones[PROF.bone("hand", side)]
        target = arm.matrix_world @ (b.head + (b.tail - b.head).normalized() * 0.1 / arm.matrix_world.to_scale()[0])
        for nm, yaw, el in (("front", 0, 15), ("side", -90 if side == "Right" else 90, 15), ("below", 0, -60)):
            d = Vector((math.sin(math.radians(yaw)) * math.cos(math.radians(el)), -math.cos(math.radians(yaw)) * math.cos(math.radians(el)),
                        math.sin(math.radians(el))))
            cam.location = target + d * 3; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(A.out, "fr%03d_%s_%s.png" % (int(f), side, nm)); bpy.ops.render.render(write_still=True)
print("CLOSEUPS OK", A.out)
