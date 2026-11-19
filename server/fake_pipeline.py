"""Stand-in for pipeline/character.py in tests and local development: same flags, no Blender, no Kimodo, writes nothing.
python server/fake_pipeline.py --character x.json [--from S] [--to S] [--exit 0|1|2] [--delay seconds] [--hang]
Prints stage lines for the --from/--to range like character.py, then ends as asked: 0 = DONE, 2 = STOP at a gate
(at the ai stage, or the last stage in range), 1 = the first step fails. --hang sleeps at that point until killed."""
import argparse
import json
import os
import sys
import time

STAGES = ["prepare", "rig", "rig_ai", "calibration", "ai", "merge", "preview"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True); ap.add_argument("--from", dest="start", default=None, choices=STAGES)
    ap.add_argument("--to", dest="end", default="preview", choices=STAGES)
    ap.add_argument("--exit", dest="code", type=int, default=int(os.environ.get("FAKE_PIPELINE_EXIT", "2")), choices=[0, 1, 2])
    ap.add_argument("--delay", type=float, default=float(os.environ.get("FAKE_PIPELINE_DELAY", "0.3")))
    ap.add_argument("--hang", action="store_true")
    A = ap.parse_args()
    C = json.load(open(A.character, encoding="utf-8"))
    ai = next((n for n, a in C.get("actions", {}).items() if "ai" in a), "attack")
    print("fake pipeline for %s (%s)" % (C.get("name"), os.path.basename(A.character)), flush=True)
    run = STAGES[STAGES.index(A.start) if A.start else 0:STAGES.index(A.end) + 1]
    stop_at = "ai" if "ai" in run else run[-1]
    for s in run:
        print(">> %s.py" % s, flush=True); time.sleep(A.delay)
        if A.code == 1:
            print("Traceback (fake)\nSystemExit: step %s.py failed" % s, flush=True); return 1
        print("== %s: up to date (fake)" % s, flush=True)
        if s == stop_at and A.hang:
            print("waiting to be cancelled", flush=True)
            while True: time.sleep(1)
        if s == stop_at and A.code == 2:
            print("\nSTOP: action '%s': key poses (fr. 0,22,48) for review (fake)." % ai, flush=True); return 2
    print("\nDONE: fake output (nothing was written)", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
