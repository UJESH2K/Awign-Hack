"""How well does the automatic label check separate true labels from planted wrong ones?

    python scripts/label_bench.py                 # Groq (free tier), all four EPIC clips
    python scripts/label_bench.py --which qwen    # local model
Writes data/solosim/label_bench.json.
"""
import argparse
import copy
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solosim import vlm  # noqa: E402
from solosim.clip_io import DATA, Clip, list_clips  # noqa: E402

FLAG = {"wrong verb", "wrong object", "wrong action"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", default=None)
    ap.add_argument("--clips", nargs="*", default=None)
    args = ap.parse_args()
    which = args.which or vlm.backend()
    rng = random.Random(7)
    rows = []
    for cid in args.clips or [c for c in list_clips() if c.startswith("P0")]:
        c = Clip(cid)
        labels = sorted({s.narration for s in c.segments})
        true = vlm.check(c, which=which)
        swapped = []
        for s in c.segments:
            w = copy.deepcopy(s)
            other = [l for l in labels if l.split()[0] != s.narration.split()[0]]
            w.narration = rng.choice(other)
            w.verb, w.noun = w.narration.split()[0], " ".join(w.narration.split()[1:])
            swapped.append(w)
        wrong = {}
        for i, w in enumerate(swapped):  # one segment wrong at a time, neighbours true
            segs = c.segments[:i] + [w] + c.segments[i + 1:]
            wrong.update(vlm.check(c, segments=segs, only={w.id}, which=which))
        for s in c.segments:
            if s.id in true and s.id in wrong:
                rows.append({"clip": cid, "segment": s.id, "label": s.narration, "true_verdict": true[s.id]["verdict"],
                             "true_seen": true[s.id].get("observed_action"), "wrong_label": next(w.narration for w in swapped if w.id == s.id),
                             "wrong_verdict": wrong[s.id]["verdict"]})
        print(cid, len(rows), flush=True)
    n = len(rows)
    ff = sum(r["true_verdict"] in FLAG for r in rows)
    rc = sum(r["wrong_verdict"] in FLAG for r in rows)
    unsure_t = sum(r["true_verdict"] == "unsure" for r in rows)
    out = {"backend": which, "segments": n, "wrong_caught": rc, "recall": round(rc / max(1, n), 3),
           "true_flagged": ff, "false_flag_rate": round(ff / max(1, n), 3), "true_unsure": unsure_t, "rows": rows}
    (DATA / "solosim" / f"label_bench_{which}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print({k: v for k, v in out.items() if k != "rows"})


if __name__ == "__main__":
    main()
