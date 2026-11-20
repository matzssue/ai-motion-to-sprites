"""Key poses by hand: a Blender scene of one sample to pose in, and its export back to a poses GLB.
blender -b --python pipeline/review/pose_edit_scene.py -- --glb <poses.glb> --action attack --frames 0,30 --names crouch,rake
    --sample <body_sN.bvh> --out <work>/<action>/poses_by_hand/edit.blend
blender -b --python pipeline/review/pose_edit_scene.py -- --export <edit.blend> --out <work>/<action>/poses_by_hand/poses.glb
The scene: bone shapes off, bones drawn as sticks in front of the mesh, one marker per key pose, auto-key on. An existing
.blend is never overwritten (it may hold the author's work). The export writes the armature and its meshes with every action,
plus <out>.json naming the sample the poses were set on: character.py refuses poses from another sample (wrong deltas,
no error otherwise)."""
import argparse, json, os, sys
import bpy

ap = argparse.ArgumentParser(description="Build a scene to pose key frames by hand, or export the posed scene to a GLB.")
ap.add_argument("--glb"); ap.add_argument("--action"); ap.add_argument("--frames"); ap.add_argument("--names", default="")
ap.add_argument("--sample", help="BVH of the sample this GLB was retargeted from"); ap.add_argument("--export", help="posed .blend")
ap.add_argument("--out", required=True)
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
A.out = os.path.abspath(A.out)

if A.export:
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.export))
    sc = bpy.context.scene; arm = next(o for o in sc.objects if o.type == "ARMATURE")
    for o in sc.objects: o.select_set(o is arm or (o.type == "MESH" and any(m.type == "ARMATURE" and m.object is arm for m in o.modifiers)))
    os.makedirs(os.path.dirname(A.out), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=A.out, export_format="GLB", use_selection=True, export_animations=True,
                              export_animation_mode="ACTIONS", export_force_sampling=True)
    meta = {k: sc.get("amts_" + k) for k in ("sample", "action", "frames", "names")}
    meta["frames"] = list(meta["frames"] or []); meta["names"] = list(meta["names"] or [])
    json.dump(meta, open(A.out + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("POSES EXPORT OK", A.out, "| sample", meta["sample"], "| frames", meta["frames"])
    raise SystemExit(0)

if not (A.glb and A.action and A.frames): ap.error("--glb, --action and --frames are needed to build the scene")
if os.path.exists(A.out):
    print("EDIT SCENE KEPT", A.out, "(exists: it may hold posing work; delete it to build again)"); raise SystemExit(0)
frames = [int(x) for x in A.frames.split(",")]
names = [x for x in A.names.split(",") if x] or ["pose_%d" % f for f in frames]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
act = next((a for a in bpy.data.actions if a.name == A.action), None) or next(a for a in bpy.data.actions if a.name.startswith(A.action))
arm.animation_data.action = act
shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
for pb in arm.pose.bones: pb.custom_shape = None   # glTF import draws bones as spheres that hide the mesh
for o in shapes: bpy.data.objects.remove(o)
arm.show_in_front = True; arm.data.display_type = "STICK"
sc.frame_start, sc.frame_end = int(act.frame_range[0]), int(act.frame_range[1])
for f, n in zip(frames, names): sc.timeline_markers.new(n, frame=f)
sc.frame_current = frames[-1]
sc.tool_settings.use_keyframe_insert_auto = True
sc["amts_sample"] = os.path.abspath(A.sample).replace("\\", "/") if A.sample else ""
sc["amts_action"] = act.name; sc["amts_frames"] = frames; sc["amts_names"] = names
for o in sc.objects: o.select_set(o is arm)
bpy.context.view_layer.objects.active = arm
os.makedirs(os.path.dirname(A.out), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=A.out)
print("EDIT SCENE OK", A.out, "| action", act.name, "| frames", ",".join(map(str, frames)), "| markers", ",".join(names))
