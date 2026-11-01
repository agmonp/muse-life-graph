"""The downloadable app: starts Muse Life Graph on this computer and opens it in the browser.

    MuseLifeGraph.exe                 # the built app (PyInstaller, packaging/muse_life_graph.spec)
    python -m mlg.desktop             # the same from a checkout (MLG_DESKTOP=1 is set for you)

The server listens on 127.0.0.1 only. Keys, caches and films live in %LOCALAPPDATA%/MuseLifeGraph
(mlg/config.py); the first visit shows the setup screen, where the user pastes their own Meta key and
graph database. Run it twice and the second start just opens the first one's page.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

PORTS = range(int(os.environ.get("MLG_PORT", "8800")), int(os.environ.get("MLG_PORT", "8800")) + 10)


def _ours(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1) as r:
            return r.status == 200 and b"build" in r.read()
    except OSError:
        return False


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _open_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "api/version", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    webbrowser.open(url)


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--pick":    # the folder / file picker, run as its own process
        from mlg.imports import _PICK
        sys.argv = [sys.argv[0], sys.argv[2]]
        exec(_PICK, {"__name__": "__pick__"})
        return
    os.environ.setdefault("MLG_DESKTOP", "1")
    for port in PORTS:
        if _ours(port):
            print(f"Muse Life Graph is already running: http://127.0.0.1:{port}/")
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return
    port = next((p for p in PORTS if _free(p)), None)
    if port is None:
        sys.exit("Ports 8800-8809 are all in use; close something and try again.")
    from mlg.config import DATA, HOME
    url = f"http://127.0.0.1:{port}/"
    print(f"Muse Life Graph is running at {url}\n"
          f"Your settings and films: {HOME}\n"
          f"(your photos stay where they are; data in {DATA})\n"
          "Close this window to stop it.\n", flush=True)
    if not os.environ.get("MLG_NO_BROWSER"):   # tests start it without opening a browser
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    import uvicorn
    from mlg.web.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
