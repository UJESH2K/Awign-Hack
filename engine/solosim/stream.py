"""Streaming analysis: a video is checked window by window and the report grows as it goes.

Annotation lint lands at once (no frames needed). Then every WINDOW seconds of footage: measure
hands and motion, re-run the timing checks for every segment the analysis has passed, and send
those segments to the AI label reviewer in parallel. The report on disk is rewritten after each
window with `analyzed_until`, so the tester sees mistakes appear on the timeline in time order
and can start fixing the first minute while the rest is still being checked.

Runs in its own process (batch.py starts several), so a batch of videos uses every core.
"""
import concurrent.futures as cf
import json
import os
import time

import cv2
import numpy as np

from . import checks, lint, vlm
from .clip_io import Clip

RATE = 4.0  # samples per second of footage
WINDOW = 10.0  # seconds of footage between report updates
CONTEXT = 1.5  # a segment is checked once the analysis is this far past its end


def _write(clip: Clip, rep: dict):
    tmp = clip.dir / "report.json.tmp"
    tmp.write_text(json.dumps(rep), encoding="utf-8")
    os.replace(tmp, clip.dir / "report.json")


def analyze(clip: Clip, vocab=None, labels: bool = True, rate: float = RATE, say=None) -> dict:
    from .signals import _boxes, _yolo

    say = say or (lambda *a: None)
    t0 = time.time()
    segs = sorted(clip.segments, key=lambda s: s.start)
    verbs, nouns = vocab or lint.vocabulary(segs)
    lint_issues = lint.run(segs, clip.duration, verbs, nouns)
    hand, face = _yolo("hand_yolov8n.pt"), _yolo("face_yolov8n.pt")
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
    cap = cv2.VideoCapture(str(clip.video))
    step = max(1, int(round(clip.fps / rate)))
    S = {k: [] for k in ("t", "blur", "bright", "dark", "blown", "head_motion", "hand_motion", "hands", "faces")}
    prev = None
    pool = cf.ThreadPoolExecutor(6) if labels and vlm.backend() in ("haiku", "claude", "groq") else None
    pending: dict[str, cf.Future] = {}
    label_results: dict[str, dict] = {}
    submitted: set[str] = set()
    next_report = WINDOW
    closed = False
    i = 0
    face_every = 3

    def sig():
        out = {k: np.array(v, np.float32) for k, v in S.items()}
        if not len(out["t"]):
            out["hands"] = np.zeros((0, 2, 5), np.float32)
            out["faces"] = np.zeros((0, 3, 5), np.float32)
        return out

    def report(until: float, final: bool):
        nonlocal label_results
        for sid, f in list(pending.items()):
            if f.done():
                try:
                    label_results.update(f.result())
                except Exception as e:  # noqa: BLE001
                    print(f"label check failed: {e!r}"[:200])
                pending.pop(sid)
        done = [g for g in segs if g.end + CONTEXT <= until or final]
        s = sig()
        issues = (checks.run(clip, s, segs, {g.id for g in done}) if len(s["t"]) >= 3 else []) + lint_issues
        if not final:  # unlabelled-activity runs that touch the moving edge may still grow
            issues = [x for x in issues if not (x.kind == "unlabelled activity" and (x.t_end or 0) > until - CONTEXT)]
        human = {g.id for g in done if (g.meta or {}).get("drafted_by") != "ai"}
        issues += vlm.issues(clip, {k: v for k, v in label_results.items() if k in human})
        if pool and not closed:
            for g in done:
                if g.id not in submitted and g.id in human:
                    submitted.add(g.id)
                    pending[g.id] = pool.submit(vlm.check, clip, None, {g.id}, 1)
        rep = checks.report(clip, s if len(s["t"]) else _empty(), issues, {"backend": vlm.backend(), "results": label_results})
        rep["progress"] = {"analyzed_until": round(until, 2), "duration": round(clip.duration, 2), "final": final,
                           "segments_checked": len(done), "labels_checked": len(label_results), "labels_pending": len(pending),
                           "seconds": round(time.time() - t0, 1)}
        rep["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write(clip, rep)
        return rep

    report(0.0, False)  # lint findings show up before a frame is decoded
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, bgr = cap.retrieve()
            if not ok:
                break
            H, W = bgr.shape[:2]
            g = cv2.cvtColor(cv2.resize(bgr, (320, int(320 * H / W)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            t = i / clip.fps
            S["t"].append(t)
            S["blur"].append(cv2.Laplacian(g, cv2.CV_64F).var())
            S["bright"].append(g.mean())
            S["dark"].append((g < 16).mean())
            S["blown"].append((g > 245).mean())
            small = cv2.resize(g, (160, int(160 * H / W)), interpolation=cv2.INTER_AREA)
            if prev is not None:
                f = dis.calc(prev, small, None)
                med = np.median(f.reshape(-1, 2), axis=0)
                S["head_motion"].append(float(np.hypot(*med)) * rate / small.shape[1])
                S["hand_motion"].append(float(np.linalg.norm(f - med, axis=2).mean()) * rate / small.shape[1])
            else:
                S["head_motion"].append(0.0)
                S["hand_motion"].append(0.0)
            prev = small
            S["hands"].append(_boxes(hand.predict(bgr, imgsz=480, conf=0.2, verbose=False)[0], W, H, 2))
            n = len(S["t"])
            if n % face_every == 1:
                S["faces"].append(_boxes(face.predict(bgr, imgsz=480, conf=0.45, verbose=False)[0], W, H, 3))
            else:
                S["faces"].append(np.full((3, 5), np.nan, np.float32))
            if t >= next_report:
                rep = report(t, False)
                say(t, rep)
                next_report += WINDOW
        i += 1
    cap.release()
    s = sig()
    s.update(rate=np.float32(rate), seconds=np.float32(time.time() - t0))
    np.savez_compressed(clip.dir / "signals.npz", **s)
    if pool:
        for g in segs:  # the last segments, which the moving edge never passed
            if g.id not in submitted and (g.meta or {}).get("drafted_by") != "ai":
                submitted.add(g.id)
                pending[g.id] = pool.submit(vlm.check, clip, None, {g.id}, 1)
        closed = True
        report(clip.duration, False)
        for sid, f in list(pending.items()):
            try:
                label_results.update(f.result(timeout=120))
            except Exception as e:  # noqa: BLE001
                print(f"label check failed: {e!r}"[:200])
        pending.clear()
        pool.shutdown(wait=False)
    rep = report(clip.duration, True)
    rep["timing"] = {"seconds": round(time.time() - t0, 1), "realtime_factor": round(clip.duration / max(0.1, time.time() - t0), 2)}
    _write(clip, rep)
    say(clip.duration, rep)
    return rep


def _empty():
    return {"t": np.zeros(0), "hands": np.zeros((0, 2, 5)), "blur": np.zeros(0), "faces": np.zeros((0, 3, 5)),
            "bright": np.zeros(0), "head_motion": np.zeros(0), "hand_motion": np.zeros(0)}
