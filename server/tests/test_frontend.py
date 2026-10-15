"""Serve the built frontend and check everything a browser asks for.

scripts/build_frontend.py copies index.html, settings.json and src/ into dist/,
and dist/ is what a static host serves. This script rebuilds it, starts a plain
static server on it, and then, for every page:

  * GET the page itself
  * GET every <script src>, <link href> and <img src> it references
  * GET every module path in settings.json (what PyScript fetches)

Any 404 or non-200 is a failure: it is exactly what would leave the browser with
a half-loaded page, and a stale dist/ would hide fixes that are already in src/.

Note that it rewrites dist/ (a gitignored build output) as a side effect.

Run it from the repository root with:

    .venv\\Scripts\\python.exe server\\tests\\test_frontend.py

Every check is printed and the process exits non-zero if any failed.
"""
import html
import http.server
import pathlib
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

import httpx

# Resolved from this file, so the script runs from any working directory.
TESTS_DIR = pathlib.Path(__file__).resolve().parent
REPO = TESTS_DIR.parent.parent                # the repository root
DIST = REPO / "dist"

results = []
failures = []


def check(label, condition, detail: object = ""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + ("" if condition else f"  <- {detail}"))
    if not condition:
        failures.append(label)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


build = subprocess.run(
    [sys.executable, str(REPO / "scripts" / "build_frontend.py")],
    capture_output=True, text=True,
)
check("the frontend build runs", build.returncode == 0,
      (build.stdout + build.stderr)[-300:])
check("dist/index.html and dist/settings.json exist",
      (DIST / "index.html").exists() and (DIST / "settings.json").exists())

port = free_port()


class Quiet(http.server.SimpleHTTPRequestHandler):
    """Serves the files without printing a line per request.

    The checks print their own PASS/FAIL lines, and one line per asset fetched
    would bury them. The signature matches the base class so the override stays
    compatible.
    """

    def log_message(self, format, *args):
        pass


handler = lambda *a, **kw: Quiet(*a, directory=str(DIST), **kw)  # noqa: E731
server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.5)

client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15.0)

try:
    root = client.get("/index.html")
    check("index.html serves 200", root.status_code == 200, root.status_code)

    settings = client.get("/settings.json")
    check("settings.json serves 200", settings.status_code == 200, settings.status_code)

    # Every module PyScript loads for the pages.
    modules = list((settings.json().get("files") or {}).keys()) if settings.status_code == 200 else []
    check("settings.json lists modules", len(modules) >= 20, len(modules))
    missing = [m for m in modules if client.get("/" + m.lstrip("./")).status_code != 200]
    check(f"all {len(modules)} modules in settings.json load", not missing, missing)

    pages = sorted((DIST / "src" / "views").glob("*.html"))
    check("every view page was found", len(pages) >= 10, len(pages))

    asset_re = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')
    for page in pages:
        rel = page.relative_to(DIST).as_posix()
        url = "/" + rel
        response = client.get(url)
        if response.status_code != 200:
            check(f"{rel} serves 200", False, response.status_code)
            continue

        body = response.text
        refs = {
            html.unescape(ref)
            for ref in asset_re.findall(body)
            if not ref.startswith(("http://", "https://", "#", "data:", "mailto:"))
        }
        # Resolve each reference the way a browser would, relative to the page.
        broken = []
        for ref in sorted(refs):
            target = urllib.parse.urljoin(url, ref)
            if client.get(target).status_code != 200:
                broken.append(f"{ref} -> {target}")
        check(f"{rel} serves 200 and all {len(refs)} of its assets load", not broken, broken)

    # The pages the top bar and sidebars navigate between must exist too.
    for name in ("login.html", "signup.html", "dashboard.html", "settings.html",
                 "create-project.html", "project-page.html", "project-members.html",
                 "project-roles.html", "project-role-details.html",
                 "sprint-dashboard.html", "sprint-page.html"):
        response = client.get(f"/src/views/{name}")
        check(f"{name} exists in the build", response.status_code == 200, response.status_code)
finally:
    client.close()
    server.shutdown()

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
if failures:
    print("failed: " + "; ".join(failures))
sys.exit(0 if passed == len(results) else 1)
