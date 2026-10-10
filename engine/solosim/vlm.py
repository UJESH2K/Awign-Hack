"""Label second opinion: does the footage show what the annotation says?

Backends:
    haiku    Claude Haiku 5.5: the automatic check on every segment (~$0.0003 each). Sees a contact
             sheet of six time-stamped frames, the label and its neighbours; returns a verdict, what
             it actually sees, and the frame that proves it.
    claude   Claude Opus 5.5: the same question, only when a tester asks for a deeper second opinion.
             Every Claude call is priced from its token usage and logged; calls stop at a hard cap
             (SOLOSIM_CLAUDE_CAP_USD).
    groq     Qwen 3.8 27B on Groq (free tier, ~95 checks/day): automatic check without a Claude key.
    qwen     local Qwen2.5-VL via Ollama (offline fallback): describes the frames WITHOUT seeing the
             label (small models agree with whatever they are told), compared by text embedding.

A label issue is a suggestion for the tester, never an automatic rejection.
"""
import base64
import concurrent.futures as cf
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

from .checks import Issue
from .clip_io import DATA, ENGINE, Clip, Segment

MODEL = "claude-opus-5-5"  # second opinion, on click
BULK_MODEL = "claude-haiku-5-5"  # automatic check
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-haiku-5-5": (0.10, 0.50)}  # USD per million input / output tokens
GROQ_MODEL = "qwen/qwen3.8-27b"
LEDGER = DATA / "solosim" / "claude_spend.json"
FRAMES = 5
# Calibrated on 64 real + 64 planted-wrong labels (scripts/label_bench.py, Haiku): a confident
# "wrong" (>= 0.7) catches 53% of planted errors and flags 3% of real labels; doubtful (0.6-0.7)
# raises that to 72% / 20%, so it is a lower-priority "check", never a "fix".
LABEL_FIX_CONF = 0.7
LABEL_CHECK_CONF = 0.6
_ledger_lock = threading.Lock()

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "wrong verb", "wrong object", "wrong action", "not visible", "unsure"]},
        "observed_action": {"type": "string", "description": "what the hands actually do: verb + object, max 6 words"},
        "evidence_frame": {"type": "integer", "description": "1-based index of the frame that shows it best"},
        "explanation": {"type": "string", "description": "max 25 words, concrete and visual"},
        "confidence": {"type": "number", "description": "0 to 1"},
    },
    "required": ["verdict", "observed_action", "evidence_frame", "explanation", "confidence"],
    "additionalProperties": False,
}
SYSTEM = (
    "You are a senior QA reviewer for first-person (head-mounted camera) video used to train robots. "
    "Annotators label each action segment with a verb and an object. You check one segment at a time, "
    "judging only from the frames you are shown. Most labels are correct: flag a label only when the frames "
    "clearly show a different verb or object, or the action is not visible at all. Direction matters "
    "(take vs put down, open vs close). If the frames are ambiguous, answer 'unsure'."
)


def _load_env():
    env = ENGINE.parent / ".env.local"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip() and not os.environ.get(k.strip()):
                    os.environ[k.strip()] = v.strip()


_load_env()


def backend() -> str:
    """The automatic checker: Haiku with a Claude key (Opus only on click), else Groq, else local."""
    if os.environ.get("ANTHROPIC_API_KEY") and claude_spend()["spent_usd"] < claude_spend()["cap_usd"]:
        return "haiku"
    return "groq" if os.environ.get("GROQ_API_KEY") else "qwen"


class SpendCap(Exception):
    pass


def claude_spend() -> dict:
    cap = float(os.environ.get("SOLOSIM_CLAUDE_CAP_USD", "8"))
    led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"calls": []}
    spent = round(sum(c["usd"] for c in led["calls"]), 4)
    return {"spent_usd": spent, "cap_usd": cap, "left_usd": round(cap - spent, 4), "calls": len(led["calls"]),
            "available": bool(os.environ.get("ANTHROPIC_API_KEY")) and spent < cap}


