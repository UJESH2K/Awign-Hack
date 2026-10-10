"""SoloSim engine: automated pre-QA for first-person robot-training data.

    uvicorn solosim.server:app --port 8765        (from engine/)

Clips
    GET  /clips                         every clip with its readiness summary
    POST /clips/upload                  a first-person video + its annotations (EPIC CSV or JSON)
    POST /clips/{id}/analyze            run the gate (background); GET /clips/{id}/progress
    GET  /clips/{id}                    the report: segments, statuses, issues, label opinions, decisions
    GET  /clips/{id}/video              the footage (range requests, so the player can seek)
    GET  /clips/{id}/track              per-sample hands / activity / blur for the overlay
    GET  /clips/{id}/frame.jpg?t=       one frame
Review
    POST /clips/{id}/decide             accept / apply the fix / reject / edit, per segment or issue
    POST /clips/{id}/claude/{segment}   deeper second opinion from Claude (capped, logged)
    GET  /clips/{id}/export             client-ready JSON: segments, QA status, reasons, provenance
Evidence
    GET  /bench                         planted-error benchmark results
    GET  /spend                         Claude ledger and Reactor budget
World-model render (render.py)
    POST /clips/{id}/render/{segment}   LingBot first-person render of the annotation (paid, needs confirm_spend)
    GET  /renders/{rid}, /renders/{rid}/frame/{k}.jpg
"""
import asyncio
import json
import threading
import time
from dataclasses import asdict

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import checks, pipeline, vlm
from .clip_io import CLIPS, DATA, Clip, Segment, list_clips

