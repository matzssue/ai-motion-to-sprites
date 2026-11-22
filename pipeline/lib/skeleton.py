"""Skeleton profile: which bone of a rig plays which role, the name prefix, body regions and the parts the rig does not
have (skeletons/<name>.json, format: schemas/skeleton.schema.json). Every stage after rigging asks the profile instead of
using bone names. Pure Python: runs in Blender's bundled Python (no jsonschema there), in the host venv and in tests,
so the checks below repeat the schema by hand (tests keep the two in step)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILTIN = os.path.join(ROOT, "skeletons")
DEFAULT = "mixamo"
SIDES = ("Left", "Right")
# role -> required; spine is a list (hips -> neck), every other role one bone
CENTER = {"hips": True, "spine": True, "neck": True, "head": True, "head_end": False}
SIDED = {"shoulder": False, "upper_arm": True, "forearm": True, "hand": True, "fingers": False,
         "upper_leg": True, "lower_leg": True, "foot": True, "toe": False, "toe_end": False}
REGIONS = ("head", "torso", "clavicles", "legs")
# optional per side `finger_chains`: {finger: [bones from the hand outwards]}; the last three are the finger's three bones
# (a metacarpal before them is allowed). The retarget carries the finger bends between skeletons that both list a finger.
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
# the retarget aims a bone at the next role along the body; that role absent -> at the bone's own tail
AIM = {"neck": "head", "head": "head_end", "shoulder": "upper_arm", "upper_arm": "forearm", "forearm": "hand", "hand": "fingers",
       "upper_leg": "lower_leg", "lower_leg": "foot", "foot": "toe", "toe": "toe_end"}
# retarget order: parents before children is settled by depth later; this order only keeps the logs stable
LIMB = ("shoulder", "upper_arm", "forearm", "hand", "upper_leg", "lower_leg", "foot", "toe")


class ProfileError(ValueError):
    pass


def side_name(s):
    """'L' / 'left' / 'Left' -> 'Left'."""
    k = str(s).lower()
    if k in ("l", "left"): return "Left"
    if k in ("r", "right"): return "Right"
    raise ProfileError("unknown side %r (Left or Right)" % (s,))


def take_arg(args, flag="--skeleton"):
    """For scripts with positional arguments: (args without `--skeleton X` / `--skeleton=X`, X or None)."""
    rest, val, i = [], None, 0
    while i < len(args):
        if args[i] == flag and i + 1 < len(args): val = args[i + 1]; i += 2; continue
        if args[i].startswith(flag + "="): val = args[i][len(flag) + 1:]
        else: rest.append(args[i])
        i += 1
    return rest, val


def locate(spec=None, base=None):
    """Built-in name (`mixamo`) or a JSON path (relative to `base`) -> file path."""
    spec = spec or DEFAULT
    if spec.lower().endswith(".json") or "/" in spec or "\\" in spec:
        return spec if os.path.isabs(spec) or not base else os.path.normpath(os.path.join(base, spec))
    p = os.path.join(BUILTIN, spec + ".json")
    if not os.path.exists(p):
        names = sorted(f[:-5] for f in os.listdir(BUILTIN) if f.endswith(".json"))
        raise ProfileError("no built-in skeleton profile %r (built-in: %s; or give a .json path)" % (spec, ", ".join(names)))
    return p


def load(spec=None, base=None):
    path = locate(spec, base)
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProfileError("%s: cannot read skeleton profile (%s)" % (path, e))
    return Profile(data, path)


def problems(D):
    """List of "<role or key>: <message>" (empty = valid); the hand-written twin of schemas/skeleton.schema.json."""
    out = []
    if not isinstance(D, dict): return ["$: a skeleton profile is a JSON object"]
    for k in ("name", "bones"):
        if k not in D: out.append("%s: required" % k)
    if not isinstance(D.get("prefix", ""), str): out.append("prefix: must be a string")
    B = D.get("bones", {}); absent = D.get("absent", [])
    if not isinstance(B, dict): return out + ["bones: must be an object"]
    if not isinstance(absent, list) or not all(isinstance(a, str) for a in absent): return out + ["absent: must be a list of role names"]
    for a in absent:
        if a not in CENTER and a not in SIDED: out.append("absent: unknown role %r" % a)
        elif CENTER.get(a) or SIDED.get(a): out.append("absent: %s is required and cannot be absent" % a)
    for k in B:
        if k not in CENTER and k not in ("left", "right") and not k.startswith("_"):
            out.append("bones.%s: unknown role (%s)" % (k, "per-side roles go under left/right" if k in SIDED else "roles: %s, left, right"
                                                     % ", ".join(CENTER)))
    for role, req in CENTER.items():
        v = B.get(role)
        if v is None:
            if role not in absent: out.append("bones.%s: missing (%s)" % (role, "required" if req else "give a bone or list it in `absent`"))
        elif role in absent: out.append("bones.%s: given and listed in `absent`" % role)
        elif role == "spine":
            if not (isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)): out.append("bones.spine: a non-empty list of bone names")
        elif not (isinstance(v, str) and v): out.append("bones.%s: a bone name" % role)
    for side in ("left", "right"):
        S = B.get(side)
        if not isinstance(S, dict): out.append("bones.%s: missing (an object of per-side roles)" % side); continue
        FC = S.get("finger_chains", {})
        if not isinstance(FC, dict): out.append("bones.%s.finger_chains: an object {finger: [bones]}" % side); FC = {}
        for f, ch in FC.items():
            if f not in FINGERS and not f.startswith("_"): out.append("bones.%s.finger_chains.%s: unknown finger (%s)" % (side, f, ", ".join(FINGERS)))
            elif f in FINGERS and not (isinstance(ch, list) and len(ch) >= 3 and all(isinstance(x, str) and x for x in ch)):
                out.append("bones.%s.finger_chains.%s: a list of at least 3 bone names" % (side, f))
        for k in S:
            if k not in SIDED and k != "finger_chains" and not k.startswith("_"): out.append("bones.%s.%s: unknown role (roles: %s)" % (side, k, ", ".join(SIDED)))
        for role, req in SIDED.items():
            v = S.get(role)
            if v is None:
                if role not in absent: out.append("bones.%s.%s: missing (%s)" % (side, role, "required" if req else "give a bone or list it in `absent`"))
            elif role in absent: out.append("bones.%s.%s: given and listed in `absent`" % (side, role))
            elif not (isinstance(v, str) and v): out.append("bones.%s.%s: a bone name" % (side, role))
    R = D.get("regions", {})
    if not isinstance(R, dict): return out + ["regions: must be an object"]
    seen = {}
    for r, roles in R.items():
        if r.startswith("_"): continue
        if r not in REGIONS: out.append("regions.%s: unknown region (regions: %s)" % (r, ", ".join(REGIONS))); continue
        if not isinstance(roles, list): out.append("regions.%s: a list of roles" % r); continue
        for x in roles:
            if x not in CENTER and x not in SIDED: out.append("regions.%s: unknown role %r" % (r, x))
            elif x in seen: out.append("regions.%s: role %s is already in region %s" % (r, x, seen[x]))
            else: seen[x] = r
    for r in REGIONS:
        if r not in R: out.append("regions.%s: missing (list its roles, [] for none)" % r)
    return out


def for_rig(spec, parents, exclude=(), log=print):
    """Profile bound to a rig ({bone: parent}). An explicit profile must match the rig. Without one (configs from before
    profiles) the default is fitted: an optional role whose bone the rig lacks becomes absent, as the old code ignored it."""
    prof = load(spec)
    if spec is None:
        lost = sorted({r for (r, s), n in prof._b.items() if n not in parents and not (CENTER.get(r) or SIDED.get(r))})
        if lost:
            log("skeleton %s: the rig has no %s bones -> treated as absent" % (prof.name, ", ".join(lost)))
            prof = prof.without(lost)
    return prof.bind(parents, exclude)


class Profile:
    def __init__(self, data, path="<profile>"):
        p = problems(data)
        if p: raise ProfileError("%s: not a valid skeleton profile:\n  %s" % (path, "\n  ".join(p)))
        self.data = data
        self.path, self.name, self.prefix = path, data["name"], data.get("prefix", "")
        self.absent = list(data.get("absent", []))
        B = data["bones"]; P = self.prefix
        self._b = {}   # (role, side or None) -> full bone name
        for role in CENTER:
            if role == "spine": continue
            if role in B: self._b[(role, None)] = P + B[role]
        self.spine = [P + n for n in B["spine"]]
        for s in SIDES:
            for role in SIDED:
                v = B[s.lower()].get(role)
                if v: self._b[(role, s)] = P + v
        self.chains = {s: {f: [P + n for n in ch] for f, ch in B[s.lower()].get("finger_chains", {}).items() if f in FINGERS}
                       for s in SIDES}
        self.regions = {r: [x for x in data["regions"][r]] for r in REGIONS}
        self.role_of = {n: k for k, n in self._b.items()}
        for i, n in enumerate(self.spine): self.role_of[n] = ("spine", None)

    def __repr__(self): return "<skeleton %s>" % self.name

    def without(self, roles):
        """Copy with these optional roles absent (no fingers: no finger chains either)."""
        D = json.loads(json.dumps(self.data)); B = D["bones"]
        for r in roles:
            B.pop(r, None); B["left"].pop(r, None); B["right"].pop(r, None)
            if r == "fingers": B["left"].pop("finger_chains", None); B["right"].pop("finger_chains", None)
        D["absent"] = sorted(set(D.get("absent", [])) | set(roles))
        return Profile(D, self.path)

    def has(self, role, side=None):
        """A sided role without a side = on both sides."""
        if role == "spine": return True
        if role in CENTER: return (role, None) in self._b
        if role not in SIDED: raise ProfileError("unknown role %r" % role)
        return (role, side_name(side)) in self._b if side else all((role, s) in self._b for s in SIDES)

    def bone(self, role, side=None):
        """Full bone name (prefix included). An absent role raises ProfileError naming the profile."""
        if role == "spine": raise ProfileError("spine is a chain: use .spine")
        if role not in CENTER and role not in SIDED: raise ProfileError("unknown role %r" % role)
        k = (role, side_name(side) if role in SIDED else None)
        if role in SIDED and not side: raise ProfileError("%s needs a side" % role)
        if k not in self._b: raise ProfileError("skeleton '%s' (%s) has no %s%s" % (self.name, self.path, role, "." + k[1].lower() if k[1] else ""))
        return self._b[k]

    def bones(self, role):
        """Every bone of a role (both sides, spine chain); absent -> []."""
        if role == "spine": return list(self.spine)
        if role in CENTER: return [self._b[(role, None)]] if (role, None) in self._b else []
        return [self._b[(role, s)] for s in SIDES if (role, s) in self._b]

    def finger_chains(self, side):
        """{finger: [full bone names from the hand outwards]} of one side; {} when the profile lists none."""
        return dict(self.chains[side_name(side)])

    def region_bones(self, region):
        return [b for r in self.regions[region] for b in self.bones(r)]

    def short(self, name):
        return name[len(self.prefix):] if self.prefix and name.startswith(self.prefix) else name

    def missing(self, needs):
        """Absent entries of `needs`: "hand" (both sides), "hand.left", "region:clavicles" (a region with no bone)."""
        out = []
        for n in needs:
            if n.startswith("region:"):
                if not self.region_bones(n[7:]): out.append(n[7:] + " region")
                continue
            role, _, s = n.partition(".")
            if not self.has(role, s or None): out.append(n)
        return out

    def skipped(self, needs):
        """{metric: reason} for every metric whose needs are not all in this skeleton."""
        out = {}
        for k, nd in needs.items():
            m = self.missing(nd)
            if m: out[k] = "skeleton '%s' has no %s" % (self.name, ", ".join(m))
        return out

    def aim(self, name):
        """Bone the retarget aims `name` at, or None (= the bone's own tail)."""
        role, s = self.role_of[name]
        if role == "hips": return self.spine[0]
        if role == "spine":
            i = self.spine.index(name); return self.spine[i + 1] if i + 1 < len(self.spine) else self.bone("neck")
        nxt = AIM.get(role)
        return self._b.get((nxt, s)) if nxt else None

    def pairs(self, other):
        """[(bone here, bone in `other`)] of every role both have, in retarget order (hips, spine, neck, head, limbs)."""
        if len(self.spine) != len(other.spine):
            raise ProfileError("skeleton '%s' has %d spine bones and '%s' %d: only a one-to-one spine is supported"
                               % (self.name, len(self.spine), other.name, len(other.spine)))
        out = [(self.bone("hips"), other.bone("hips"))] + list(zip(self.spine, other.spine))
        out += [(self.bone(r), other.bone(r)) for r in ("neck", "head")]
        for s in SIDES:
            out += [(self.bone(r, s), other.bone(r, s)) for r in LIMB if self.has(r, s) and other.has(r, s)]
        return out

    def same_roles(self, other):
        """[(bone here, bone in `other`)] of every role both have (tips and fingers too), for copying a clip by role."""
        return [(n, other._b[k]) for k, n in self._b.items() if k in other._b] + list(zip(self.spine, other.spine))

    def bind(self, parents, exclude=()):
        """Profile against one rig: `parents` = {bone: parent or None}. Checks that every bone the profile names exists;
        a finger chain the rig does not have whole is dropped (chains are optional: a renamed template rig lacks Index4)."""
        lost = [(s, f) for s in SIDES for f, ch in self.chains[s].items() if any(n not in parents for n in ch)]
        prof = self
        if lost:
            D = json.loads(json.dumps(self.data))
            for s, f in lost: D["bones"][s.lower()]["finger_chains"].pop(f)
            prof = Profile(D, self.path)
        return Rig(prof, parents, exclude)


class Rig:
    """A profile bound to a rig: region, side and finger set of every bone (structural, not by name)."""
    def __init__(self, prof, parents, exclude=()):
        self.prof = prof
        lost = ["%s%s -> '%s'" % (r, "." + s.lower() if s else "", n) for (r, s), n in prof._b.items() if n not in parents]
        lost += ["spine -> '%s'" % n for n in prof.spine if n not in parents]
        if lost:
            raise ProfileError("skeleton '%s' (%s) does not match this rig, missing bones: %s" % (prof.name, prof.path, ", ".join(lost)))
        kids = {}
        for b, p in parents.items(): kids.setdefault(p, []).append(b)
        side_of = {n: s for (r, s), n in prof._b.items() if s}
        self.side = {}
        for b in parents:
            x = b
            while x is not None and x not in side_of: x = parents.get(x)
            self.side[b] = "" if x is None else side_of[x][0]
        # fingers: every bone below a hand (rig fingers and the finger_* bones prepare_rig grows), when the profile has fingers
        self.fingers, self.finger_root = set(), {}
        for s in SIDES:
            if not prof.has("fingers", s): continue
            for root in kids.get(prof.bone("hand", s), []):
                if root in exclude: continue
                todo = [root]
                while todo:
                    x = todo.pop(); self.fingers.add(x); self.finger_root[x] = root; todo += kids.get(x, [])
        self.region = {}
        for r in REGIONS:
            for b in prof.region_bones(r): self.region[b] = r
        self.arms = set(prof.bones("upper_arm") + prof.bones("forearm") + prof.bones("hand"))

    def bone_side(self, name):
        """'L' / 'R' / '' (from the nearest sided role above the bone)."""
        return self.side.get(name, "")
