"""One GPU shared by several processes: a Kimodo script or an Eevee render waits until the GPU is free and holds a lock until exit.
Kimodo's text encoder allocates 14.3 GB on an 8 GB card and spills into RAM: a foreign render next to it took 28 min instead of ~2.
Renders wait only for the lock (threshold_mb=None). A child of the lock owner (env AMTS_GPU_LOCK) does not wait.
Lock = $KIMODO_DIR/gpu.lock with a PID (the temp dir when there is no Kimodo); a dead PID means an abandoned lock.
AMTS_GPU_QUEUE=0 turns the queue off. It also waits while someone without the lock uses
the GPU (memory above AMTS_GPU_THRESHOLD_MB, default 2500). On Windows nvidia-smi does not report per-process memory.
os.kill(pid, 0) on Windows KILLS the process, so liveness there goes through OpenProcess."""
import atexit, os, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import KIMODO_DIR

# without Kimodo nothing else uses the GPU this way: renders still queue among themselves, but no ~/kimodo is created
LOCK = os.path.join(KIMODO_DIR, "gpu.lock") if os.path.isdir(KIMODO_DIR) else os.path.join(tempfile.gettempdir(), "ai-motion-to-sprites-gpu.lock")
THRESHOLD_MB = int(os.environ.get("AMTS_GPU_THRESHOLD_MB", "2500"))


def _alive(pid):
    if sys.platform != "win32":
        try: os.kill(pid, 0); return True
        except OSError: return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return False
    code = ctypes.c_ulong(); k.GetExitCodeProcess(h, ctypes.byref(code)); k.CloseHandle(h)
    return code.value == 259                 # STILL_ACTIVE


def _memory_mb():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True)
        return int(r.stdout.split()[0])
    except Exception:
        return 0


def _users():
    """who holds GPU memory (Windows performance counter; nvidia-smi on Windows does not list processes)"""
    if sys.platform != "win32": return ""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            r"(Get-Counter '\GPU Process Memory(*)\Dedicated Usage').CounterSamples | ? CookedValue -gt 300MB | "
                            r"% { $i=[int]($_.InstanceName -replace '^pid_(\d+)_.*','$1'); '{0} {1} MB' -f (Get-Process -Id $i -EA 0).ProcessName,[int]($_.CookedValue/1MB) }"],
                           capture_output=True, text=True, timeout=20)
        return ", ".join(x.strip() for x in r.stdout.splitlines() if x.strip())
    except Exception:
        return ""


def acquire(who="", threshold_mb=THRESHOLD_MB):
    if os.environ.get("AMTS_GPU_QUEUE") == "0": return
    owner = os.environ.get("AMTS_GPU_LOCK")
    if owner and _alive(int(owner)) and os.path.exists(LOCK) and open(LOCK).read().split()[:1] == [owner]: return
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    last = 0
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try: pid = int(open(LOCK).read().split()[0])
            except Exception: pid = 0
            if pid and _alive(pid):
                reason = "GPU held by PID %d (%s)" % (pid, LOCK)
            else:
                try: os.remove(LOCK)
                except OSError: pass
                continue
        else:
            os.write(fd, ("%d %s" % (os.getpid(), who)).encode()); os.close(fd)
            mb = _memory_mb() if threshold_mb is not None else 0
            if threshold_mb is None or mb <= threshold_mb:
                os.environ["AMTS_GPU_LOCK"] = str(os.getpid())
                atexit.register(lambda: os.path.exists(LOCK) and os.remove(LOCK))
                return
            os.remove(LOCK); reason = "GPU busy without the lock: %d MB > %d MB (%s)" % (mb, threshold_mb, _users())
        if time.time() - last > 60: print("waiting:", reason, flush=True); last = time.time()
        time.sleep(15)
