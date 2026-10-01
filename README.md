# Flood

Local-first artificial agent lineage & simulation platform — a bounded
"mini-Matrix": AI agents inhabit a deterministic world, form lineages,
inherit knowledge and culture, and can be observed or entered by a human.

## Layout

| Path | What it is |
|---|---|
| `backend/` | Python + FastAPI simulation API. World truth lives here. |
| `frontend/` | React + Vite + TS research console (dashboards, lineage, replay). |
| `world-client/` | Godot 4 3D world client (observer/participant cameras). Renders; never owns world truth. |
| `architecture.md` | Baseline architecture. |
| `implementation-guide.md` | Layer-by-layer build guide. |
| `sprint-roadmap.md` | Sprints S01–S50+ with verification checklists. |
| `quick-reference.md` | Everyday commands (backend, console, Godot, DB, git). |
| `worklog.md` | Per-sprint log: plan → scope → implement → verify → commit+push. |

## Quickstart

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
.venv/Scripts/pytest -q
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Web console (Node 18+):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 — /api is proxied to :8000
```

World client (Godot 4.x):

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000   # terminal 1
tools/godot.cmd --path world-client                                      # terminal 2 — jump in
```

The client creates a live world on connect (seed via `FLOOD_SEED`), renders
it in 3D, and streams agent positions at 5 Hz. Headless checks:

```bash
tools/godot.cmd --headless --path world-client --script res://tests/smoke.gd
FLOOD_SMOKE=1 tools/godot.cmd --headless --path world-client   # E2E vs live backend
```

`tools/godot.cmd` resolves the engine: `GODOT_EXE` env var → `godot` on
PATH → newest winget install. If `godot` is already on your PATH, the usual
`godot --path world-client` (from repo root) or `godot --path .` (from
inside `world-client/`) works identically.

## Rules of the road

- The simulation engine is deterministic; agents are probabilistic.
- The world owns truth. Models and clients propose actions; the engine validates them.
- Every sprint ends runnable, tested, committed, and logged in `worklog.md`.
