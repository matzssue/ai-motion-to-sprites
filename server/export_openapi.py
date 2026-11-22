"""Writes the service's OpenAPI document to web/src/api/openapi.json (the source of the generated TypeScript types).
python -m server.export_openapi [--check]   --check fails when the committed file is out of date."""
import json
import os
import sys

from .app import create_app
from .settings import Settings

TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "src", "api", "openapi.json")


def document() -> str:
    app = create_app(Settings(characters=[], pipeline_command=["python"], origins=[], reviewer="x"))
    try: return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    finally: app.state.jobs.close()


def main(argv) -> int:
    doc = document()
    if "--check" in argv:
        current = open(TARGET, encoding="utf-8").read() if os.path.exists(TARGET) else ""
        if current != doc: print("%s is out of date: run python -m server.export_openapi" % TARGET); return 1
        print("openapi.json up to date"); return 0
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    open(TARGET, "w", encoding="utf-8", newline="\n").write(doc); print("wrote", TARGET); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
