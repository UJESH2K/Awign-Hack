"""Run the gate on every clip (or the ones named), then optionally the label benchmark.

    python scripts/analyze_all.py                 # all clips
    python scripts/analyze_all.py P01_04 --bench  # one clip, then the label benchmark on P01_04 + P01_08
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solosim import pipeline  # noqa: E402
from solosim.clip_io import Clip, list_clips  # noqa: E402


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list_clips()
    for cid in names:
        t = time.time()
        rep = pipeline.analyze(Clip(cid), progress=lambda m, f: None)
        s = rep["summary"]
        print(f"{cid}: readiness {s['readiness']} | pass {s['pass']} check {s['check']} fix {s['fix']} | "
              f"labels {len(rep['label'].get('results', {}))}/{s['segments']} | {time.time() - t:.0f}s", flush=True)
    if "--bench" in sys.argv:
        subprocess.run([sys.executable, str(Path(__file__).parent / "label_bench.py"), "--clips", "P01_04", "P01_08"], check=False)


if __name__ == "__main__":
    main()
