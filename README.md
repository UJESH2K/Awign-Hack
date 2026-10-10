# SoloSim

**Robot-training video, checked before a human opens it.**

Awign Hackathon · Physical AI · Bengaluru · 10–11 October 2026

---

## The one-paragraph version

Robots learn manipulation by watching people: thousands of hours of head-mounted, first-person
video, with every action cut into a segment that carries a verb, an object, a start and an end.
Capturing that footage scales — you hand out cameras. **Checking it does not.** Today a QA tester
re-watches the clip end to end to find a start that was two seconds early. If you collect 10,000
hours and checking takes 10,000 hours, you have not built a pipeline, you have moved the
bottleneck. SoloSim is an automated pre-QA gate that sits between the annotator and the QA tester.
It reads the pixels, checks every annotation against what the hands are actually doing, and hands
the tester a list of *moments* instead of a video. On our measured runs it auto-passes **68.6%** of
segments, leaves **97.4%** of correct annotations untouched, and costs **₹15 per hour of footage**
at **4.3× realtime**.

---

## Table of contents

1. [Where the data comes from](#1-where-the-data-comes-from)
2. [The idea that makes it cheap](#2-the-idea-that-makes-it-cheap)
3. [The pipeline, stage by stage](#3-the-pipeline-stage-by-stage)
4. [What it costs, in rupees](#4-what-it-costs-in-rupees)
5. [What it saves, on 10,000 hours](#5-what-it-saves-on-10000-hours)
6. [How accurate it is](#6-how-accurate-it-is)
7. [The accuracy ladder: swap the model, buy recall](#7-the-accuracy-ladder-swap-the-model-buy-recall)
8. [The world-model check](#8-the-world-model-check)
9. [Why this is not a thing that already exists](#9-why-this-is-not-a-thing-that-already-exists)
10. [What we are not claiming](#10-what-we-are-not-claiming)
11. [The product: three rooms](#11-the-product-three-rooms)
12. [Run it](#12-run-it)
13. [Repository layout](#13-repository-layout)
14. [Demo script](#14-demo-script)
15. [Credits](#15-credits)

---

## 1. Where the data comes from

Nothing in this prototype is staged. Every number on every screen was produced by the code in this
repository, on real first-person footage, during the hackathon.

### The footage

**EPIC-KITCHENS-100** (Damen et al., IJCV 2022) — the standard academic benchmark for first-person
manipulation video. People wear a head-mounted GoPro and cook in their own kitchens, unscripted.
It is the closest public analogue to what Awign captures: unposed, hand-centric, messy, with real
occlusion and real motion blur.

* Licence: CC BY-NC 4.0.
* We use the **256p mirror on Hugging Face** — 456×256, which matters (see [limits](#10-what-we-are-not-claiming)).
* Videos used: **P01_03, P01_04, P01_08, P01_10** — four clips, **132 annotated segments**.
* Annotations: the dataset's **official narrated action segments** (`start`, `end`, `verb`, `noun`,
  `narration`), authored by human annotators, not by us.

That last point is the one to hold on to: **we did not write the labels we are checking.** They are
a third party's human annotations. When the gate flags one, it is flagging a real person's real
work, not a mistake we planted for the demo.

### How it gets into the system

Two paths, both live:

1. **Import** — `solosim.clip_io.import_epic(...)` pulls a video and its EPIC CSV into
   `engine/data/solosim/clips/<id>/` as `video.mp4` + `annotations.json`.
2. **Upload** — drag any first-person video onto the Annotator page with an EPIC-style CSV or a
   JSON `[{start, end, label}]`. This is the path we demo. The clip in the screenshots,
   `P01_08-214207`, was uploaded through the browser at 21:42 on 10 October and analysed live.

If you upload a video **without** annotations, `draft.py` runs a VLM first pass and writes draft
segments, so the gate has something to check. Those drafts carry a placeholder name, and the gate
knows they are its own — it asks you to name them, it does not accuse you of a mistake.

### Ground truth for the benchmark

To measure a gate you need errors you can count. `engine/scripts/bench.py` takes the **unmodified**
EPIC annotations and plants realistic annotator slips on 20% of segments, 20 rounds, **500 planted
errors** in total:

| Planted slip | What it simulates |
|---|---|
| `start early` | the annotator scrubbed back too far before marking the start |
| `end late` | the annotator let the segment run past the end of the action |
| `truncated` | a mistyped end time — the segment collapses to a fraction of a second |
| `deleted` | an action that was never labelled at all |

The same script also runs the gate on the **untouched** annotations, so every flag it raises there
is a false flag. That is where the 2.6% comes from. Labels are measured separately by
`engine/scripts/label_bench.py`: every segment is checked twice — once with its real label, once
with a label copied from a different action in the same video.

---

## 2. The idea that makes it cheap

This is the part that makes the whole thing possible, and it is worth stating plainly, because it
is the difference between a demo and a pipeline.

> **Cost scales with the number of annotations, not with the duration of the footage.**

A naive "AI checks your video" product sends frames to a model continuously. At 60 fps, an hour of
video is 215,784 frames. Nobody can pay for that, and nobody needs to — because **an annotation is
an assertion about a span of time, and an assertion can only be wrong at its edges and in its
content.** So:

* **A continuous, unbroken action is one check, however long it runs.** A 2-second "take cup" and a
  60-second "wash dishes" cost exactly the same: one model call. We do not re-ask every second
  whether the washing is still washing. The segment is evaluated **once**, when the analysis window
  passes its end (`CONTEXT = 1.5` s in `stream.py`) — when the continuation has actually ended.
* **Timing is only tested where something changes.** The early-start and late-end checks do not
  scan the segment; they find the first and last moment of hand activity inside it and compare
  those two instants to the two timestamps the annotator typed. Two comparisons per segment, at the
  disruptions — the transitions — not across the span.
* **The gaps are only read for disruptions.** Between segments we look for *runs of hand activity
  that nobody labelled* (`GAP_ACTIVE_S = 1.0` s). Idle time produces nothing. A missed action
  announces itself by being a disruption in an otherwise quiet gap.
* **The cheap layer is cheap enough to be continuous.** Hands, faces, blur, brightness, head motion
  and optical flow are measured by a local sweep at **4 samples per second** — 6.7% of frames, on
  CPU, free. That sweep exists only to tell the expensive layer *where to look*.

Measured on our clips, that means:

| Layer | Frames touched per hour of footage | Share of all frames | Who pays |
|---|---|---|---|
| All frames at 59.94 fps | 215,784 | 100% | — |
| Local sweep (4/s) | 14,400 | **6.7%** | your CPU, free |
| Sent to a language model | 4,105 | **1.90%** | ₹15 |

**Less than two frames in a hundred ever reach a model**, and the ones that do are chosen because
an annotation claims something about them. That is the whole trick.

A second consequence, which is what makes it usable rather than merely affordable: when a tester
fixes a segment, `checks.run(..., check_ids={...})` re-runs the checks **for that segment only**.
A one-click fix re-validates in milliseconds, not by re-analysing the video.

---

## 3. The pipeline, stage by stage

```
capture (head-mounted)
   └─> VLM first pass (draft.py, only if unannotated)
        └─> human annotator
             └─> ┌──────────────── SoloSim gate ────────────────┐
                 │ 0  lint      annotation file alone, 0 frames │
                 │ 1  sweep     4 samples/s, local, CPU         │
                 │ 2  checks    timing · capture · privacy      │
                 │ 3  label     1 model call per segment        │
                 │ 4  world     optional render test            │
                 └──────────────────────────────────────────────┘
                      └─> QA tester (flagged moments only)
                           └─> client-ready JSON
```

### Stage 0 — Lint · `lint.py` · 0 frames decoded, 0 cost

Mistakes that are visible in the annotation file itself, before a single frame is read: a segment
that ends before it starts, times outside the clip, an empty label, a duplicate id, a segment that
runs for minutes, a verb that disagrees with the narration, two segments that say the same thing
over the same seconds, and **typos found from the batch's own vocabulary** — a rare word one or two
edits away from a word the rest of the batch uses three or more times ("sopon" → "spoon"). This
stage lands instantly, before the video even starts decoding.

### Stage 1 — Sweep · `signals.py` / `stream.py` · local, CPU, free

One decode pass at 4 samples/s produces, per sample:

| Signal | Measured by | Used for |
|---|---|---|
| `hands` | YOLOv8 hand detector, ≤2 boxes | boundaries, "hands off-screen", the box drawn on the frame |
| `faces` | YOLOv8 face detector, ≤3 boxes | privacy — bystanders must be blurred before delivery |
| `hand_motion` | DIS optical flow minus the median (camera) motion | **the activity signal**: what the hands do, not what the head does |
| `head_motion` | median optical flow | "camera whip" — the action swung out of frame |
| `blur` | variance of the Laplacian | smeared frames teach a robot nothing |
| `bright` / `dark` / `blown` | mean luma, crushed and clipped pixel share | lighting failures |
| `emb` | CLIP ViT-B/32, 512-d | compare a frame to the label text offline |

Separating **hand motion from head motion** is what makes first-person video tractable. In a
head-mounted camera the entire frame moves when the wearer looks away; subtract the median flow
and what is left is the hands and the object. That residual is the activity signal every timing
check is built on.

### Stage 2 — Checks · `checks.py` · local, free

Each produces an **issue** carrying: the exact time, a box on the frame when there is one, one
plain sentence for the tester, and — where it can — a **one-click fix with a concrete value**.

**Timing**
* `too short` — under 0.35 s: no real hand action is that short; it is a mistyped end.
* `overlap` — two different actions claim the same seconds, beyond the 1.0 s that EPIC segments
  legitimately overlap. Fix: *end this one where the next begins*.
* `early start` — the segment begins more than 1.3 s before the hands move, **and** the frames before
  the movement are genuinely idle. Fix: *move the start to 0:02.9*.
* `late end` — the mirror image, after the hands stop.
* `unlabelled activity` — ≥1.0 s of hand activity in a gap no segment covers. Fix: *add a segment
  from 0:15.8 to 0:18.1*.

**Capture** — blur over half the segment, too dark, camera whip, no hand visible for the whole
segment (a manipulation label with no hands on screen cannot teach a robot the motion).

**Privacy** — a face above 0.85 confidence. Deliberately strict: kitchen objects (taps, plates,
pizza) reach 0.82 on EPIC, so the threshold sits above them.

Every threshold in that list was calibrated on the planted-error benchmark, and they are written
into the report so a reviewer can see what the gate was using.

### Stage 3 — Label · `vlm.py` · one model call per segment

"Does the footage show this verb on this object?" The model gets a contact sheet of **5
time-stamped frames** from the segment, the label, and its neighbours — neighbours matter, because
*take* versus *put down* is decided by what happened on either side. It returns structured JSON: a
verdict (`correct` / `wrong verb` / `wrong object` / `wrong action` / `not visible` / `unsure`),
**what it actually sees** in its own words, which frame proves it, and a confidence.

Two properties that matter for a QA product:

* **It never auto-rejects.** A label issue is a suggestion. The tester decides.
* **It says what it sees, not just that it disagrees** — "carry bottle to table" is actionable in a
  way that "label mismatch" is not.

Confidence is split into tiers, calibrated on the label benchmark: ≥0.7 is a `fix`, 0.6–0.7 is a
lower-priority `check`, below that it stays quiet.

### Stage 4 — World model · `render.py` · opt-in, pop-up before every rupee

The deepest question a pre-QA gate can ask: **would this annotation actually work as a
robot-training scenario?** We take the segment's real first frame, feed it to **Reactor LingBot
World 2** with the annotation as the prompt, and generate the next ~11 seconds in first person.
Then we compare the generated world to the real footage and report where it breaks: hands merged,
object morphed, scene changed, action not performed. If a world model cannot reproduce the action
from the annotation, the annotation does not describe the action well enough to train on.

This is the only stage that spends real money per use, so it never does so quietly: **a pop-up
quotes the cost before every render**, there is a per-render cap, and every call is written to a
local ledger.

---

## 4. What it costs, in rupees

Every figure below is computed from `engine/data/solosim/claude_spend.json` — the actual ledger,
written by the actual calls. Conversion at **₹88 = $1**.

### Measured, per unit

| Unit | USD | INR |
|---|---|---|
| One segment checked by the label model (Claude Haiku 5.5, 473 real calls) | $0.000209 | **₹0.018** |
| One 99-second clip, 32 segments, end to end | $0.0067 | **₹0.59** |
| **One hour of footage** (821 segments at EPIC density) | $0.1717 | **₹15.11** |
| One deep second opinion on a single segment (Claude Opus 5.5, on click) | $0.00643 | ₹0.57 |
| One world-model render (Reactor, ~11 s generated) | $0.077 | ₹6.78 |

> **A 99-second clip with 32 human annotations is fully checked for 59 paise.**

### What the whole prototype cost to build

| | Calls | USD | INR |
|---|---|---|---|
| Claude Haiku 5.5 (automatic label checks) | 473 | $0.0989 | ₹8.70 |
| Claude Opus 5.5 (deep second opinions) | 1 | $0.0064 | ₹0.57 |
| **Claude total** | **474** | **$0.1054** | **₹9.27** |
| Reactor LingBot World 2 | 4 renders | $0.301 | ₹26.49 |
| Local compute (YOLOv8, CLIP, optical flow) | all of it | $0 | ₹0 |
| **Everything** | | **$0.41** | **₹35.76** |

**The entire prototype — every benchmark, every demo clip, 474 model calls, four world-model
renders — cost under ₹36.** Not a projection. The ledger is in the repository.

### Why it is this cheap

Because of [section 2](#2-the-idea-that-makes-it-cheap). The local sweep does the looking and costs
nothing; the model is asked exactly **one question per human assertion**. 821 questions per hour of
EPIC footage, at ₹0.018 each.

*A caveat we would rather state than have you find:* 821 segments/hour is **EPIC kitchen density**,
which is extremely high — unscripted cooking is one of the densest manipulation streams that
exists. Sparser footage is proportionally cheaper, because the cost is per annotation. That is the
point of the design, and it is also why we quote the dense case.

---

## 5. What it saves, on 10,000 hours

Take the figure at the top of the brief: **10,000 hours of video.** If checking it takes 10,000
hours, the pipeline has no throughput. Here is the same 10,000 hours through SoloSim, using the
**aggregate measured** rate across our live runs — 377 seconds of footage analysed in 87.2 seconds
of wall clock, **4.32× realtime**:

| | Value |
|---|---|
| Footage | 10,000 h |
| Annotations in it, at measured density | ~8.2 million segments |
| Machine time to check all of it | **2,313 machine-hours** |
| …on 8 parallel workers | 289 h — **12 days** |
| …on 16 parallel workers | 145 h — **6 days** |
| …on 32 parallel workers | 72 h — **3 days** |
| …on 64 parallel workers | 36 h — **1.5 days** |
| Model spend for the whole 10,000 h | $1,717 — **₹1.51 lakh** |
| Footage a human still has to open | **3,140 h (31.4%)** |
| **Hours of watching that never happen** | **6,860 h** |

The analysis is **embarrassingly parallel** — one process per clip, no shared state, each writes
its own report — so the wall-clock number is a scheduling decision, not an engineering limit.
Three days on a modest 32-worker box, for a corpus that would otherwise take a human
year-equivalents.

### The honest version of the saving

Two numbers, and they are different:

* **The defensible one, measured: 68.6% of segments auto-pass**, so a human opens 31.4% of the
  corpus. 6,860 hours of watching eliminated outright.
* **The larger one, which we believe but have not measured end-to-end:** on the 31.4% that *is*
  reviewed, the tester does not watch the clip either. They get a list of timestamps, each with the
  frame, a sentence, and a button. Watching 99 seconds to find a 2-second slip becomes clicking
  *Next* and pressing *Apply*. We have not run a controlled study of tester minutes, so we quote
  the 68.6% and leave the rest to the demo, where you can watch it happen.

And the second-order saving, which is the expensive one: **bad labels that reach the client teach
robots the wrong thing.** A late end means the robot learns that "take cup" includes two seconds of
nothing. A wrong verb means it learns the opposite motion. Those cost model training runs, not QA
hours.

---

## 6. How accurate it is

All of this is on the Evidence page in the app, generated from
`engine/data/solosim/bench.json` and `label_bench_haiku.json`.

### Timing · 500 planted slips, 20 rounds, 4 clips

| Planted slip | Planted | Caught | Recall |
|---|---|---|---|
| `truncated` — mistyped end time | 122 | 122 | **100%** |
| `end late` — segment runs past the action | 123 | 88 | **71.5%** |
| `start early` — segment begins before the action | 134 | 62 | 46.3% |
| `deleted` — action never labelled | 121 | 55 | 45.5% |
| **All timing slips** | **500** | **327** | **65.4%** |

### The number that matters more than recall

| | Value |
|---|---|
| **False flag rate on untouched human annotations** | **2.6%** |
| **Correct annotations that pass untouched** | **97.4%** |
| Segments auto-passed on live clips | 68.6% |
| Human review load | 31.4% of segments |

A QA gate that cries wolf is worse than no gate — testers learn to dismiss it and the signal dies.
**97.4% of real human annotations go through this gate without being touched.** That is the
property we optimised for, and it holds across all four clips (1.9%–3.1%).

### Labels · 64 real + 64 planted-wrong labels, Claude Haiku 5.5

| Confidence tier | Shown as | Wrong labels caught | False flags on real labels |
|---|---|---|---|
| ≥ 0.7 | `fix` | 53.1% | **3.1%** |
| 0.6 – 0.7 | `check` | 71.9% | 20.3% |
| any disagreement | (not surfaced) | **85.9%** | 34.4% |

This table *is* the product decision. The model can find **85.9%** of wrong labels — but at that
setting it also argues with a third of the correct ones, and the tester stops listening. So we
surface the 0.7 tier as an actionable fix, show the middle tier as a quieter "worth a look", and
keep the noisy tail out of the interface. **The recall is available; the restraint is deliberate.**

---

## 7. The accuracy ladder: swap the model, buy recall

The gate's intelligence sits behind **one function call and one interface** (`vlm.py`). The checks,
the scoring, the UI and the export do not know or care which model answered. That makes accuracy a
procurement decision rather than a rewrite:

| Backend | Model | When it runs | Cost per segment | Why you'd pick it |
|---|---|---|---|---|
| `qwen` | Qwen2.5-VL via Ollama | offline fallback | ₹0 | air-gapped; no key; describes frames *without* seeing the label, so it cannot be led |
| `groq` | Qwen 3.8 27B on Groq | automatic, no Claude key | ₹0 (free tier) | zero marginal cost |
| `haiku` | **Claude Haiku 5.5** | **automatic, every segment** | **₹0.018** | what every number here was measured with |
| `claude` | Claude Opus 5.5 | only when a tester clicks | ₹0.57 | the hard calls — 32× the cost, so it is 32× rarer |

Three things follow, and they are the reason this prototype is a floor and not a ceiling:

1. **Every measurement in this README is from the cheap tier.** 65.4% timing recall and 97.4%
   specificity are what ₹0.018 per segment buys. Opus is already wired in and already better on the
   hard cases; it is gated behind a click purely because we were spending our own money.
2. **Resolution, not model choice, is our binding constraint on labels.** We are checking 456×256
   video — the public EPIC mirror. Awign captures in 4K. "Which hand", "which of two similar jars",
   "open versus close a drawer" are legible at 4K and genuinely are not at 456×256. The model is
   not the bottleneck; the pixels are.
3. **The planted-error benchmark is a harness, not a one-off.** Swap the backend, re-run
   `bench.py` and `label_bench.py`, and the same tables regenerate. Model selection becomes
   measurable instead of a matter of taste — which is exactly how you would run this at
   10,000-hour scale.

The two-tier design is the general shape: **a cheap model on everything, an expensive model on the
few that matter.** The cheap tier is what makes 8.2 million segments affordable. The expensive tier
is what makes the hard few per cent correct. Neither alone works.

---

## 8. The world-model check

Everything above asks *"is this annotation accurate?"* This stage asks a harder question:
***"is this annotation good enough to train a robot?"***

We take the segment's real first frame, hand it to **Reactor LingBot World 2** with the annotation
as the prompt, generate ~11 seconds of first-person world, and then compare it to the real footage
frame by frame — scene similarity, whether hands are still detectable, and an AI judge that names
the failures.

Four real renders, all in the repository with their judgements:

| Annotation | Verdict | What broke |
|---|---|---|
| `fold tablecloth` | **fails** | black cloth morphs to white striped; kitchen layout changes; drifts off the fold by frame 6 |
| `wash cup` | **partial** | hands merge at frame 7; cup oversized and loses its handle at frame 12 |
| `pour water into glass` | **fails** | object morphed |
| `continue cutting pizza` | **fails** | object morphed |

This is a genuinely novel QA signal and we want to be precise about what it means. A failure here
is **not proof the annotation is wrong** — world models morph objects on their own. It is a flag
that *this annotation, from this frame, does not constrain the action tightly enough for a
generative model to reproduce it* — which is a real property of a training example, and one no
existing QA tool measures at all.

Cost: $0.077 (₹6.78) per render, 11 seconds generated. **A pop-up quotes it before every single
one.** Per-render cap, local ledger, nothing spent without a click.

---

## 9. Why this is not a thing that already exists

| What exists | What it does | What it does not do |
|---|---|---|
| CVAT, Label Studio, SuperAnnotate | help a human draw and label faster, then route to a human reviewer | never look at the pixels to ask whether the label is *true* |
| Dataset QA scripts | schema checks, duration histograms, class balance | nothing frame-aware; a start two seconds early is invisible to them |
| Consensus / multi-annotator agreement | two people label the same clip and you compare | **doubles the cost**, and agreeing annotators are wrong together |
| Video understanding APIs | caption or classify a whole clip | no notion of a segment boundary, no fix, no cost model for 10,000 h |
| Generic "AI video QA" | sample frames, caption, flag | cost scales with footage, so it dies at scale |

Four things are genuinely new here, and they compound:

1. **Checking is gated on annotations, not on footage.** The expensive layer fires once per human
   assertion, at the disruptions — so a corpus of 8.2 million segments costs ₹1.51 lakh instead of
   being arithmetically impossible. This is the load-bearing idea.
2. **Every flag is a moment, not a verdict.** A timestamp, a boxed frame, one sentence, and a button
   with a concrete value in it — *"Move the end of 'take cup' to 0:02.9"*. The tester starts from
   evidence; they never re-watch to find what the gate meant.
3. **It is a gate, not a gatekeeper.** It never rejects anything. The annotator sees their own
   mistakes before QA does and can fix them in one click — or submit anyway, and nothing stops them.
   A tool that blocks the worker gets routed around inside a week; a tool that makes them look good
   to QA gets adopted. That is a product decision, enforced in the code.
4. **It asks whether the annotation would train a robot**, via the world-model render. That question
   does not currently have a tool.

---

## 10. What we are not claiming

We would rather you hear the limits from us.

* **65.4% timing recall is not 100%.** Starts that slide into the previous action without idle time
  in between are invisible to an activity-based check — if the hands never stop, there is no
  disruption to find. That is a real class of miss, it is in the table above, and the fix is a
  learned boundary model rather than a threshold.
* **Deleted actions: 45.5%.** A missed action is only found if it produced ≥1.0 s of clear hand
  activity in an uncovered gap. Quiet actions get missed.
* **456×256 is a severe handicap on labels.** Fine verb distinctions are not resolvable at that
  size. Numbers at 4K would differ, and we have not run them, so we do not quote them.
* **No controlled study of tester minutes.** We quote the auto-pass share because we measured it.
  We do not quote a "5× faster reviewer" number, because we did not measure one.
* **The world-model check is a signal, not a verdict**, for the reasons in section 8.
* **Segment density is dataset-specific.** 821/hour is dense kitchen work. Your mileage varies, and
  the cost varies with it — downward, in most cases.
* **One deep Opus call in the whole ledger.** Not because it was not useful — because it was our
  own money, under a hard cap.

---

## 11. The product: three rooms

One light theme across the whole product; the only dark surface in the app is the video itself, so
your eye goes to the footage. Nothing is pre-computed — every screen in the demo is analysed live
in front of you.

**`/annotator` — the annotator's room.** Drag a video and its annotations in. Analysis streams: a
progress ring, a readiness score that counts up, mistakes appearing on the timeline **in time
order** as the moving edge passes them, so you can start fixing the first minute while the fourth is
still being checked. Then: fix what you want, and submit. *The submit button never blocks.* If you
have open issues it asks once, and if you say submit anyway, it submits. You cannot force an
annotator, and a tool that tries gets abandoned.

**`/qa` — the QA desk.** Submitted, returned and approved lanes. Per submission: who sent it,
readiness, how many segments need eyes, and a **mistake report** — what this annotator gets wrong
most often, which is a coaching signal, not just a defect list. Auto-fix all one-click issues,
approve, or return with a note. Resubmissions are versioned.

**`/review/[id]` — the review room.** A video editor, because that is the tool this is competing
with. Frame-accurate stepping, 0.25×–2× speed, theater mode, fullscreen, keyboard shortcuts
anywhere on the page (space, ←/→ for a frame, shift+←/→ for a second, T, F). The scrubber carries a
coloured tick at every flagged moment. The segment timeline sits under the player with the
hand-activity trace behind it, so you can *see* the start that was early. On the right, the nudge
list: press **Next**, the footage jumps to the exact second, the hands are boxed, one sentence says
what is wrong, **Apply** writes the fix and re-checks that segment alone. *Ask Claude* gets a deeper
second opinion on the hard ones.

Plus `/queue` (all clips and their state) and `/bench` (the evidence page — every number in section
6, generated from the benchmark files).

Export is client-ready JSON: every segment with its QA status, the reasons, and the full review
trail of who decided what.

**Verified for the demo:** no console or page errors on any route; no horizontal overflow at 1920,
1512, 1280, 834 or 390 px; `tsc --noEmit` clean; `eslint` clean; production build green.

---

## 12. Run it

```bash
# engine (Python 3.12)
cd engine
python -m venv --system-site-packages .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn solosim.server:app --port 8765

# web
cd web && npm install
npm run dev     # http://localhost:3000   (or: npm run build && npm start)
```

Keys live in `.env.local` at the repository root — **gitignored, server-side only, never shipped to
the browser.**

| Key | Used for | Cost control |
|---|---|---|
| `GROQ_API_KEY` | automatic label check (Qwen 3.8 27B vision) | free tier |
| `ANTHROPIC_API_KEY` | Haiku 5.5 automatic check; Opus 5.5 second opinion on click | hard cap `SOLOSIM_CLAUDE_CAP_USD`, every call priced and written to a ledger |
| `REACTOR_API_KEY` | LingBot World 2 render check | cost pop-up before every render, per-render cap, local ledger |

**Without any keys the gate still runs.** Lint, timing, capture and privacy are entirely local; the
label check falls back to a local Qwen2.5-VL via Ollama. The parts that cost money are the parts
you can turn off.

---

## 13. Repository layout

```
engine/solosim/
  clip_io.py    clips on disk, EPIC import
  draft.py      VLM first pass for unannotated uploads
  lint.py       annotation-only checks, before a frame is decoded
  signals.py    per-sample measurement (YOLOv8 hands/faces, DIS optical flow, blur, CLIP)
  stream.py     streaming analysis: the report grows window by window
  checks.py     timing / capture / privacy -> issues with time, box, nudge, one-click fix
  vlm.py        label second opinion: Haiku (auto), Opus (on click, capped), Groq, local Qwen
  render.py     LingBot World 2 first-person render + failure points
  bench.py      planted-error benchmark
  pipeline.py   one clip through the gate
  server.py     HTTP API
engine/scripts/ bench.py, label_bench.py and friends
engine/data/solosim/
  clips/<id>/   video.mp4, annotations.json, signals.npz, report.json, review.json
  bench.json, label_bench_haiku.json, claude_spend.json   <- the ledgers behind every number here
web/src/app/    /  /annotator  /qa  /queue  /review/[id]  /bench
```

Version 1 (a drone flying inside a generated world) is at `github.com/UJESH2K/WorldSim`, tag `v1`.

---

## 14. Demo script

| # | Time | Beat |
|---|---|---|
| 1 | 0:30 | **Landing.** The bottleneck in robot data is checking, not capture. Point at the measured numbers: 4.3× realtime, ₹15/hour, 97.4% of correct annotations untouched. |
| 2 | 1:30 | **Annotator, live.** Drag in a real EPIC clip. Watch mistakes appear on the timeline in time order as analysis streams. Fix one in a click. Submit with issues still open — *it lets you.* |
| 3 | 2:00 | **Review room.** Press Next: the footage jumps to "Ends 7.7 s after the hands stop", hands boxed. Apply — the segment re-checks alone. Show a missed action found in a gap, and a wrong label with what the model actually sees. Ask Claude on the hard one. |
| 4 | 1:00 | **World model.** "wash cup" rendered next to the real footage: frame 7 hands merged, frame 12 cup oversized. This annotation is not yet a usable robot scenario. (The pop-up quotes ₹6.78 first.) |
| 5 | 0:30 | **QA desk.** The mistake report — what this annotator gets wrong most. Approve, or return with a note. |
| 6 | 0:30 | **Evidence.** 500 planted slips, 65.4% caught at 2.6% false flags. And the limits, stated. |

---

## 15. Credits

* **EPIC-KITCHENS-100** — Damen et al., IJCV 2022. CC BY-NC 4.0. 256p mirror via Hugging Face.
* **Hand and face detection** — Bingsu/adetailer YOLOv8.
* **CLIP** ViT-B/32 — OpenAI.
* **Optical flow** — OpenCV DIS.
* **Label review** — Claude Haiku 5.5 and Claude Opus 5.5, Anthropic.
* **World model** — Reactor LingBot World 2.

Built for the Awign Physical AI Hackathon, Bengaluru, 10–11 October 2026.