def _charge(usage, what: str, model: str = MODEL) -> float:
    pin, pout = PRICES[model]
    usd = usage.input_tokens * pin / 1e6 + usage.output_tokens * pout / 1e6
    with _ledger_lock:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"calls": []}
        led["calls"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "what": what, "model": model, "in": usage.input_tokens,
                             "out": usage.output_tokens, "usd": round(usd, 5)})
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(led, indent=1), encoding="utf-8")
    return usd


def _frames(clip: Clip, g: Segment, n=FRAMES, width=640):
    out = []
    for t in np.linspace(g.start, g.end, n):
        im = clip.frame_at(float(t))
        if im is None:
            continue
        if im.shape[1] > width:
            im = cv2.resize(im, (width, int(width * im.shape[0] / im.shape[1])), interpolation=cv2.INTER_AREA)
        jpg = cv2.imencode(".jpg", cv2.cvtColor(im, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])[1]
        out.append((float(t), base64.b64encode(jpg).decode()))
    return out


def _question(g: Segment, prev: str, nxt: str) -> str:
    return (f"Annotated action for this segment ({g.start:.2f}-{g.end:.2f} s): \"{g.narration}\" "
            f"(verb: {g.verb}, object: {g.noun}).\n"
            f"Context only - the segment before is labelled \"{prev}\", the one after \"{nxt}\".\n"
            "Does the annotated verb and object match what the camera wearer's hands do in these frames?")


def _finish(out: dict, frames, g: Segment, which: str) -> dict:
    if out.get("verdict") not in SCHEMA["properties"]["verdict"]["enum"]:
        out["verdict"] = "unsure"
    try:
        k = max(1, min(len(frames), int(out.get("evidence_frame") or 1))) - 1
    except (TypeError, ValueError):
        k = 0
    out["t"] = frames[k][0] if frames else g.mid
    out["backend"] = which
    return out


def contact_sheet(clip: Clip, g: Segment, n: int = 6, cell: int = 240):
    """n frames of the segment in a 3-column grid, each stamped with its number and time."""
    ts = [float(t) for t in np.linspace(g.start, g.end, n)]
    cells = []
    for i, t in enumerate(ts):
        im = clip.frame_at(t)
        im = cv2.resize(im, (cell, int(cell * im.shape[0] / im.shape[1])), interpolation=cv2.INTER_AREA)
        im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR)
        cv2.rectangle(im, (0, 0), (118, 24), (0, 0, 0), -1)
        cv2.putText(im, f"{i + 1}  {t:.1f}s", (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(im)
    rows = [np.hstack(cells[r:r + 3]) for r in range(0, n, 3)]
    sheet = np.vstack(rows)
    return ts, base64.b64encode(cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])[1]).decode()


def _groq(clip, g, prev, nxt):
    ts, sheet = contact_sheet(clip, g)
    frames = [(t, None) for t in ts]
    content = [{"type": "text", "text": f"{len(ts)} frames of the segment in time order, left to right then top to bottom; "
                                        "each is stamped with its number and time."},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sheet}"}}]
    keys = "; ".join(f"{k}: {v.get('description') or '/'.join(v.get('enum', []))}" for k, v in SCHEMA["properties"].items())
    content.append({"type": "text", "text": _question(g, prev, nxt) + f"\nReply with a JSON object only. Keys - {keys}"})
    body = {"model": GROQ_MODEL, "max_tokens": 400, "temperature": 0, "reasoning_effort": "none", "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "Content-Type": "application/json",
                                  "User-Agent": "solosim/0.1"})
    for attempt in range(12):  # free tier: 7k input tokens/min, so wait as long as it asks
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 11:
                raise
            time.sleep(float(e.headers.get("retry-after") or (2 + 3 * attempt)) + 0.5)
    return _finish(json.loads(r["choices"][0]["message"]["content"]), frames, g, "groq")


