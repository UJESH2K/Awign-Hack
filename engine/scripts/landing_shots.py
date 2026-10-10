"""Images for the landing page, taken from the running product (both servers up).

    python scripts/landing_shots.py
"""
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PUB = Path(__file__).resolve().parents[2] / "web" / "public" / "shots"
PUB.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        pg.goto("http://localhost:3000/review/P01_08", wait_until="load")
        time.sleep(5)
        pg.locator("aside article button").first.click()
        time.sleep(2.5)
        pg.screenshot(path=str(PUB / "review.png"))
        # the render comparison, on a failure frame
        pg.locator("button[title^='wash cup']").first.click()
        time.sleep(2)
        pg.get_by_text("Earlier renders of this segment").locator("button").first.click()
        time.sleep(3)
        fail = pg.locator("li button", has_text="hands merged").nth(1)
        fail.click()
        time.sleep(2)
        pg.locator("section", has_text="Will it work as a robot scenario?").last.screenshot(path=str(PUB / "render.png"))
        b.close()
    for f in PUB.glob("*.png"):
        print(f, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
