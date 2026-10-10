"""AI first pass for footage that arrives without annotations (e.g. a clip just recorded on a phone).

Segments come from the measured hand/object activity: runs of activity above the clip's own
threshold, merged across short pauses and split when they run long. The AI reviewer then names
each one (verb + object) without being told anything. Every drafted segment is marked so the
tester knows it came from the machine.
"""
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np

from . import checks, vlm
from .clip_io import Clip, Segment

MIN_S, MAX_S, MERGE_S = 0.8, 6.0, 0.6


def segments_from_activity(sig: dict) -> list[tuple[float, float]]:
    t = sig["t"]
    act, on, _ = checks._activity(sig)
    busy = act > on
    runs, s = [], None
    for i, b in enumerate(np.append(busy, False)):
        if b and s is None:
            s = i
        elif not b and s is not None:
            runs.append([float(t[s]), float(t[i - 1])])
            s = None
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] < MERGE_S:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        if b - a < MIN_S:
            continue
        n = int(np.ceil((b - a) / MAX_S))
        edges = np.linspace(a, b, n + 1)
        out += [(round(float(edges[k]), 2), round(float(edges[k + 1]), 2)) for k in range(n)]
    return out


NAME_SCHEMA = {"type": "object", "properties": {"verb": {"type": "string"}, "object": {"type": "string"},
                                                "action": {"type": "string"}},
               "required": ["verb", "object", "action"], "additionalProperties": False}
ASK = ("Name the single action the camera wearer's hands perform, as an annotator would: a verb and its object, "
       "at most 5 words, lower case.")


def _name_claude(clip: Clip, a: float, b: float) -> str:
    import anthropic

    g = Segment(id="draft", start=a, end=b, verb="", noun="", narration="")
    _, sheet = vlm.contact_sheet(clip, g, cell=320)
    r = anthropic.Anthropic().messages.create(
        model=vlm.BULK_MODEL, max_tokens=1000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": NAME_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Six frames in time order (left to right, then top to bottom) from a head-mounted camera."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": sheet}},
            {"type": "text", "text": ASK}]}])
    vlm._charge(r.usage, f"draft {clip.id} {a:.1f}-{b:.1f}", vlm.BULK_MODEL)
    if r.stop_reason == "refusal":
        return "unnamed action"
    d = json.loads(next(x.text for x in r.content if x.type == "text"))
    return (d.get("action") or f"{d.get('verb', '')} {d.get('object', '')}").strip().lower() or "unnamed action"


def _name(clip: Clip, a: float, b: float) -> str:
    if vlm.backend() == "haiku":
        try:
            return _name_claude(clip, a, b)
        except Exception as e:  # noqa: BLE001 - fall back to Groq
            print(f"draft naming failed: {e!r}"[:200])
    if not os.environ.get("GROQ_API_KEY"):
        return "unnamed action"
    g = Segment(id="draft", start=a, end=b, verb="", noun="", narration="")
    _, sheet = vlm.contact_sheet(clip, g)
    content = [{"type": "text", "text": "Six frames in time order (left to right, then top to bottom) from a head-mounted camera."},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sheet}"}},
               {"type": "text", "text": "Name the single action the camera wearer's hands perform, as an annotator would: a verb and "
                                        'its object, at most 5 words. Reply with JSON only: {"verb": "...", "object": "...", "action": "..."}'}]
    body = {"model": vlm.GROQ_MODEL, "max_tokens": 120, "temperature": 0, "reasoning_effort": "none",
            "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "Content-Type": "application/json",
                                  "User-Agent": "solosim/0.1"})
    for attempt in range(3):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            d = json.loads(r["choices"][0]["message"]["content"])
            return (d.get("action") or f"{d.get('verb', '')} {d.get('object', '')}").strip().lower() or "unnamed action"
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(float(e.headers.get("retry-after") or (2 + 3 * attempt)) + 0.5)
        except (ValueError, KeyError):
            break
    return "unnamed action"


def draft(clip: Clip, sig: dict, progress=None) -> list[Segment]:
    spans = segments_from_activity(sig)
    segs = []
    for i, (a, b) in enumerate(spans):
        name = _name(clip, a, b)
        parts = name.split()
        segs.append(Segment(id=f"ai-{i:03d}", start=a, end=b, verb=parts[0] if parts else "", noun=" ".join(parts[1:]),
                            narration=name, meta={"drafted_by": "ai"}))
        if progress:
            progress(f"AI first pass: named {i + 1}/{len(spans)} segments", (i + 1) / max(1, len(spans)))
    clip.save_segments(segs)
    return segs