app = FastAPI(title="SoloSim engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_jobs: dict[str, dict] = {}  # clip id -> {"stage", "fraction", "status", "started"}
_lock = threading.Lock()


def _clip(cid: str) -> Clip:
    if "/" in cid or "\\" in cid or ".." in cid:
        raise HTTPException(404, "no such clip")
    try:
        return Clip(cid)
    except FileNotFoundError:
        raise HTTPException(404, "no such clip") from None


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _review(c: Clip) -> dict:
    return _read(c.dir / "review.json") or {"decisions": [], "original": None}


@app.get("/health")
async def health():
    return {"ok": True, "time": time.time(), "label_backend": vlm.backend()}


@app.get("/clips")
async def clips():
    out = []
    for cid in list_clips():
        c = Clip(cid)
        rep = _read(c.dir / "report.json")
        rv = _review(c)
        out.append({**c.summary(), "summary": rep["summary"] if rep else None, "generated": rep.get("generated") if rep else None,
                    "decisions": len(rv["decisions"]), "job": _jobs.get(cid)})
    return out


# ------------------------------------------------------------------ analysis
def _run(cid: str):
    def say(stage, frac):
        _jobs[cid].update(stage=stage, fraction=round(frac, 3))

    try:
        pipeline.analyze(Clip(cid), progress=say)
        _jobs[cid]["status"] = "done"
    except Exception as e:  # noqa: BLE001 - shown in the UI
        _jobs[cid].update(status="error", stage=f"error: {e!r}"[:300])


@app.post("/clips/{cid}/analyze")
async def analyze(cid: str):
    _clip(cid)
    with _lock:
        if _jobs.get(cid, {}).get("status") == "running":
            return _jobs[cid]
        _jobs[cid] = {"status": "running", "stage": "Starting", "fraction": 0.0, "started": time.time()}
    threading.Thread(target=_run, args=(cid,), daemon=True).start()
    return _jobs[cid]


@app.get("/clips/{cid}/progress")
async def progress(cid: str):
    return _jobs.get(cid) or {"status": "idle"}


@app.get("/clips/{cid}")
async def report(cid: str):
    c = _clip(cid)
    rep = _read(c.dir / "report.json")
    return {"clip": c.summary(), "segments": c.segments_json(), "report": rep, "review": _review(c), "job": _jobs.get(cid),
            "spend": vlm.claude_spend()}


@app.get("/clips/{cid}/video")
async def video(cid: str):
    c = _clip(cid)
    return FileResponse(c.video, media_type="video/mp4")


@app.get("/clips/{cid}/track")
async def track(cid: str):
    c = _clip(cid)
    if not (c.dir / "signals.npz").exists():
        raise HTTPException(409, "not measured yet: analyze the clip first")
    return await asyncio.to_thread(pipeline.track, c)


@app.get("/clips/{cid}/frame.jpg")
async def frame(cid: str, t: float = 0.0, w: int = 480):
    c = _clip(cid)
    im = await asyncio.to_thread(c.frame_at, t)
    if im is None:
        raise HTTPException(404, "no frame")
    if im.shape[1] > w:
        im = cv2.resize(im, (w, int(w * im.shape[0] / im.shape[1])), interpolation=cv2.INTER_AREA)
    jpg = cv2.imencode(".jpg", cv2.cvtColor(im, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------------------ upload
@app.post("/clips/upload")
async def upload(video: UploadFile = File(...), annotations: UploadFile = File(...), title: str = Form(""), task: str = Form("")):
    import re
    import tempfile

    raw_ann = (await annotations.read()).decode("utf-8", errors="replace")
    cid = re.sub(r"[^A-Za-z0-9_-]+", "-", (title or video.filename or "clip").rsplit(".", 1)[0])[:40].strip("-") or "clip"
    cid = f"{cid}-{time.strftime('%H%M%S')}"
    d = CLIPS / cid
    d.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir=d) as f:
        f.write(await video.read())
        src = f.name
    segs = _parse_annotations(raw_ann)
    if not segs:
        raise HTTPException(400, "no segments found: upload EPIC-style CSV or JSON [{start, end, label}]")
    await asyncio.to_thread(_to_browser_mp4, src, d / "video.mp4")
    (d / "annotations.json").write_text(json.dumps({
        "title": title or video.filename, "task": task or "first-person task",
        "source": {"dataset": "upload", "filename": video.filename, "annotation_file": annotations.filename},
        "segments": segs}, indent=1), encoding="utf-8")
    return Clip(cid).summary()


def _parse_annotations(text: str) -> list[dict]:
    import csv
    import io

    def ts(v):
        v = str(v).strip()
        if ":" in v:
            parts = [float(p) for p in v.split(":")]
            return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
        return float(v)

    segs = []
    text = text.strip()
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        rows = data.get("segments", data) if isinstance(data, dict) else data
        for i, r in enumerate(rows):
            label = r.get("narration") or r.get("label") or f"{r.get('verb', '')} {r.get('noun', '')}".strip()
            parts = label.split()
            segs.append({"id": str(r.get("id", f"s{i}")), "start": round(ts(r.get("start", r.get("start_timestamp"))), 2),
                         "end": round(ts(r.get("end", r.get("stop_timestamp"))), 2), "verb": r.get("verb") or (parts[0] if parts else ""),
                         "noun": r.get("noun") or " ".join(parts[1:]), "narration": label, "meta": {}})
    else:
        for i, r in enumerate(csv.DictReader(io.StringIO(text))):
            label = r.get("narration") or r.get("label") or f"{r.get('verb', '')} {r.get('noun', '')}".strip()
            parts = label.split()
            segs.append({"id": r.get("narration_id") or r.get("id") or f"s{i}",
                         "start": round(ts(r.get("start_timestamp") or r.get("start")), 2),
                         "end": round(ts(r.get("stop_timestamp") or r.get("end")), 2),
                         "verb": r.get("verb") or (parts[0] if parts else ""), "noun": (r.get("noun") or " ".join(parts[1:])).replace(":", " "),
                         "narration": label, "meta": {}})
    return sorted(segs, key=lambda s: s["start"])


def _to_browser_mp4(src: str, dst):
    """Re-encode to H.264 the browser can play and seek (needs ffmpeg; falls back to a copy)."""
    import os
    import shutil
    import subprocess

    ff = shutil.which("ffmpeg")
    if ff:
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(dst)],
                       check=True)
        os.unlink(src)
    else:
        shutil.move(src, dst)


# ------------------------------------------------------------------ review
class Decision(BaseModel):
    segment: str | None = None
    issue: str | None = None
    action: str  # accept (label is fine) | apply (take the suggested fix) | reject (drop the segment) | edit | add
    values: dict = {}
    note: str = ""


