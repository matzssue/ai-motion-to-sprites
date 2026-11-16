"""Motion parameter variants from one command: a grid of values -> parallel runs (prop in hands + audit
[+ comparison with a reference]) -> table from best. Instead of launching 2-3 variants by hand.
python pipeline/variants.py --rig rig_ai.glb --motion <motion>.json --merged merged_x.glb --out dir
    --set grip.right.x=0.06,0.08,0.10 --set hold.body_clearance=0.14,0.18   (cartesian product)
    [--file variants.json]   ({"name": {"grip.right.x": 0.1, ...}, ...} - named variants instead of a grid)
    [--frames 10,45,56]      (quick try: only these frames, no path in time or smoothness metrics, ~15 s per variant)
    [--reference v10.glb]    (position difference vs the approved version) [--parallel 3]
A value with a bracket is a vector: --set "grip.right.direction=[0.3,0.95,0];[0.7,0.7,0]" (variants split by a semicolon)."""
import argparse, ctypes, itertools, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from config import BLENDER, script_path

GB_PER_PROCESS = 0.7   # Blender with a 25k-triangle character takes ~0.3 GB; the rest is headroom


def free_ram_gb():
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 30
    except ImportError:
        pass

    class M(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                   ("tot", "avail", "tp", "ap", "tv", "av", "ae")]
    m = M(); m.l = ctypes.sizeof(M)
    try: ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.avail / 2 ** 30
    except Exception: return 4.0


def set_path(d, path, v):
    *parents, k = path.split(".")
    for p in parents: d = d.setdefault(p, {})
    d[k] = v


def blender(script, log, *args):
    r = subprocess.run([BLENDER, "-b", "--python", script_path(script), "--", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    open(log, "a", encoding="utf-8").write(r.stdout + "\n" + r.stderr[-2000:])
    return r.stdout.splitlines()


def run_variant(name, changes, A, base, prop):
    D = os.path.join(A.out, name); os.makedirs(D, exist_ok=True)
    R = json.loads(json.dumps(base))
    for k, v in changes.items(): set_path(R, k, v)
    motion = os.path.join(D, "motion.json"); json.dump(R, open(motion, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    glb = os.path.join(D, "prop.glb"); log = os.path.join(D, "log.txt"); open(log, "w").close()
    fr = ["--frames", A.frames] if A.frames else []
    t0 = time.time()
    out = blender("prop_in_hands.py", log, "--glb", A.merged, "--rig-data", A.rig.replace(".glb", "_data.json"),
                  "--motion", motion, "--out", glb, *fr)
    w = {"name": name, "changes": changes, "glb": glb}
    if not any(l.startswith("OK ") for l in out): w["error"] = "prop step failed (%s)" % log; return w
    w["limits_hit"] = [l[6:] for l in out if l.startswith("LIMIT ")]
    blender("motion_audit.py", log, "--glb", glb, "--action", R["action"], "--out", os.path.join(D, "audit"),
            "--prop", prop, "--no-closeups", *fr)
    try: rep = json.load(open(os.path.join(D, "audit", "audit.json"), encoding="utf-8"))
    except OSError: w["error"] = "audit failed (%s)" % log; return w
    w.update(score=rep["score"], scores=rep["scores"], area=rep["score_area"], maxima=rep["maxima"],
             errors={k: v["max"] for k, v in rep["errors"].items()}, limits=rep["limits"])
    if A.reference and not A.frames:
        cmp_ = blender("compare_motion.py", log, "--a", A.reference, "--b", glb, "--action", R["action"], "--prop", prop,
                       "--out", os.path.join(D, "diff.json"))
        if any(l.startswith("COMPARE") for l in cmp_):
            dd = json.load(open(os.path.join(D, "diff.json"), encoding="utf-8"))
            w["from_ref_mm"] = round(max(v["mm"] for v in dd.values()), 1); w["from_ref_deg"] = round(max(v["deg"] for v in dd.values()), 1)
    w["time_s"] = round(time.time() - t0)
    return w


def value(s):
    try: return json.loads(s)
    except ValueError: return s


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Run a grid of motion-file parameter variants in parallel and rank them by audit.")
    ap.add_argument("--rig", required=True); ap.add_argument("--motion", required=True); ap.add_argument("--merged", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--set", action="append", default=[]); ap.add_argument("--file")
    ap.add_argument("--frames"); ap.add_argument("--reference"); ap.add_argument("--parallel", type=int, default=3)
    A = ap.parse_args()
    base = json.load(open(A.motion, encoding="utf-8")); os.makedirs(A.out, exist_ok=True)
    prop = json.load(open(A.rig.replace(".glb", "_data.json"), encoding="utf-8"))["prop"]["name"]
    if A.file:
        variants = list(json.load(open(A.file, encoding="utf-8")).items())
    else:
        axes = []
        for u in A.set:
            k, vs = u.split("=", 1)
            axes.append([(k, value(v)) for v in (vs.split(";") if "[" in vs else vs.split(","))])
        variants = [("_".join("%s=%s" % (k.split(".")[-1], json.dumps(v).replace(" ", "")) for k, v in combo).replace('"', ""), dict(combo))
                    for combo in itertools.product(*axes)]
    n = max(1, min(A.parallel, int(free_ram_gb() / GB_PER_PROCESS), len(variants)))
    print("variants %d, parallel %d (free RAM %.1f GB)" % (len(variants), n, free_ram_gb()), flush=True)
    with ThreadPoolExecutor(n) as ex:
        results = list(ex.map(lambda nz: run_variant(nz[0], nz[1], A, base, prop), variants))
    results.sort(key=lambda w: w.get("score", 1e9))
    json.dump(results, open(os.path.join(A.out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    groups = ("penetration", "joints", "smoothness", "grip")
    L = ["| variant | score | " + " | ".join(groups) + " | area | vs reference | worst | at limit |", "|---|---|" + "---|" * (len(groups) + 4)]
    for w in results:
        if "error" in w: L.append("| %s | - | %s |" % (w["name"], w["error"])); continue
        worst = sorted(w["errors"].items(), key=lambda kv: -kv[1] / max(w["limits"][kv[0]], 1e-9))[:3]
        L.append("| %s | %.2f | %s | %.3f | %s | %s | %s |" % (
            w["name"], w["score"], " | ".join("%.2f" % w["scores"].get(g, 0) for g in groups), w["area"],
            "%s mm / %s deg" % (w["from_ref_mm"], w["from_ref_deg"]) if "from_ref_mm" in w else "-",
            ", ".join("%s %.3g" % (k, v) for k, v in worst) or "OK", "; ".join(w.get("limits_hit", [])) or "-"))
    open(os.path.join(A.out, "table.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L)); print("VARIANTS OK", os.path.join(A.out, "table.md"))
