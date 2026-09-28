# Flood: Worklog

Working log for the Flood project: what was built, when, and why.

Roadmap: `sprint-roadmap.md` · Architecture: `architecture.md` · Implementation guide: `implementation-guide.md` · Commands: `quick-reference.md`

## Workflow

Every sprint runs the same loop:

1. **Plan** — write the sprint goal here before building.
2. **Scope** — what is in, what is explicitly out.
3. **Implement** — build it.
4. **Verify** — tests pass; the sprint's verification checklist from the roadmap is checked off.
5. **Commit + push** — commit at sprint end, push to the remote.
6. **Update this worklog** — append the sprint entry.

Every sprint must end with a runnable system.

## Entry template

```markdown
## SXX — Name (YYYY-MM-DD)

### Plan
One paragraph: why this sprint exists.

### Scope
In: ...
Out: ...

### Implementation
What was actually built. Brief; details live in code and tests.

### Verification
- Tests: ...
- Roadmap checklist: ...

### Commits
- `hash` — summary
```

## Key Decisions

### D001 — Godot 4 replaces PixiJS as the world client (2026-09-28)

The architecture doc originally prescribed React with Canvas/PixiJS 2D world
rendering. Decision: the world client is **Godot 4 in 3D**, because the goal
is to "jump into the Matrix" — free-fly camera, agent follow-cam, and
eventually first-person participant mode among agents at work. Aesthetic
target is deliberately blocky (dark world, green-tinted grid, glowing
agents), not realism.

Constraints that keep this compatible with the rest of the architecture:

- World truth stays in the Python simulation engine. Godot only renders
  state and proposes actions over the Simulation API.
- React survives as the later research console (dashboard, lineage
  explorer, replay timeline, experiments).
- New sprint **S06B — 3D World Client (Godot)** inserted after S06
  (Scripted Agent), so the world is inhabited the first time you enter it.
  No existing sprint numbers changed.

Context: Flood is the successor in spirit to `../worldsim` (settlement-level
civilization simulator, deterministic seeded worlds, RL + Ollama advisors).
Worldsim proved the serve-a-live-world-over-FastAPI pattern (its S52/S53)
but is visually a flat 2D top-down tile map with settlement markers —
explicitly the graphical direction Flood is avoiding. Worldsim's "agents"
are settlement controllers, not embodied individuals, so it cannot deliver
the 3D jump-in experience without a redesign; Flood's individual-agent
domain model can.

## Status

- **Next sprint:** S04 — Actions & Rules
- Completed sprints: S01, S02, S03 (2026-09-28)
- Full roadmap: `sprint-roadmap.md`

## Sprint Log

## S01 — Repository & Development Baseline (2026-09-28)

### Plan
Create the project skeleton and local development workflow: a runnable
FastAPI backend, a runnable web console that talks to it, an openable Godot
4 world-client project, and the surrounding hygiene (README, env config,
gitignore, tests). This is the empty box every later sprint builds inside.

### Scope
In: backend skeleton (FastAPI, `/api/health`, pytest suite); Vite + React +
TS console that displays backend health; Godot 4 project with an empty main
scene; `.env.example` + `.gitignore`; README; architecture repo structure
updated for `world-client/`. GitHub remote `jamesdileva/matrix` (public).
Out: database (S02), world engine (S03), any UI beyond the health check,
Godot connection/rendering (S06B), CI.

### Implementation
- `backend/`: FastAPI app (`app/main.py`, CORS + `/api/health` in
  `app/api/health.py`), pydantic-settings config (`app/config/settings.py`,
  `FLOOD_` env prefix), pytest suite (`tests/test_health.py`, 2 tests),
  `pytest.ini`, `requirements.txt`. Env at `backend/.venv` (gitignored).
  Python 3.14.3, FastAPI 0.141, SQLAlchemy 2.1 (installed, unused until S02).
- `frontend/`: Vite 5 + React 18 + TS. `src/App.tsx` fetches `/api/health`
  and shows backend status (dark console, green accents). Dev proxy
  `/api` → `127.0.0.1:8000` (`vite.config.ts`). `npm run build` =
  `tsc --noEmit` + `vite build`.
- `world-client/`: Godot 4 project (`project.godot`, main scene set) with
  empty `scenes/main.tscn` (root `Node` "Main").
