"""Which files the service may serve: the GLB and audit files of one action's review (by kind, never by a requested
path) and gate preview images (by index). Every resolved path must lie inside the character's work dir."""
import os
from typing import Literal, Optional

from .status import Paths, choice_files, gate_images, merged_files

Kind = Literal["glb", "audit", "samples"]
Source = Literal["choice", "merged"]
EXTENSIONS = {"glb": (".glb",), "audit": (".json",), "samples": (".json",), "image": (".png", ".jpg", ".jpeg", ".webp")}
MEDIA = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}


class Refused(Exception):
    """A path that resolved outside the work dir or to a wrong file type."""


def inside(path: str, root: str) -> bool:
    """True when `path` (after resolving links and `..`) lies within `root`."""
    p, r = os.path.realpath(path), os.path.realpath(root)
    try: return os.path.commonpath([os.path.normcase(p), os.path.normcase(r)]) == os.path.normcase(r)
    except ValueError: return False   # another drive on Windows


def checked(path: str, work: str, kind: str) -> str:
    if not inside(path, work): raise Refused("%s is outside the work dir" % os.path.basename(path))
    if not path.lower().endswith(EXTENSIONS[kind]): raise Refused("%s is not a %s file" % (os.path.basename(path), kind))
    return os.path.realpath(path)


def review_file(P: Paths, action: str, source: Source, kind: Kind) -> Optional[str]:
    """Path of one review file, checked; None when it does not exist (yet)."""
    files = choice_files(P, action) if source == "choice" else merged_files(P, action)
    if not files: return None
    path = files[kind]
    if not os.path.exists(path): return None
    return checked(path, P.work, kind)


def image_file(P: Paths, kind: str, action: Optional[str], index: int) -> Optional[str]:
    images = gate_images(P, kind, action)
    if not 0 <= index < len(images): return None
    return checked(images[index], P.work, "image")


def media_type(path: str) -> str:
    return MEDIA.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
