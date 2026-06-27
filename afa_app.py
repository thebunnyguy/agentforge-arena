#!/usr/bin/env python3
"""AgentForge Arena — one-command local app launcher.

Double-click ``start.command`` (macOS) or run ``python3 afa_app.py``. It:
  * builds the React UI the first time (if ``web/dist`` is missing),
  * starts the background evaluation worker,
  * serves the UI **and** API from a single port, and
  * opens your browser.

Press Ctrl-C (or close the terminal window) to stop everything.

No paid APIs, no network needed to browse existing results. Running new
evaluations needs a local model backend (Ollama, etc.). Trusted single-user
local tool: it runs agent code with host privileges and makes no
untrusted-agent isolation claims.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("AFA_HOST", "127.0.0.1")
PORT = int(os.environ.get("AFA_PORT", "8000"))
# reports/runs.sqlite is the committed, read-only EVIDENCE database (the 600
# audited runs). The app works on a separate, gitignored copy so neither
# browsing nor running new evaluations ever mutates the evidence DB. Set
# AFA_DB_PATH to override (e.g. point straight at the evidence DB).
_EVIDENCE_DB = ROOT / "reports" / "runs.sqlite"
DB_PATH = os.environ.get("AFA_DB_PATH", str(ROOT / "reports" / "app.sqlite"))
URL = f"http://{HOST}:{PORT}"

# Make kernel / runner / afa_api importable without PYTHONPATH gymnastics.
for _p in (ROOT, ROOT / "kernel", ROOT / "runner"):
    sys.path.insert(0, str(_p))


def _log(msg: str) -> None:
    print(f"[afa] {msg}", flush=True)


def ensure_web_build() -> bool:
    """Return True if a built SPA is available (building it if needed)."""
    web = ROOT / "web"
    dist_index = web / "dist" / "index.html"
    if dist_index.is_file():
        return True
    if not (web / "package.json").is_file():
        _log("web/ not found — the API will run but the UI won't be served.")
        return False
    npm = shutil.which("npm")
    if not npm:
        _log("npm/Node not found — can't build the UI. Install Node 18+, then re-run.")
        return False
    if not (web / "node_modules").is_dir():
        _log("installing web dependencies (first run only)…")
        subprocess.run([npm, "install"], cwd=web, check=True)
    _log("building the UI (first run only)…")
    subprocess.run([npm, "run", "build"], cwd=web, check=True)
    return dist_index.is_file()


def start_worker() -> subprocess.Popen:
    env = dict(
        os.environ,
        AFA_DB_PATH=DB_PATH,
        PYTHONPATH=os.pathsep.join(
            [str(ROOT), str(ROOT / "kernel"), str(ROOT / "runner")]
        ),
    )
    _log("starting evaluation worker…")
    return subprocess.Popen(
        [sys.executable, "-m", "afa_api.worker"], cwd=str(ROOT), env=env
    )


def open_browser_when_ready() -> None:
    health = f"{URL}/api/v1/healthz"
    for _ in range(120):
        try:
            with urllib.request.urlopen(health, timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    if not os.environ.get("AFA_NO_BROWSER"):
        _log(f"opening {URL}")
        try:
            webbrowser.open(URL)
        except Exception:
            pass


def _seed_working_db() -> None:
    """Copy the read-only evidence DB to the working DB on first run, so the
    committed reports/runs.sqlite is never mutated by browsing or eval runs."""
    dst = Path(DB_PATH)
    if str(dst) == str(_EVIDENCE_DB):
        return  # user explicitly pointed at the evidence DB; respect it
    if not dst.exists() and _EVIDENCE_DB.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_EVIDENCE_DB, dst)
        _log(f"seeded working DB from evidence DB -> {dst}")


def main() -> None:
    # Serve the SPA from the API and bind to our DB before importing the app.
    _seed_working_db()
    os.environ["AFA_DB_PATH"] = DB_PATH
    os.environ["AFA_SERVE_WEB"] = "1"

    has_ui = ensure_web_build()
    worker = start_worker()
    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    import uvicorn  # imported late so an early --help is instant

    from afa_api.main import app

    app.state.db_path = DB_PATH  # authoritative DB binding for the lifespan
    _log(f"DB: {DB_PATH}")
    _log(f"serving {'UI + API' if has_ui else 'API only (UI not built)'} on {URL}")
    _log("press Ctrl-C to stop.")
    try:
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    finally:
        _log("shutting down worker…")
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except Exception:
            worker.kill()


if __name__ == "__main__":
    main()
