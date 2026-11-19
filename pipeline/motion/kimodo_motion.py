"""Motion from Kimodo (SOMA, 30 fps) following a motion file: one sentence per phase, body without turning (Root2D), in place
or with "root_speed" travelling forward and saved back in place (kimodo_common.root_track),
optionally hands driven by constraints (with --template: pose from a sample of the no-hands stage). Output: <name>.npz + one BVH per sample.
$KIMODO_PYTHON pipeline/motion/kimodo_motion.py --motion <motion>.json --emb emb.pt --out dir --name n
    [--samples 4] [--seed 0] [--template dir/root.npz:IDX]
Every multi_prompt phase needs at least one constrained frame (otherwise a reshape error inside Kimodo)."""
import argparse, json, os, sys

ap = argparse.ArgumentParser(description="Generate motion samples with Kimodo from per-phase sentences.")
ap.add_argument("--motion", required=True); ap.add_argument("--emb", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--name", required=True); ap.add_argument("--samples", type=int, default=4); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--template", default=None, help="npz:index of a sample from the no-hands stage")
A = ap.parse_args()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import kimodo_common
kimodo_common.setup(os.path.basename(__file__))
import numpy as np, torch
from kimodo.model.load_model import load_model
from kimodo.constraints import Root2DConstraintSet, LeftHandConstraintSet, RightHandConstraintSet

R = json.load(open(A.motion, encoding="utf-8"))
emb = torch.load(A.emb)
texts = [f["text"] for f in R["phases"]]
durs = [f["duration"] for f in R["phases"]]
keep_s = sum(durs)
durs[-1] += R.get("tail_padding", 0.0)   # the end of a Kimodo sequence collapses: generate longer, cut

dev = "cuda:0"
model = load_model(kimodo_common.KIMODO_MODEL, device=dev, text_encoder=kimodo_common.CachedEncoder(emb, dev))
sk30 = model.skeleton; FPS = model.fps
nfs = [int(round(d * FPS)) for d in durs]; T = sum(nfs)
fi = torch.arange(T)
track = kimodo_common.root_track(R, T, FPS, dev)
cons = [Root2DConstraintSet(sk30, fi, track, global_root_heading=torch.tensor([[1.0, 0.0]], device=dev).repeat(T, 1))]

if A.template:
    path, idx = A.template.rsplit(":", 1); d = np.load(path)
    sl = sk30.get_skel_slice(sk30.somaskel77)
    P = torch.from_numpy(d["posed_joints"][int(idx)][:, sl]).float().to(dev)
    Rm = torch.from_numpy(d["global_rot_mats"][int(idx)][:, sl]).float().to(dev)
    bi = sk30.bone_index; NP = P.shape[0]
    D = R["hands"]
    fr, mode = [], []
    for w in D["windows"]:
        a_ = int(round(w["from"] * FPS)); b_ = T - 1 if w["to"] == "end" else int(round(w["to"] * FPS))
        for f in range(a_, b_ + 1, max(1, int(round(w["every"] * FPS)))): fr.append(f); mode.append(w["mode"])
    Pn = torch.stack([P[min(f, NP - 1)] for f in fr]).clone(); Rn = torch.stack([Rm[min(f, NP - 1)] for f in fr]).clone()
    P = P.clone(); P[:, :, [0, 2]] += track[:NP, None]; Pn[:, :, [0, 2]] += track[fr][:, None]   # template saved in place
    tgt_r = torch.tensor(D["right_target_from_shoulder"], device=dev); tgt_l = torch.tensor(D["left_from_right"], device=dev)
    for k, (f, t) in enumerate(zip(fr, mode)):
        if t == "aim":
            src = P[min(f, NP - 1)]; rh = src[bi["RightArm"]] + tgt_r
            tg = {"Right": rh, "Left": rh + tgt_l}
        else:
            # the whole pose from frame 0: a template from the end of a sample may be a crouch and carries into the result
            src = P[0]; Pn[k] = P[0]; Rn[k] = Rm[0]
            tg = {s: P[0][bi[s + "Hand"]] for s in ("Right", "Left")}
        for s in ("Right", "Left"):
            delta = tg[s] - src[bi[s + "Hand"]]
            for n in sk30.bone_order_names:
                if n.startswith(s + "Hand"): Pn[k, bi[n]] = src[bi[n]] + delta
    fr_t = torch.tensor(fr)
    for cls in (LeftHandConstraintSet, RightHandConstraintSet):
        cons.append(cls(sk30, fr_t, Pn, Rn, torch.zeros(len(fr), 2, device=dev)))
    bounds = np.cumsum([0] + nfs)
    for i in range(len(nfs)):
        if not any(bounds[i] <= f < bounds[i + 1] for f in fr):
            raise SystemExit("phase %d has no hand-constrained frame - Kimodo would fail on reshape" % (i + 1))
    print("hands: frames", fr)

torch.manual_seed(A.seed); np.random.seed(A.seed)
os.makedirs(A.out, exist_ok=True)
out = model(texts, nfs, constraint_lst=cons, num_denoising_steps=100, num_samples=A.samples, multi_prompt=True,
            num_transition_frames=5, post_processing=False, return_numpy=True)
keep = int(round(keep_s * FPS))
pj, gr = kimodo_common.back_in_place(out["posed_joints"][:, :keep], track), out["global_rot_mats"][:, :keep]
np.savez(os.path.join(A.out, A.name + ".npz"), posed_joints=pj, global_rot_mats=gr)
kimodo_common.save_bvhs(A.out, A.name, pj, gr, sk30, A.samples, dev, FPS)
