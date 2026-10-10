"""Screenshots of the reviewer workspace in the states a judge sees (needs both servers up).

    python scripts/demo_shots.py P01_08 P01_08_14
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "ui_shots"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    clip = sys.argv[1] if len(sys.argv) > 1 else "P01_08"
    seg = sys.argv[2] if len(sys.argv) > 2 else None
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://localhost:3000/review/{clip}", wait_until="load")
        time.sleep(5)
        cards = pg.locator("aside article button").first
        cards.click()
        time.sleep(2.5)
        pg.screenshot(path=str(OUT / f"review-{clip}-nudge.png"))
        if seg:
            pg.locator(f"button[title^='{seg_label(pg, clip, seg)}']").first.click()
            time.sleep(2)
            earlier = pg.get_by_text("Earlier renders of this segment")
            if earlier.count():
                earlier.locator("button").first.click()
                time.sleep(3)
            pg.mouse.wheel(0, 900)
            time.sleep(1.5)
            pg.screenshot(path=str(OUT / f"review-{clip}-render.png"))
        b.close()
    print("errors:", errors)


def seg_label(pg, clip, seg):
    import json
    import urllib.request

    d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:8765/clips/{clip}").read())
    return next(s["narration"] for s in d["segments"] if s["id"] == seg)


if __name__ == "__main__":
    main()
