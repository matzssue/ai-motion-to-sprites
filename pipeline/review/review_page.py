"""Motion review in one command: GLB -> audit + 8 directions (all frames) + hand close-ups
-> page.html with audit numbers and a comparison with the previous version (self-contained, images inlined).
python pipeline/review/review_page.py --glb X.glb --action attack --out dir --title "Crossbowman shot" [--prop crossbow]
    [--previous dir_of_previous_review] [--hand-frames 10,45,56,85] [--px 360] [--note "what changed"]
    [--rest-is-normal] [--no-loop]   (library walk/idle: prop on the back; without it "hand to prop" 50 cm = FAIL)
    [--skeleton mixamo|profile.json]  (metrics the skeleton cannot measure are listed as skipped)
Finished steps (audit, frames, close-ups) are skipped when their output is newer than the GLB."""
import argparse, base64, glob, html, json, os, sys
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from chain import blender

DIRS = ["s", "sw", "w", "nw", "n", "ne", "e", "se"]
COLS = 10   # frames per sheet row
LABELS = {
    "prop_in_head": "prop in head", "prop_in_torso": "prop in torso", "prop_in_legs": "prop in legs",
    "prop_in_clavicles": "prop in shoulder", "hands_in_head": "hand in head", "hands_in_torso": "hand in torso",
    "forearms_in_head": "forearm in head", "forearms_in_torso": "forearm in torso",
    "fingers_in_prop": "fingers in prop", "wrist_bend_L": "left wrist bend",
    "wrist_bend_R": "right wrist bend", "wrist_twist_L": "left wrist twist",
    "wrist_twist_R": "right wrist twist", "elbow_jump": "elbow jump", "prop_jump": "prop jump",
    "hand_jump": "hand jump", "finger_jump": "finger jump", "head_jump": "head jump", "prop_rot_jump": "prop rotation jump",
    "loop_seam_deg": "loop seam (rotation)", "loop_seam_m": "loop seam (elbow)", "prop_above_head": "prop above head",
    "hand_to_prop_L": "left hand to prop", "hand_to_prop_R": "right hand to prop", "loose_fingers": "loose fingers",
    "stretch": "mesh stretch", "skin_twist": "arm skin twist", "skin_spread": "arm skin spread",
}
DEGREES = ("wrist", "hand_jump", "finger_jump", "head_jump", "prop_rot_jump", "loop_seam_deg", "skin_twist")
FRACTIONS = ("loose_fingers", "skin_spread")


def fresh(path, glb): return os.path.exists(path) and os.path.getmtime(path) >= os.path.getmtime(glb)


def fmt(k, v):
    if v is None: return "-"
    if k.startswith(FRACTIONS): return "%.0f%%" % (100 * v)
    return "%.1f&deg;" % v if k.startswith(DEGREES) else "%.1f cm" % (100 * v)


