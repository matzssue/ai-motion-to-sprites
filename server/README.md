# Review service (`server/`)

A local FastAPI service over `pipeline/character.py`. It answers three questions for a reviewer: which character and
which stage waits for a human, what exactly that gate needs, and what the verdict writes. The web UI in `web/`
(`/characters/`, `/character/?id=`, `/review/?character=&action=`) is its client.

## Run

```bash
pip install -e ".[server]"                       # FastAPI + uvicorn (the `dev` extra adds the test client)
python -m server path/to/character.json          # one or more files
python -m server path/to/characters/ --fake      # or folders: every JSON with `work_dir` and `actions`
```

Service and web app together (from `web/`): `npm run local -- <character.json or folder> [--fake]`. It starts this
service and `next dev` (both bound to 127.0.0.1) with `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765`; open
`http://127.0.0.1:3000/characters/` (`localhost` works too).

| Flag | Default | Meaning |
|---|---|---|
| `--port` | 8765 | port on 127.0.0.1 (the host is fixed) |
| `--fake` | off | run `server/fake_pipeline.py` instead of `character.py` (`--fake-exit 0/1/2`, `--fake-delay s`) |
| `--pipeline-cmd` | this Python + `pipeline/character.py` | another command taking `character.py`'s flags (e.g. the game's submodule copy) |
| `--origin` | `localhost`/`127.0.0.1` on ports 3000 and 3123 | extra browser origin allowed by CORS (repeatable) |
| `--reviewer` | the OS user | name written to the trail when a verdict names none |

Character ids come from `name` in `character.json` (`-2`, `-3` for duplicates).

## Endpoints

The OpenAPI document (`/docs`, `/openapi.json`, committed as `web/src/api/openapi.json`) is the contract; every request
and response is a Pydantic model in `models.py`.

| Method and path | What |
|---|---|
| `GET /api/health` | version, pipeline command, number of characters |
| `GET /api/characters` | every character with its waiting gate, next stale stage, done flag, active run |
| `GET /api/characters/{id}` | `PipelineState`: the seven stages, the gate, every action (best sample, scores, audits, approval) and `config_sha` |
| `GET /api/characters/{id}/actions/{action}/manifest.json?source=choice\|merged` | manifest in the format of the viewer's `?data=` loader, with absolute URLs |
| `GET /api/characters/{id}/actions/{action}/files/{glb\|audit\|samples}?source=` | the files that manifest names, nothing else |
| `GET /api/characters/{id}/images/{rig\|poses}/{index}?action=` | gate preview images (rig previews, key-pose previews) |
| `POST /api/characters/{id}/verdicts/preview` | what a verdict would write: before/after values and a unified diff; writes nothing |
| `POST /api/characters/{id}/verdicts` | write the verdict and append it to the trail |
| `GET /api/characters/{id}/verdicts?action=` | the trail, oldest first |
| `POST /api/characters/{id}/runs` | queue a run (`from_stage`, `to_stage`: names from `STAGES` only); 202 |
| `GET /api/jobs`, `GET /api/jobs/{job}` | runs and their state |
| `POST /api/jobs/{job}/cancel` | cancel a queued run, or kill a running one with its whole process tree |
| `GET /api/jobs/{job}/events?after=` | server-sent events: `line` `{n, text}` (id = n, resumable with `Last-Event-ID`), `state`, `end` |

## Pipeline state (`status.py`)

Read-only, from the files, by the rules of `character.py`: the same file names, the same freshness rule
(`lib/stages.fresh`, imported, not copied), the same stage order, and AI actions in config order because a run stops at
the first gate. A stage is `up_to_date`, `stale` (the next run does it), `waiting` (a human gate), `failed` (a STOP that
needs a fix: calibration FAIL, audit FAIL after merge, missing `key_poses`), `blocked` (after a waiting/failed stage or
after a stale stage that ends in a STOP) or `skipped` (no library/AI actions). Stages after a stale one are shown stale too:
the run rewrites their inputs.

