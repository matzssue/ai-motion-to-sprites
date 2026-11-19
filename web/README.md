# Motion review viewer (`web/`)

A browser viewer for one audited motion: it plays the animated GLB in 3D and shows where and when
`motion_audit.py` found a problem. It replaces reading `page.html` frame strips next to a table of numbers.

- 3D: pick an action, play / pause at 1×, ½×, ¼×, scrub by frame or quarter frame, orbit, 8 game directions
  (s … se, 30° down as in `preview_8.py`), ground grid, prop and skeleton toggles.
- Timeline: one row per metric with data, grouped as in the audit (penetration, joints, smoothness, grip), the
  value over the clip against its dashed limit, failing samples shaded. Clicking a shaded range jumps to the
  failing frame, puts a marker on the audit point in 3D and moves the camera close to it.
- Table: value at the playhead, clip maximum, limit, share of the clip over the limit. Labels and units are the
  ones of `pipeline/review/review_page.py`.

Everything runs in the browser. Files are parsed in the tab and never uploaded, so the static build needs no server.

## Run

Node 20.9 or newer.

```
cd web
npm ci
npm run dev          # http://localhost:3000
```

| Script | What it does |
|---|---|
| `npm run dev` | dev server |
| `npm run lint` | ESLint (Next.js rules + TypeScript) |
| `npm run typecheck` | `next typegen` + `tsc --noEmit` (strict) |
| `npm test` | Vitest: the pure logic in `src/audit`, `src/motion` and the license script |
| `npm run build` | static export into `out/`; `BASE_PATH=/ai-motion-to-sprites npm run build` for GitHub Pages |
| `npm run licenses` | license gate over the production packages in `package-lock.json` |
| `npm run local -- <character.json or folder> [--fake]` | review service (`python -m server`) + dev server, wired together |
| `npm run api:types` | regenerate `src/api/schema.d.ts` from `src/api/openapi.json` |
| `npm run api:check` | fail when `src/api/schema.d.ts` is out of date (CI) |

`.github/workflows/deploy-pages.yml` builds and deploys `out/` to GitHub Pages. It only runs by hand
(`workflow_dispatch`) after Pages is enabled with "GitHub Actions" as the source.

## Data

Drop onto the page (or "Open files…"), in any order:

1. the animated GLB **the audit ran on**: the file passed to `motion_audit.py --glb` (`prop_*.glb` after
   `prop_in_hands.py`). A later `merged_*.glb` of the same take can be retimed and grounded: on the crossbowman
   sample its points were 3–16 mm off;
2. `audit.json` from the audit folder, or a review folder's `data.json` (it embeds the report);
3. optionally `audit_samples.json` from the same folder: without it the timeline only shows each error's range.

When samples are loaded, the action whose length matches the audit is selected. A warning appears when another
action is shown. Bad files get a message naming the file and the field (`src/audit/parse.ts`).

For development, `?data=<folder or manifest.json>` loads files over HTTP, with paths relative to the manifest:

```json
{ "title": "crossbowman attack", "action": "attack", "glb": "prop_kf_s1.glb", "audit": "audit.json", "samples": "audit_samples.json" }
```

Put the folder under `web/public/local/` (gitignored) and open `http://localhost:3000/?data=local/<folder>/`.
The repository ships no characters, so no sample data is committed.

## Server-backed pages

With the review service (`../server/README.md`) the app also has:

- `/characters/`: every configured character and what it waits for;
- `/character/?id=<id>`: the seven stages as a stepper (each status as a glyph and words, not colour alone), the
  waiting gate with its preview images and verdict controls, one card per action (best sample and all scores, audits,
  approval), a run control (stage range, live log, cancel, end state: done / stopped at a gate / failed / cancelled)
  and the review trail. The page reloads its state when a run ends or a verdict is written;
- `/review/?character=<id>&action=<action>[&source=choice|merged]`: this viewer fed by the service's manifest, with the
  verdict next to the motion. Approve or reject asks the service for a preview first and shows exactly what would be
  written (file, JSON path, before/after, diff); nothing is written before "Write it".

The service's address is `NEXT_PUBLIC_API_BASE`, inlined at build time (`npm run local` sets it). Without it, or with
the service stopped, these pages say how to start it, and the file viewer at `/` keeps working with dropped files:
the static export (no API base) is the public demo. Query parameters address characters and actions because a static
export has no dynamic route segments.

### The API contract

`server/` is the single source of the request and response shapes:

```
server/models.py (Pydantic) ─► python -m server.export_openapi ─► src/api/openapi.json (committed)
                                                                   └► npm run api:types ─► src/api/schema.d.ts (committed)
```

`src/api/types.ts` only gives names to the generated types and `src/api/client.ts` checks at compile time that its
calls return them, so a change on the server is a type error here. `server/tests/test_openapi.py` fails when
`openapi.json` is stale, `npm run api:check` when `schema.d.ts` is.

Client state: `src/api/resource.ts` (load/reload keeping shown data), `src/review/verdictFlow.ts` (compose → preview →
confirm → written), `src/runs/log.ts` (log lines by index, so a reconnect does not duplicate them). The run log streams
over server-sent events (`EventSource`) and is flushed into React ten times a second; the playhead still stays out of
React state.

## How it works

Read `src/state/store.ts` first: it holds everything the UI shows and every action that changes it.

