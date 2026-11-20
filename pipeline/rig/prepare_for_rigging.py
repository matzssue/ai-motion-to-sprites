"""Prepare a model from a 3D generator for rigging: decimate, shrink the texture, export FBX with the texture embedded.
blender -b --python pipeline/rig/prepare_for_rigging.py -- --src=model.glb --out=model_for_rig.fbx [--tris=25000] [--texture=1024]
    [--prop=prop.glb]
--prop: a separate prop mesh in the model's frame (where it rests on the body); its objects are renamed `amts_prop*`, so the
auto-rig detects joints on the body alone (a pole on Flisak's back put the head top on its knob) and prepare_rig takes it whole.
Generators output product-render detail (hundreds of thousands of triangles, 4K textures) that a ~100 px sprite cannot show;
it only slows every later step and auto-riggers reject heavy files. A separate PNG next to the FBX gets lost on upload."""
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from stages import PROP_MESH  # noqa: E402


def parse_args(argv):
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parsed = {}
    for argument in argv:
        if argument in ("-h", "--help"):
            print(__doc__); raise SystemExit(0)
        key, _, value = argument.lstrip("-").partition("=")
        parsed[key] = value if value else True
    return parsed


def import_file(path):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise SystemExit("prepare_for_rigging: missing file %s" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise SystemExit("prepare_for_rigging: unsupported format %s" % ext)


def count_triangles(meshes):
    total = 0
    for obj in meshes:
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
    return total


def main():
    args = parse_args(sys.argv)
    src, out = args.get("src", ""), args.get("out", "")
    if not src or not out:
        raise SystemExit("prepare_for_rigging: --src and --out are required")
    target_tris = int(args.get("tris", 0) or 0)
    texture_size = int(args.get("texture", 0) or 0)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_file(src)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("prepare_for_rigging: the model has no mesh")
    if any(o.name.startswith(PROP_MESH) for o in meshes):
        raise SystemExit("prepare_for_rigging: the model has objects named %s* - that prefix marks a separate prop" % PROP_MESH)
    if args.get("prop"):
        before = set(bpy.data.objects)
        import_file(args["prop"])
        props = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
        if not props:
            raise SystemExit("prepare_for_rigging: the prop %s has no mesh" % args["prop"])
        for o in props:
            o.name = o.data.name = PROP_MESH
        meshes += props
        print("prepare_for_rigging: separate prop %s - %d meshes, %d vertices" % (os.path.basename(args["prop"]), len(props),
                                                                                sum(len(o.data.vertices) for o in props)))
    # glTF import splits vertices at UV seams. Without welding, Decimate pulls seam edges apart and the mesh becomes
    # a shell with holes (0 -> 29k open edges), which breaks auto-rig weights.
    for obj in meshes:
        bm = bmesh.new(); bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bm.to_mesh(obj.data); bm.free()
    before = count_triangles(meshes)
    print("prepare_for_rigging: %d meshes, %d triangles" % (len(meshes), before))
    if target_tris > 0 and before > target_tris:
        ratio = float(target_tris) / float(before)
        for obj in meshes:
            mod = obj.modifiers.new(name="Decimate", type="DECIMATE")
            mod.ratio = ratio
            bpy.context.view_layer.objects.active = obj     # applying needs an active object; none in --background
            bpy.ops.object.modifier_apply(modifier=mod.name)
        print("prepare_for_rigging: ratio %.3f -> %d triangles" % (ratio, count_triangles(meshes)))
    if texture_size > 0:
        for image in bpy.data.images:
            if image.size[0] > texture_size or image.size[1] > texture_size:
                print("prepare_for_rigging: texture '%s' %dx%d -> %dx%d" % (image.name, image.size[0], image.size[1], texture_size, texture_size))
                image.scale(texture_size, texture_size)
    out_path = os.path.abspath(out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=out_path, path_mode="COPY", embed_textures=True, add_leaf_bones=False, bake_anim=False)
    print("prepare_for_rigging: %s (%.1f MB)" % (out_path, os.path.getsize(out_path) / 2 ** 20))


if __name__ == "__main__":
    main()
