"""Record the demo's screen captures at 1920x1080 with Playwright (driving the installed Chrome).

    .venv\\Scripts\\python.exe docs\\video\\capture.py [--base http://127.0.0.1:8803] [--only timeline,faces] [--make]

Run it against a local copy of the site (`scripts/run_site_local.py --port 8803 --data data/capture/data
--gpu local`, access code "localtest"), never the public demo. Each shot is one recorded browser session
written to data/video/<name>.webm, then converted to .mp4. `--make` also records a new film being made from
one sentence (about 8 minutes, a few dollars of Muse calls); without it that shot is skipped.
The shot list with timings is docs/video/SHOTS.md.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "video"
W, H = 1920, 1080
HERO = "film_20261030_171616"          # "Taya Growing Up", English subtitles, v2 preferred blind both times
SCAN = "360bdd0d361e337a7967b3b8129f71b0a7c8c7596cd673f63b76cfc9f2a943f9:moment"   # a 1970s scan Muse dated
REQUEST = "A one-minute film of Taya growing up, from a baby to her last birthday, warm and simple."
QUESTION = "When did we go to the beach with the kids?"
NEW = "film_20261031_175659"            # the film `--make` recorded on 2026-10-31


def slow_scroll(page: Page, px: int, seconds: float, steps: int = 60) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, px / steps)
        time.sleep(seconds / steps)


def go(page: Page, base: str, hash_: str, settle: float = 2.5) -> None:
    page.goto(f"{base}/#{hash_}")
    page.wait_for_load_state("networkidle")
    time.sleep(settle)


def timeline(page: Page, base: str) -> None:
    go(page, base, "/timeline")
    slow_scroll(page, 5200, 9)
    time.sleep(1)


def library(page: Page, base: str) -> None:
    """Browse actual memory cards for the opening scope shot."""
    go(page, base, '/memories', 3)
    page.locator('a[href^="#/memory/"]').first.wait_for()
    slow_scroll(page, 850, 6)
    time.sleep(2)


def faces(page: Page, base: str) -> None:
    go(page, base, "/faces", 4)
    page.mouse.move(700, 520)
    slow_scroll(page, 500, 3)
    time.sleep(1.5)
    btn = page.locator("button[data-a='yes']").first   # "Yes, <suggested name>": one answer names the group
    if btn.count():
        btn.scroll_into_view_if_needed()
        time.sleep(1.2)
        btn.hover()
        time.sleep(0.8)
        btn.click()
        time.sleep(2.5)


def add(page: Page, base: str) -> None:
    go(page, base, "/add", 4)
    slow_scroll(page, 400, 4)
    time.sleep(2)


def dated(page: Page, base: str) -> None:
    go(page, base, "/timeline", 1.5)
    page.evaluate(f"openViewer({SCAN!r})")
    time.sleep(7)


def connections(page: Page, base: str) -> None:
    go(page, base, "/connections", 4)
    page.locator("#tplay").click()
    time.sleep(22)


def search(page: Page, base: str) -> None:
    go(page, base, "", 2)
    box = page.locator("#q")
    box.click()
    box.type(QUESTION, delay=55)
    box.press("Enter")
    page.wait_for_selector(".answer", timeout=120_000)
    time.sleep(4)
    slow_scroll(page, 600, 4)
    time.sleep(2)


def film(page: Page, base: str) -> None:
    """The finished hero film: both cuts, the critic's notes on the first, the blind test card, the scenes."""
    go(page, base, f"/film/{HERO}", 3)
    page.locator("#fversions").scroll_into_view_if_needed()
    time.sleep(3)
    note = page.locator("[data-seek='v1']").first
    if note.count():
        note.hover()
        time.sleep(1)
        note.click()
        time.sleep(6)
        page.evaluate("document.querySelectorAll('video').forEach(v => v.pause())")
    slow_scroll(page, 900, 6)
    time.sleep(2)
    slow_scroll(page, 900, 6)
    time.sleep(2)


