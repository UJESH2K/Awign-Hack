"""Will this annotation work as a robot-training scenario? Render it in LingBot World 2 and see.

From the segment's first real frame, LingBot generates the next few seconds in first person,
prompted with the annotation. The render is then compared with what really happened:

    real vs render   a vision model sees both contact sheets and lists every point where the
                     render fails: hands vanish or merge, the object morphs or disappears, the
                     action is not performed, the scene turns into another place
    scene drift      ResNet-18 similarity of every rendered frame to the real start frame
    hands            the hand detector on every rendered frame

A segment whose action renders cleanly is a reusable scenario; failure points show which part
of the annotation (object, verb, hand pose) the world cannot reproduce. Paid: every run is capped
in seconds, authorised against the local Reactor ledger, and only starts with confirm_spend.
"""
import asyncio
import base64
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .clip_io import DATA, Clip

router = APIRouter()
RENDERS = DATA / "solosim" / "renders"
CHUNKS = 12  # ~6 s of generated video
_runs: dict[str, dict] = {}


def prompt_for(narration: str, task: str) -> str:
    return ("Strict first-person view from a head-mounted camera, the camera wearer's own hands in the lower half of the "
            f"frame. In a {task or 'home kitchen'}, the hands {narration}, slowly and clearly, the object staying in view. "
            "The camera holds steady; the room, furniture and lighting stay exactly as in the first frame. Photorealistic, "
            "two human hands, natural skin, no extra people.")


def _sheet(frames: list[np.ndarray], n=6, cell=240) -> str:
    idx = np.linspace(0, len(frames) - 1, min(n, len(frames))).astype(int)
    cells = []
    for j, i in enumerate(idx):
        im = cv2.resize(frames[i], (cell, int(cell * frames[i].shape[0] / frames[i].shape[1])), interpolation=cv2.INTER_AREA)
        im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR)
        cv2.rectangle(im, (0, 0), (60, 24), (0, 0, 0), -1)
        cv2.putText(im, str(j + 1), (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(im)
    while len(cells) % 3:
        cells.append(np.zeros_like(cells[0]))
    sheet = np.vstack([np.hstack(cells[r:r + 3]) for r in range(0, len(cells), 3)])
    return base64.b64encode(cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])[1]).decode()


JUDGE = {
    "renders_action": "true if the render clearly shows the annotated action being performed",
    "verdict": "works | partial | fails",
    "failures": "list of {frame: 1-6 in the render sheet, kind: hands missing|hands merged|extra hand|object vanished|object morphed|wrong action|scene changed|camera drift, what: max 15 words}",
    "summary": "max 30 words: what this means for using the annotation as a robot-training scenario",
}


def judge(real: list[np.ndarray], render: list[np.ndarray], narration: str) -> dict:
    """Free vision judge (Groq): real footage vs render, failure points by frame."""
    import os
    import urllib.request

    from . import vlm  # loads .env.local

    if not os.environ.get("GROQ_API_KEY"):
        return {"verdict": "unknown", "failures": [], "summary": "no judge configured", "renders_action": False}
    keys = "; ".join(f"{k}: {v}" for k, v in JUDGE.items())
    content = [{"type": "text", "text": f"Image 1: six frames of REAL first-person footage of the annotated action \"{narration}\"."},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_sheet(real)}"}},
               {"type": "text", "text": "Image 2: six frames (numbered 1-6) of a WORLD-MODEL RENDER that started from the first real frame "
                                        "and was asked to show the same action."},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_sheet(render)}"}},
               {"type": "text", "text": "Compare them. Where does the render fail to reproduce the annotation? Be specific about "
                                        f"hands and the object. Reply with a JSON object only. Keys - {keys}"}]
    body = {"model": vlm.GROQ_MODEL, "max_tokens": 600, "temperature": 0, "reasoning_effort": "none", "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "You audit world-model renders used as robot-training scenarios."},
                         {"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "Content-Type": "application/json",
                                  "User-Agent": "solosim/0.1"})
    import urllib.error

    for attempt in range(6):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=90).read())
            out = json.loads(r["choices"][0]["message"]["content"])
            out["failures"] = [f for f in out.get("failures", []) if isinstance(f, dict)]
            return out
        except urllib.error.HTTPError as e:  # free tier: wait as long as it asks
            time.sleep(float(e.headers.get("retry-after") or (3 + 3 * attempt)) + 1)
        except Exception:  # noqa: BLE001 - retry, then report no judgement
            time.sleep(2 + 2 * attempt)
    return {"verdict": "unknown", "failures": [], "summary": "judge unavailable", "renders_action": False}


