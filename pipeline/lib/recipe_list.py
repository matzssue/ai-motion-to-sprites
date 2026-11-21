"""The recipes a motion file names: `recipe` is one entry {"name": ..., inputs} or a list of them, run in that order
(pipeline/recipes/README.md). Pure Python: chain.py, character.py and the recipes themselves read it the same way."""


def entries(motion):
    """The motion file's recipe entries in run order ([] without `recipe`)."""
    r = motion.get("recipe")
    return [] if not r else [r] if isinstance(r, dict) else list(r)


def problems(motion):
    """What chain.py refuses before any Blender step: the same recipe twice in one action."""
    names = [e.get("name") for e in entries(motion)]
    return ["recipe %s is listed %d times: once per action" % (n, names.count(n)) for n in sorted(set(names), key=str) if names.count(n) > 1]


def entry(motion, name):
    """The one entry of recipe `name`; ValueError when the motion file does not list it exactly once."""
    found = [e for e in entries(motion) if e.get("name") == name]
    if len(found) != 1: raise ValueError("the motion file lists the recipe %s %d times, it needs it once" % (name, len(found)))
    return found[0]
