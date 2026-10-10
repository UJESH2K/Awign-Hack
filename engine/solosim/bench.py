"""Planted-error benchmark: corrupt real annotations in known ways and measure what is caught.

Every corruption mimics a common annotator slip:
    start early   the segment starts 1.5-3 s before the action (clicked too soon)
    end late      the segment ends 1.5-3 s after it (forgot to stop)
    truncated     the end lands 0.1-0.3 s after the start (mis-typed time)
    deleted       an action was never labelled
    wrong label   the label of another action in the same clip (copy-paste slip)

A planted error counts as caught when an issue of a matching kind lands on that segment (or, for a
deleted segment, an "unlabelled activity" issue overlaps where it was). False flags are issues on
untouched segments that the original annotation did not already have.
"""
import copy
import random

import numpy as np

from . import checks
from .clip_io import Clip, Segment

KINDS = ["start early", "end late", "truncated", "deleted", "wrong label"]
CATCHES = {
    "start early": {"early start", "overlap"},
    "end late": {"late end", "overlap"},
    "truncated": {"too short"},
    "deleted": {"unlabelled activity"},
    "wrong label": {"label mismatch"},
}


def plant(segments: list[Segment], rng: random.Random, share: float = 0.2, kinds=KINDS):
    segs = [copy.deepcopy(s) for s in segments]
    n = max(1, int(len(segs) * share))
    picks = rng.sample(range(len(segs)), n)
    planted, deleted = [], set()
    labels = sorted({s.narration for s in segs})
    for i in picks:
        g = segs[i]
        kind = rng.choice(kinds)
        if kind == "start early":
            d = rng.uniform(1.5, 3.0)
            g.start = round(max(0.0, g.start - d), 2)
        elif kind == "end late":
            g.end = round(g.end + rng.uniform(1.5, 3.0), 2)
        elif kind == "truncated":
            g.end = round(g.start + rng.uniform(0.1, 0.3), 2)
        elif kind == "deleted":
            deleted.add(i)
        elif kind == "wrong label":
            other = [l for l in labels if l.split()[0] != g.narration.split()[0]]
            if not other:
                continue
            g.narration = rng.choice(other)
            g.verb, g.noun = g.narration.split()[0], " ".join(g.narration.split()[1:])
        planted.append({"segment": g.id, "kind": kind, "start": segments[i].start, "end": segments[i].end})
    return [s for j, s in enumerate(segs) if j not in deleted], planted


def score(clip: Clip, sig: dict, rounds: int = 10, seed: int = 0, kinds=KINDS, label_fn=None) -> dict:
    """label_fn(clip, sig, segments) -> list[Issue] adds label checks (slow; optional)."""
    rng = random.Random(seed)
    base = {(i.segment, i.kind) for i in checks.run(clip, sig)}
    per = {k: [0, 0] for k in kinds}  # caught, planted
    false_flags = untouched = 0
    for _ in range(rounds):
        segs, planted = plant(clip.segments, rng, kinds=kinds)
        issues = checks.run(clip, sig, segs)
        if label_fn:
            issues += label_fn(clip, sig, segs)
        touched = {p["segment"] for p in planted}
        for p in planted:
            per[p["kind"]][1] += 1
            want = CATCHES[p["kind"]]
            if p["kind"] == "deleted":
                hit = any(i.kind in want and i.t_end is not None and i.t < p["end"] and i.t_end > p["start"] for i in issues)
            else:
                hit = any(i.segment == p["segment"] and i.kind in want for i in issues)
            per[p["kind"]][0] += hit
        flagged = {i.segment for i in issues if i.segment and i.segment not in touched and (i.segment, i.kind) not in base}
        false_flags += len(flagged)
        untouched += len([s for s in segs if s.id not in touched])
    caught = sum(v[0] for v in per.values())
    total = sum(v[1] for v in per.values())
    return {"recall": round(caught / max(1, total), 3), "planted": total, "caught": caught,
            "by_kind": {k: {"caught": v[0], "planted": v[1], "recall": round(v[0] / max(1, v[1]), 3)} for k, v in per.items()},
            "false_flag_rate": round(false_flags / max(1, untouched), 3), "baseline_flags": len(base)}


def summarise(results: dict) -> dict:
    by = {}
    for r in results.values():
        for k, v in r["by_kind"].items():
            a = by.setdefault(k, [0, 0])
            a[0] += v["caught"]
            a[1] += v["planted"]
    caught = sum(a[0] for a in by.values())
    planted = sum(a[1] for a in by.values())
    return {"recall": round(caught / max(1, planted), 3), "planted": planted, "caught": caught,
            "by_kind": {k: {"caught": a[0], "planted": a[1], "recall": round(a[0] / max(1, a[1]), 3)} for k, a in by.items()},
            "false_flag_rate": round(float(np.mean([r["false_flag_rate"] for r in results.values()])), 3)}
