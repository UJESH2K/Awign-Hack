"""One clip through the whole gate: measure -> check -> second opinion -> report.

The report is what the tester opens: every segment with a status (pass / check / fix), every issue
with its exact time, a box when there is one, the one-line nudge and, where possible, the fix.
"""
import json
import time
from dataclasses import asdict

import numpy as np

from . import checks, draft, signals, vlm
from .clip_io import Clip


def analyze(clip: Clip, progress=None, labels: bool = True) -> dict:
    say = progress or (lambda *a, **k: None)
    t0 = time.time()
    say("Measuring every frame: hands, faces, blur, light, motion", 0.02)
    sig = signals.load(clip, progress=lambda m, f: say(m, 0.02 + 0.5 * f))
    if not clip.segments:
        say("No annotations: AI first pass from hand activity", 0.53)
        draft.draft(clip, sig, progress=lambda m, f: say(m, 0.53 + 0.3 * f))
    say("Checking timing and capture", 0.55)
    issues = checks.run(clip, sig)
    label_results = {}
    human = {s.id for s in clip.segments if (s.meta or {}).get("drafted_by") != "ai"}  # AI-named labels: no second AI opinion
    if labels and human:
        say(f"Second opinion on every label ({vlm.backend()})", 0.6)
        try:
            label_results = vlm.check(clip, only=human, progress=lambda m, f: say(m, 0.6 + 0.35 * f))
        except Exception as e:  # noqa: BLE001 - the gate still reports timing/capture without labels
            say(f"label check unavailable: {e!r}"[:200], 0.95)
        issues += vlm.issues(clip, label_results)
    rep = checks.report(clip, sig, issues, {"backend": vlm.backend(), "results": label_results})
    rep["timing"] = {"seconds": round(time.time() - t0, 1), "measure_seconds": float(sig.get("seconds", 0))}
    rep["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (clip.dir / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    say("Done", 1.0)
    return rep


def track(clip: Clip) -> dict:
    """Compact per-sample tracks for the player overlay and the timeline."""
    sig = signals.load(clip)
    act, on, _ = checks._activity(sig)

    def boxes(arr):
        return [[[round(float(v), 3) for v in b] for b in fr if not np.isnan(b[0])] for fr in arr]

    return {"t": [round(float(v), 2) for v in sig["t"]], "activity": [round(float(v), 3) for v in act], "active_on": round(on, 3),
            "blur": [round(float(v), 1) for v in sig["blur"]], "blur_min": checks.BLUR_MIN,
            "bright": [round(float(v), 1) for v in sig["bright"]], "hands": boxes(sig["hands"]),
            "faces": boxes(sig["faces"]), "head_motion": [round(float(v), 3) for v in sig["head_motion"]]}


def issues_as_dicts(issues) -> list[dict]:
    return [asdict(i) for i in issues]
