"""Shared setup for scripts run with Kimodo's Python (KIMODO_PYTHON): HF_HOME, Kimodo source on sys.path, GPU lock,
and a stand-in text encoder that serves precomputed sentence embeddings from kimodo_text.py."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import KIMODO_DIR, KIMODO_MODEL  # noqa: E402

os.environ.setdefault("HF_HOME", os.path.join(KIMODO_DIR, "hf"))
sys.path.insert(0, os.path.join(KIMODO_DIR, "repo"))


def setup(who):
    import gpu_queue
    gpu_queue.acquire(who)


class CachedEncoder:
    """Pretends to be Kimodo's text encoder, returning ready embeddings from kimodo_text.py."""
    def __init__(self, d, dev="cuda:0"): self.d, self.dev = d, dev
    def to(self, device): self.dev = device; return self
    def eval(self): return self
    def get_device(self):
        import torch
        return torch.device(self.dev)
    def __call__(self, text):
        import torch
        one = isinstance(text, str); lst = [text] if one else list(text)
        e = torch.stack([self.d[t].reshape(-1) for t in lst])[:, None].to(self.dev)
        return (e[0], 1) if one else (e, [1] * len(lst))


def root_track(motion, n_frames, fps, dev):
    """Root (x, z) per Kimodo frame, facing +Z (heading [1, 0]). In place unless the motion file sets "root_speed" (m/s):
    a run pinned in place comes out as a standing pose (all 4 samples of a sprint moved < 0.2 deg), so locomotion travels
    forward during generation and back_in_place() removes the travel before saving."""
    import torch
    z = torch.arange(n_frames, device=dev, dtype=torch.float32) * (float(motion.get("root_speed", 0.0)) / fps)
    return torch.stack([torch.zeros_like(z), z], dim=-1)


def back_in_place(pj, track):
    """posed_joints [samples, frames, joints, 3] minus the commanded root travel (Y up: travel on x, z)."""
    t = track[:pj.shape[1]].cpu().numpy()
    pj = pj.copy(); pj[..., 0] -= t[None, :, 0, None]; pj[..., 2] -= t[None, :, 1, None]
    return pj


def save_bvhs(out_dir, name, pj, gr, sk30, n_samples, dev, fps):
    """BVH per sample on the SOMA77 skeleton (T-pose) for soma_to_mixamo.py."""
    import torch
    from kimodo.exports.bvh import save_motion_bvh
    from kimodo.skeleton import SOMASkeleton30, global_rots_to_local_rots
    sk = sk30.somaskel77.to(dev) if isinstance(sk30, SOMASkeleton30) else sk30
    for i in range(n_samples):
        jp = torch.from_numpy(pj[i]).to(dev); jr = torch.from_numpy(gr[i]).to(dev)
        if jr.shape[1] != sk.nbjoints:
            local = sk30.to_SOMASkeleton77(global_rots_to_local_rots(jr, sk30)); root = jp[:, sk30.root_idx, :]
        else:
            local = global_rots_to_local_rots(jr, sk); root = jp[:, sk.root_idx, :]
        p = os.path.join(out_dir, "%s_s%d.bvh" % (name, i))
        save_motion_bvh(p, local, root, skeleton=sk, fps=fps, standard_tpose=True)
        print("BVH", p, jp.shape[0], "frames @", fps)
