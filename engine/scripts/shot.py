"""Screenshot pages for a visual check (needs the web dev server on :3000).

    python scripts/shot.py lab audit              # desktop, full page
    python scripts/shot.py lab --mobile
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "ui_shots"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    paths = ["/" + a.strip("/") for a in sys.argv[1:] if not a.startswith("--")]
    mobile = "--mobile" in sys.argv
    wait = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--wait=")), 4.0)
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
                          device_scale_factor=1)
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        for path in paths:
            page.goto("http://localhost:3000" + path, wait_until="load")
            time.sleep(wait)
            name = path.strip("/").replace("/", "_") or "home"
            f = OUT / f"{name}{'-m' if mobile else ''}.png"
            page.screenshot(path=str(f), full_page=True)
            width = page.evaluate("document.documentElement.scrollWidth")
            print(f, "scrollWidth", width)
        b.close()
    for e in errors:
        print("ERROR:", e)


if __name__ == "__main__":
    main()