def sheet(folder, d, px):
    files = sorted(glob.glob(os.path.join(folder, "%s_*.png" % d)))
    rows = (len(files) + COLS - 1) // COLS; a = Image.new("RGB", (COLS * px, max(rows, 1) * px), (82, 84, 89))
    for i, p in enumerate(files):
        a.paste(Image.open(p).convert("RGB").resize((px, px), Image.LANCZOS), ((i % COLS) * px, (i // COLS) * px))
    return a, len(files)


def build(A):
    """Audit, frames, close-ups -> data.json in the review folder (sheets and close-ups as webp files)."""
    os.makedirs(A.out, exist_ok=True); data_p = os.path.join(A.out, "data.json")
    SKEL = ["--skeleton", A.skeleton] if getattr(A, "skeleton", None) else []
    aud = os.path.join(A.out, "audit")
    if not fresh(os.path.join(aud, "audit.json"), A.glb):
        blender("motion_audit.py", "AUDIT", "--glb", A.glb, "--action", A.action, "--out", aud, *(["--prop", A.prop] if A.prop else []),
                *(["--rest-is-normal"] if A.rest_is_normal else []), *(["--no-loop"] if A.no_loop else []), *SKEL)
    fr = os.path.join(A.out, "frames")
    if not fresh(os.path.join(fr, "done.json"), A.glb):
        blender("preview_8.py", "PREVIEW OK", "--glb", A.glb, "--actions", A.action, "--out", fr, "--all", "--px", str(A.px))
    hc = os.path.join(A.out, "hands")
    if A.hand_frames and not fresh(os.path.join(hc, "done"), A.glb):
        blender("hand_closeups.py", "CLOSEUPS OK", "--glb", A.glb, "--action", A.action, "--frames", A.hand_frames, "--out", hc, "--px", "360", *SKEL)
        open(os.path.join(hc, "done"), "w").close()
    n = 0
    for d in DIRS:
        a, n = sheet(os.path.join(fr, A.action), d, A.px); a.save(os.path.join(A.out, d + ".webp"), "WEBP", quality=72, method=4)
    hands = []
    for f in [int(float(x)) for x in A.hand_frames.split(",")] if A.hand_frames else []:
        for side in ("Right", "Left"):
            ims = [Image.open(os.path.join(hc, "fr%03d_%s_%s.png" % (f, side, w))).convert("RGB").resize((240, 240), Image.LANCZOS)
                   for w in ("front", "side", "below")]
            strip = Image.new("RGB", (720, 240)); [strip.paste(im, (i * 240, 0)) for i, im in enumerate(ims)]
            name = "hand_%03d_%s.webp" % (f, side); strip.save(os.path.join(A.out, name), "WEBP", quality=78); hands.append((f, side, name))
    rep = json.load(open(os.path.join(aud, "audit.json"), encoding="utf-8"))
    data = {"title": A.title, "glb": A.glb, "frames": n, "px": A.px, "audit": rep, "hands": hands}
    json.dump(data, open(data_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return data


CSS = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
<style>
:root{--bg:#f3f4f1;--panel:#ffffff;--text:#1c2126;--muted:#5d6670;--line:#d6d9d3;--accent:#2f6f5e;--bad:#b3402e;--good:#2f6f5e}
@media (prefers-color-scheme:dark){:root{--bg:#15181b;--panel:#1e2327;--text:#e6e8e3;--muted:#98a1a8;--line:#333a40;--accent:#6fc2a8;--bad:#ef8a75;--good:#6fc2a8;color-scheme:dark}}
body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:28px}
h1{font:600 28px/1.15 system-ui,sans-serif;margin:0}h2{font:600 18px/1.2 system-ui,sans-serif;margin:0 0 10px}
p{margin:0;max-width:68ch}.muted{color:var(--muted)}
.head{display:flex;flex-direction:column;gap:10px}.pills{display:flex;flex-wrap:wrap;gap:8px}
.pill{border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px;font-variant-numeric:tabular-nums;background:var(--panel)}
.pill.bad{border-color:var(--bad);color:var(--bad)}.pill.ok{border-color:var(--good);color:var(--good)}
.ctl{position:sticky;top:0;z-index:5;background:var(--bg);padding-block:8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;border-bottom:1px solid var(--line)}
.ctl button{font:600 13px system-ui,sans-serif;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--text);cursor:pointer}
.ctl button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--bg)}
.ctl input[type=range]{flex:1 1 180px;min-width:0;accent-color:var(--accent)}
.ctl output{font-variant-numeric:tabular-nums;min-width:8ch;color:var(--muted)}
.views{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%%,260px),1fr));gap:12px}
.views.pair{grid-template-columns:repeat(auto-fill,minmax(min(100%%,520px),1fr))}
figure{margin:0;display:flex;flex-direction:column;gap:4px}
figcaption{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.two{display:flex;gap:4px}.two>div{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}.two small{font-size:11px;color:var(--muted)}
canvas,.hands img{width:100%%;height:auto;display:block;border-radius:4px;background:var(--panel)}
.hands{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%%,420px),1fr));gap:14px}
.tab{overflow-x:auto}table{border-collapse:collapse;width:100%%;font-variant-numeric:tabular-nums;font-size:14px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--muted);font-size:12px;letter-spacing:.05em;text-transform:uppercase}
td.bad{color:var(--bad);font-weight:600}td.better{color:var(--good)}td.worse{color:var(--bad)}
</style></head><body>"""

JS = """<script>
(function(){
const D=%(data)s, COLS=%(cols)d, PX=D.px, N=D.frames, FPS=24;
const img={}, cv=[];
function load(src){const i=new Image();i.src=src;return i}
for(const k of D.dirs){img[k]=load(D.sheets[k]); if(D.prev) img['p_'+k]=load(D.prev[k])}
function px(c){return c.dataset.k.startsWith('p_')?D.px_prev:PX}
document.querySelectorAll('canvas[data-k]').forEach(c=>{c.width=px(c);c.height=px(c);cv.push(c)});
let frame=0, playing=true, speed=1, t0=null, f0=0;
const slider=document.getElementById('slider'), out=document.getElementById('nr'), bp=document.getElementById('play');
function draw(){
  for(const c of cv){const i=img[c.dataset.k]; if(!i.complete||!i.naturalWidth) continue;
    const n=Math.min(frame,(c.dataset.k.startsWith('p_')?D.frames_prev:N)-1);
    const p=px(c); c.getContext('2d').drawImage(i,(n%%COLS)*p,Math.floor(n/COLS)*p,p,p,0,0,p,p)}
  slider.value=frame; out.textContent='frame '+frame+' / '+(N-1);
}
function tick(t){
  if(playing){ if(t0===null){t0=t;f0=frame} frame=Math.floor(f0+(t-t0)/1000*FPS*speed)%%N; draw() }
  requestAnimationFrame(tick);
}
bp.onclick=()=>{playing=!playing;t0=null;bp.textContent=playing?'Pause':'Play'};
slider.max=N-1; slider.oninput=()=>{playing=false;bp.textContent='Play';frame=+slider.value;draw()};
document.querySelectorAll('[data-speed]').forEach(b=>b.onclick=()=>{speed=+b.dataset.speed;t0=null;
  document.querySelectorAll('[data-speed]').forEach(x=>x.setAttribute('aria-pressed',x===b))});
document.getElementById('back').onclick=()=>{playing=false;bp.textContent='Play';frame=(frame+N-1)%%N;draw()};
document.getElementById('fwd').onclick=()=>{playing=false;bp.textContent='Play';frame=(frame+1)%%N;draw()};
Object.values(img).forEach(i=>i.onload=draw);
if(matchMedia('(prefers-reduced-motion: reduce)').matches){playing=false;bp.textContent='Play'}
requestAnimationFrame(tick);
})();
</script></body></html>"""


def page(data, folder, prev=None, prev_folder=None, diff=None, note=""):
    rep = data["audit"]; rp = prev["audit"] if prev else None
    inline = lambda d, n: "data:image/webp;base64," + base64.b64encode(open(os.path.join(d, n), "rb").read()).decode()
    title = html.escape(data["title"])
    H = [CSS % {"title": title}, "<main>", '<div class="head"><h1>%s</h1>' % title]
    if note: H.append("<p>%s</p>" % html.escape(note))
    pills = ['<span class="pill %s">audit %s &middot; score %.2f</span>' % ("ok" if rep["result"] == "OK" else "bad", rep["result"], rep["score"])]
    pills += ['<span class="pill">%s %.2f</span>' % (g, v) for g, v in rep.get("scores", {}).items()]
    if rp: pills.append('<span class="pill">previous: %s &middot; %.2f</span>' % (rp["result"], rp["score"]))
    H.append('<div class="pills">%s</div></div>' % "".join(pills))
    H.append('<section><h2>Motion from 8 directions</h2><div class="ctl"><button id="play" type="button">Pause</button>'
             '<button id="back" type="button" aria-label="Previous frame">&#9664;</button><button id="fwd" type="button" aria-label="Next frame">&#9654;</button>'
             '<button type="button" data-speed="1" aria-pressed="true">1&times;</button><button type="button" data-speed="0.5" aria-pressed="false">&frac12;&times;</button>'
             '<button type="button" data-speed="0.25" aria-pressed="false">&frac14;&times;</button>'
             '<input id="slider" type="range" min="0" value="0" aria-label="Frame"><output id="nr"></output></div>')
    H.append('<div class="views%s">' % (" pair" if prev else ""))
    for d in DIRS:
        if prev: H.append('<figure><figcaption>%s</figcaption><div class="two"><div><canvas data-k="%s"></canvas><small>now</small></div>'
                          '<div><canvas data-k="p_%s"></canvas><small>previous</small></div></div></figure>' % (d, d, d))
        else: H.append('<figure><figcaption>%s</figcaption><canvas data-k="%s"></canvas></figure>' % (d, d))
    H.append("</div></section>")
    if data["hands"]:
        H.append('<section><h2>Hands up close</h2><p class="muted">Each strip: front, side, below.</p><div class="hands">')
        for f, s, n in data["hands"]:
            side = "right" if s == "Right" else "left"
            H.append('<figure><figcaption>frame %d &middot; %s</figcaption><img alt="%s hand, frame %d" src="%s"></figure>' % (f, side, side, f, inline(folder, n)))
        H.append("</div></section>")
    H.append('<section><h2>Audit numbers</h2><div class="tab"><table><thead><tr><th>metric</th><th>now</th><th>limit</th><th>share of clip</th>'
             + ("<th>previous</th>" if rp else "") + "</tr></thead><tbody>")
    for k, v in rep["maxima"].items():
        lim = rep["limits"].get(k); e = rep["errors"].get(k)
        if not v and not (rp and rp["maxima"].get(k)): continue
        row = '<tr><td>%s</td><td class="%s">%s</td><td>%s</td><td>%s</td>' % (
            LABELS.get(k, k), "bad" if e else "", fmt(k, v), fmt(k, lim) if lim is not None else "reported only", "%d%%" % round(100 * e["share"]) if e else "")
        if rp:
            w = rp["maxima"].get(k); cl = "" if w is None or abs(w - v) < 1e-6 else ("better" if v < w else "worse")
            row += '<td class="%s">%s</td>' % (cl, fmt(k, w))
        H.append(row + "</tr>")
    for k, why in rep.get("skipped", {}).items():
        H.append('<tr><td>%s</td><td class="muted">skipped</td><td colspan="%d" class="muted">%s</td></tr>' % (
            LABELS.get(k, k), 3 if rp else 2, html.escape(why)))
    H.append("</tbody></table></div></section>")
    if diff:
        H.append('<section><h2>Difference from the previous version</h2><div class="tab"><table><thead><tr><th>part</th><th>max position</th>'
                 "<th>mean</th><th>max rotation</th></tr></thead><tbody>")
        for k, w in diff.items():
            if w["mm"] > 0.5 or w["deg"] > 0.5:
                H.append("<tr><td>%s</td><td>%.0f mm (fr. %s)</td><td>%.0f mm</td><td>%.0f&deg;</td></tr>" % (k, w["mm"], w["mm_fr"], w["mm_sum"] / w["n"], w["deg"]))
        H.append("</tbody></table></div></section>")
    H.append("</main>")
    js = {"dirs": DIRS, "px": data["px"], "frames": data["frames"], "sheets": {d: inline(folder, d + ".webp") for d in DIRS}}
    if prev: js["prev"] = {d: inline(prev_folder, d + ".webp") for d in DIRS}; js["frames_prev"] = prev["frames"]; js["px_prev"] = prev["px"]
    H.append(JS % {"data": json.dumps(js), "cols": COLS})
    return "\n".join(H)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Build a self-contained review page: audit, 8-direction player, hand close-ups.")
    ap.add_argument("--glb", required=True); ap.add_argument("--action", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True); ap.add_argument("--prop"); ap.add_argument("--previous")
    ap.add_argument("--hand-frames", default=""); ap.add_argument("--px", type=int, default=360); ap.add_argument("--note", default="")
    ap.add_argument("--rest-is-normal", action="store_true", help="library action: prop on the back, as in calibration")
    ap.add_argument("--no-loop", action="store_true", help="one-shot action: audit without the loop seam")
    ap.add_argument("--skeleton", default=None, help="skeleton profile of the rig: built-in name or JSON path (default mixamo)")
    A = ap.parse_args()
    SKEL = ["--skeleton", A.skeleton] if A.skeleton else []
    data = build(A); prev = diff = None
    if A.previous:
        prev = json.load(open(os.path.join(A.previous, "data.json"), encoding="utf-8"))
        dp = os.path.join(A.out, "diff.json")
        blender("compare_motion.py", "COMPARE", "--a", prev["glb"], "--b", A.glb, "--action", A.action, "--out", dp, *(["--prop", A.prop] if A.prop else []), *SKEL)
        diff = json.load(open(dp, encoding="utf-8"))
    doc = page(data, A.out, prev, A.previous, diff, A.note)
    out = os.path.join(A.out, "page.html"); open(out, "w", encoding="utf-8").write(doc)
    print("REVIEW OK", out, "%.1f MB" % (len(doc) / 2 ** 20), "| audit", data["audit"]["result"], data["audit"]["score"])
