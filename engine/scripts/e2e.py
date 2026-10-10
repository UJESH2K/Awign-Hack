"""End-to-end check of the reviewer flows in a real browser (both servers up).

    python scripts/e2e.py            # apply a fix + export (free)
    python scripts/e2e.py --claude   # also one Claude Opus second opinion (~1-2 cents)
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "ui_shots"
API = "http://127.0.0.1:8765"


def api(path):
    return json.loads(urllib.request.urlopen(API + path).read())


def main(clip="P01_10"):
    errors = []
    before = api(f"/clips/{clip}")
    fixes = [i for i in before["report"]["issues"] if i["severity"] == "fix" and i.get("suggestion")
             and not any(d["issue"] == i["id"] for d in before["review"]["decisions"])]
    print(f"{clip}: {len(fixes)} open fixes with a suggestion")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://localhost:3000/review/{clip}", wait_until="load")
        time.sleep(5)
        pg.locator("aside button[role='radio']", has_text="fix").click()
        time.sleep(0.5)
        pg.locator("aside article button").first.click()
        time.sleep(1.5)
        apply = pg.locator("aside button", has_text="Apply:").first
        label = apply.inner_text()
        apply.click()
        time.sleep(4)
        after = api(f"/clips/{clip}")
        print("applied:", label.replace("\n", " "), "| decisions", len(before["review"]["decisions"]), "->", len(after["review"]["decisions"]))
        pg.screenshot(path=str(OUT / f"e2e-{clip}-applied.png"))
        if "--claude" in sys.argv:
            target = next(i for i in after["report"]["issues"] if i["group"] == "label" and i["segment"])
            seg = next(s for s in after["segments"] if s["id"] == target["segment"])
            pg.locator(f"button[title^='{seg['narration']}']").first.click()
            time.sleep(1.5)
            pg.locator("button", has_text="Ask Claude about this label").click()
            pg.wait_for_selector("text=Claude (second opinion)", timeout=90000)
            time.sleep(1)
            pg.screenshot(path=str(OUT / f"e2e-{clip}-claude.png"))
            print("claude spend:", api("/spend")["claude"])
        r = urllib.request.urlopen(f"{API}/clips/{clip}/export")
        exp = json.loads(r.read())
        print("export:", len(exp["segments"]), "segments,", sum(s["qa_status"] == "reviewed" for s in exp["segments"]), "reviewed,",
              len(exp["review_log"]), "log entries")
        b.close()
    print("errors:", errors)


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if not a.startswith("--")), "P01_10"))
