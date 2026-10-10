"""Automated pre-QA: every annotated segment checked against the pixels.

Each issue says exactly where (time, and a box when there is one), what is wrong, and what to
change (a concrete suggestion the tester can apply in one click), so a reviewer starts from
the evidence instead of re-watching the clip.

    timing   overlap with the next segment, too short, a start before the hands act, an end
             after they stop, unlabelled hand activity between segments
    capture  blur, too dark / blown out, the camera whipping, hands out of view, bystander faces
    label    an AI second opinion (vlm.py) attached later; never auto-rejects
"""
from dataclasses import asdict, dataclass, field

import numpy as np

from .clip_io import Clip, Segment

# Calibrated on unmodified EPIC-KITCHENS annotations + planted errors (scripts/bench.py).
OVERLAP_S = 1.0  # EPIC segments legitimately overlap a little (two hands, two actions)
SHORT_S = 0.35
IDLE_S = 1.3  # a boundary this far from the first / last hand activity is suspicious
GAP_ACTIVE_S = 1.0  # unlabelled hand activity this long between segments
BLUR_MIN = 35.0  # Laplacian variance on a 320-px-wide frame
DARK_MEAN = 45.0
WHIP = 0.9  # head motion, frame-widths per second
FACE_CONF = 0.85  # kitchen objects (taps, plates, pizza) reach 0.82 on EPIC; real faces score higher


@dataclass
class Issue:
    id: str
    segment: str | None
    kind: str
    group: str  # timing | capture | label | privacy
    severity: str  # fix (a concrete change), check (look at it), info
    t: float
    title: str
    detail: str
    nudge: str  # one sentence for the tester
    t_end: float | None = None
    box: list | None = None  # normalised x0 y0 x1 y1 on the frame at t
    suggestion: dict | None = None  # {"field": "start"|"end"|"narration"|"add", "value": ...}
    evidence: dict = field(default_factory=dict)


def _activity(sig) -> tuple[np.ndarray, float, float]:
    """Hand/object activity per sample and the clip's on/off thresholds."""
    a = sig["hand_motion"].astype(np.float32)
    k = np.ones(5) / 5
    a = np.convolve(a, k, mode="same")
    return a, float(np.percentile(a, 55)), float(np.percentile(a, 30))


def _window(t, s, e):
    return (t >= s) & (t <= e)


def _hand_box(sig, i):
    h = sig["hands"][i]
    ok = ~np.isnan(h[:, 0])
    if not ok.any():
        return None
    b = h[ok]
    return [float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())]


