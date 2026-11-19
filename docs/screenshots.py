"""Retina screenshots of the UI for the docs / blog post.

Needs the UI running (.venv/bin/python ui.py) and Google Chrome installed
(Playwright drives the installed Chrome; no browser download).

  .venv/bin/python docs/screenshots.py                 # all shots
  .venv/bin/python docs/screenshots.py 03-compare      # just one
"""
import sys, urllib.parse as up
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/"
OUT = Path(__file__).parent / "screenshots"
CTX = ("Polygonfaces AI Society meetup, presented by Martin Atrin. "
       "Title: 'Agents at work: payments, models and machines'.")
EDIT = ("19:You can preload it with five bucks and let the agents go wild on the internet. "
        "Shops that already support agentic commerce will be able to sell; the others will have a hard time.")

SHOTS = {
    "01-new-job":   ("#" + up.urlencode({"source": "https://www.youtube.com/watch?v=Dng83kIb-BY",
                                         "name": "meetup-full", "context": CTX}), False),
    "02-running":   ("#job=meetup-full", False),
    "03-compare":   ("#job=sample-10m&t=196", True),
    "04-edit-line": ("#" + up.urlencode({"job": "sample-10m", "t": 130, "edit": EDIT}), True),
    "05-full-job":  ("#job=meetup-full&t=1210", True),
}


def main(names):
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        for name in names:
            frag, has_video = SHOTS[name]
            page.goto("about:blank")
            page.goto(BASE + frag)
            page.wait_for_selector("#jobs div, #jobs span")
            if has_video:
                page.wait_for_selector("#vN")
                # wait until both players have decoded the frame at the seek target
                page.wait_for_function("""() => ['#vO', '#vN'].every(s => {
                    const v = document.querySelector(s); return v && v.readyState >= 2 && !v.seeking; })""",
                                       timeout=30000)
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(OUT / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or list(SHOTS))
