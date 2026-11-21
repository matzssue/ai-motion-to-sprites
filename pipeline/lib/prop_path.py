"""The prop's way through a clip (prop_in_hands.py), the parts that need no Blender: when it is aimed, where an approved
key pose puts it on another frame's body, and which frames' offsets are averaged. Tests: tests/test_prop_path.py."""
import numpy as np


def aim_window(phases, key_poses, fps, fire_s=None):
    """(rise from, full from, full to, down to) in frames, or None when no key pose is named `aim`.
    Rise: over the phase that holds the aim key pose, up to that pose. Full: to the end of the phase that holds the shot
    (`fire_s`; without one, the phase of the aim pose). Down: over the first half of the phase after it (Kusznik, audit
    score with the fall over its first half / the whole of it / its second half: 10.19 / 11.20 / 12.51).
    The right hand's height said it before: on Kusznik's shot the hand was highest in the recoil, the stock was pinned in
    the armpit on frames 54-86 and hung at the hip on the approved aim frame 44."""
    ak = (key_poses or {}).get("aim")
    if ak is None or not phases: return None
    ends = [0.0]
    for p in phases: ends.append(ends[-1] + p["duration"] * fps)
    phase_of = lambda t: next((i for i in range(len(phases)) if t < ends[i + 1]), len(phases) - 1)
    up0 = max(t for t in ends[:-1] if t < ak) if ak > 0 else 0.0
    i = phase_of(max(ak, fire_s * fps) if fire_s is not None else ak)
    full_to = ends[i + 1]; down_to = full_to + 0.5 * (ends[i + 2] - full_to) if i + 2 < len(ends) else full_to
    return up0, float(ak), full_to, down_to


def aim_weight(f, win):
    """0..1 on frame f: a smooth step up to the aim pose and down after the shot."""
    up0, ak, full_to, down_to = win
    step = lambda x: (lambda y: y * y * (3 - 2 * y))(min(1.0, max(0.0, x)))
    if f <= ak: return 1.0 if ak <= up0 else step((f - up0) / (ak - up0))
    if f <= full_to: return 1.0
    return 0.0 if down_to <= full_to and f > full_to else 1.0 - step((f - full_to) / (down_to - full_to))


def nearest(f, key_frames):
    """The key frame nearest to f (the earlier one on a tie), None without any."""
    return min(key_frames, key=lambda k: (abs(k - f), k)) if key_frames else None


def carry(p_key, o_key, R_key, o, R=None):
    """A point `p_key` set against a body part (origin o_key, rotation R_key) on a key pose, on the frame where that part
    is at `o` turned `R`: it keeps its place on the part. Without R the part's turn is left out (the point only follows
    the origin)."""
    p_key, o_key, o = (np.asarray(v, float) for v in (p_key, o_key, o))
    d = p_key - o_key
    return o + (d if R is None else np.asarray(R, float) @ np.asarray(R_key, float).T @ d)


def smooth_runs(off, frames, state, half=3, loop=False):
    """{frame: offset averaged over the frames up to `half` away (triangle weights)} - only over neighbours reached
    without a change of `state(frame)`. An offset means something else on each side of such a change (the prop turns
    about the hand grip while held, about its rear end while that rests in the armpit): Kusznik's frame 54 took the
    average of both kinds and ended 9.5 cm in the left upper arm.
    `loop` = the last frame is the first again: the neighbours past one end are those before the other."""
    out = {}; first, last = frames[0], frames[-1]; span = last - first
    wrap = lambda g: g if first <= g <= last or not loop else (g + span if g < first else g - span)
    for f in frames:
        ok = lambda g: wrap(g) in off and state(wrap(g)) == state(f)
        lo = hi = 0
        while -lo < half and ok(f + lo - 1): lo -= 1
        while hi < half and ok(f + hi + 1): hi += 1
        acc, ws = np.zeros(len(off[f])), 0
        for k in range(lo, hi + 1):   # in frame order: the sum is the one a plain +-half average gives, bit for bit
            w = 1 - abs(k) / (half + 1); acc += np.array(off[wrap(f + k)]) * w; ws += w
        out[f] = list(acc / ws)
    return out


def best_path(U, trans, loop=False):
    """Cheapest chain of states, one per frame (Viterbi) -> [state index]. U[i][s] = cost of state s on frame i,
    trans[a][b] = cost of changing a -> b between neighbours. `loop` = the last frame is the first again: both get the
    same state, the cheapest chain that has it (two equal poses ended 20 deg apart in the hand's roll over the seam)."""
    def run(U):
        acc = U[0]; back = []
        for u in U[1:]:
            m = acc[:, None] + trans; b = m.argmin(0); back.append(b); acc = m[b, np.arange(len(u))] + u
        k = int(acc.argmin()); total = float(acc[k]); pth = [k]
        for b in reversed(back): k = int(b[k]); pth.append(k)
        return total, pth[::-1]
    total, pth = run(U)
    if loop and len(U) > 2 and pth[0] != pth[-1]:
        best = None
        for s in range(len(U[0])):
            if U[0][s] >= 1e9 or U[-1][s] >= 1e9: continue
            a = np.full(len(U[0]), 1e9); a[s] = U[0][s]; z = np.full(len(U[0]), 1e9); z[s] = U[-1][s]
            r = run([a] + list(U[1:-1]) + [z])
            if best is None or r[0] < best[0]: best = r
        if best is not None: pth = best[1]
    return pth
