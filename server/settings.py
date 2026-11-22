"""Service configuration, fixed at startup: which characters, which pipeline command, which browser origins."""
import getpass
import json
import os
import re
import sys
from dataclasses import dataclass, field

from .pipeline_lib import CHARACTER_PY

DEFAULT_PORT = 8765
DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3123", "http://127.0.0.1:3123"]
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".next", "out"}


@dataclass
class Character:
    id: str
    config_path: str


@dataclass
class Settings:
    characters: list[Character]
    pipeline_command: list[str] = field(default_factory=lambda: [sys.executable, CHARACTER_PY])
    origins: list[str] = field(default_factory=lambda: list(DEFAULT_ORIGINS))
    reviewer: str = field(default_factory=lambda: _user())

    def character(self, cid: str):
        return next((c for c in self.characters if c.id == cid), None)


def _user() -> str:
    try: return getpass.getuser()
    except Exception: return "reviewer"


def looks_like_character(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f: data = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "work_dir" in data and isinstance(data.get("actions"), dict)


def find_configs(paths: list[str]) -> list[str]:
    """character.json files given directly, plus every JSON file under a given folder that has `work_dir` and `actions`."""
    out = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p): out.append(p); continue
        if not os.path.isdir(p): raise SystemExit("no such file or folder: %s" % p)
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            out += [os.path.join(root, f) for f in sorted(files) if f.endswith(".json") and looks_like_character(os.path.join(root, f))]
    return list(dict.fromkeys(out))


def assign_ids(configs: list[str]) -> list[Character]:
    """URL-safe id from the character's `name` (or the file name); duplicates get -2, -3..."""
    seen: dict[str, int] = {}; out = []
    for p in configs:
        try: name = json.load(open(p, encoding="utf-8")).get("name") or ""
        except (OSError, ValueError, AttributeError): name = ""
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", name or os.path.splitext(os.path.basename(p))[0]).strip("-") or "character"
        seen[base] = seen.get(base, 0) + 1
        out.append(Character(base if seen[base] == 1 else "%s-%d" % (base, seen[base]), p))
    return out
