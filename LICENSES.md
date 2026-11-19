# Licenses of dependencies and models

This repository is MIT and contains **no** models, clips or weights. Everything below is installed or downloaded by
the user. Rule for new dependencies: the license must allow commercial use (prefer MIT, BSD, Apache-2.0); check it
before adding a row. CI (`tools/check_licenses.py`) fails when any SPDX identifier of an installed host package is not on its
permissive allowlist: GPL, AGPL, LGPL, MPL, non-commercial and unknown licenses fail.

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
| Mixamo clips and rigs | Adobe Mixamo terms | yes, inside projects | raw FBX files must not be redistributed; not in this repo |

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
| `pytest`, `ruff`, `pip-licenses` | MIT | yes | development only |
