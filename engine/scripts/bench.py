"""Planted-error benchmark for the timing checks (free, offline). Writes data/solosim/bench.json.

    python scripts/bench.py --rounds 20
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solosim import bench, checks, signals  # noqa: E402
from solosim.clip_io import DATA, Clip, list_clips  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=20)
    args = ap.parse_args()
    kinds = ["start early", "end late", "truncated", "deleted"]
    res, review = {}, {}
    for cid in [c for c in list_clips() if c.startswith("P0")]:
        c = Clip(cid)
        s = signals.load(c)
        res[cid] = bench.score(c, s, rounds=args.rounds, kinds=kinds)
        flagged = {i.segment for i in checks.run(c, s) if i.segment}
        review[cid] = {"segments": len(c.segments), "flagged": len(flagged)}
        print(cid, res[cid]["recall"], res[cid]["false_flag_rate"], flush=True)
    summ = bench.summarise(res)
    segs = sum(v["segments"] for v in review.values())
    flagged = sum(v["flagged"] for v in review.values())
    out = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "rounds": args.rounds, "share_planted": 0.2,
           "summary": summ, "clips": res, "review_load": {"segments": segs, "flagged": flagged,
                                                           "share": round(flagged / max(1, segs), 3)},
           "thresholds": {k: getattr(checks, k) for k in ("OVERLAP_S", "SHORT_S", "IDLE_S", "GAP_ACTIVE_S", "BLUR_MIN")}}
    (DATA / "solosim" / "bench.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
