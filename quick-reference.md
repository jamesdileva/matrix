# Flood: Quick Reference

Everyday commands. Commands are written from the **repo root** and work in
Git Bash and cmd (forward slashes). Keep this doc current: whenever a
command becomes part of the routine, add it here in the same sprint.

## Backend

```bash
# First-time setup
cd backend && python -m venv .venv
backend/.venv/Scripts/pip install -r backend/requirements.txt

# Tests (full suite)
backend/.venv/Scripts/python -m pytest backend/tests -q          # from repo root
cd backend && .venv/Scripts/python -m pytest -q                  # from backend/

# Dev server
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
#   health check: curl http://127.0.0.1:8000/api/health
```

## Web console

```bash
cd frontend && npm install          # first time / after deps change
cd frontend && npm run dev          # http://localhost:5173 — /api proxied to :8000
cd frontend && npm run build        # typecheck + production build
```

## Godot world client

```bash
tools/godot.cmd -e --path world-client      # open editor
tools/godot.cmd --path world-client         # run the client (needs backend on :8000)
tools/godot.cmd --headless --path world-client --quit   # headless load check

# client headless tests (no backend needed)
tools/godot.cmd --headless --path world-client --script res://tests/smoke.gd

# full E2E smoke (needs backend running)
FLOOD_SMOKE=1 tools/godot.cmd --headless --path world-client
```

Environment: `FLOOD_API` (backend URL, default `http://127.0.0.1:8000`),
`FLOOD_SEED` (world seed, default `matrix`), `FLOOD_SMOKE=1` (self-test).
Controls: LMB agent = follow, LMB empty/Esc = release, hold RMB = look,
WASD/QE = move, wheel = speed. (In Git Bash, prefix godot.cmd calls with
`MSYS_NO_PATHCONV=1` when args contain `res://`.)

`tools/godot.cmd` resolves the engine: `GODOT_EXE` env var -> `godot` on PATH
-> newest winget install. If `godot` resolves in your shell, plain
`godot --path world-client` is identical.

## World engine (S03+)

```bash
cd backend
.venv/Scripts/python -m app.simulation --seed matrix --width 32 --height 32  # print the Void
.venv/Scripts/python -m app.simulation --seed matrix --agents 3 --ticks 40   # + scripted agents living in it
.venv/Scripts/python -m pytest tests/test_simulation_world.py -q             # engine tests
```

The engine (`app/simulation/`) is pure Python — no DB, no API. Same seed
always produces the same world, the same agents, the same history.

## Simulation API (S06B+)

```bash
# backend must be running (see Backend section)
curl -s -X POST localhost:8000/api/worlds -H "Content-Type: application/json" \
     -d '{"seed": "matrix", "agents": 3}'          # create live world
curl -s localhost:8000/api/worlds/1                # state snapshot
curl -s "localhost:8000/api/worlds/1/events?since_id=0&limit=50"
curl -s -X POST localhost:8000/api/worlds/1/step   # advance one tick
curl -s -X POST localhost:8000/api/worlds/1/pause  # /resume · DELETE removes
```

## Database (S02+)

```bash
cd backend
.venv/Scripts/alembic upgrade head                        # apply migrations (creates flood.db)
.venv/Scripts/alembic revision --autogenerate -m "msg"    # new migration from model changes
.venv/Scripts/alembic downgrade base                      # drop everything (destructive!)
.venv/Scripts/alembic current                             # show applied revision
```

Dev database: `backend/flood.db` (SQLite, gitignored). Tests use throwaway
SQLite files in pytest `tmp_path` — never the dev database.

## Git / GitHub

```bash
git status --short && git add -A && git commit -m "..." && git push
```

Remote: `jamesdileva/matrix` (public), branch `main`.

## Sprint loop

Every sprint: **plan → scope → implement → verify (tests) → commit + push →
update `worklog.md`**. Every sprint ends runnable. See `worklog.md`.