@app.post("/clips/{cid}/decide")
async def decide(cid: str, d: Decision):
    c = _clip(cid)
    rv = _review(c)
    if rv["original"] is None:
        rv["original"] = c.segments_json()
    segs = list(c.segments)
    rep = _read(c.dir / "report.json") or {"issues": []}
    issue = next((i for i in rep["issues"] if i["id"] == d.issue), None) if d.issue else None
    if d.action == "apply" and issue and issue.get("suggestion"):
        sug = issue["suggestion"]
        if sug["field"] == "add":
            v = sug["value"]
            segs.append(Segment(id=f"added-{int(time.time())}", start=v["start"], end=v["end"], verb=d.values.get("verb", "?"),
                                noun=d.values.get("noun", ""), narration=d.values.get("narration", "unlabelled action (to name)"),
                                meta={"added_by": "qa"}))
        else:
            for g in segs:
                if g.id == issue["segment"]:
                    if sug["field"] == "narration":
                        g.narration = sug["value"]
                        g.verb, g.noun = sug["value"].split()[0], " ".join(sug["value"].split()[1:])
                    else:
                        setattr(g, sug["field"], float(sug["value"]))
    elif d.action == "edit" and d.segment:
        for g in segs:
            if g.id == d.segment:
                for k in ("start", "end"):
                    if k in d.values:
                        setattr(g, k, float(d.values[k]))
                if "narration" in d.values:
                    g.narration = d.values["narration"]
                    g.verb, g.noun = g.narration.split()[0], " ".join(g.narration.split()[1:])
    elif d.action == "reject" and d.segment:
        segs = [g for g in segs if g.id != d.segment]
    if d.action in ("apply", "edit", "reject"):
        c.save_segments(sorted(segs, key=lambda s: s.start))
    rv["decisions"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "segment": d.segment or (issue or {}).get("segment"),
                            "issue": d.issue, "kind": (issue or {}).get("kind"), "action": d.action, "values": d.values, "note": d.note})
    (c.dir / "review.json").write_text(json.dumps(rv, indent=1), encoding="utf-8")
    # Re-check the edited timeline right away (cheap: signals are cached; label opinions stay cached).
    if d.action in ("apply", "edit", "reject") and (c.dir / "signals.npz").exists():
        await asyncio.to_thread(_recheck, c)
    return await report(cid)


def _recheck(c: Clip):
    from . import signals

    c = Clip(c.id)
    sig = signals.load(c)
    old = _read(c.dir / "report.json") or {}
    label = old.get("label") or {}
    results = {k: v for k, v in (label.get("results") or {}).items() if any(s.id == k for s in c.segments)}
    issues = checks.run(c, sig) + vlm.issues(c, results)
    rep = checks.report(c, sig, issues, {"backend": label.get("backend"), "results": results})
    rep["timing"], rep["generated"] = old.get("timing"), time.strftime("%Y-%m-%d %H:%M:%S")
    (c.dir / "report.json").write_text(json.dumps(rep), encoding="utf-8")


@app.post("/clips/{cid}/claude/{sid}")
async def claude(cid: str, sid: str):
    c = _clip(cid)
    if not any(s.id == sid for s in c.segments):
        raise HTTPException(404, "no such segment")
    try:
        res = await asyncio.to_thread(vlm.check, c, None, {sid}, 1, None, "claude")
    except vlm.SpendCap as e:
        raise HTTPException(402, str(e)) from e
    r = res.get(sid)
    if r is None:
        raise HTTPException(502, "Claude did not answer; try again")
    return {"result": r, "issues": [asdict(i) for i in vlm.issues(c, {sid: r}, start=2000)], "spend": vlm.claude_spend()}


@app.get("/clips/{cid}/export")
async def export(cid: str):
    c = _clip(cid)
    rep = _read(c.dir / "report.json")
    if not rep:
        raise HTTPException(409, "analyze the clip first")
    rv = _review(c)
    by = {}
    for i in rep["issues"]:
        if i.get("segment"):
            by.setdefault(i["segment"], []).append(i)
    decided = {d["segment"] for d in rv["decisions"] if d.get("segment")}
    out = {"clip": c.summary(), "qa": {"tool": "SoloSim pre-QA", "generated": rep.get("generated"), "readiness": rep["summary"]["readiness"],
                                         "label_backend": (rep.get("label") or {}).get("backend"), "decisions": len(rv["decisions"])},
           "segments": [{**asdict(s), "qa_status": "reviewed" if s.id in decided else rep["status"].get(s.id, "new"),
                         "qa_reasons": [{"kind": i["kind"], "t": i["t"], "detail": i["title"]} for i in by.get(s.id, [])]}
                        for s in c.segments],
           "open_issues": [i for i in rep["issues"] if not i.get("segment")],
           "review_log": rv["decisions"]}
    return Response(json.dumps(out, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{cid}-qa.json"'})


# ------------------------------------------------------------------ evidence
@app.get("/bench")
async def bench():
    root = DATA / "solosim"
    return {"timing": _read(root / "bench.json"), "labels": {k: _read(root / f"label_bench_{k}.json") for k in ("groq", "qwen", "claude")}}


@app.get("/spend")
async def spend():
    out = {"claude": vlm.claude_spend()}
    try:
        from lucid import budget

        out["reactor"] = {k: v for k, v in budget.summary().items() if k != "sessions"}
    except Exception:  # noqa: BLE001
        out["reactor"] = None
    return out


try:  # the LingBot render check lives in its own module (paid; optional)
    from .render import router as render_router

    app.include_router(render_router)
except ImportError:
    pass