| Gate | Waiting when | Approve writes |
|---|---|---|
| AI rig | `rig_ai.glb` is fresh and nothing later is newer than it (calibration, body, choice, output) and no rig approval in the trail since | nothing: a new run continues past it; the trail records the look |
| key poses | `body.json` exists, `poses/poses.glb` is newer than it, no `poses_approved.json` | `<work>/<action>/poses_approved.json` `{"glb": <picked poses GLB>}`; the pick is one of `poses/poses.glb`, `poses_*/poses.glb` |
| motion | `poses_approved.json` exists and `choice.json` is newer than the motion file, `rig_ai.glb` and the approval | `actions.<action>.approved = {"bvh", "score", "date", "npz"}` from `choice.json` |

## Verdicts (`verdicts.py`, `json_edit.py`)

- A verdict must match a gate that is waiting now (409 otherwise). A rejection needs a note and writes only the trail.
- `character.json` is edited as text: only the `approved` member of that action is inserted or replaced, in the
  object's own style (one-line objects stay one-line, the file's indent unit and line endings are kept). Key order,
  `_` comment keys and every other byte stay. The result is parsed back and compared with the intended data, validated
  against `schemas/character.schema.json`, and written to a temp file in the same folder, flushed and `os.replace`d.
- The preview returns `config_sha`; the write sends it back as `expected_config_sha`, and a file changed in between
  is refused (409). Verdicts are refused while a run of that character is queued or running.
- Trail: `<work_dir>/review_trail.jsonl`, one JSON object per line (`id`, `at`, `reviewer`, `gate`, `action`,
  `decision`, `note`, `changes` with before/after/diff). Append-only.

## Safety rules

- **Bound to 127.0.0.1 only**, with a trusted-host check (`127.0.0.1`, `localhost`) against DNS rebinding.
- **No command or path from a request.** The command is fixed at startup; a run adds `--character <configured path>`
  and at most `--from`/`--to` with a stage name validated against `STAGES`. Unknown request keys are ignored.
- **Files by kind, never by path.** Review files are named by `glb`/`audit`/`samples` and resolved from `choice.json`
  or the merge outputs; images by index into a fixed glob. Every resolved path must lie inside the character's work dir
  (after resolving links and `..`) and have the right extension, or the answer is 403.
- **Writes only where `character.py` reads**: the configured `character.json`, `poses_approved.json` in the action
  folder, and the trail.
- CORS allows only the configured web origins; POSTs from another `Origin` or without `application/json` are refused
  (CORS alone does not stop a foreign page from sending a simple POST).

## Fake pipeline

`fake_pipeline.py` takes `character.py`'s flags, prints one `>> stage` / `== stage: up to date (fake)` pair per stage in
the `--from`/`--to` range (sleeping `--delay` seconds each), then ends as asked: `--exit 0` prints `DONE`, `--exit 2`
prints a `STOP:` line about key poses at the `ai` stage (or the last stage in range) and exits 2, `--exit 1` fails the
first step. `--hang` sleeps at that point until killed. It reads the config and writes nothing.

## Before a real run

- A real run starts Blender and Kimodo (GPU, many GB of RAM, tens of minutes). Cancel kills the whole process tree;
  a stage killed half-way may leave an output newer than its inputs, which the freshness rule then takes as finished.
  After a cancel, delete that stage's output or run with `--from` that stage.
- Exit code 2 counts as a gate only with a `STOP:` line; argparse errors also exit 2 and are shown as failed.
- The state uses this checkout's `prepare_rig.py` as an input of `rig_ai`. With `--pipeline-cmd` pointing at another
  copy of the pipeline, its own script times decide what that run rebuilds.
- Approving key poses after a `choice.json` exists makes the AI stage stale: the next run samples Kimodo again
  through the approved poses (that is `character.py`'s rule).

## Tests

`python -m pytest server/tests` (also part of `python -m pytest`): a synthetic character and work dir built in a temp
folder stage by stage; state rules, verdict writer (key order, comments, atomicity, schema refusal), path safety, the
job runner with the fake command (queue, cancel, exit codes, log stream) and the API through the test client. No test
needs Blender, Kimodo, a GPU or real character files. `python -m server.export_openapi` rewrites the committed
OpenAPI document; `server/tests/test_openapi.py` fails when it is out of date.