- Root: `README.md` (layout + quickstart), `.env.example`, `.gitignore`.
  `architecture.md` §5 repo structure updated: `world-client/` added,
  `frontend/world/` (canvas-era) removed.
- Remote: public repo `jamesdileva/matrix` created with gh; `main` tracks
  `origin/main`; baseline docs commit pushed before this sprint's commit.

### Verification
- Tests: `pytest -q` — **2 passed**. (One benign deprecation warning:
  starlette suggests httpx2 for TestClient; revisit when it matters.)
- Backend starts: uvicorn booted clean; `GET /api/health` → 200
  `{"status":"ok","service":"flood-backend","version":"0.1.0",...}`.
- Frontend starts: vite dev ready on :5173; page serves HTTP 200.
- Frontend can call backend: `GET localhost:5173/api/health` through the
  dev proxy returned the backend health JSON.
- Frontend builds: `tsc --noEmit && vite build` clean (143 KB js bundle).
- Godot: project imports and loads cleanly — `tools/godot.cmd --headless
  --path world-client --import` and `... --quit` both exit 0 on Godot
  4.7.2-stable (winget install, same engine as the user's surfhop project).
  Roadmap checklist fully green. `tools/godot.cmd` locator wrapper added
  (surfhop pattern: `GODOT_EXE` → `godot` on PATH → newest winget exe).
- No secrets: only `.env.example` (placeholders) is tracked; `.env`,
  `.venv/`, `node_modules/`, `dist/`, `.godot/` gitignored; confirmed via
  `git status` review before commit.

### Commits
- `1c385f0` — Initial commit: baseline docs + worklog (D001) [pushed]
- `9f46712` — S01: repository baseline — backend, web console, Godot client skeleton [pushed]
- `951c82a` — S01 addendum: Godot headless check passes; add tools/godot.cmd locator [pushed]
- `090b18e` — S02: database & persistence — SQLAlchemy models, Alembic migrations, isolated-db tests [pushed]

## S02 — Database & Persistence (2026-09-28)

### Plan
Give Flood durable state. Introduce SQLite + SQLAlchemy with the five
roadmap tables (World, Population, Agent, Event, Experiment), Alembic
migrations wired to app settings, and isolated per-test databases. This is
the layer every later sprint reads and writes through — schema decisions
here (IDs, JSON payloads, lineage fields) should follow architecture §6
closely so the engine sprints don't need rework.

### Scope
In: SQLAlchemy 2.0 models for worlds, populations, agents (with
parent_id/generation lineage fields), events, experiments; engine/session
factory; Alembic environment + initial autogenerated migration; pytest
fixtures on tmp_path SQLite files; a dispose/reopen test proving events
survive a process restart; `quick-reference.md` (repo-level command doc).
Out: repositories/service layer (arrives with the world engine), the other
implementation-guide tables (WorldObject, Message, WorldSnapshot,
AgentRelationship — later sprints), Postgres, API endpoints touching the
database, test-directory taxonomy (flat `tests/` until the suite grows).

### Implementation
- `backend/app/persistence/`: SQLAlchemy 2.0 typed models (`models.py`) —
  `worlds`, `populations`, `agents`, `events`, `experiments` — fields
  follow architecture §6. Agents carry lineage fields now (self-FK
  `parent_id`, `generation`); events are indexed on `(world_id, tick)`;
  `populations.root_agent_id` is a plain int (FK would make
  populations/agents circularly dependent — enforced in app logic at S09).
  JSON columns where shapes are still fluid (location, budgets, rules,
  memory, payload).
- `database.py`: `Base`, `make_engine` (SQLite `check_same_thread=False`),
  global engine/`SessionLocal`, `get_db` FastAPI dependency.
- Settings: `database_url` (default `sqlite:///./flood.db`,
  `FLOOD_DATABASE_URL` override).
- Alembic: `alembic.ini` + `env.py` wired to app settings (`compare_type`,
  `render_as_batch` for SQLite); initial migration
  `411e0de3bc57_initial_tables` autogenerated — all five tables plus
  `ix_events_world_tick`.
- Tests: `conftest.py` with per-test `tmp_path` SQLite fixtures; 9 new
  tests across world/agents/events/experiments, including a
  dispose-and-reopen restart-persistence test.
- Root: `quick-reference.md` created (living command doc; linked from
  README, worklog, architecture §5). `.gitignore` covers `*.db`.

### Verification
- Tests: pytest **11 passed** (2 API + 9 persistence). One fix during the
  run: child-as-`parent_id=parent.id` before flush writes NULL — test now
  flushes the parent first, mirroring the real engine's ordering.
- DB initializes from empty state: fresh tmp DB per test; alembic works on
  a nonexistent database file.
- World insert/retrieve ✅ · Agent insert/retrieve ✅ · Parent ID stored ✅
  (self-FK round-trips; `parent`/`children` relationships resolve).
- Events persist after process restart: engine disposed, file reopened,
  world + event intact ✅.
- Tests use isolated databases: every test gets its own `tmp_path` SQLite
  file; nothing touches the dev database ✅.
- Migrations: `alembic upgrade head` on a fresh DB creates all 5 tables +
  index; `downgrade base` drops cleanly; `upgrade head` again →
  `411e0de3bc57 (head)` ✅.
- Roadmap S02 checklist: fully green.

### Commits
- `090b18e` — S02: database & persistence — SQLAlchemy models, Alembic migrations, isolated-db tests [pushed]

## S03 — Deterministic World Engine (2026-09-28)

### Plan
Create the first Void: a pure, in-memory, deterministic grid world. Same
seed produces the same world; a tick counter advances; terrain comes in
floor/wall/water with seeded generation; basic objects sit on cells under
strict position validation; the full state serializes and restores exactly.
The engine owns truth and stays free of DB/API concerns — persistence of
live worlds arrives with the API/experiment layers, keeping the engine
pure and trivially testable.

### Scope
In: `app/simulation` package — `Position`, `Terrain`, `WorldObject`,
`World` — with a seeded generator (border walls, interior scatter),
`place_object` validation, tick stepping, `to_dict`/`from_dict` round
trip, an ASCII `render` for debugging, and a `python -m app.simulation`
demo CLI. Full tests for every roadmap checklist item.
Out: actions/movement (S04), event bus (S05), agents (S06), database
integration for live worlds (comes with the API/experiment layers),
physics beyond one-object-per-cell occupancy.

### Implementation
- `backend/app/simulation/` — pure engine, no DB/API imports:
  - `world.py`: `Position` (frozen, hashable), `Terrain` (floor/wall/water
    with display chars), `WorldObject` (id, type, position, created_tick,
    properties, created_by_agent_id), `World` (grid, tick, seeded
    `generate()`, validated `place_object()`, `step()`, `to_dict`/
    `from_dict`, ASCII `render()`).
  - `errors.py`: `SimulationError` → `InvalidPositionError` /
    `CellOccupiedError`. The world rejects; it never half-applies.
  - `__main__.py`: demo CLI — `python -m app.simulation --seed matrix`.
- Generator: border ring of walls (containment, natural fit for escape
  scenarios later), interior scatter of water/wall/floor via
  `random.Random(seed)`, then row-major object scatter (trees/stones/food).
- Determinism discipline documented in the module: string seeds hash via
  sha512 (stable), all order-sensitive iteration is row-major or sorted —
  nothing depends on set/dict ordering.
- `quick-reference.md`: new "World engine" section.

### Verification
- Tests: pytest **25 passed** (11 prior + 14 world-engine).
- Same seed creates same world: `to_dict()` equality test, plus demo runs
  of `--seed matrix` producing byte-identical md5 output across runs;
  different seed differs ✅.
- Tick advances correctly: 0 → step() → 1 → 2 ✅.
- Objects have valid positions: every generated object is in-bounds floor,
  `object_at()` resolves, ids unique and sequential ✅.
- Invalid positions rejected: out-of-bounds, wall/water terrain, occupied
  cell, non-integer and bool coordinates all raise ✅.
- World state serializes: full `to_dict`/`from_dict` round-trip equality
  (including tick, custom properties, agent attribution), JSON-safe, and
  restored worlds continue the object-id sequence ✅.
- Roadmap S03 checklist: fully green.

### Commits
- `b9672c4` — S03: deterministic world engine — seeded grid, terrain, objects, tick, serialization [pushed]
