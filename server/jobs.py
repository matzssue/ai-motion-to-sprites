"""Pipeline runs: one at a time, the rest queued. The command is fixed at startup (settings.pipeline_command); a run
only adds --character <configured path>, the whitelisted --from/--to stage names and --sample <action of that
character>=<int>. Threads, not asyncio
subprocesses, so it works under any event loop (uvicorn picks a selector loop on Windows, which has no subprocesses)."""
import os
import signal
import subprocess
import sys
import threading
import uuid
from collections import deque
from typing import Callable, Optional

from .models import JobSummary
from .trail import now_iso

MAX_LINES = 20000
GATE_EXIT = 2   # character.py stop(): a human gate, not a failure


class Job:
    def __init__(self, character_id: str, config_path: str, start: Optional[str], end: Optional[str],
                 samples: Optional[dict[str, int]] = None):
        self.id = uuid.uuid4().hex[:12]; self.character_id = character_id; self.config_path = config_path
        self.samples = dict(samples or {})
        self.start = start; self.end = end; self.state = "queued"; self.exit_code: Optional[int] = None
        self.outcome: Optional[str] = None; self.created_at = now_iso(); self.started_at = None; self.ended_at = None
        self.lines: list[str] = []; self.dropped = 0; self.proc: Optional[subprocess.Popen] = None; self.cancel_requested = False
        self.finished = threading.Event()

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")

    def summary(self) -> JobSummary:
        return JobSummary(id=self.id, character_id=self.character_id, from_stage=self.start, to_stage=self.end, samples=self.samples, state=self.state,
                          exit_code=self.exit_code, outcome=self.outcome, created_at=self.created_at, started_at=self.started_at,
                          ended_at=self.ended_at, line_count=self.dropped + len(self.lines))

    def lines_after(self, n: int) -> tuple[int, list[str]]:
        """Lines with absolute index >= n (older ones may have been dropped) and the index of the first one returned."""
        first = max(n, self.dropped)
        return first, self.lines[first - self.dropped:]


def outcome_of(lines: list[str], code: Optional[int]) -> tuple[str, Optional[str]]:
    """(state, the line that explains it). Exit 2 is a gate only with a STOP line: argparse also exits 2 on bad flags."""
    stop = next((ln for ln in reversed(lines) if ln.startswith("STOP:")), None)
    if code == 0: return "done", next((ln for ln in reversed(lines) if ln.startswith("DONE")), None)
    if code == GATE_EXIT and stop: return "waiting_for_review", stop
    return "failed", next((ln for ln in reversed(lines) if ln.strip()), None)


def kill_tree(proc: subprocess.Popen) -> None:
    """Blender and Kimodo run as children of character.py: stop the whole tree."""
    if proc.poll() is not None: return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: return
        try: proc.wait(5)
        except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL)


class JobManager:
    def __init__(self, command: list[str], on_end: Optional[Callable[[Job], None]] = None):
        self.command = list(command); self.on_end = on_end
        self.jobs: dict[str, Job] = {}; self.queue: deque[Job] = deque(); self.current: Optional[Job] = None
        self.cv = threading.Condition(); self.closed = False
        self.worker = threading.Thread(target=self._loop, name="pipeline-jobs", daemon=True); self.worker.start()

    def argv(self, job: Job) -> list[str]:
        return [*self.command, "--character", job.config_path, *(["--from", job.start] if job.start else []),
                *(["--to", job.end] if job.end else []), *[x for n, i in job.samples.items() for x in ("--sample", "%s=%d" % (n, i))]]

    def submit(self, character_id: str, config_path: str, start: Optional[str], end: Optional[str],
               samples: Optional[dict[str, int]] = None) -> Job:
        job = Job(character_id, config_path, start, end, samples)
        with self.cv:
            self.jobs[job.id] = job; self.queue.append(job); self.cv.notify_all()
        return job

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self.jobs.get(job_id)
        if not job: return None
        with self.cv:
            if job.state == "queued":
                self.queue.remove(job); self._finish(job, "cancelled", None, "cancelled before it started")
                return job
            if job.state != "running": return job
            job.cancel_requested = True; proc = job.proc
        if proc: kill_tree(proc)
        return job

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def active_for(self, character_id: str) -> Optional[Job]:
        return next((j for j in self.list() if j.character_id == character_id and j.active), None)

    def busy(self, character_id: str) -> bool:
        return self.active_for(character_id) is not None

    def close(self) -> None:
        with self.cv:
            self.closed = True; pending = list(self.queue); self.queue.clear(); cur = self.current; self.cv.notify_all()
        for j in pending: self._finish(j, "cancelled", None, "service stopped")
        if cur and cur.proc: cur.cancel_requested = True; kill_tree(cur.proc)
        self.worker.join(10)

    def _finish(self, job: Job, state: str, code: Optional[int], outcome: Optional[str]) -> None:
        job.state = state; job.exit_code = code; job.outcome = outcome; job.ended_at = now_iso(); job.finished.set()
        if self.on_end:
            try: self.on_end(job)
            except Exception: pass

    def _append(self, job: Job, line: str) -> None:
        job.lines.append(line)
        if len(job.lines) > MAX_LINES: drop = len(job.lines) - MAX_LINES; del job.lines[:drop]; job.dropped += drop

    def _loop(self) -> None:
        while True:
            with self.cv:
                while not self.queue and not self.closed: self.cv.wait()
                if self.closed: return
                job = self.queue.popleft(); self.current = job; job.state = "running"; job.started_at = now_iso()
            self._run(job)
            with self.cv: self.current = None

    def _run(self, job: Job) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
        try:
            job.proc = subprocess.Popen(self.argv(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        env=env, **kw)
        except OSError as e:
            self._append(job, "cannot start the pipeline: %s" % e); self._finish(job, "failed", None, str(e)); return
        if job.cancel_requested: kill_tree(job.proc)
        for raw in job.proc.stdout:
            self._append(job, raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        code = job.proc.wait()
        if job.cancel_requested: self._finish(job, "cancelled", code, "cancelled by the reviewer"); return
        state, why = outcome_of(job.lines, code)
        self._finish(job, state, code, why)
