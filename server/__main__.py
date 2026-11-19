"""python -m server <character.json or folder>... [--port 8765] [--fake [--fake-exit 2]] [--pipeline-cmd "..."] [--origin URL]
Binds to 127.0.0.1 only. The pipeline command is fixed here; requests can only pick a configured character and stages."""
import argparse
import os
import shlex
import sys

from .settings import DEFAULT_ORIGINS, DEFAULT_PORT, Settings, assign_ids, find_configs

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_pipeline.py")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m server", description="Local review service over pipeline/character.py.")
    ap.add_argument("paths", nargs="+", help="character.json files, or folders to scan for them")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--fake", action="store_true", help="run server/fake_pipeline.py instead of pipeline/character.py")
    ap.add_argument("--fake-exit", type=int, choices=[0, 1, 2], default=2, help="how the fake pipeline ends (default 2: a gate)")
    ap.add_argument("--fake-delay", type=float, default=0.4)
    ap.add_argument("--pipeline-cmd", help="command that takes character.py's flags (default: this Python + pipeline/character.py)")
    ap.add_argument("--origin", action="append", default=[], help="extra browser origin allowed by CORS (repeatable)")
    ap.add_argument("--reviewer", help="name written to the trail when a verdict names none (default: the OS user)")
    A = ap.parse_args(argv)
    configs = find_configs(A.paths)
    if not configs: raise SystemExit("no character.json found in %s" % ", ".join(A.paths))
    s = Settings(characters=assign_ids(configs), origins=DEFAULT_ORIGINS + A.origin)
    if A.fake: s.pipeline_command = [sys.executable, FAKE, "--exit", str(A.fake_exit), "--delay", str(A.fake_delay)]
    elif A.pipeline_cmd: s.pipeline_command = shlex.split(A.pipeline_cmd, posix=os.name != "nt")
    if A.reviewer: s.reviewer = A.reviewer
    import uvicorn
    from .app import create_app
    print("characters:", ", ".join("%s (%s)" % (c.id, c.config_path) for c in s.characters))
    print("pipeline:", " ".join(s.pipeline_command))
    uvicorn.run(create_app(s), host="127.0.0.1", port=A.port, log_level="info")


if __name__ == "__main__":
    main()
