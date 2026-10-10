# SoloSim — robot training data, checked before QA opens it

Awign Hackathon: Physical AI · Bengaluru · Oct 10–11, 2026

Robots learn manipulation from people: thousands of hours of head-mounted (first-person) video,
every action cut into segments with a verb, an object, a start and an end. Capturing it scales;
**checking it does not**. Annotators make slips (a start two seconds early, "take" when the hand
puts down, an action never labelled), QA re-watches everything, and bad labels that slip through
teach robots the wrong thing.

SoloSim is an automated **pre-QA gate** between the annotator and the QA tester:

1. **Measures every frame** of the first-person clip: hands, faces, blur, light, head motion, hand/object activity.
2. **Checks every segment against the pixels** and turns each problem into a *nudge*: the exact
   time, the frame with a box on it, one sentence for the tester, and a one-click fix
   ("Move the end of 'take cup' to 0:02.9").
3. **Asks an AI reviewer about every label** (does the footage show this verb on this object?) and
   says what it actually sees. Claude gives a deeper second opinion on request, under a hard spend cap.
4. **Renders the annotation in a world model** (Reactor LingBot World 2) in first person from the
   segment's real first frame, and shows where the render fails (hands lost, object morphed,
   action not performed): whether the annotation works as a robot-training scenario.
5. **Exports client-ready JSON**: every segment with its QA status, reasons and the review trail.

## Where it sits in the pipeline

```
capture (head-mounted) -> VLM first pass -> annotator -> [ SoloSim gate ] -> QA tester (flagged only) -> client
```

## Measured (real footage, planted errors)

Footage and labels: EPIC-KITCHENS-100 (head-mounted GoPro, official narrated action segments),
four videos, 132 segments. `python engine/scripts/bench.py` plants annotator slips on 20% of
segments per round and counts what is caught; the website's Evidence page reads the results live.

| Planted slip | Caught |
|---|---|
| End time mistyped (segment 0.1–0.3 s) | 100% |
| Segment ends 1.5–3 s after the action | 72% |
| Action never labelled | 46% |
| Segment starts 1.5–3 s before the action | 46% |
| **All timing slips (500 planted)** | **65%**, with **2.6%** new false flags |

Labels (`engine/scripts/label_bench.py`): every segment is checked with its real label and with a
label copied from another action in the same video; results on the Evidence page.

What it cannot do yet: starts that slide into the previous action without idle time, and fine
verbs at 456×256 (the public EPIC copy). Awign captures in 4K.

## Run

```bash
# engine (Python 3.12)
cd engine
python -m venv --system-site-packages .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn solosim.server:app --port 8765

# website
cd web && npm install && npm run dev      # http://localhost:3000
```

Keys live in `.env.local` at the repo root (gitignored, server-side only):

| Key | Used for | Cost control |
|---|---|---|
| `GROQ_API_KEY` | automatic label check (Qwen 3.8 27B vision, free tier) | free tier: 1,000 requests/day, 7k input tokens/min |
| `ANTHROPIC_API_KEY` | Claude Opus 5.5 second opinion, only when a tester clicks | hard cap `SOLOSIM_CLAUDE_CAP_USD`, every call priced and logged |
| `REACTOR_API_KEY` | LingBot World 2 render check | cost pop-up before every render, per-render cap, local ledger |

Without keys the gate still runs: timing, capture and privacy checks are local; the label check
falls back to a local Qwen2.5-VL via Ollama.

Upload any first-person video with EPIC-style CSV or JSON `[{start, end, label}]` from the Review
queue page, or import more EPIC videos with `solosim.clip_io.import_epic(...)`.

## Layout

```
engine/solosim/
  clip_io.py     clips on disk, EPIC import
  signals.py     per-frame measurements (YOLOv8 hands/faces, DIS optical flow, blur, CLIP)
  checks.py      timing / capture / privacy checks -> issues with time, box, nudge, fix
  vlm.py         label second opinion: Groq (auto), Claude (on click, capped), local Qwen (offline)
  render.py      LingBot World 2 first-person render of an annotation + failure points
  bench.py       planted-error benchmark
  pipeline.py    one clip through the gate; server.py the HTTP API
engine/lucid/    world-model client, budget ledger and frame audit (from v1)
web/             Next.js: landing, review queue, reviewer workspace, evidence
```

Version 1 (a drone flying inside a generated world) is at github.com/UJESH2K/WorldSim, tag `v1`.

## Credits

EPIC-KITCHENS-100 (Damen et al., IJCV 2022), CC BY-NC 4.0, 256p mirror on Hugging Face. Hand and
face detectors: Bingsu/adetailer YOLOv8. World model: Reactor LingBot World 2.
