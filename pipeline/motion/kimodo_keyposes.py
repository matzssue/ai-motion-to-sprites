"""Motion from Kimodo through key poses (FullBodyConstraintSet): poses reviewed BEFORE generation, Kimodo fills the rest.
Poses = a Kimodo base sample with bones rotated by the difference "posed vs the same frame after retarget" (keyposes_to_kimodo.py).
$KIMODO_PYTHON pipeline/motion/kimodo_keyposes.py --motion <motion>.json --emb emb.pt --base e1/body.npz:2
    --poses poses.json --keys 0:0,55:44,125:0 --out dir --name kf     (Kimodo frame at 30 fps : pose frame at 24 fps)
A multi_prompt phase without a key frame crashed Kimodo on reshape: `Poses.crop_move` returns an empty set then."""
import argparse, json, os, sys

ap = argparse.ArgumentParser(description="Generate motion with Kimodo constrained by full-body key poses.")
ap.add_argument("--motion", required=True); ap.add_argument("--emb", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--name", required=True); ap.add_argument("--samples", type=int, default=4); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--base", required=True); ap.add_argument("--poses", required=True)
ap.add_argument("--keys", required=True, help="Kimodo frame:pose frame (24 fps), e.g. 0:0,55:44,125:0")
A = ap.parse_args()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import kimodo_common
kimodo_common.setup(os.path.basename(__file__))
import numpy as np, torch
from kimodo.model.load_model import load_model
from kimodo.skeleton import global_rots_to_local_rots
from kimodo.constraints import Root2DConstraintSet, FullBodyConstraintSet

R = json.load(open(A.motion, encoding="utf-8")); emb = torch.load(A.emb)
texts = [f["text"] for f in R["phases"]]; durs = [f["duration"] for f in R["phases"]]
keep_s = sum(durs); durs[-1] += R.get("tail_padding", 0.0)


class Poses(FullBodyConstraintSet):
    """A multi_prompt phase without a key frame gets an empty set and Kimodo crashes on reshape: the empty one adds nothing."""
    def crop_move(self, start, end):
        m = (self.frame_indices >= start) & (self.frame_indices < end)
        if not bool(m.any()): return Empty()
        return Poses(self.skeleton, self.frame_indices[m] - start, self.global_joints_positions[m], self.global_joints_rots[m], self.smooth_root_2d[m])


class Empty:
    name = "fullbody"
    def update_constraints(self, data_dict, index_dict): pass
    def crop_move(self, start, end): return self
    def to(self, *a, **k): return self


dev = "cuda:0"
model = load_model(kimodo_common.KIMODO_MODEL, device=dev, text_encoder=kimodo_common.CachedEncoder(emb, dev))
sk30 = model.skeleton; FPS = model.fps; sk77 = sk30.somaskel77.to(dev)
nfs = [int(round(d * FPS)) for d in durs]; T = sum(nfs)
path, idx = A.base.rsplit(":", 1); d = np.load(path)
P = torch.from_numpy(d["posed_joints"][int(idx)]).float().to(dev); G = torch.from_numpy(d["global_rot_mats"][int(idx)]).float().to(dev)
W = json.load(open(A.poses))
M = torch.tensor([[1.0, 0, 0], [0, 0, -1], [0, 1, 0]], device=dev)          # Kimodo (Y up) -> Blender (Z up)
bi = sk77.bone_index; par = sk77.joint_parents.tolist(); names = sk77.bone_order_names
for n, v in W["control"].items():
    print("axes %-9s Blender %s | from Kimodo %s" % (n, np.round(v, 1), np.round((M @ P[55, bi[n]] * 100).cpu().numpy(), 1)))
C = torch.tensor(W["C"], device=dev); Gt = C @ M                              # Kimodo -> character world
sl = sk30.get_skel_slice(sk77)
keys = [tuple(int(x) for x in k.split(":")) for k in A.keys.split(",")]
pos, rot = [], []
for fk, fb in keys:
    fb0 = int(round(fb * FPS / 24)); Go = G[fb0]; loc = global_rots_to_local_rots(Go[None], sk77)[0]
    _, spr, _ = sk77.fk(loc[None], P[fb0, sk77.root_idx][None])
    Gn = Go.clone()
    for j, n in enumerate(names):
        if n in W["D"][str(fb)]:
            Dk = Gt.T @ torch.tensor(W["D"][str(fb)][n], device=dev) @ Gt; Gn[j] = Dk @ Go[j]
        elif par[j] >= 0: Gn[j] = Gn[par[j]] @ loc[j]
    locn = global_rots_to_local_rots(Gn[None], sk77)[0]
    _, pn, _ = sk77.fk(locn[None], P[fb0, sk77.root_idx][None])
    print("Kimodo key %3d <- pose fr. %2d (base %d): FK check %.4f m, hands moved R %.2f m, L %.2f m" % (
        fk, fb, fb0, float((spr[0] - P[fb0]).norm(dim=-1).max()),
        float((pn[0, bi["RightHand"]] - P[fb0, bi["RightHand"]]).norm()), float((pn[0, bi["LeftHand"]] - P[fb0, bi["LeftHand"]]).norm())))
    pos.append(pn[0][sl]); rot.append(Gn[sl])
track = kimodo_common.root_track(R, T, FPS, dev)
fr = torch.tensor([k[0] for k in keys])
for p, fk in zip(pos, fr.tolist()): p[:, [0, 2]] += track[fk]   # the base sample was saved in place
rest = torch.tensor([f for f in range(T) if f not in set(fr.tolist())])
cons = [Root2DConstraintSet(sk30, rest, track[rest],
                            global_root_heading=torch.tensor([[1.0, 0.0]], device=dev).repeat(len(rest), 1)),
        Poses(sk30, fr, torch.stack(pos), torch.stack(rot))]
torch.manual_seed(A.seed); np.random.seed(A.seed)
os.makedirs(A.out, exist_ok=True)
out = model(texts, nfs, constraint_lst=cons, num_denoising_steps=100, num_samples=A.samples, multi_prompt=True,
            num_transition_frames=5, post_processing=False, return_numpy=True)
keep = int(round(keep_s * FPS))
pj, gr = out["posed_joints"][:, :keep], out["global_rot_mats"][:, :keep]
for (fk, fb), target in zip(keys, pos):
    if fk < keep:
        e = np.linalg.norm(pj[:, fk][:, sl] - target.cpu().numpy()[None], axis=-1)
        print("hit on pose fr. %3d: mean %.3f m, max %.3f m (per sample: %s)" % (fk, e.mean(), e.max(), np.round(e.max(1), 3)))
pj = kimodo_common.back_in_place(pj, track)
np.savez(os.path.join(A.out, A.name + ".npz"), posed_joints=pj, global_rot_mats=gr)
kimodo_common.save_bvhs(A.out, A.name, pj, gr, sk30, A.samples, dev, FPS)