def _claude(clip, g, prev, nxt, model: str = MODEL):
    import anthropic

    if not claude_spend()["available"]:
        raise SpendCap("Claude checks are off: no key, or the spend cap is reached")
    ts, sheet = contact_sheet(clip, g, cell=320)
    frames = [(t, None) for t in ts]
    content = [{"type": "text", "text": f"{len(ts)} frames of the segment in time order, left to right then top to bottom; "
                                        "each is stamped with its number and time."},
               {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": sheet}},
               {"type": "text", "text": _question(g, prev, nxt)}]
    which = "claude" if model == MODEL else "haiku"
    kw = {}
    if model == MODEL:  # Opus: server-side refusal fallback (Haiku has none; a refusal reads as 'unsure')
        kw = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    r = anthropic.Anthropic().beta.messages.create(
        model=model, max_tokens=2000, system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}], **kw,
    )
    _charge(r.usage, f"{clip.id}/{g.id}", model)
    if r.stop_reason == "refusal":
        return _finish({"verdict": "unsure", "observed_action": "", "evidence_frame": 1, "explanation": "model declined",
                        "confidence": 0.0}, frames, g, which)
    return _finish(json.loads(next(b.text for b in r.content if b.type == "text")), frames, g, which)


def _haiku(clip, g, prev, nxt):
    return _claude(clip, g, prev, nxt, model=BULK_MODEL)


def _ollama(path, body, timeout=240):
    req = urllib.request.Request("http://localhost:11434" + path, json.dumps(body).encode())
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _qwen(clip, g, labels, label_vecs):
    frames = _frames(clip, g, n=3, width=456)
    ims = [cv2.imdecode(np.frombuffer(base64.b64decode(b), np.uint8), cv2.IMREAD_COLOR) for _, b in frames]
    h = min(i.shape[0] for i in ims)
    tile = np.hstack([cv2.resize(i, (int(i.shape[1] * h / i.shape[0]), h)) for i in ims])
    b64 = base64.b64encode(cv2.imencode(".jpg", tile)[1]).decode()
    prompt = ("Three frames, left to right in time, from a head-mounted camera. What do the person's hands do? "
              'JSON only: {"verb": "<one verb>", "object": "<object>", "action": "<verb object, max 5 words>"}')
    try:
        d = json.loads(_ollama("/api/chat", {"model": "qwen2.5vl:3b", "stream": False, "format": "json",
                                              "options": {"num_ctx": 4096, "temperature": 0},
                                              "messages": [{"role": "user", "content": prompt, "images": [b64]}]})["message"]["content"])
    except Exception:  # noqa: BLE001 - offline model hiccup: no opinion
        return {"verdict": "unsure", "observed_action": "", "evidence_frame": 2, "explanation": "local model unavailable",
                "confidence": 0.0, "t": g.mid, "backend": "qwen"}
    seen = d.get("action", "")
    v = np.array(_ollama("/api/embed", {"model": "nomic-embed-text", "input": [f"search_query: {seen}"]})["embeddings"][0], np.float32)
    v /= np.linalg.norm(v)
    sims = label_vecs @ v
    rank = int((sims > sims[labels.index(g.narration)]).sum())
    verdict = "correct" if rank < 3 else "wrong action" if rank > len(labels) // 2 else "unsure"
    return {"verdict": verdict, "observed_action": seen, "evidence_frame": 2, "confidence": round(1 - rank / len(labels), 2),
            "explanation": f"local model sees '{seen}'; the label ranks {rank + 1} of {len(labels)} by similarity",
            "t": g.mid, "backend": "qwen"}


def _key(g: Segment, prev, nxt, which) -> str:
    return hashlib.sha1(f"{which}|{g.start:.2f}|{g.end:.2f}|{g.narration}|{prev}|{nxt}".encode()).hexdigest()[:16]


def _save(path, cache):
    """Merge into what is on disk (another process may be checking the same clip)."""
    with _ledger_lock:
        disk = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        disk.update(cache)
        path.write_text(json.dumps(disk), encoding="utf-8")