def measure(real0: np.ndarray, render: list[np.ndarray]) -> list[dict]:
    """Per rendered frame: similarity to the real start frame, and hands seen."""
    from lucid.audit import embed

    from .signals import _yolo

    z0 = embed([real0])[0]
    zs = embed(render)
    hand = _yolo("hand_yolov8n.pt")
    out = []
    for i, (im, z) in enumerate(zip(render, zs)):
        res = hand.predict(cv2.cvtColor(im, cv2.COLOR_RGB2BGR), imgsz=640, conf=0.25, verbose=False)[0]
        H, W = im.shape[:2]
        boxes = [[b[0] / W, b[1] / H, b[2] / W, b[3] / H] for b in res.boxes.xyxy.tolist()]
        out.append({"k": i, "scene": round(float(z @ z0), 3), "hands": len(boxes), "hand_boxes": boxes})
    return out


async def _render(rid: str, clip: Clip, seg, seconds: int):
    from lucid import budget
    from lucid.worlds.base import Scene
    from lucid.worlds.reactor_world import ReactorWorld

    d = RENDERS / rid
    (d / "render").mkdir(parents=True, exist_ok=True)
    (d / "real").mkdir(parents=True, exist_ok=True)
    st = _runs[rid]
    st.update(status="running", stage="Preparing the seed frame")
    seed = clip.frame_at(seg.start)
    seed_path = d / "seed.jpg"
    cv2.imwrite(str(seed_path), cv2.cvtColor(cv2.resize(seed, (1280, int(1280 * seed.shape[0] / seed.shape[1])), interpolation=cv2.INTER_CUBIC), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    real = [clip.frame_at(float(t)) for t in np.linspace(seg.start, seg.end, 12)]
    for i, im in enumerate(real):
        cv2.imwrite(str(d / "real" / f"{i:03d}.jpg"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    prompt = prompt_for(seg.narration, clip.task.split(",")[0] if clip.task else "home kitchen")
    world = ReactorWorld("drone", log=lambda m: st.update(stage=m))
    frames = []
    try:
        await world.open(planned_seconds=seconds)
        st.update(stage="LingBot is generating the scenario")
        await world.start(Scene(name=f"{clip.id}/{seg.id}", prompt=prompt, seed_image=str(seed_path), seed=7))
        for k in range(CHUNKS):
            ch = await world.next_chunk()
            im = ch.hires if ch.hires is not None else ch.frames[-1]
            frames.append(im)
            cv2.imwrite(str(d / "render" / f"{k:03d}.jpg"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
            st.update(stage=f"Rendered {k + 1}/{CHUNKS} chunks", frames=k + 1)
    except budget.BudgetExceeded as e:
        st.update(stage=f"stopped at the cap: {e}")
    finally:
        await world.close()
        st["usage"] = world.usage()
    if not frames:
        st.update(status="error", stage="no frames rendered")
        return
    st.update(stage="Comparing the render with the real footage")
    metrics = await asyncio.to_thread(measure, real[0], frames)
    verdict = await asyncio.to_thread(judge, real, frames, seg.narration)
    sheet_idx = np.linspace(0, len(frames) - 1, min(6, len(frames))).astype(int).tolist()
    for f in verdict.get("failures", []):
        try:
            f["k"] = sheet_idx[max(1, min(len(sheet_idx), int(f.get("frame", 1)))) - 1]
        except (TypeError, ValueError):
            f["k"] = 0
    drift = [m["k"] for m in metrics if m["scene"] < 0.8]
    out = {"id": rid, "clip": clip.id, "segment": seg.id, "narration": seg.narration, "prompt": prompt, "start": seg.start,
           "end": seg.end, "chunks": len(frames), "real_frames": len(real), "metrics": metrics, "judge": verdict,
           "drift_from": drift[0] if drift else None, "usage": st.get("usage"), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (d / "render.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    st.update(status="done", stage="Done", result=out)


class RenderRequest(BaseModel):
    confirm_spend: bool = False
    seconds: int = 30


@router.post("/clips/{cid}/render/{sid}")
async def start_render(cid: str, sid: str, req: RenderRequest):
    from lucid import budget

    try:
        clip = Clip(cid)
    except FileNotFoundError:
        raise HTTPException(404, "no such clip") from None
    seg = next((s for s in clip.segments if s.id == sid), None)
    if seg is None:
        raise HTTPException(404, "no such segment")
    if not req.confirm_spend:
        raise HTTPException(428, "This uses paid Reactor credit and needs your confirmation first.")
    if any(r.get("status") == "running" for r in _runs.values()):
        raise HTTPException(409, "a render is already running")
    seconds = max(20, min(60, req.seconds))
    try:
        budget.authorize("reactor/lingbot-world-2", seconds)
    except budget.BudgetExceeded as e:
        raise HTTPException(402, str(e)) from e
    rid = f"{cid}-{sid}-{time.strftime('%H%M%S')}"
    _runs[rid] = {"id": rid, "clip": cid, "segment": sid, "status": "starting", "stage": "Connecting to LingBot", "frames": 0}

    def run():
        asyncio.run(_render(rid, clip, seg, seconds))

    threading.Thread(target=run, daemon=True).start()
    return _runs[rid]


@router.get("/renders")
async def list_renders(clip: str | None = None):
    out = []
    for f in sorted(RENDERS.glob("*/render.json"), reverse=True):
        r = json.loads(f.read_text(encoding="utf-8"))
        if clip is None or r["clip"] == clip:
            out.append({k: r[k] for k in ("id", "clip", "segment", "narration", "chunks", "at")} | {"verdict": r["judge"].get("verdict")})
    running = [r for r in _runs.values() if r.get("status") in ("starting", "running") and (clip is None or r["clip"] == clip)]
    return {"renders": out, "running": running}


@router.get("/renders/{rid}")
async def get_render(rid: str):
    if rid in _runs and _runs[rid].get("status") != "done":
        return _runs[rid]
    f = RENDERS / rid / "render.json"
    if "/" in rid or "\\" in rid or not f.exists():
        raise HTTPException(404, "no such render")
    return {"status": "done", "result": json.loads(f.read_text(encoding="utf-8"))}


@router.get("/renders/{rid}/{kind}/{k}.jpg")
async def render_frame(rid: str, kind: str, k: int):
    f = RENDERS / rid / kind / f"{k:03d}.jpg"
    if kind not in ("render", "real") or "/" in rid or not f.exists():
        raise HTTPException(404, "no such frame")
    return Response(f.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


def rejudge(rid: str) -> dict:
    """Run the (free) judge again on a stored render: no new world-model spend."""
    d = RENDERS / rid
    r = json.loads((d / "render.json").read_text(encoding="utf-8"))
    load = lambda kind, n: [cv2.cvtColor(cv2.imread(str(d / kind / f"{k:03d}.jpg")), cv2.COLOR_BGR2RGB) for k in range(n)]  # noqa: E731
    frames, real = load("render", r["chunks"]), load("real", r["real_frames"])
    verdict = judge(real, frames, r["narration"])
    sheet_idx = np.linspace(0, len(frames) - 1, min(6, len(frames))).astype(int).tolist()
    for f in verdict.get("failures", []):
        try:
            f["k"] = sheet_idx[max(1, min(len(sheet_idx), int(f.get("frame", 1)))) - 1]
        except (TypeError, ValueError):
            f["k"] = 0
    r["judge"] = verdict
    (d / "render.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    return r


@router.post("/renders/{rid}/judge")
async def judge_again(rid: str):
    if "/" in rid or "\\" in rid or not (RENDERS / rid / "render.json").exists():
        raise HTTPException(404, "no such render")
    return {"status": "done", "result": await asyncio.to_thread(rejudge, rid)}
