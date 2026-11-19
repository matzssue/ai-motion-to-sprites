"""FastAPI app over the pipeline of the configured characters. The OpenAPI document of this app is the contract of
the web UI (web/src/api/schema.d.ts, generated). Safety rules: server/README.md."""
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import files, status, verdicts
from .jobs import JobManager
from .models import (ErrorBody, Health, JobSummary, Manifest, PipelineState, CharacterSummary, RunRequest, TrailEntry, VerdictPlan,
                     VerdictRequest, VerdictResult)
from .pipeline_lib import STAGES
from .settings import Settings

VERSION = "0.1.0"
ERRORS = {404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 422: {"model": ErrorBody}}


def create_app(settings: Settings, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")) -> FastAPI:
    jobs = JobManager(settings.pipeline_command)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        jobs.close()

    app = FastAPI(title="ai-motion-to-sprites review service", version=VERSION, lifespan=lifespan,
                  description="Local service over pipeline/character.py: pipeline state, review files, verdicts and runs.",
                  generate_unique_id_function=lambda route: route.name)
    app.state.jobs = jobs; app.state.settings = settings

    @app.middleware("http")
    async def refuse_foreign_writes(request: Request, call_next):
        """CORS does not stop a foreign page from *sending* a simple POST: refuse other origins and non-JSON bodies."""
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin not in settings.origins: return JSONResponse({"detail": "origin not allowed"}, 403)
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return JSONResponse({"detail": "send application/json"}, 415)
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "Last-Event-ID"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))   # against DNS rebinding

    def character(cid: str):
        c = settings.character(cid)
        if not c: raise HTTPException(404, "no character %r" % cid)
        return c

    def state_of(cid: str) -> PipelineState:
        c = character(cid); st = status.derive(c.config_path, c.id)
        job = jobs.active_for(c.id)
        if job: st.character.active_job = job.summary()
        return st

    def paths_of(cid: str, action: Optional[str] = None) -> status.Paths:
        c = character(cid)
        C = status.read_json(c.config_path)
        if not isinstance(C, dict) or "work_dir" not in C: raise HTTPException(409, "character.json cannot be read")
        if action is not None and action not in C.get("actions", {}): raise HTTPException(404, "no action %r" % action)
        return status.Paths(c.config_path, C)

    @app.get("/api/health", response_model=Health, tags=["service"])
    def health():
        return Health(status="ok", version=VERSION, pipeline_command=settings.pipeline_command, characters=len(settings.characters))

    @app.get("/api/characters", response_model=list[CharacterSummary], tags=["characters"])
    def list_characters():
        return [state_of(c.id).character for c in settings.characters]

    @app.get("/api/characters/{cid}", response_model=PipelineState, responses=ERRORS, tags=["characters"])
    def get_character(cid: str):
        return state_of(cid)

    @app.get("/api/characters/{cid}/actions/{action}/manifest.json", response_model=Manifest, response_model_exclude_none=True,
             responses=ERRORS, tags=["review"])
    def get_manifest(cid: str, action: str, request: Request, source: files.Source = "choice"):
        P = paths_of(cid, action)
        try:
            glb, audit, samples = (files.review_file(P, action, source, k) for k in ("glb", "audit", "samples"))
        except files.Refused as e:
            raise HTTPException(403, str(e))
        if not glb or not audit: raise HTTPException(404, "no reviewable %s files for '%s' yet" % (source, action))

        def url(kind):
            return str(request.url_for("get_review_file", cid=cid, action=action, kind=kind).include_query_params(source=source))
        what = "best sample" if source == "choice" else "after merge"
        return Manifest(title="%s %s (%s)" % (P.C["name"], action, what), action=action, glb=url("glb"), audit=url("audit"),
                        samples=url("samples") if samples else None)

    @app.get("/api/characters/{cid}/actions/{action}/files/{kind}", responses={**ERRORS, 403: {"model": ErrorBody},
             200: {"content": {"model/gltf-binary": {}, "application/json": {}}}}, response_class=FileResponse, tags=["review"])
    def get_review_file(cid: str, action: str, kind: files.Kind, source: files.Source = "choice"):
        P = paths_of(cid, action)
        try: path = files.review_file(P, action, source, kind)
        except files.Refused as e: raise HTTPException(403, str(e))
        if not path: raise HTTPException(404, "no %s file for '%s'" % (kind, action))
        return FileResponse(path, media_type=files.media_type(path), headers={"Cache-Control": "no-store"})

    @app.get("/api/characters/{cid}/images/{kind}/{index}", responses={**ERRORS, 403: {"model": ErrorBody},
             200: {"content": {"image/png": {}}}}, response_class=FileResponse, tags=["review"])
    def get_gate_image(cid: str, kind: Literal["rig", "poses"], index: int, action: Optional[str] = None):
        P = paths_of(cid, action)
        try: path = files.image_file(P, kind, action, index)
        except files.Refused as e: raise HTTPException(403, str(e))
        if not path: raise HTTPException(404, "no such image")
        return FileResponse(path, media_type=files.media_type(path), headers={"Cache-Control": "no-store"})

    def verdict_call(fn, cid: str, req: VerdictRequest, *args):
        c = character(cid)
        if jobs.busy(c.id): raise HTTPException(409, "a pipeline run of this character is queued or running; wait or cancel it")
        try: return fn(c.config_path, c.id, req, *args)
        except verdicts.VerdictError as e: raise HTTPException(e.status, e.detail)

    @app.post("/api/characters/{cid}/verdicts/preview", response_model=VerdictPlan, responses=ERRORS, tags=["verdicts"])
    def preview_verdict(cid: str, req: VerdictRequest):
        return verdict_call(verdicts.preview, cid, req)

    @app.post("/api/characters/{cid}/verdicts", response_model=VerdictResult, responses=ERRORS, tags=["verdicts"])
    def submit_verdict(cid: str, req: VerdictRequest):
        return verdict_call(verdicts.apply, cid, req, settings.reviewer)

    @app.get("/api/characters/{cid}/verdicts", response_model=list[TrailEntry], responses=ERRORS, tags=["verdicts"])
    def list_verdicts(cid: str, action: Optional[str] = None):
        paths_of(cid)
        return verdicts.history(character(cid).config_path, action)

    @app.post("/api/characters/{cid}/runs", response_model=JobSummary, status_code=202, responses=ERRORS, tags=["runs"])
    def start_run(cid: str, req: RunRequest):
        c = character(cid)
        if req.from_stage and req.to_stage and STAGES.index(req.from_stage) > STAGES.index(req.to_stage):
            raise HTTPException(422, "from_stage comes after to_stage")
        if jobs.busy(c.id): raise HTTPException(409, "this character already has a queued or running run")
        return jobs.submit(c.id, c.config_path, req.from_stage, req.to_stage).summary()

    @app.get("/api/jobs", response_model=list[JobSummary], tags=["runs"])
    def list_jobs():
        return [j.summary() for j in jobs.list()]

    def job_of(job_id: str):
        job = jobs.jobs.get(job_id)
        if not job: raise HTTPException(404, "no job %r" % job_id)
        return job

    @app.get("/api/jobs/{job_id}", response_model=JobSummary, responses=ERRORS, tags=["runs"])
    def get_job(job_id: str):
        return job_of(job_id).summary()

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobSummary, responses=ERRORS, tags=["runs"])
    def cancel_job(job_id: str):
        job_of(job_id)
        return jobs.cancel(job_id).summary()

    @app.get("/api/jobs/{job_id}/events", responses={**ERRORS, 200: {"content": {"text/event-stream": {}}, "description":
             "Server-sent events: `line` {n, text} for every log line (id = n), `state` (JobSummary) on every change, "
             "`end` (JobSummary) once the job has ended and every line was sent."}}, response_class=StreamingResponse, tags=["runs"])
    async def job_events(job_id: str, request: Request, after: int = 0):
        job = job_of(job_id)
        last_id = request.headers.get("last-event-id")
        if last_id and last_id.isdigit(): after = int(last_id) + 1

        async def stream():
            n = after; sent_state = None; quiet = 0.0
            while True:
                if await request.is_disconnected(): return
                first, lines = job.lines_after(n)
                for i, text in enumerate(lines):
                    yield "id: %d\nevent: line\ndata: %s\n\n" % (first + i, json.dumps({"n": first + i, "text": text}, ensure_ascii=False))
                n = first + len(lines)
                s = job.summary()
                if s.state != sent_state: yield "event: state\ndata: %s\n\n" % s.model_dump_json(); sent_state = s.state
                if not job.active and n >= s.line_count:
                    yield "event: end\ndata: %s\n\n" % s.model_dump_json(); return
                quiet = 0.0 if lines else quiet + 0.15
                if quiet >= 15: yield ": keep-alive\n\n"; quiet = 0.0
                await asyncio.sleep(0.15)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