def check(clip: Clip, segments: list[Segment] | None = None, only: set | None = None, workers: int = 4,
          progress=None, which: str | None = None) -> dict:
    """Second opinion per segment -> {segment_id: result}. Cached per clip."""
    segs = sorted(segments if segments is not None else clip.segments, key=lambda s: s.start)
    which = which or backend()
    cache_f = clip.dir / "label_cache.json"
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    jobs = []
    for n, g in enumerate(segs):
        if only is not None and g.id not in only:
            continue
        prev = segs[n - 1].narration if n else "(start of video)"
        nxt = segs[n + 1].narration if n + 1 < len(segs) else "(end of video)"
        jobs.append((g, prev, nxt, _key(g, prev, nxt, which)))
    todo = [j for j in jobs if j[3] not in cache]
    if todo and which in ("claude", "groq", "haiku"):
        fn = {"claude": _claude, "groq": _groq, "haiku": _haiku}[which]
        with cf.ThreadPoolExecutor(6 if which == "haiku" else 2) as ex:
            futs = {ex.submit(fn, clip, g, p, x): k for g, p, x, k in todo}
            for i, f in enumerate(cf.as_completed(futs)):
                try:
                    cache[futs[f]] = f.result()
                    _save(cache_f, cache)
                except SpendCap:
                    raise
                except Exception as e:  # noqa: BLE001 - one failed call must not sink the batch; retried next time
                    print(f"label check failed ({which}): {e!r}"[:300])
                if progress:
                    progress(f"label check {i + 1}/{len(todo)}", (i + 1) / len(todo))
    elif todo:
        labels = sorted({s.narration for s in clip.segments} | {g.narration for g, *_ in todo})
        vecs = np.array(_ollama("/api/embed", {"model": "nomic-embed-text", "input": [f"search_query: {l}" for l in labels]})["embeddings"], np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        for i, (g, p, x, k) in enumerate(todo):
            cache[k] = _qwen(clip, g, labels, vecs)
            if progress:
                progress(f"label check {i + 1}/{len(todo)}", (i + 1) / len(todo))
    if todo:
        _save(cache_f, cache)
    return {g.id: {**cache[k], "segment": g.id} for g, _, _, k in jobs if k in cache}


def issues(clip: Clip, results: dict, segments: list[Segment] | None = None, start: int = 1000) -> list[Issue]:
    segs = {s.id: s for s in (segments if segments is not None else clip.segments)}
    out = []
    for sid, r in results.items():
        g = segs.get(sid)
        if g is None:
            continue
        v = r.get("verdict")
        who = {"claude": "Claude Opus", "groq": "The AI reviewer", "haiku": "The AI reviewer"}.get(r.get("backend"), "The local model")
        conf = float(r.get("confidence") or 0)
        if v in ("wrong verb", "wrong object", "wrong action") and conf >= LABEL_CHECK_CONF:
            seen = (r.get("observed_action") or "").strip()
            sure = conf >= LABEL_FIX_CONF or r.get("backend") == "claude"
            out.append(Issue(id=f"i{start + len(out)}", segment=sid, kind="label mismatch" if sure else "label doubtful", group="label",
                             severity="fix" if sure else "check",
                             t=float(r.get("t", g.mid)), title=f"{v.capitalize()}: the footage shows '{seen}'" if sure
                             else f"Doubtful label: the footage may show '{seen}'",
                             detail=r.get("explanation", ""), nudge=f"{who} sees '{seen}', not '{g.narration}'. Relabel?",
                             suggestion={"field": "narration", "value": seen} if seen else None,
                             evidence={"verdict": v, "confidence": r.get("confidence"), "backend": r.get("backend")}))
        elif v == "not visible":
            out.append(Issue(id=f"i{start + len(out)}", segment=sid, kind="action not visible", group="label", severity="check",
                             t=float(r.get("t", g.mid)), title="The labelled action is not visible",
                             detail=r.get("explanation", ""), nudge=f"{who} cannot see '{g.narration}' happen in this segment.",
                             evidence={"confidence": r.get("confidence"), "backend": r.get("backend")}))
    return out
