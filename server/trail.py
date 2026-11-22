"""Audit trail of verdicts: one JSON object per line in <work_dir>/review_trail.jsonl, append-only."""
import os
from datetime import datetime, timezone

from .models import TrailEntry

FILE = "review_trail.jsonl"


def path(work_dir: str) -> str:
    return os.path.join(work_dir, FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(work_dir: str) -> list[TrailEntry]:
    """Every entry, oldest first; a broken line is skipped (the file is append-only and may be edited by hand)."""
    p = path(work_dir)
    if not os.path.exists(p): return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try: out.append(TrailEntry.model_validate_json(line))
            except ValueError: continue
    return out


def append(work_dir: str, entry: TrailEntry) -> None:
    os.makedirs(work_dir, exist_ok=True)
    with open(path(work_dir), "a", encoding="utf-8", newline="\n") as f:
        f.write(entry.model_dump_json() + "\n"); f.flush(); os.fsync(f.fileno())


def timestamp(entry: TrailEntry) -> float:
    return datetime.fromisoformat(entry.at).timestamp()
