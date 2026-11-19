"""Actions processed separately (each from the same merged file) -> one GLB; every action put on the ground of action --ground.
blender -b --python pipeline/motion/combine_actions.py -- --base merged.glb [--action walk=after_walk.glb ...] [--ground walk] --out x.glb
Why not a chain (output of one step as input of the next): every GLB export reorders vertices, and the grip solver
samples prop vertices by index - a shot processed after the walk differed from the approved one by 2 cm and 3 deg.
Ground: a Kimodo clip stood 0.5 m lower than the library walk, and in game the sprite jumped ~35 px on every clip change."""
import argparse, sys
import bpy
from mathutils import Vector

ap = argparse.ArgumentParser(description="Combine separately processed actions into one GLB and align them to one ground.")
ap.add_argument("--base", required=True); ap.add_argument("--action", action="append", default=[]); ap.add_argument("--out", required=True)
ap.add_argument("--ground", default="walk", help="reference action: the lowest foot point of every action = its lowest point; "
                "@rest = the rest pose's feet ('' = off)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=A.base)
base = set(bpy.data.objects)
for entry in A.action:
    n, path = entry.split("=", 1)
    objs_before, acts_before = set(bpy.data.objects), set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [a for a in set(bpy.data.actions) - acts_before]
    act = next(a for a in new if a.name.split(".")[0] == n)
    old = bpy.data.actions.get(n)
    if old is None: raise SystemExit("no action %s in the base" % n)
    old.user_clear(); bpy.data.actions.remove(old)
    act.name = n; act.use_fake_user = True
    for a in new:
        if a is not act: bpy.data.actions.remove(a)
    for o in set(bpy.data.objects) - objs_before: bpy.data.objects.remove(o, do_unlink=True)
    print("action", n, "<-", path)
arm = next(o for o in base if o.type == "ARMATURE")


def curves(act):
    for layer in act.layers:
        for strip in layer.strips:
            for slot in act.slots:
                cb = strip.channelbag(slot)
                if cb: yield from cb.fcurves


def feet_min(act):
    """lowest head of foot and toe bones over the whole clip (every 2nd frame); tails from GLB are meaningless (bone lengths)"""
    arm.animation_data.action = act
    if act.slots: arm.animation_data.action_slot = act.slots[0]
    bones = [b for b in arm.pose.bones if "foot" in b.name.lower() or "toe" in b.name.lower()]
    a, b = (int(x) for x in act.frame_range)
    z = 1e9
    for f in range(a, b + 1, 2):
        bpy.context.scene.frame_set(f)
        z = min(z, *((arm.matrix_world @ k.head).z for k in bones))
    return z


def rest_feet_min():
    """lowest head of foot and toe bones in the rest pose: the auto-rig builds the rest pose on the mesh standing on the floor"""
    return min((arm.matrix_world @ b.head_local).z for b in arm.data.bones if "foot" in b.name.lower() or "toe" in b.name.lower())


if A.ground:
    if A.ground == "@rest":
        z0 = rest_feet_min()
    else:
        ref = bpy.data.actions.get(A.ground)
        if ref is None: raise SystemExit("--ground %s: no such action (or @rest)" % A.ground)
        z0 = feet_min(ref)
    hips = next(b for b in arm.pose.bones if "hips" in b.name.lower())
    for act in bpy.data.actions:
        dz = z0 - feet_min(act)
        if abs(dz) < 0.002: continue
        bpy.context.scene.frame_set(int(act.frame_range[0]))
        # world offset -> space of the hips `location` (with the parent and rig scale)
        m = (arm.matrix_world @ hips.matrix @ hips.matrix_basis.inverted()).to_3x3()
        d = m.inverted() @ Vector((0.0, 0.0, dz))
        path = 'pose.bones["%s"].location' % hips.name
        track = {c.array_index: c for c in curves(act) if c.data_path == path}
        if len(track) < 3: raise SystemExit("action %s: hips without location curves, cannot ground it" % act.name)
        for i in range(3):
            for k in track[i].keyframe_points:
                k.co.y += d[i]; k.handle_left.y += d[i]; k.handle_right.y += d[i]
        print("ground: %s moved by %+.3f m (to %s)" % (act.name, dz, A.ground))
arm.animation_data.action = None
bpy.ops.export_scene.gltf(filepath=A.out, export_format="GLB", export_animations=True)
print("COMBINE OK", A.out)
