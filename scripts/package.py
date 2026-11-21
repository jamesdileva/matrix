"""Build the packaged Flood app (S54): npm console → PyInstaller server.

The result is `dist/flood-server/` — a self-contained directory whose
`flood-server.exe` serves the API and the research console from one
process on one port. No Python, npm, or node_modules needed on the
target machine.

    python scripts/package.py           # full build
    python scripts/package.py --skip-console   # reuse an existing dist

Run from the repository root.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # PyInstaller resolves relative bits against the spec dir
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DIST = ROOT / "dist"
PY = str(BACKEND / ".venv" / "Scripts" / "python.exe")


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def build_console() -> None:
    step("building the research console (npm)")
    subprocess.run("npm install --no-fund --no-audit", cwd=FRONTEND, shell=True, check=True)
    subprocess.run("npm run build", cwd=FRONTEND, shell=True, check=True)
    if not (FRONTEND / "dist" / "index.html").exists():
        raise SystemExit("console build produced no dist/index.html")


def bundle() -> None:
    step("bundling the server with PyInstaller")
    subprocess.run(
        [
            PY, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            "--name", "flood-server",
            "--distpath", str(DIST),
            "--workpath", str(ROOT / "build" / "pyinstaller"),
            "--specpath", str(ROOT / "build" / "pyinstaller"),
            "--paths", str(BACKEND),
            "--add-data", f"{FRONTEND / 'dist'};frontend_dist",
            "--collect-all", "uvicorn",
            str(BACKEND / "flood_server.py"),
        ],
        check=True,
    )
    exe = DIST / "flood-server" / "flood-server.exe"
    if not exe.exists():
        raise SystemExit("PyInstaller produced no flood-server.exe")
    print(f"bundle ready: {exe}", flush=True)


def smoke() -> None:
    step("smoke: the bundled server answers, then stops")
    exe = DIST / "flood-server" / "flood-server.exe"
    process = subprocess.Popen([str(exe), "--port", "8021"], cwd=str(DIST / "flood-server"))
    failures = []
    try:
        ok = False
        # 180 s: the first launch of a fresh bundle can sit under
        # Windows Defender's scanner for a long while before it binds.
        for _ in range(180):
            time.sleep(1.0)
            try:
                with urllib.request.urlopen("http://127.0.0.1:8021/api/health", timeout=3) as r:
                    body = json.loads(r.read())
                    print("health:", body["status"], flush=True)
                    ok = body["status"] == "ok"
                    break
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
                continue
        if not ok:
            print("poll failures (last 5):", failures[-5:], flush=True)
            raise SystemExit("bundled server never answered /api/health")
        with urllib.request.urlopen("http://127.0.0.1:8021/", timeout=5) as r:
            page = r.read().decode("utf-8", "replace")
        print("console served:", "FLOOD" in page or "root" in page, flush=True)
    finally:
        process.terminate()
    print("smoke passed", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Package the Flood app.")
    parser.add_argument("--skip-console", action="store_true", help="reuse an existing frontend/dist")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()

    if not args.skip_console:
        build_console()
    bundle()
    if not args.skip_smoke:
        smoke()
    print(f"\nDONE — the app is {DIST / 'flood-server' / 'flood-server.exe'} "
          "(API + research console on one port)", flush=True)


if __name__ == "__main__":
    main()
