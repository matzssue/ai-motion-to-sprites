"""Prints the body proportions the auto-rig takes from the SOMA77 skeleton (pipeline/rig/auto_rig.py `SOMA`), so anyone
can recompute them. The BVH ships with Kimodo (Apache-2.0); it is not in this repository.
python tools/soma_proportions.py <kimodo repo>/kimodo/assets/skeletons/somaskel77/somaskel77_standard_tpose.bvh
BVH frame: Y up, Z forward, centimetres; the rest pose is the hierarchy's offsets (T-pose). Height H = HeadEnd above the
root (the floor)."""
import sys

import numpy as np


def joints(path):
    """{joint: global rest position} from a BVH hierarchy (offsets summed, no rotations)."""
    out, stack, name = {}, [], None
    for line in open(path, encoding="utf-8"):
        w = line.split()
        if not w: continue
        if w[0] in ("ROOT", "JOINT"): name = w[1]
        elif w[0] == "End": name = None
        elif w[0] == "{": stack.append(name)
        elif w[0] == "}": stack.pop()
        elif w[0] == "OFFSET" and name:
            parent = next((p for p in reversed(stack[:-1]) if p), None)
            out[name] = (out[parent] if parent else np.zeros(3)) + np.array([float(x) for x in w[1:4]])
        elif w[0] == "MOTION": break
    return out


def proportions(j):
    """The auto-rig's SOMA proportions, both sides averaged. Heights are Y, depth (forward) is Z."""
    def side(f):
        return 0.5 * (f("Left") + f("Right"))
    y = {k: v[1] for k, v in j.items()}
    H = y["HeadEnd"]
    ankle = side(lambda s: y[s + "Foot"])
    knee = side(lambda s: y[s + "Shin"])
    hip = side(lambda s: y[s + "Leg"])
    arm = side(lambda s: y[s + "Arm"])
    seg = lambda a, b: float(np.linalg.norm(j[b] - j[a]))
    return {
        "hips_z": y["Hips"] / H,
        "hips_t": (y["Hips"] - ankle) / (arm - ankle),
        "hip_sep": (j["LeftLeg"][0] - j["RightLeg"][0]) / H,
        "upleg_down": (y["Hips"] - hip) / (y["Hips"] - knee),
        "knee_t": (knee - ankle) / (y["Hips"] - ankle),
        "ankle_z": ankle / H,
        "arm_z": arm / H,
        "elbow_t": side(lambda s: seg(s + "Arm", s + "ForeArm") / (seg(s + "Arm", s + "ForeArm") + seg(s + "ForeArm", s + "Hand"))),
        "wrist_t": side(lambda s: (seg(s + "Arm", s + "ForeArm") + seg(s + "ForeArm", s + "Hand")) / (
            seg(s + "Arm", s + "ForeArm") + seg(s + "ForeArm", s + "Hand") + seg(s + "Hand", s + "HandMiddleEnd"))),
        "arm_len": side(lambda s: seg(s + "Arm", s + "ForeArm") + seg(s + "ForeArm", s + "Hand")) / H,
        "neck_above_arm": (y["Neck1"] - arm) / H,
        "head_above_neck": (y["Head"] - y["Neck1"]) / H,
        "head_forward": (j["Head"][2] - j["Neck1"][2]) / H,
        "neck_behind_arm": (side(lambda s: j[s + "Arm"][2]) - j["Neck1"][2]) / H,
        "toe_base_t": side(lambda s: (j[s + "ToeBase"][2] - j[s + "Foot"][2]) / (j[s + "ToeEnd"][2] - j[s + "Foot"][2])),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    for k, v in proportions(joints(sys.argv[1])).items():
        print("%-16s %.4f" % (k, v))
