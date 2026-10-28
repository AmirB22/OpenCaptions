"""Local web UI. One worker thread does the heavy work, jobs live in the data directory."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import models, paths
from ..languages import is_supported, language_options
from ..pipeline import analyze, load_analysis, render
from ..styles import FONTS, PRESETS, hook_from_options, resolve

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="opencaptions")
_pool = ThreadPoolExecutor(max_workers=1)
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _job_dir(job_id: str) -> Path:
    return paths.jobs_dir() / job_id


def _save(job: dict) -> None:
    d = _job_dir(job["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")


def _load_all() -> None:
    root = paths.jobs_dir()
    if not root.exists():
        return
    for p in root.glob("*/job.json"):
        try:
            job = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if job.get("status") in ("analyzing", "rendering"):
            job["status"], job["error"] = "error", "interrupted by a restart"
        _jobs[job["id"]] = job


_load_all()


def _get(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


def _update(job: dict, **kw) -> None:
    with _lock:
        job.update(kw)
        _save(job)


def _source(job: dict) -> Path:
    return _job_dir(job["id"]) / job["source"]


@app.get("/api/config")
def config() -> dict:
    return {
        "presets": {k: asdict(v) for k, v in PRESETS.items()},
        "fonts": [{"id": k, "label": f.label, "installed": ok}
                  for (k, f), ok in zip(FONTS.items(), models.installed_fonts().values())],
        "model_ready": models.model_ready(),
        "languages": language_options(),
        "whisper_ready": importlib.util.find_spec("faster_whisper") is not None,
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)


@app.post("/api/jobs")
def create_job(file: UploadFile = File(...), language: str = Form("en")) -> dict:
    language = language.strip().lower() or "en"
    if not is_supported(language):
        raise HTTPException(400, f"unsupported language '{language}'")
    if language != "en" and importlib.util.find_spec("faster_whisper") is None:
        raise HTTPException(400, "other languages need Whisper, run: pip install -e '.[whisper]'")
    if language.startswith("en") and not models.model_ready():
        raise HTTPException(400, "speech model missing, run: opencaptions models fetch")
    job_id = uuid.uuid4().hex[:10]
    suffix = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = ".mp4"
    d = _job_dir(job_id)
    d.mkdir(parents=True)
    src = d / f"source{suffix}"
    with src.open("wb") as f:
        shutil.copyfileobj(file.file, f, 1 << 20)
    job = {"id": job_id, "name": file.filename or "video", "source": src.name, "status": "analyzing",
           "stage": "queued", "progress": 0.0, "error": None, "outputs": [], "created": time.time(),
           "language": language}
    _jobs[job_id] = job
    _save(job)
    _pool.submit(_run_analyze, job)
    return job


def _run_analyze(job: dict) -> None:
    def prog(stage: str, frac: float) -> None:
        job["stage"], job["progress"] = stage, round(frac, 3)

    try:
        analyze(_source(job), _job_dir(job["id"]), progress=prog, language=job.get("language", "en"),
                whisper_model=os.environ.get("OPENCAPTIONS_WHISPER_MODEL", "medium"))
        _update(job, status="ready", stage="done", progress=1.0)
    except Exception as e:
        _update(job, status="error", error=str(e))


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _get(job_id)
    out = dict(job)
    if job["status"] in ("ready", "rendering") or (job["status"] == "error" and (_job_dir(job_id) / "analysis.json").exists()):
        a = load_analysis(_job_dir(job_id))
        out["analysis"] = {"duration": a["duration"], "sentences": a["sentences"], "scenes": len(a["scenes"]),
                           "words": [w["w"] for w in a["words"]]}
    return out


class RenderRequest(BaseModel):
    keep: list[int]
    preset: str = "plain"
    overrides: dict = Field(default_factory=dict)
    brand: list[str] = Field(default_factory=list)
    fixes: list[str] = Field(default_factory=list)
    edits: dict[int, str] = Field(default_factory=dict)
    hook: dict = Field(default_factory=dict)


@app.post("/api/jobs/{job_id}/render")
def start_render(job_id: str, req: RenderRequest) -> dict:
    job = _get(job_id)
    if job["status"] not in ("ready", "error") or not (_job_dir(job_id) / "analysis.json").exists():
        raise HTTPException(409, "job is not ready")
    if not req.keep:
        raise HTTPException(400, "select at least one sentence")
    try:
        style = resolve({"preset": req.preset, **req.overrides})
        hook_from_options(req.hook)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    n = len(job["outputs"]) + 1
    fname = f"out_{n}.mp4"
    _update(job, status="rendering", stage="queued", progress=0.0, error=None)
    _pool.submit(_run_render, job, req, style, fname)
    return job


def _run_render(job: dict, req: RenderRequest, style, fname: str) -> None:
    def prog(stage: str, frac: float) -> None:
        job["stage"], job["progress"] = stage, round(frac, 3)

    d = _job_dir(job["id"])
    try:
        r = render(_source(job), d, req.keep, style, d / fname, brand=req.brand, fixes=req.fixes, edits=req.edits, hook=hook_from_options(req.hook), progress=prog)
        with _lock:
            job["outputs"].append({"file": fname, "duration": round(r["duration"], 1),
                                   "label": f"{req.preset}, {len(req.keep)} sentences",
                                   "created": time.time()})
        _update(job, status="ready", stage="done", progress=1.0)
    except Exception as e:
        _update(job, status="error", error=str(e))


@app.get("/api/jobs/{job_id}/source")
def source(job_id: str):
    return FileResponse(_source(_get(job_id)))


@app.get("/api/jobs/{job_id}/outputs/{fname}")
def output(job_id: str, fname: str):
    job = _get(job_id)
    if not any(o["file"] == fname for o in job["outputs"]):
        raise HTTPException(404, "no such output")
    return FileResponse(_job_dir(job_id) / fname, media_type="video/mp4",
                        filename=f"{Path(job['name']).stem}_{fname}")


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = _get(job_id)
    if job["status"] in ("analyzing", "rendering"):
        raise HTTPException(409, "job is running")
    shutil.rmtree(_job_dir(job_id), ignore_errors=True)
    _jobs.pop(job_id, None)
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
