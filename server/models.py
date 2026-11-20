"""Request and response models: the OpenAPI document generated from them is the contract of web/src/api/schema.d.ts."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

StageName = Literal["prepare", "rig", "rig_ai", "calibration", "ai", "merge", "preview"]
StageStatus = Literal["up_to_date", "stale", "waiting", "failed", "blocked", "skipped"]
GateKind = Literal["rig", "poses", "motion"]
JobState = Literal["queued", "running", "done", "waiting_for_review", "failed", "cancelled"]


class ImageRef(BaseModel):
    id: str = Field(description="opaque id for GET .../images/{id}")
    label: str


class Gate(BaseModel):
    kind: GateKind
    action: Optional[str] = None
    title: str
    needs: str = Field(description="what the reviewer must do")
    writes: Optional[str] = Field(None, description="what an approval writes (None: nothing, the trail only)")
    images: list[ImageRef] = []
    poses_options: list[str] = Field([], description="poses GLBs an approval may name, relative to the action folder")


class StageState(BaseModel):
    name: StageName
    status: StageStatus
    detail: str
    output: Optional[str] = None


class AuditSummary(BaseModel):
    result: str
    score: float
    source: str = Field(description="which audit: 'best sample' or 'after merge'")


class SampleScore(BaseModel):
    name: str
    score: float
    moved: Optional[float] = Field(None, description="how far the hands moved in the raw sample (m, the larger hand's extent "
                                   "against the hips); missing in files from before it was measured")


class Approved(BaseModel):
    bvh: Optional[str] = None
    score: float
    date: Optional[str] = None


class ActionState(BaseModel):
    name: str
    kind: Literal["library", "ai"]
    prop: bool
    loop: bool
    step: Literal["library", "body", "poses", "motion", "approved"]
    status: Literal["up_to_date", "stale", "waiting", "error"]
    detail: str
    gate: Optional[Gate] = None
    best: Optional[SampleScore] = None
    picked: Optional[Literal["auto", "by hand"]] = Field(None, description="how `best` was chosen: automatically or `--sample`")
    samples: list[SampleScore] = []
    approved: Optional[Approved] = None
    audit: Optional[AuditSummary] = None
    merged_audit: Optional[AuditSummary] = None
    review_sources: list[Literal["choice", "merged"]] = Field([], description="manifest sources that exist for this action")


class JobSummary(BaseModel):
    id: str
    character_id: str
    from_stage: Optional[StageName] = None
    to_stage: Optional[StageName] = None
    samples: dict[str, int] = {}
    state: JobState
    exit_code: Optional[int] = None
    outcome: Optional[str] = Field(None, description="the pipeline's last STOP/DONE/failed line")
    created_at: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    line_count: int


class CharacterSummary(BaseModel):
    id: str
    name: str
    config_path: str
    work_dir: Optional[str] = None
    gate: Optional[Gate] = None
    stale_stage: Optional[StageName] = None
    done: bool = False
    problems: list[str] = []
    active_job: Optional[JobSummary] = None


class PipelineState(BaseModel):
    character: CharacterSummary
    config_sha: str = Field(description="sha256 of character.json; send it back as expected_config_sha")
    stages: list[StageState]
    actions: list[ActionState]


class Manifest(BaseModel):
    """The format the viewer's ?data= loader reads; URLs are absolute."""
    title: Optional[str] = None
    action: Optional[str] = None
    glb: str
    audit: str
    samples: Optional[str] = None


class VerdictRequest(BaseModel):
    gate: GateKind
    action: Optional[str] = Field(None, description="required for poses and motion")
    decision: Literal["approve", "reject"]
    note: str = Field("", max_length=2000)
    reviewer: Optional[str] = Field(None, max_length=80)
    poses_glb: Optional[str] = Field(None, description="one of gate.poses_options; default the first")
    expected_config_sha: Optional[str] = Field(None, description="refuse the write if character.json changed since")


class Change(BaseModel):
    file: str
    json_path: str
    before: Any = None
    after: Any = None
    diff: str = Field("", description="unified diff of the file's text")


class VerdictPlan(BaseModel):
    request: VerdictRequest
    changes: list[Change]
    summary: str
    config_sha: str


class TrailEntry(BaseModel):
    id: str
    at: str
    reviewer: str
    gate: GateKind
    action: Optional[str] = None
    decision: Literal["approve", "reject"]
    note: str = ""
    changes: list[Change] = []


class VerdictResult(BaseModel):
    entry: TrailEntry
    summary: str


class RunRequest(BaseModel):
    from_stage: Optional[StageName] = None
    to_stage: Optional[StageName] = None
    samples: dict[str, int] = Field({}, description="action -> sample index of its latest batch, instead of the automatic "
                                    "choice (character.py --sample action=N)")


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    pipeline_command: list[str]
    characters: int


class ErrorBody(BaseModel):
    detail: Any