def run(clip: Clip, sig: dict, segments: list[Segment] | None = None, check_ids: set | None = None) -> list[Issue]:
    """All segments count as coverage; only those in `check_ids` (default all) get per-segment checks."""
    segs = sorted(segments if segments is not None else clip.segments, key=lambda s: s.start)
    t = sig["t"]
    act, on, off = _activity(sig)
    hands_seen = ~np.isnan(sig["hands"][:, 0, 0])
    issues: list[Issue] = []

    def add(**k):
        issues.append(Issue(id=f"i{len(issues)}", **k))

    for n, g in enumerate(segs):
        if check_ids is not None and g.id not in check_ids:
            continue
        w = _window(t, g.start, g.end)
        idx = np.flatnonzero(w)
        # ---------------- timing
        if g.length < SHORT_S:
            add(segment=g.id, kind="too short", group="timing", severity="fix", t=g.start, t_end=g.end,
                title=f"'{g.narration}' lasts {g.length:.2f} s",
                detail="Shorter than any real hand action; usually a mis-typed end time.",
                nudge=f"Check the end time of '{g.narration}'.", evidence={"length_s": round(g.length, 2)})
        if n + 1 < len(segs) and g.end - segs[n + 1].start > OVERLAP_S and segs[n + 1].narration != g.narration:
            nxt = segs[n + 1]
            add(segment=g.id, kind="overlap", group="timing", severity="fix", t=nxt.start, t_end=g.end,
                title=f"Overlaps '{nxt.narration}' by {g.end - nxt.start:.1f} s",
                detail="Two different actions claim the same seconds of hand motion.",
                nudge=f"End '{g.narration}' at {nxt.start:.2f} s, where '{nxt.narration}' begins.",
                suggestion={"field": "end", "value": round(nxt.start, 2)}, evidence={"overlap_s": round(g.end - nxt.start, 2)})
        if len(idx) >= 3:
            a = act[idx]
            live = np.flatnonzero(a > on)
            if len(live):
                t_on, t_off = float(t[idx[live[0]]]), float(t[idx[live[-1]]])
                # A boundary is suspicious only if the hands are idle there AND busy inside.
                if t_on - g.start > IDLE_S and a[: max(1, live[0])].mean() < off * 1.2:
                    add(segment=g.id, kind="early start", group="timing", severity="fix", t=g.start, t_end=t_on,
                        title=f"Starts {t_on - g.start:.1f} s before the hands move",
                        detail="The first part of the segment shows no hand or object motion.",
                        nudge=f"Move the start of '{g.narration}' to {t_on - 0.2:.2f} s.",
                        suggestion={"field": "start", "value": round(t_on - 0.2, 2)}, box=_hand_box(sig, idx[live[0]]),
                        evidence={"idle_s": round(t_on - g.start, 2)})
                if g.end - t_off > IDLE_S and a[live[-1] + 1:].mean() < off * 1.2:
                    add(segment=g.id, kind="late end", group="timing", severity="fix", t=t_off, t_end=g.end,
                        title=f"Ends {g.end - t_off:.1f} s after the hands stop",
                        detail="The last part of the segment shows no hand or object motion.",
                        nudge=f"Move the end of '{g.narration}' to {t_off + 0.2:.2f} s.",
                        suggestion={"field": "end", "value": round(t_off + 0.2, 2)},
                        evidence={"idle_s": round(g.end - t_off, 2)})
        # ---------------- capture
        if len(idx):
            blurry = sig["blur"][idx] < BLUR_MIN
            if blurry.mean() > 0.5:
                worst = idx[np.argmin(sig["blur"][idx])]
                add(segment=g.id, kind="blur", group="capture", severity="check", t=float(t[worst]),
                    title=f"{blurry.mean():.0%} of the segment is blurred",
                    detail="Fine finger and object detail is lost; models learn little from smeared frames.",
                    nudge="Mark as low quality or ask for a re-capture.", evidence={"blurred_share": round(float(blurry.mean()), 2)})
            if sig["bright"][idx].mean() < DARK_MEAN:
                add(segment=g.id, kind="too dark", group="capture", severity="check", t=float(t[idx[len(idx) // 2]]),
                    title=f"Too dark (mean brightness {sig['bright'][idx].mean():.0f}/255)",
                    detail="Hands and objects are hard to see.", nudge="Mark as low quality; check the lighting in this session.")
            whip = np.median(sig["head_motion"][idx])
            if whip > WHIP:
                add(segment=g.id, kind="camera whip", group="capture", severity="check", t=float(t[idx[np.argmax(sig['head_motion'][idx])]]),
                    title=f"Head turns fast ({whip:.1f} frame-widths/s)",
                    detail="The action is partly out of view while the camera swings.", nudge="Confirm the action is visible at all.",
                    evidence={"head_motion": round(float(whip), 2)})
            if g.length >= 1.2 and not hands_seen[idx].any():
                add(segment=g.id, kind="hands out of view", group="capture", severity="check", t=float(t[idx[len(idx) // 2]]),
                    title="No hand visible in the whole segment",
                    detail="A manipulation label with no hands on screen cannot teach a robot the motion.",
                    nudge=f"Check that '{g.narration}' is really visible; otherwise tag it 'hands off-screen'.")
            fc = sig["faces"][idx][:, :, 4]
            if np.nanmax(np.nan_to_num(fc, nan=0)) > FACE_CONF:
                j = idx[int(np.nanargmax(np.nan_to_num(fc, nan=0).max(1)))]
                f = sig["faces"][j][0]
                add(segment=g.id, kind="face", group="privacy", severity="fix", t=float(t[j]), box=[float(v) for v in f[:4]],
                    title="A face is visible", detail="Bystander faces must be blurred before delivery.",
                    nudge="Blur the face before this clip leaves QA.", evidence={"conf": round(float(f[4]), 2)})

    # ---------------- unlabelled activity between segments
    covered = np.zeros(len(t), bool)
    for g in segs:
        covered |= _window(t, g.start - 0.3, g.end + 0.3)
    busy = (act > on) & ~covered
    run_start = None
    for i, b in enumerate(np.append(busy, False)):
        if b and run_start is None:
            run_start = i
        elif not b and run_start is not None:
            s, e = float(t[run_start]), float(t[i - 1])
            if e - s >= GAP_ACTIVE_S:
                mid = (run_start + i - 1) // 2
                add(segment=None, kind="unlabelled activity", group="timing", severity="fix", t=s, t_end=e,
                    box=_hand_box(sig, mid), title=f"{e - s:.1f} s of hand activity with no label",
                    detail="The hands are working but no segment covers it: a missed action.",
                    nudge=f"Add a segment from {s:.2f} s to {e:.2f} s.",
                    suggestion={"field": "add", "value": {"start": round(s, 2), "end": round(e, 2)}})
            run_start = None
    return issues


def segment_status(segments, issues) -> dict:
    by = {}
    for i in issues:
        if i.segment:
            by.setdefault(i.segment, []).append(i)
    out = {}
    for g in segments:
        its = by.get(g.id, [])
        out[g.id] = "fix" if any(i.severity == "fix" for i in its) else "check" if its else "pass"
    return out


def stable_ids(issues: list[Issue]) -> None:
    """Ids that survive a re-check, so a reviewer's decision stays on the issue it was made on."""
    import hashlib

    seen: dict[str, int] = {}
    for i in issues:
        base = "i" + hashlib.md5(f"{i.kind}|{i.segment}|{i.t:.1f}|{i.title}".encode()).hexdigest()[:8]
        seen[base] = seen.get(base, 0) + 1
        i.id = base if seen[base] == 1 else f"{base}-{seen[base]}"


def report(clip: Clip, sig: dict, issues: list[Issue], label: dict | None = None) -> dict:
    stable_ids(issues)
    status = segment_status(clip.segments, issues)
    n = max(1, len(clip.segments))
    passed = sum(v == "pass" for v in status.values())
    hands = float((~np.isnan(sig["hands"][:, 0, 0])).mean()) if len(sig["hands"]) else 1.0
    sharp = float((sig["blur"] >= BLUR_MIN).mean()) if len(sig["blur"]) else 1.0
    groups = {}
    for i in issues:
        groups[i.group] = groups.get(i.group, 0) + 1
    # Readiness: share of segments needing nothing, discounted by capture quality.
    score = round(100 * (0.7 * passed / n + 0.15 * hands + 0.15 * sharp))
    return {"clip": clip.summary(), "segments": clip.segments_json(), "status": status, "issues": [asdict(i) for i in issues],
            "summary": {"segments": n, "pass": passed, "fix": sum(v == "fix" for v in status.values()),
                        "check": sum(v == "check" for v in status.values()), "issues": len(issues), "groups": groups,
                        "hands_visible": round(hands, 3), "sharp_frames": round(sharp, 3), "readiness": score,
                        "review_share": round(1 - passed / n, 3)},
            "label": label or {}}
