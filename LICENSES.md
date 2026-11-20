# Licenses of dependencies and models

This repository is MIT and contains **no** models, clips or weights. Everything below is installed or downloaded by
the user. Rule for new dependencies: the license must allow commercial use (prefer MIT, BSD, Apache-2.0); check it
before adding a row. CI (`tools/check_licenses.py`) fails when any SPDX identifier of an installed host package (base dependencies and
the `server` extra) is not on its permissive allowlist: GPL, AGPL, LGPL, MPL, non-commercial and unknown licenses fail.

## Models and assets

| Dependency | License | Commercial use | Note |
|---|---|---|---|
| Kimodo `Kimodo-SOMA-*` checkpoints | NVIDIA Open Model License | yes | default (`Kimodo-SOMA-RP-v1.1`); weights are not redistributed here |
| Kimodo `Kimodo-G1-*` checkpoints | NVIDIA Open Model License | yes | weights are not redistributed here |
| Kimodo `Kimodo-SMPLX-RP-v1` | NVIDIA R&D Model License | **no** | refused by `KIMODO_MODEL` check in `pipeline/lib/config.py` |
| Meta-Llama-3-8B-Instruct | Llama 3 Community License | yes | gated on Hugging Face; used only for sentence embeddings |
| `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp` | MIT (Hugging Face license tag) | yes | adapter on top of Llama 3, whose license still applies to the base weights |
| `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised` | MIT (Hugging Face license tag, checked 2026-11-19) | yes | loaded by `kimodo_text.py`; same note on the base weights |
| SOMA-X body models (MANO hands) | MANO license | **no** | must not be used; this pipeline does not load them |
| SOMA77 skeleton proportions (`kimodo/assets/skeletons/somaskel77/somaskel77_standard_tpose.bvh`, Kimodo repository) | Apache-2.0 | yes | numbers only: body proportions of the auto-rig (`pipeline/rig/auto_rig.py` `SOMA`, recomputed by `tools/soma_proportions.py`), spine split, clavicle start and finger joints of the own skeleton (`pipeline/lib/own_skeleton.py`) |
| ANSUR II summary statistics (Gordon et al. 2014, "2012 Anthropometric Survey of U.S. Army Personnel: Methods and Summary Statistics", NATICK/TR-15/007, U.S. Army) | report approved for public release, distribution unlimited; only measured means (facts) are used | yes | numbers only (means of stature, crotch, axilla, acromial and lateral malleolus height, foot length): the auto-rig's joint-to-surface relations (`auto_rig.py` `HIPS_ABOVE_CROTCH`, `ARM_UP`, `ANKLE_PER_FOOT`) |
| Mixamo clips and rigs | Adobe Mixamo terms | yes, inside projects | raw FBX files must not be redistributed; not in this repo. Mixamo output must not be used to create, train, test or improve ML/AI systems (Mixamo Additional Terms) nor to recreate the service (Adobe General Terms). Not affiliated with Adobe; "Mixamo-compatible" means bone naming only. No Mixamo rig, clip or joints file is a source or a check of the auto-rig's numbers; a `--template` FBX the user supplies is read at run time for its own layout |

## Code

| Dependency | License | Commercial use | Note |
|---|---|---|---|
| Kimodo (code) | Apache-2.0 | yes | own venv |
| SOMA-X (`py-soma-x`) | Apache-2.0 | yes | installed with Kimodo |
| PyTorch | BSD-3-Clause | yes | Kimodo venv |
| `transformers`, `peft` | Apache-2.0 | yes | Kimodo venv (`kimodo_text.py`) |
| `bitsandbytes` | MIT | yes | Kimodo venv (4-bit Llama) |
| Blender | GPL-2.0-or-later | yes | outputs (GLB, renders) are not covered by the GPL; the scripts here that import `bpy` are MIT, which is GPL-compatible |
| `numpy` | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 (2.4) | yes | host Python; bundled parts carry their own permissive licenses |
| `scipy` | BSD-3-Clause | yes | host Python |
| `Pillow` | MIT-CMU (HPND) | yes | host Python |
| `jsonschema` (+ `attrs`, `referencing`, `rpds-py`, `jsonschema-specifications`) | MIT | yes | host Python, config validation (`schemas/`) |
| `psutil` | BSD-3-Clause | yes | optional, `variants.py` free-RAM probe |
| `fastapi` | MIT | yes | `server` extra: the review service (`server/`) |
| `starlette` | BSD-3-Clause | yes | via FastAPI |
| `pydantic`, `pydantic-core`, `typing-inspection`, `annotated-types`, `annotated-doc` | MIT | yes | via FastAPI: request and response models |
| `anyio` | MIT | yes | via Starlette |
| `opentelemetry-api` | Apache-2.0 | yes | via FastAPI |
| `uvicorn` (+ `click`, `h11`) | BSD-3-Clause (`h11` MIT) | yes | `server` extra: the ASGI server |
| `idna` | BSD-3-Clause | yes | via AnyIO |
| `typing_extensions`, `exceptiongroup` | PSF-2.0, MIT | yes | backports on Python 3.10 |
| `pytest`, `ruff`, `pip-licenses` | MIT | yes | development only |
| `httpx2` (+ `httpcore2`, `truststore`) | BSD-3-Clause (`truststore` MIT) | yes | development only: Starlette's test client. The older `httpx` pulled `certifi` (MPL-2.0); `httpx2` does not |

## Web viewer (`web/`)

npm packages, checked by `web/scripts/check-licenses.mjs` over every production package in `web/package-lock.json`
(88 packages, all platforms' optional binaries included). Same allowlist as `tools/check_licenses.py`, plus CC-BY-4.0
for browser-support data.

| Dependency | License | Commercial use | Note |
|---|---|---|---|
| `next` (+ `@next/swc-*` binaries, `@next/env`, `styled-jsx`, `postcss`) | MIT | yes | static export only |
| `@swc/helpers` | Apache-2.0 | yes | via Next.js |
| `caniuse-lite` | CC-BY-4.0 | yes (attribution) | browser-support data used at build time |
| `react`, `react-dom` | MIT | yes | |
| `three` | MIT | yes | |
| `@react-three/fiber`, `@react-three/drei` (+ `three-stdlib`, `three-mesh-bvh`, `camera-controls`, `troika-three-text`) | MIT | yes | |
| `@mediapipe/tasks-vision`, `hls.js`, `draco3d`, `@dimforge/rapier3d-compat`, `promise-worker-transferable` | Apache-2.0 | yes | pulled in by drei and three-stdlib, unused here |
| the remaining small packages (`tslib`, `which`, `ieee754`, …) | MIT, ISC, BSD-3-Clause, 0BSD | yes | full list: `npm run licenses` in `web/` |
| `webgl-constants` | MIT (LICENSE file; no `license` field) | yes | via drei; listed by hand in the license script |
| `zustand` | MIT | yes | state |
| `zod` | MIT | yes | audit file validation |
| `sharp` | replaced by an empty MIT stub (`web/stubs/sharp`) | yes | Next.js's optional image optimizer; the real package bundles libvips (LGPL-3.0) and is never installed |
| `typescript` | Apache-2.0 | yes | development only |
| `openapi-typescript` (+ `@redocly/openapi-core`, `yaml-ast-parser`, `minimatch`, …) | MIT (tree: MIT, ISC, Apache-2.0, BlueOak-1.0.0) | yes | development only: generates `src/api/schema.d.ts` |
| `eslint`, `eslint-config-next`, `vitest`, `@types/*` | MIT | yes | development only |