```
files / ?data=  ──►  src/loading/load.ts         GLTFLoader.parseAsync, JSON.parse + zod (src/audit/parse.ts)
                     │
                     ▼
                     src/state/store.ts           useReview (model, audit, action, play state, selection, camera)
                     │                            usePlayhead (current frame, changes every animation frame)
          ┌──────────┴───────────┐
          ▼                      ▼
 components/scene/*        components/Timeline, MetricTable, PlaybackBar, AuditHeader
 (react-three-fiber)       (DOM)
```

- **Two stores, on purpose.** `useReview` changes rarely; components subscribe to it with hooks and re-render.
  The frame changes 60 times a second, so it lives in `usePlayhead`, which no component reads as a hook. The render
  loop (`useFrame` in `Character.tsx`) advances it and reads it with `getState()`. DOM readouts (timeline cursor,
  slider, frame number, "at playhead" column) follow it with `usePlayheadEffect`, which writes to elements through
  refs. Playing a clip re-renders no React component.
- **Plain three.js where possible.** `src/motion/rig.ts` (`MotionRig`) poses the GLB at a given frame:
  `action.time = frame / 24; mixer.update(0)` on a paused action. When the action changes, every node goes back
  to its rest transform first: a bone without tracks in the new clip would otherwise keep the pose of the old one.
  `motion_audit.py` and `preview_8.py` reset `matrix_basis` for the same reason. It has no React and no WebGL, so
  it is unit-tested (`rig.test.ts`).
- **Client only.** `components/scene/Scene.tsx` is loaded with `next/dynamic` and `ssr: false`; the static
  export prerenders only the page around it.
- **Validation.** `src/audit/schema.ts` holds the zod schemas and every TypeScript type for the audit files.
  Older reports without `scores` or `no_limit` get defaults; a file from another tool or a wrong field gives a
  message instead of a blank page.

### Coordinates: Blender (x, y, z) → three.js (x, z, −y)

The audit's `where` points are Blender world coordinates (Z up, the character faces −Y). Blender's glTF importer
maps glTF (x, y, z) to Blender (x, −z, y), so `blenderToThree` is the inverse (`src/motion/coords.ts`).

Evidence (a script that loads the GLB with three.js in Node, skins every body vertex at the audit frame, and
measures the distance from the converted `where` to the nearest vertex; `where` is a hand, forearm or body vertex):

| sample | point | (x, z, −y) | identity | (x, −z, y) | (x, z, y) |
|---|---|---|---|---|---|
| crossbowman `prop_kf_s1.glb` | `hands_in_head`, fr. 71 | **0.01 mm** | 408 mm | 193 mm | 19 mm |
| crossbowman | `hands_in_torso` fr. 8, `forearms_in_head` fr. 80, `fingers_in_prop` fr. 99 | **0.00 mm** | 61–460 mm | 4–56 mm | 10–92 mm |
| crossbowman | mesh-stretch vertex in 100 samples across the clip | **worst 0.00 mm** | | | |
| exploder `merged_kf_s1.glb` | `hands_in_head` fr. 22.5 / `hands_in_torso` fr. 23.25 | **0.10 / 0.01 mm** | 177 / 305 mm | | |

There is no hidden scale. Every GLB has an `Armature` node with scale 0.01 and a 90° X rotation (Mixamo
centimetres), but it is part of the glTF node tree, so three.js world space equals glTF world space. The
character's origin is at the hips (the crossbowman's feet are at y = −0.965 at rest). A `where` at z = 0.56
is about 1.5 m above the feet: head height in a hunched aim. In the browser, the `hands_in_head` marker at
frame 71 lands where the audit close-ups (`closeups/hands_in_head_fr71.00_front.png`, `_right.png`) show the
claw touching the jaw.

### Time: frame = seconds × 24

The audit imports the GLB after `read_factory_settings`, so Blender runs at 24 fps and a glTF key at t seconds
lands on frame 24·t. The GLB keys themselves are 30 fps (the crossbowman attack has 125 keys over 4.125 s).
The audit samples from frame 0 to int(last frame) every ¼ frame, so its last `t` is ⌊24·duration⌋
(99.0 for 4.125 s, 49.0 for 2.067 s). The same vertex check at 30 fps: 13.9 mm at frame 71 and up to 83 mm over
the clip; at 24 fps, 0.00 mm. One frame off: 4–14 mm.

## Dependencies and licenses

Production: `next`, `react`, `react-dom`, `three`, `@react-three/fiber`, `@react-three/drei`, `zustand`, `zod`.
All MIT. The server-backed pages add no production package. Development adds `openapi-typescript` (MIT; its tree is MIT,
ISC, Apache-2.0 and BlueOak-1.0.0). The whole production tree is checked by `scripts/check-licenses.mjs` (CI job `web`). The allowlist
matches `tools/check_licenses.py` (no GPL, LGPL, AGPL, MPL, non-commercial or unknown), plus CC-BY-4.0 for the
`caniuse-lite` browser data.

Next.js lists `sharp` as an optional dependency for its image optimizer, and sharp's binaries bundle libvips
(LGPL-3.0). This app is a static export with `images.unoptimized`, so sharp is never used. `package.json`
replaces it with the empty MIT package in `stubs/sharp` (`overrides: { "sharp": "$sharp" }`).

Development tools are pinned to versions that run on Node 20.17: Vitest 3, ESLint 9, TypeScript 5.9.