def crew(page: Page, base: str) -> None:
    """The film recorded by `make`, finished: the Picture Checker's verdicts on the scenes, then the crew log."""
    go(page, base, f"/film/{NEW}", 3)
    page.locator("#fscenes").scroll_into_view_if_needed()
    time.sleep(1)
    out = page.locator("#fscenes .thumbs .out").first
    if out.count():
        out.hover()
    time.sleep(6)
    page.locator("#fcrew").scroll_into_view_if_needed()
    time.sleep(1)
    page.evaluate("document.querySelector('.crew').scrollTop = 0")
    time.sleep(2)
    for _ in range(8):
        page.evaluate("document.querySelector('.crew').scrollBy(0, 70)")
        time.sleep(1)
    time.sleep(2)


def home(page: Page, base: str) -> None:
    go(page, base, "", 3)
    page.evaluate("document.querySelector('video')?.play()")
    time.sleep(14)


def make(page: Page, base: str) -> None:
    """A new film from one sentence, recorded live: the crew log, the pause-and-ask card, both cuts."""
    go(page, base, "/films", 2)
    req = page.locator("#freq")
    req.click()
    req.type(REQUEST, delay=40)
    time.sleep(1)
    page.locator("#fmake").click()
    t0 = time.time()
    answered = False
    while time.time() - t0 < 20 * 60:
        time.sleep(3)
        if not answered and page.locator(".card.ask button[data-q]").count():
            time.sleep(4)
            page.locator(".card.ask").scroll_into_view_if_needed()
            time.sleep(3)
            for k in range(page.locator(".card.ask .q").count()):   # each question: its first answer
                opt = page.locator(".card.ask .q").nth(k).locator("button.opt").first
                opt.scroll_into_view_if_needed()
                opt.hover()
                time.sleep(1)
                opt.click()
                time.sleep(2.5)
            answered = True
        state = page.locator("#fhead .eyebrow").inner_text() if page.locator("#fhead .eyebrow").count() else ""
        if state.strip().lower() in ("ready", "failed", "stopped"):   # the label is shown in capitals
            break
    page.locator("#fversions").scroll_into_view_if_needed()
    time.sleep(5)


SHOTS = {"home": home, "timeline": timeline, "library": library, "faces": faces, "add": add, "dated": dated,
         "connections": connections, "search": search, "film": film, "crew": crew, "make": make}


def to_mp4(webm: Path) -> Path:
    mp4 = webm.with_suffix(".mp4")
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-i", str(webm), "-c:v", "libx264", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-r", "30", str(mp4)], check=True)
    return mp4


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8803")
    ap.add_argument("--code", default="localtest")
    ap.add_argument("--only", default="")
    ap.add_argument("--make", action="store_true")
    a = ap.parse_args()
    names = [n for n in (a.only.split(",") if a.only else SHOTS) if n and (n != "make" or a.make)]
    OUT.mkdir(parents=True, exist_ok=True)
    host = a.base.split("//")[1].split(":")[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        for name in names:
            ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                      record_video_dir=str(OUT / "_raw"), record_video_size={"width": W, "height": H})
            ctx.add_cookies([{"name": "mlg_code", "value": a.code, "domain": host, "path": "/"}])
            ctx.add_init_script("try { sessionStorage.setItem('demo-banner', 'closed') } catch (e) {}")
            page = ctx.new_page()
            t = time.time()
            try:
                SHOTS[name](page, a.base)
            except Exception as e:  # noqa: BLE001 - keep what was recorded, report the rest
                print(f"{name}: {type(e).__name__}: {e}")
            raw = Path(page.video.path())
            ctx.close()
            webm = OUT / f"{name}.webm"
            raw.replace(webm)
            print(f"{name}: {time.time() - t:.0f} s -> {to_mp4(webm).name}", flush=True)
        browser.close()
    # the hero film's two cuts, as clips for the hook and the payoff
    films = ROOT / "data" / "site_pull" / "films" / HERO
    for v in ("v1", "v2"):
        if (films / v / "film.mp4").exists():
            shutil.copy2(films / v / "film.mp4", OUT / f"taya_{v}.mp4")


if __name__ == "__main__":
    main()
