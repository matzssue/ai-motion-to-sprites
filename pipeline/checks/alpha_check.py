"""Body alpha check in a composited frame: a mask (holdout, occluder) must not cut a body part in the middle so that
islands of it remain (fingertips without the middle of the finger = "the boat shows through the fingers").
Island = a visible piece of the body detached from the rest of the same blob of the raw render.
python pipeline/checks/alpha_check.py --raw body_layer.png --final composited.png [--out dir]   (two alphas in the same pixels)
Limits: islands >= 30 px count; more than 100 px per frame = FAIL (mask edge specks are 2-19 px, cut fingertips 65-374 px)."""
import argparse, json, os
import numpy as np
from PIL import Image
from scipy import ndimage

ISLAND_PX = 30         # px at 1920x1080: mask edge specks 2-19 px, cut-off fingertips 65-374 px
ISLANDS_LIMIT = 100    # sum of islands per frame: approved frames 0, a frame with 3 cut fingers 526-591
SEMI_OPEN = 5          # reported only: semi-transparent blobs thicker than 5 px (a mask edge is 1-3 px)


def measure(raw, final):
    """raw, final: alpha 0..1 of the same layer before and after the mask/composite -> islands, semi-transparent px, island mask"""
    blobs, nb = ndimage.label(raw > 0.5, structure=np.ones((3, 3)))
    vis, nv = ndimage.label((final > 0.5) & (raw > 0.5), structure=np.ones((3, 3)))
    size = np.bincount(vis.ravel(), minlength=nv + 1); islands = []; mask = np.zeros_like(raw, bool)
    for b in range(1, nb + 1):
        w = np.unique(vis[(blobs == b) & (vis > 0)])
        if len(w) < 2: continue
        main = w[size[w].argmax()]
        for k in w:
            if k != main and size[k] >= ISLAND_PX:
                ys, xs = np.where(vis == k); islands.append({"px": int(size[k]), "center": [int(xs.mean()), int(ys.mean())]}); mask |= vis == k
    semi = (raw > 0.98) & (final > 0.08) & (final < 0.92)
    semi_open = int(ndimage.binary_opening(semi, structure=np.ones((SEMI_OPEN, SEMI_OPEN))).sum())
    return islands, semi_open, mask


def main():
    ap = argparse.ArgumentParser(description="Find body pieces cut off by a mask when compositing a sprite frame.")
    ap.add_argument("--raw", required=True, help="RGBA render of the body layer before masking")
    ap.add_argument("--final", required=True, help="RGBA of the same layer after masking/compositing, same size")
    ap.add_argument("--out", default="alpha_check")
    A = ap.parse_args()
    os.makedirs(A.out, exist_ok=True)
    load = lambda p: np.asarray(Image.open(p).convert("RGBA"), np.float32)[..., 3] / 255.0
    raw, final = load(A.raw), load(A.final); rgb = np.asarray(Image.open(A.final).convert("RGB"))
    islands, semi, mask = measure(raw, final); total = sum(w["px"] for w in islands)
    ok = total <= ISLANDS_LIMIT
    report = {"islands_limit_px": ISLANDS_LIMIT, "island_min_px": ISLAND_PX, "islands_px": total, "islands": islands,
              "semi_transparent_px": semi, "result": "OK" if ok else "FAIL"}
    print("ALPHA %s  body islands cut by the mask %4d px (limit %d)%s  semi-transparent blobs %d px (reported only)" % (
        "OK  " if ok else "FAIL", total, ISLANDS_LIMIT, "".join(" [%d px at %s]" % (w["px"], w["center"]) for w in islands), semi), flush=True)
    if not ok:          # close-up: the frame with islands in red next to it
        ys, xs = np.where(mask); x0, x1 = max(xs.min() - 120, 0), min(xs.max() + 120, rgb.shape[1]); y0, y1 = max(ys.min() - 90, 0), min(ys.max() + 90, rgb.shape[0])
        mk = rgb.copy(); mk[mask] = (0.4 * mk[mask] + 0.6 * np.array([255, 30, 30])).astype(np.uint8)
        pair = np.concatenate([rgb[y0:y1, x0:x1], mk[y0:y1, x0:x1]], 1); s = max(1, 600 // max(pair.shape[0], 1))
        Image.fromarray(pair).resize((pair.shape[1] * s, pair.shape[0] * s), Image.NEAREST).save(os.path.join(A.out, "alpha_islands.png"))
    json.dump(report, open(os.path.join(A.out, "alpha.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
