"""The tool's own skeleton (`amts`, profile skeletons/amts.json): bone names, hierarchy, which joints place each bone and the
rest-orientation rule. auto_rig.py builds it from a joints file when no Mixamo template is given. Pure Python + numpy:
runs in Blender's bundled Python, in the host venv and in tests.

Names: Blender style, side suffix `.L` / `.R` (Blender's mirror tools understand it). 65 bones, 52 deform:
  hips, spine.1, spine.2, spine.3, neck, head, head_end
  shoulder, upper_arm, forearm, hand, <finger>.1-3 and <finger>_end for thumb/index/middle/ring/pinky, thigh, shin, foot,
  toe, toe_end - per side.
Every `*_end` bone is a leaf that only marks where its parent ends (FBX keeps no bone tails); it does not deform.

Rest orientation (fixed, documented in the README): every bone's Y axis runs from its head to its tail (the next joint
along the body; a leaf continues its parent's direction). Roll: the bone's Z axis is a reference vector made
perpendicular to Y -
  hand and fingers: the palm normal of that hand (towards the palm), so a positive rotation about local X curls a finger
    into the palm;
  everything else: the character's front (-Y world; the model faces -Y), or world up (+Z) for a bone within 30 deg of the
    front (feet, toes).
Nothing here comes from a Mixamo file or rig. Proportions the detector does not measure come from the SOMA77 skeleton of
Kimodo (`kimodo/assets/skeletons/somaskel77/somaskel77_standard_tpose.bvh`, Kimodo repository, Apache-2.0; the same
skeleton the motion is generated on): the spine split, the clavicle start and the finger joints."""
import numpy as np

NAME = "amts"
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
SIDES = (("L", "Left"), ("R", "Right"))   # bone suffix, joint-key side

# --- proportions from SOMA77 (standard T-pose BVH, both sides averaged; see the module docstring)
# spine.1/.2/.3 heads: fraction of hips -> neck (SOMA Spine1 / Spine2 / Chest on Hips -> Neck1)
SPINE_SPLIT = (0.109, 0.264, 0.428)
# clavicle head (sternoclavicular joint): fraction of the shoulder joint's distance from the midline (SOMA 0.097 / 0.085)
CLAVICLE_X = 0.09
# finger knuckle (first joint): fraction of wrist -> that finger's tip along the hand axis (SOMA MCP t / tip t)
KNUCKLE = {"index": 0.524, "middle": 0.492, "ring": 0.495, "pinky": 0.549}
# the three bones of each finger as fractions of knuckle -> tip (SOMA phalanx lengths; thumb: CMC -> MCP -> IP -> tip)
PHALANX = {"thumb": (0.44, 0.262, 0.298), "index": (0.418, 0.266, 0.316), "middle": (0.45, 0.31, 0.24),
           "ring": (0.487, 0.297, 0.217), "pinky": (0.467, 0.236, 0.297)}
# thumb base (CMC) as fractions of the hand length (wrist -> middle fingertip): along the hand, towards the thumb side,
# towards the palm
THUMB_BASE = (0.121, 0.168, 0.071)
END_FRAC = 0.5        # a leaf `*_end` bone is this fraction of its parent's length
FRONT = np.array([0.0, -1.0, 0.0])
UP = np.array([0.0, 0.0, 1.0])
NEAR_FRONT = np.cos(np.radians(30.0))


def finger_key(side, finger, i):
    """Joint key of a finger joint in the joints file: LeftHandIndex1 (knuckle) .. LeftHandIndex4 (tip)."""
    return "%sHand%s%d" % (side, finger.capitalize(), i)


def _bones():
    """[(bone, parent, head joint, tail joint or None, group)] parents before children. Joint keys are the joints-file
    vocabulary (auto_rig.solve keys, see auto_rig.py)."""
    out = [("hips", None, "Hips", "Spine", "center"), ("spine.1", "hips", "Spine", "Spine1", "center"),
           ("spine.2", "spine.1", "Spine1", "Spine2", "center"), ("spine.3", "spine.2", "Spine2", "Neck", "center"),
           ("neck", "spine.3", "Neck", "Head", "center"), ("head", "neck", "Head", "HeadTop_End", "center"),
           ("head_end", "head", "HeadTop_End", None, "center")]
    for s, S in SIDES:
        out += [("shoulder." + s, "spine.3", S + "Shoulder", S + "Arm", "arm"),
                ("upper_arm." + s, "shoulder." + s, S + "Arm", S + "ForeArm", "arm"),
                ("forearm." + s, "upper_arm." + s, S + "ForeArm", S + "Hand", "arm"),
                ("hand." + s, "forearm." + s, S + "Hand", finger_key(S, "middle", 1), "hand")]
        for f in FINGERS:
            prev = "hand." + s
            for i in (1, 2, 3):
                name = "%s.%d.%s" % (f, i, s)
                out.append((name, prev, finger_key(S, f, i), finger_key(S, f, i + 1), "hand")); prev = name
            out.append(("%s_end.%s" % (f, s), prev, finger_key(S, f, 4), None, "hand"))
        out += [("thigh." + s, "hips", S + "UpLeg", S + "Leg", "leg"), ("shin." + s, "thigh." + s, S + "Leg", S + "Foot", "leg"),
                ("foot." + s, "shin." + s, S + "Foot", S + "ToeBase", "leg"),
                ("toe." + s, "foot." + s, S + "ToeBase", S + "Toe_End", "leg"),
                ("toe_end." + s, "toe." + s, S + "Toe_End", None, "leg")]
    return out


