"""Merge several single-animation files (FBX/GLB on the same skeleton) into ONE GLB with named actions.
blender -b --python pipeline/motion/merge_actions.py -- --base=rig.(fbx|glb) --anim=walk=walk.fbx --anim=attack=clip.glb --out=out.glb
    [--skip-fingers] [--skeleton=mixamo|profile.json]
Mixamo exports every animation as its own FBX with the whole character repeated; a sprite renderer wants one GLB
with all actions, so every frame comes from the same mesh, camera and scale fit.
A clip bone goes to the base bone of the same role (library clips use the Mixamo skeleton, the base its --skeleton profile),
then to the same name, then to the same name without the profile prefix (fingers). A clip whose bones match none of these
moves nothing - and reports no error, apart from the count of shared bones."""
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import skeleton  # noqa: E402


def parse_args(argv):
    """Arguments after `--`; `--anim` may repeat, hence not a plain dict."""
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parsed = {"anims": []}
    for argument in argv:
        if argument in ("-h", "--help"):
            print(__doc__); raise SystemExit(0)
        clean = argument.lstrip("-")
        if "=" not in clean:
            parsed[clean] = True
            continue
        key, value = clean.split("=", 1)
        if key == "anim":
            name, _, path = value.partition("=")
            parsed["anims"].append((name, path))
        else:
            parsed[key] = value
    return parsed


def import_file(path):
    """Imports and returns the set of objects that arrived."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise SystemExit("merge_actions: missing file %s" % path)
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise SystemExit("merge_actions: unsupported format %s" % ext)
    return set(bpy.data.objects) - before


FINGER_HINTS = ("thumb", "index", "middle", "ring", "pinky")


def is_finger_bone(name):
    return any(h in name.lower() for h in FINGER_HINTS)


def bone_map(source, target, base_prof):
    """{base bone: clip bone}: by role from the library (Mixamo) skeleton, by name, by name without the prefix."""
    lib = skeleton.load()
    by_role = {b: a for a, b in lib.same_roles(base_prof)}
    out = {}
    for b in target.pose.bones:
        for n in (by_role.get(b.name), b.name, lib.prefix + base_prof.short(b.name)):
            if n and n in source.pose.bones: out[b.name] = n; break
    return out


def retarget_action(source, target, name, skip_fingers=False, base_prof=None):
    """Copies the animation from the SOURCE skeleton onto the BASE one, frame by frame, via `pose_bone.matrix`.

    Why not just reassign the action: curves are LOCAL rotations relative to the skeleton REST POSE, and Mixamo's
    "With Skin" and "Without Skin" exports have rest poses 31 deg apart in the upper arms and 35 deg in the forearms.
    A naive transplant squeezed every animation's arms ~31 deg towards the torso, with zero errors in the log.
    `pose_bone.matrix` is in armature space, so it does not depend on the rest pose and the difference cancels out.
    Parents before children: a child's `matrix` is relative to the ALREADY placed parent.
    --skip-fingers: Mixamo places finger bones even when the mesh has nothing to deform; on a mitten-like hand they get
    random weights and TEAR the mesh. Skipped bones stay at rest, where the mesh was skinned, so it stays intact.
    """
    action = source.animation_data.action
    start, end = int(action.frame_range[0]), int(action.frame_range[1])
    src_of = bone_map(source, target, base_prof) if base_prof else {b.name: b.name for b in target.pose.bones if b.name in source.pose.bones}
    shared = [b.name for b in target.pose.bones if b.name in src_of]
    if not shared:
        raise SystemExit("merge_actions: skeletons share no bones")
    if len(shared) != len(target.pose.bones):
        print("merge_actions: WARNING - %d of %d bones shared" % (len(shared), len(target.pose.bones)))
    if skip_fingers:
        shared = [n for n in shared if not is_finger_bone(n)]
    ordered = sorted(shared, key=lambda n: len(target.pose.bones[n].parent_recursive))
    for bone in target.pose.bones:
        bone.rotation_mode = "QUATERNION"
    baked = bpy.data.actions.new(name)
    baked.use_fake_user = True
    target.animation_data.action = baked     # the base file's own action must step aside, or frame_set overwrites the pose
    scene = bpy.context.scene
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for bone_name in ordered:
            bone = target.pose.bones[bone_name]
            bone.matrix = source.pose.bones[src_of[bone_name]].matrix.copy()
            # a bone NOT connected to its parent also got the head POSITION of the clip dummy; with other proportions
            # toes and fingers were torn to splinters (18% of foot edges). Only the root moves.
            if bone.parent is not None:
                bone.location = (0.0, 0.0, 0.0)
            bpy.context.view_layer.update()
        for bone_name in ordered:
            bone = target.pose.bones[bone_name]
            bone.keyframe_insert("location", frame=frame)
            bone.keyframe_insert("rotation_quaternion", frame=frame)
            bone.keyframe_insert("scale", frame=frame)
    return baked


def find_armature(objects):
    return next((o for o in objects if o.type == "ARMATURE"), None)


def main():
    args = parse_args(sys.argv)
    base, out, anims = args.get("base", ""), args.get("out", ""), args["anims"]
    if not base or not out or not anims:
        raise SystemExit("merge_actions: --base, --out and at least one --anim are required")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    base_objects = import_file(base)
    armature = find_armature(base_objects)
    if armature is None:
        raise SystemExit("merge_actions: %s has no skeleton" % base)
    if armature.animation_data is None:
        armature.animation_data_create()
    collected = []
    # without --skeleton: same names only, as before profiles (the game calls this on rigs of any naming)
    base_prof = skeleton.for_rig(args["skeleton"], {b.name: b.parent.name if b.parent else None for b in armature.data.bones}).prof         if args.get("skeleton") else None
    for name, path in anims:
        imported = import_file(path)
        source = find_armature(imported)
        if source is None or source.animation_data is None or source.animation_data.action is None:
            print("merge_actions: SKIPPING '%s' - no action in %s" % (name, path))
            for obj in imported: bpy.data.objects.remove(obj, do_unlink=True)
            continue
        action = retarget_action(source, armature, name, "skip-fingers" in args, base_prof)
        # THE NAME MUST BE EXACT: when the clip file carries an action with the same name, Blender renames the new one
        # to `<name>.001`, the export writes it under that name and a renderer looking for the original finds nothing.
        if action.name != name:
            raise SystemExit("merge_actions: action '%s' landed as '%s' - name clash with an action already in %s. "
                             "Rename the action IN THE CLIP FILE." % (name, action.name, os.path.basename(path)))
        collected.append(action)
        print("merge_actions: '%s' <- %s (%.2f s)" % (name, os.path.basename(path),
              (action.frame_range[1] - action.frame_range[0]) / bpy.context.scene.render.fps))
        for obj in imported:    # mesh and skeleton of the clip duplicate the base
            bpy.data.objects.remove(obj, do_unlink=True)
    if not collected:
        raise SystemExit("merge_actions: no action collected")
    for action in list(bpy.data.actions):   # the base file brings its own generically named action
        if action not in collected:
            bpy.data.actions.remove(action)
    armature.animation_data.action = collected[0]
    bpy.context.scene.frame_set(int(collected[0].frame_range[0]))
    out_path = os.path.abspath(out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB", export_animation_mode="ACTIONS",
                              export_animations=True, export_apply=False)
    print("merge_actions: %s (%d animations: %s)" % (out, len(collected), ", ".join(a.name for a in collected)))


if __name__ == "__main__":
    main()