BONES = _bones()
PARENT = {b[0]: b[1] for b in BONES}
JOINT_KEYS = sorted({b[2] for b in BONES} | {b[3] for b in BONES if b[3]})


def is_end(name):
    return name.split(".")[0].endswith("_end")


def is_finger(name):
    return name.split(".")[0].split("_")[0] in FINGERS


def deforming(name, fingers=True):
    """Leaves never deform; fingers only when `fingers` (auto_rig --no-fingers keeps them rigid)."""
    return not is_end(name) and (fingers or not is_finger(name))


def missing(joints):
    """Joint keys the skeleton needs and `joints` lacks."""
    return [k for k in JOINT_KEYS if k not in joints]


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


def palm_normal(joints, side):
    """Unit normal towards the palm of hand `side` ('Left'/'Right') from the wrist and the index/pinky knuckles.
    Thumb side w (index - pinky knuckle) and hand axis a (wrist -> middle knuckle): right hand w = a x n, left hand
    w = n x a (fingers along a, palm facing n)."""
    w0 = np.asarray(joints[side + "Hand"], float)
    a = _unit(np.asarray(joints[finger_key(side, "middle", 1)], float) - w0)
    w = np.asarray(joints[finger_key(side, "index", 1)], float) - np.asarray(joints[finger_key(side, "pinky", 1)], float)
    if a is None: return None
    w = _unit(w - a * (w @ a))
    if w is None: return None
    return np.cross(w, a) if side == "Right" else np.cross(a, w)


def roll_reference(name, y, palm):
    """Z axis of a bone whose Y axis is `y` (unit): see the module docstring. `palm`: {'L'|'R': normal or None}."""
    s = name.rsplit(".", 1)[-1] if "." in name else ""
    group = next(b[4] for b in BONES if b[0] == name)
    ref = palm.get(s) if group == "hand" else None
    if ref is not None and abs(float(ref @ y)) < NEAR_FRONT:
        z = ref - y * (ref @ y)
    else:
        z = (UP if abs(float(FRONT @ y)) > NEAR_FRONT else FRONT)
        z = z - y * (z @ y)
    return _unit(z)


def _zero_length(name, hk, tk):
    """Why a bone has no length, in words: which finger of which hand, or which joints."""
    what = "joints %s and %s coincide" % (hk, tk)
    if is_finger(name):
        base, i, s = name.split(".")
        return ("bone %s has zero length: the %s finger of the %s hand, bone %s - %s. hand_fingers.py never places two joints "
                "of a finger at one point, so the joints file was edited by hand, comes from another detector or from an older "
                "run (a thin claw without a cross-section copied the previous joint); move one joint along the finger, or "
                "delete the file to detect again" % (name, base, {"L": "left", "R": "right"}[s], i, what))
    return "bone %s has zero length: %s (move one of them in the joints file, or delete the file to detect again)" % (name, what)


def bone_frames(joints):
    """{bone: (head, tail, z)} in the joints' frame (world, metres): what the Blender build sets as head, tail and roll
    (`align_roll(z)`). Raises KeyError naming the missing joints."""
    lost = missing(joints)
    if lost: raise KeyError("joints missing for the %s skeleton: %s" % (NAME, ", ".join(lost)))
    J = {k: np.asarray(v, float) for k, v in joints.items() if not k.startswith("_")}
    palm = {s: palm_normal(J, S) for s, S in SIDES}
    out = {}
    for name, parent, hk, tk, _ in BONES:
        head = J[hk]
        if tk:
            tail = J[tk]
        else:
            ph, pt, _ = out[parent]
            tail = head + (pt - ph) * END_FRAC
        if np.linalg.norm(tail - head) < 1e-5:
            raise ValueError(_zero_length(name, hk, tk))
        y = _unit(tail - head)
        out[name] = (head, tail, roll_reference(name, y, palm))
    return out


def own_joints(j):
    """Joints from the detector (auto_rig.solve keys) with the parts this skeleton places itself: the spine split and the
    clavicle start (SOMA proportions above). Fingers are added separately (from the hand mesh). Returns a new dict."""
    out = {k: np.asarray(v, float) for k, v in j.items()}
    hips, neck = out["Hips"], out["Neck"]
    for key, t in zip(("Spine", "Spine1", "Spine2"), SPINE_SPLIT):
        out[key] = hips + t * (neck - hips)
    for _, S in SIDES:
        arm = out[S + "Arm"]
        out[S + "Shoulder"] = np.array([CLAVICLE_X * arm[0], arm[1], arm[2]])
    return out
