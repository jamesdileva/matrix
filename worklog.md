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

- **Next sprint:** S23 — Prison Sandbox
- Completed sprints: S01–S22, S06B (S22 done 2026-10-08)
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
- `6f6cffc` — worklog: record S03 commit hash [pushed]

## S04 — Actions & Rules (2026-09-28)

### Plan
Give entities a rules engine. The world accepts action proposals (move,
look, inspect, pick_up, drop, place) as plain dicts, validates every one,
mutates state only when legal, and records exactly one event per attempt —
executed or rejected. This is the contract every mind will use from S08
onward: the model proposes, the world decides. The LLM never mutates world
state directly.

### Scope
In: entity registry + per-entity inventories on `World`;
`execute_action(actor_id, action)` dispatcher with the six roadmap
actions; `ActionResult` / `ActionEvent` with rejection reasons; event-per-
attempt semantics; serialization of entities/inventory/events; tests for
every roadmap checklist item. Out: event bus, persistence, query/filtering
(S05), Agent lifecycle and bounded observation (S06), use/build/destroy/
speak/trade actions (later sprints), diagonal movement, pathfinding.

### Implementation
- `backend/app/simulation/actions.py` — the proposal contract:
  `execute_action(world, actor_id, action)` dispatches plain-dict actions
  (`{"action": "move", "direction": "north"}`) to six handlers
  (move/look/inspect/pick_up/drop/place). Rule violations raise an
  internal `_Rejected(reason)` that becomes an `ActionResult(ok=False)`
  plus an `ACTION_REJECTED` event; successes become `ACTION_EXECUTED`.
  `ActionResult.data` carries look/inspect results and move targets.
- `world.py` additions: entity registry (`add_entity`, `remove_entity`,
  `entity_position`), per-entity inventories, the event log with
  sequential ids (`world.events`, `_record`), and `execute_action` on
  `World` (late import — the two modules reference each other only at
  call time). Serialization extended: entities, inventory, events,
  `next_event_id` all round-trip; `WorldObject.position` is now nullable
  (None while carried).
- Rules encoded this sprint: 4-directional movement; walls and water both
  block; cells holding objects block entry; an entity may share its own
  cell with at most one dropped object; pick_up/inspect reach is the
  actor's cell plus orthogonal neighbours (Manhattan ≤ 1); drop targets
  the actor's cell, place targets an adjacent cell; unknown actions and
  unknown actors are rejected — always with an event, never with a
  mutation.

### Verification
- Tests: pytest **45 passed** (20 new action/rules tests).
- Valid move succeeds ✅ · wall collision fails ✅ (and water, out-of-
  bounds, entities, objects all block with distinct reasons).
- Pick-up works ✅ (ground → inventory, cell freed, carried object
  serializes with null position) · drop works ✅ (inventory → ground,
  at the actor's cell or — via place — an adjacent one).
- Invalid actions do not mutate state ✅: nine malformed/illegal
  proposals (unknown action, missing/bad direction, unknown/non-int
  object ids, non-dict payloads) all rejected; world state byte-identical
  before/after.
- Every action creates an event ✅: exactly one event per attempt,
  `ACTION_EXECUTED`/`ACTION_REJECTED` types correct, ids strictly
  sequential; the event log itself round-trips through serialization and
  restored worlds keep accepting actions.
- Bugs caught and fixed mid-sprint: `from_dict` referenced `ActionEvent`
  with a TYPE_CHECKING-only import (NameError at runtime — caught by the
  round-trip test); `_register` rejected carried objects during restore
  (None positions); plus two test-logic errors of my own (assumed border
  walls on a plain constructed world; stale position in an event-
  sequence assertion). Engine and tests both end the sprint honest.
- Roadmap S04 checklist: fully green.

### Commits
- `0837ea9` — S04: actions & rules — validated action proposals, events per attempt [pushed]
- `1c468fd` — worklog: record S04 commit hash [pushed]

## S05 — Event Bus & Timeline (2026-09-28)

### Plan
Make everything observable. Generalize S04's action log into the platform
event model (id, tick, type, actor, target, payload — deliberately no
wall-clock timestamp inside the engine, since timestamps are metadata the
persistence layer owns and the engine must stay deterministic). Add an
EventBus so outer layers can subscribe — the database recorder today, the
API/WebSocket stream later — persist events to the `events` table, provide
recent-event queries with type/actor/since filtering, and prove the whole
chain with the roadmap's verification: a scripted sequence whose every
event lands in the database, in order, surviving a restart.

### Scope
In: `simulation/events.py` (Event + EventTypes vocabulary),
`simulation/bus.py` (EventBus), world emitting OBJECT_CREATED /
ENTITY_ADDED / ENTITY_REMOVED alongside action events, bus wiring through
`World(generate(..., event_bus=...))`, `DatabaseEventRecorder` +
`EventRepository` (recent/type/actor/since_id queries), `sequence` column
migration for the events table, scripted-sequence + restart + filter
tests. Out: WebSocket/streaming API (S13+), replay/time machine (S37),
event retention policy (S12), MESSAGE_SENT/DISCOVERY_MADE/etc. types
(they arrive with the features that produce them), wall-clock timestamps
inside the engine (determinism).

### Implementation
- `simulation/events.py` — the platform event model: `Event` (id, tick,
  type, actor_id, target_id, payload) + `EventTypes` vocabulary. No
  wall-clock inside the engine: timestamps are persistence metadata, and
  same-seed worlds produce identical event logs (asserted by test).
- `simulation/bus.py` — synchronous `EventBus`; subscribers run in
  subscription order; the bus never influences state, so determinism is
  untouched. `World` accepts an `event_bus` (constructor and `generate`).
- World now emits the full core vocabulary: `WORLD_SEEDED` (first event,
  from `generate`), `OBJECT_CREATED` (every `place_object`, with actor and
  target), `ENTITY_ADDED`/`ENTITY_REMOVED`, plus the existing
  `ACTION_EXECUTED`/`ACTION_REJECTED` (action + result folded into
  payload). Restore-from-dict registers entities without re-emitting.
- Refactor: S04's `ActionEvent` → the general `Event` (action details now
  live in payload); persistence models renamed `WorldModel`/
  `PopulationModel`/`AgentModel`/`EventModel`/`ExperimentModel` to end the
  domain-vs-database name collision.
- `persistence/repositories.py` — `DatabaseEventRecorder` (bus subscriber
  writing each event in a short session) and `EventRepository.recent()`
  with type/actor/since_id filters applied *before* the limit (the last N
  of a kind, not N rows that happen to match) and `count()`.
- Migration `4e0df830e730`: `events.sequence` column preserving the
  engine's per-world timeline id alongside the global row id (replay will
  need it at S37).

### Verification
- Tests: pytest **57 passed** (12 new: 7 bus/model, 5 persistence).
- Roadmap verification — scripted sequence (look, four moves with a wall
  rejection, pick-up, double pick-up rejection, unknown action, drop):
  every expected event lands in the `events` table **in order**, with
  correct actor ids, engine `sequence` ids matching the in-memory log,
  wall-clock timestamps present, and the rejection payloads carrying
  reasons — all verified after disposing the engine and reopening storage
  (simulated restart) ✅.
- Bus: delivers to all subscribers in subscription order, matching the
  world's own log; multi-world recorders stay isolated to their world ✅.
- Queries: tail-limit returns the newest N ascending; type/actor filters
  work (actor filter includes the actor's ENTITY_ADDED); since_id returns
  strictly later rows ✅.
- Determinism guard: same seed → identical event logs ✅.
- Test-only fixes this sprint: my hardcoded coordinates kept losing to
  seeded terrain (two tests now use plain all-floor worlds, one scans for
  a free cell), and two tests dropped the `event_bus=` wiring or predated
  entity events — each caught by a red suite, none by eyeball.
- Roadmap S05 checklist: fully green.

### Commits
- `45e8810` — S05: event bus & timeline — event model, bus, persistence, filtered queries [pushed]
- `7b85cdc` — worklog: record S05 commit hash [pushed]

## S06 — Scripted Agent (2026-09-28)

### Plan
Put the first inhabitant in the Void. An Agent is a thin actor over the
action contract: it spawns into the world, observes a bounded
neighbourhood, and a pluggable policy turns observation into a decision
executed through `world.execute_action`. Policies are scripted this
sprint — no model calls — but the seam they define is exactly where S07/S08
plug in intelligence: same observe-decide-act lifecycle, same decision
dict shape as the future LLM contract. An Engine owns the tick loop:
world advances, then each agent (ascending id, deterministic) acts.

### Scope
In: `Agent` (spawn / observe / act, goal updates, status lifecycle),
`Policy` protocol, three scripted policies (AlwaysMoveNorth, Wander,
Forager), `Engine` (step/run with deterministic ordering), the bounded
observation shape from implementation guide §6 (self, movement cells,
nearby by radius, inventory, messages placeholder), entity overlay in
`render()`, `--agents/--ticks` flags on the demo CLI, and tests for every
roadmap checklist item plus determinism and a 300-tick survival run.
Out: model provider (S07), LLM agent (S08), memory/cognition internals,
reproduction and lineage (S09+), agent-state persistence (experiments
layer), a cognition scheduler (every agent acts every tick for now),
RandomAgent and the other §30 test agents (S30).

### Implementation
- `simulation/agent.py` — `Agent`: spawn (via `world.add_entity`), status
  lifecycle (created -> alive), goal tracking, and the three lifecycle
  phases. `observe()` returns the bounded view from guide §6 — `self`
  (id/position/tick/goal), `cells` (here + 4 directions with terrain,
  object, entity — the movement senses), `nearby` (objects/entities
  within a configurable radius, sorted by distance then id), `inventory`,
  and a `messages` placeholder. Observation is sensing, not acting: no
  events, no cost. `act()` runs observe -> policy.decide -> execute via
  the action contract; malformed decisions come back as rejections and
  the agent survives. `Policy` is a Protocol whose decision dict shape
  (`{"action": ..., "goal_update": ...}`) mirrors the future LLM
  contract (guide §7) — S08 swaps minds, not plumbing.
- `simulation/policies.py` — three scripted, pure, deterministic
  policies: `AlwaysMoveNorthPolicy` (trivial), `WanderPolicy` (first
  legal direction of a fixed order, looks when stuck), `ForagerPolicy`
  (pick up what's in reach, step greedily toward the nearest visible
  object, wander otherwise).
- `simulation/engine.py` — `Engine`: owns a world plus agents, `step()`
  advances the world then lets every agent act in ascending id order;
  `run(ticks)` loops. Determinism contract documented: same seed + same
  script -> identical histories (test-proven).
- `world.py`: public read accessors `entity_at` / `entity_positions`;
  `render()` overlays entities as `@`.
- Demo CLI grew `--agents N --ticks T`: spawns wanderers on the first
  free floor cells and animates them, printing final positions and
  executed/rejected event counts.

### Verification
- Tests: pytest **68 passed** (11 new).
- Roadmap checklist: agent spawns ✅ (status, position, ENTITY_ADDED
  naming the agent) · moves ✅ (policy-driven, event tick correct) ·
  observes ✅ (bounded nearby with radius filtering — an object at
  distance 4 is invisible at radius 2 — cells report terrain, inventory
  empty, messages placeholder) · interacts with an object ✅ (forager
  picks up adjacent food; also walks two cells toward visible food then
  grabs it) · events identify the correct agent ✅ (two agents, one
  step, actors partition exactly; each agent's position reflects only
  its own policy).
- Determinism: two engines, same seed and script, 25 ticks with mixed
  policies -> identical `to_dict()` ✅.
- Survival: two agents (wander + forager) run 300 ticks on a generated
  world — alive, on valid cells, every event attributed to a known actor
  ✅ (guide §9's "several hundred ticks").
- Resilience: a policy that emits garbage gets `invalid_action`
  rejections; the agent stays alive and unmoved ✅.
- Live demo: `--seed matrix --agents 3 --ticks 40` -> 120 executed
  actions, 0 rejected, agents visible as `@@@` in the ASCII render.
- Test-authoring notes: direction order follows the DIRECTIONS dict
  (here/north/south/east/west) — one expectation fixed; observation
  radius is real (a distance-3 food item is invisible at radius 2) —
  one scenario corrected. Red suite caught both, as designed.
- Roadmap S06 checklist: fully green.

### Commits
- `c11fbcf` — S06: scripted agent — Agent, policies, Engine, bounded observation [pushed]
- `e65c463` — worklog: record S06 commit hash [pushed]

## S06B — 3D World Client (2026-09-28)

### Plan
The jump-in moment. Two halves: first the backend grows a real Simulation
API — create a world, step it, watch its state and events — binding the
pure engine to a database row with event persistence end to end, and
running worlds on an asyncio tick loop (the client should watch a live
world, not drive it). Then the Godot 4 client connects over REST, builds
the Void in 3D (instanced walls/water, emissive agents with name labels,
Matrix-dark baseline per D001), interpolates agent movement between
snapshots at 5 Hz, and offers a free-fly camera plus click-to-follow.
The client renders and watches; world truth stays server-side.

### Scope
In: `World.snapshot()`, `WorldHost` (asyncio loop with pause/resume/
step/max-ticks), `WorldRegistry` (DB row + engine + recorder + host per
world, lifespan-managed), Simulation API (POST/GET/DELETE worlds, state,
step, pause/resume, events since_id), full pytest coverage with an
isolated-app fixture including the engine→bus→DB chain; Godot client
(`api.gd` REST, `world_view.gd` instanced rendering + interpolation +
screen-space agent picking, `free_cam.gd` fly/follow camera, `main.gd`
orchestration + event log UI + Matrix-dark environment), a headless
fixture smoke test, and a true E2E smoke: live uvicorn + headless client
connects, renders real state, quits clean.
Out: WebSocket push (REST polling at 5 Hz for now; push lands with the
S13 dashboard where it pays off), participant avatar and movement (S20),
agent inspector panel (S14), materials/shader polish beyond the baseline,
client-side prediction (interpolation only), world persistence/reconnect
(S38), CORS-independent deployment concerns.

### Implementation
- Backend — the Simulation API is real now:
  - `app/host.py`: `WorldHost` (asyncio tick loop with pause/resume,
    manual step, `max_ticks` bounded runs for tests — the bound counts
    loop *iterations* so a paused host still terminates) and
    `WorldRegistry` (per world: DB row + generated world + scripted
    agents alternating wander/forager + `DatabaseEventRecorder` on the
    bus + host; lifespan-managed, stopped on shutdown).
  - `app/api/worlds.py`: POST `/worlds` (create; async — autostart needs
    the event loop), GET `/worlds` + `/{id}` (state snapshot incl.
    paused/agent_count), POST `/{id}/step|pause|resume`, GET
    `/{id}/events?since_id&limit`, DELETE `/{id}`. Truth stays in the
    engine; routes only orchestrate.
  - `World.snapshot()`: render-ready state (terrain rows, ground objects,
    entity positions) with no events or bookkeeping.
- Godot client (`world-client/`), all nodes built in code:
  - `scripts/api.gd`: REST client over short-lived HTTPRequest nodes
    (state + events polls can be in flight together), JSON-safe error
    handling, `FLOOD_API` override.
  - `scripts/world_view.gd`: one-shot instanced terrain (walls as green-
    edged boxes, translucent water), object meshes per type, agents as
    emissive capsules with billboard `Label3D` names; per-snapshot
    rebuild of objects, create/move/remove of agents with positional
    interpolation toward snapshot targets; screen-space agent picking
    (no physics on the client).
  - `scripts/free_cam.gd`: fly camera (WASD/QE, RMB-drag look, wheel
    speed) with follow mode (camera orbits the picked agent, Esc/LMB
    releases).
  - `scripts/main.gd`: connection state machine (create world → poll
    state at 5 Hz + events since_id), Matrix-dark environment (fog,
    ambient green, clear color), event-log HUD, first-frame camera
    framing, `FLOOD_SMOKE` self-test mode (connect → first live snapshot
    with agents → print + quit, 25 s timeout).
  - `tests/smoke.gd`: headless SceneTree test — compiles all scripts,
    builds terrain/objects/agents from a canned snapshot, applies a
    second snapshot (move/despawn/spawn/pickup), drives interpolation to
    completion, asserts the scene graph.

### Verification
- Backend: pytest **79 passed** (11 new API/host tests, isolated app per
  test). New regression test for the autostart path — an autostarted
  world ticks on its own (asyncio loop) and DELETE stops it cleanly.
- Godot headless: `--import` clean; `tests/smoke.gd` → **SMOKE OK**
  (terrain instance counts, agent create/move/remove, pickup rebuild,
  interpolation reaches snapshot target). First run failed with the lerp
  only 16% complete after one frame — correct client behavior, wrong
  test expectation; the test now drives a full-weight frame.
- E2E: live uvicorn + headless client (`FLOOD_SMOKE=1 FLOOD_SEED=e2e`) →
  **FLOOD_SMOKE OK world=15 tick=2 agents=3**: the client created a real
  world over HTTP, rendered its live snapshot, quit clean. Live API then
  showed tick 71, 3 agents, 33 objects, and 100+ persisted ACTION
  events — engine → bus → recorder → database → API, end to end.
- Bug the E2E caught (tests couldn't): `create_world` was a sync route,
  so FastAPI ran it in a worker thread and `asyncio.create_task` died
  with "no running event loop" — 500 to the client. All pytest worlds
  used autostart=False, which skips that path. Route is now async and
  the autostart path has test coverage.
- Roadmap S06B checklist: connects and renders real state ✅ (E2E);
  free-fly camera + follow-cam implemented, interactive feel is yours to
  confirm when you open it ✅; world truth server-side ✅ (client only
  creates and polls — it never mutates state).
- Roadmap S06B checklist: fully green.

### Commits
- `6c94755` — S06B: 3D world client — Simulation API, Godot client, E2E smoke [pushed]

## S07 — Model Provider Abstraction (2026-10-08)

### Plan
Connect intelligence without coupling the simulation to one provider.
The world engine is done and inhabited by scripted minds; before an LLM
ever enters the Void, the seam it plugs into must exist, be safe, and be
provable offline. This sprint builds that seam: the provider interface,
the structured decision contract between a brain and the world, an
offline mock, one HTTP provider for real models, and the configuration
recorded with every experiment — so S08 can swap a brain in without
touching the engine.

### Scope
In: `app/models/` package — `ModelProvider` protocol (`async generate`,
guide §8) with `ModelRequest`/`ModelResponse` and one uniform
`ProviderError`; `Decision` schema + `parse_decision` (structure only —
the world stays the authority on rules); `MockProvider` (deterministic,
no network); `OpenAICompatibleProvider` (chat-completions over httpx,
configurable `base_url`, covers OpenAI-style APIs and Ollama alike,
transport injectable for tests); provider factory + `model_configuration`
from settings; `ModelPolicy` bridge (async refresh / sync decide with a
safe `look` fallback); `FLOOD_MODEL_*` settings;
`ExperimentRepository.create` stamping the model configuration onto
experiment rows. Tests for all of it, including the roadmap's four
verification items.
Out: the live decision loop / cognition scheduler wiring into the tick
(S08), agent short memory, real model calls from a running world, the
Google/Anthropic-native SDKs (the OpenAI-compatible shape is the
common denominator; native providers arrive when a model actually needs
one).

### Implementation
- `backend/app/models/` — the abstraction, dependency-free (imports
  nothing from the engine or the database):
  - `provider.py`: protocol + request/response dataclasses +
    `ProviderError`. Async by design; every failure mode is one
    exception so callers can treat "the brain said nothing" uniformly.
  - `decision.py`: `Decision` + `parse_decision`. Extracts JSON from
    raw model text (strips markdown fences and surrounding prose),
    validates structure, normalizes guide §7's `{"type": ...}` verb
    spelling to the engine's `{"action": ...}` contract, drops
    wrongly-typed optional annotation fields, ignores unknown keys.
    Structural rejection only — unknown verbs and illegal moves are
    the world's job (rejected actions with recorded events).
  - `mock.py`: `MockProvider` — forager-style heuristic, deterministic,
    emits engine-contract JSON. Runs the full provider → parser →
    decision path with zero I/O.
  - `openai_compat.py`: `OpenAICompatibleProvider` — POSTs
    chat-completions with the observation as the user message and a
    default system prompt describing the decision contract. Network,
    HTTP, timeout and malformed-body failures all become
    `ProviderError`.
  - `config.py`: `provider_from_settings` (the single place provider
    choice is interpreted) and `model_configuration` — the effective,
    JSON-safe, credential-free record stamped onto experiments.
- `backend/app/simulation/model_policy.py` — `ModelPolicy`: the
  sync/async bridge. `refresh` (awaited by the loop owner — the S08
  host; tests today) stores the provider's validated decision;
  `decide` returns it, or the safe `look` fallback when nothing valid
  is stored. A broken brain can cost a rejected or idle action, never
  world state. The one stateful policy — transport, not memory;
  determinism holds iff the provider is deterministic (hence replay
  records decisions, guide §"replay").
- Settings: `FLOOD_MODEL_PROVIDER` (`mock` default — the simulation
  runs with no LLM, guide §8), `FLOOD_MODEL_NAME`, `FLOOD_MODEL_BASE_URL`,
  `FLOOD_MODEL_API_KEY`, `FLOOD_MODEL_TEMPERATURE`, `FLOOD_MODEL_MAX_TOKENS`,
  `FLOOD_MODEL_TIMEOUT_S`; `.env.example` updated.
- `ExperimentRepository.create` (`app/persistence/repositories.py`)
  stamps `model_configuration()` by default.

### Verification
- Tests: pytest **133 passed** (54 new: decision parsing incl. both
  verb shapes and every rejection reason; mock offline + determinism;
  OpenAI-compatible post/parse/error-mapping via `httpx.MockTransport`
  — no network touched; factory + configuration secrets hygiene;
  experiment recording; ModelPolicy fallback paths and live-world
  safety runs). The pre-existing suite (79) untouched and green.
- Roadmap S07 checklist:
  - Mock model works with no network ✅ (deterministic, exercised
    through the full parse path).
  - Provider errors do not corrupt world state ✅ (exploding/garbage
    providers driven 10 ticks in a live world: agent never moves,
    objects and inventory unchanged, exactly one legal `look`
    ACTION_EXECUTED event per tick, last_error recorded).
  - Invalid model output is rejected ✅ (prose, arrays, missing
    action, non-object action, empty/non-string verb — each rejected
    with a machine-readable reason; optional wrong-typed fields
    dropped, not fatal).
  - Model configuration is recorded with experiment ✅
    (`ExperimentRepository` stamps the effective config; JSON-serialized
    output asserted free of the API key).
  - End goal — swap brains without changing the world engine ✅ (the
    engine, Agent and World are untouched; providers are constructed
    in one factory function).
- E2E unchanged: live uvicorn + headless Godot client →
  **FLOOD_SMOKE OK world=17 tick=2 agents=3**; the live world kept
  ticking (tick 91+) with persisted ACTION events — engine → bus →
  recorder → database → API. Client headless test `SMOKE OK`.

### Commits
- `5155b9e` — S07: model provider abstraction — providers, decision schema, ModelPolicy bridge [pushed]

## S08 — First LLM Agent (2026-10-08)

### Plan
The Void is inhabited by scripted minds through a proven seam (S07).
This sprint puts an actual language model inside: a decision loop that
drives model agents through the live tick, short memory, and logged
decisions and utterances — with the world proving it keeps running when
the brain fails. Scripted agents and engine determinism stay untouched.

### Scope
In: `Engine.step_async` (world advances, then each agent refreshes its
model policy and acts, in id order); bounded `AgentMemory` folded into
the observation; minimal speech — a decision's `message` becomes an
`AGENT_MESSAGE` event (logged, not yet perceived by others; delivery is
the communication sprint); `MODEL_DECISION`/`MODEL_ERROR` events on the
world timeline (provider, model, observation, decision, outcome);
`POST /worlds` gains `brains: "scripted" | "model"` (model brains only
via explicit opt-in — never auto-started by settings); driven 300-tick
survival run (guide §9); documented local-model path (Ollama,
`qwen2.5:7b-instruct` recommended — non-thinking, strong JSON, 4.7 GB;
`phi4-mini` if speed outranks reliability).
Out: cognition scheduler / think intervals / global compute budget
(every model agent thinks every tick for now — tps is the throttle);
reproduction/lineage (S09); message delivery to other agents
(communication sprint); memory persistence across worlds (experiments
layer); streaming, multi-model populations (guide §26), native SDKs.

### Implementation
- `backend/app/simulation/engine.py` — `step_async`: the model-aware
  tick. World advances first, then each agent (ascending id, the
  existing determinism contract) refreshes its model policy — the
  provider is awaited *between* the world advancing and the agent
  acting — and acts. Duck-typed `refresh` detection: scripted
  policies take the identical pure-synchronous path as `step`
  (parity-tested). `has_model_policies` reports whether a world needs
  the async path at all.
- `backend/app/simulation/memory.py` — `AgentMemory`: bounded (16)
  ring of recent outcomes (tick, action, ok, reason, goal),
  deep-copied in and out so observations and events never alias live
  memory. Lives on the `Agent`, appended in `act()` after every
  attempt, and folded into the observation (guide §6's precedent:
  current_goal) — a decision that cannot see what just happened
  cannot learn from it.
- Decision/error/utterance timeline — `MODEL_DECISION` (provider,
  model, decision, full observation incl. memory, outcome),
  `MODEL_ERROR` (reason + the fallback action that ran) and
  `AGENT_MESSAGE` (the utterance) events, recorded by the engine right
  after each model agent acts. Guide §7's storage list — action,
  rationale, observation, outcome — with the outcome of a *recorded*
  decision; replay never re-calls the model.
- `backend/app/host.py` — `brains` opt-in: `WorldRegistry.create`
  validates it, builds one provider from settings shared by every
  agent, and gives each agent its own `ModelPolicy` (a policy holds
  one agent's in-flight decision). `WorldHost.advance_once` is the
  model-aware step used by both the tick loop and the API's manual
  step; the sync `step_once` is gone — nothing needed it.
- `backend/app/api/worlds.py` — `brains` on create (400 on unknown
  value or misconfigured provider), `brains`/`provider` in world
  state and listings, step route is async (model worlds await inside
  the step).
- `backend/app/models/openai_compat.py` — `ProviderError` now always
  names the exception type. Found live: Ollama cold starts raise a
  timeout whose `str()` is empty, and an empty reason in the event
  log is a debugging dead end.
- `ModelPolicy.last_response` — provenance for the decision event.

### Verification
- Tests: pytest **155 passed** (22 new: memory bounds/eviction/alias
  safety; scripted parity under `step` vs `step_async`; decision
  events with provenance/outcome; utterance events; error events with
  fallback; 300-tick survival (guide §9); memory flowing into
  observations; mid-run provider failure injection; API brains
  opt-in, 400s, decision events via the API and through the recorder,
  autostarted model world ticking and stopping clean; timeout error
  mapping).
- Roadmap S08 checklist:
  - Agent can observe the Void ✅ — the bounded observation (with
    memory) is in every request and logged on every MODEL_DECISION.
  - Agent can make a valid action ✅ — live: 9 real decisions from
    qwen2.5:7b-instruct, all `outcome.ok=True`.
  - Invalid model action is safely rejected ✅ — live: a cold-start
    provider timeout on the very first call logged MODEL_ERROR, ran
    the safe fallback, and the world continued for 4 more ticks.
  - Model response is logged ✅ — MODEL_DECISION events persisted
    through the recorder, queryable via the events API.
  - Simulation remains stable after model failure ✅ — the live
    failure above, plus 300-tick survival and mid-run failure
    injection tests.
- **A real LLM lived in the Void**: live uvicorn with
  `FLOOD_MODEL_PROVIDER=ollama FLOOD_MODEL_NAME=qwen2.5:7b-instruct`,
  `POST /worlds {"brains": "model"}` → world 18 ticked 5 times with 2
  qwen agents; one cold-start MODEL_ERROR then 9 logged decisions
  (incl. a model-authored `thought_summary`), memory flowing into
  observations, all actions world-validated.
- E2E unchanged: scripted world via headless Godot client →
  **FLOOD_SMOKE OK world=19 tick=2 agents=3**; client headless test
  `SMOKE OK`.

### Commits
- `169ffce` — S08: first LLM agent — model-aware tick loop, short memory, decision events, brains opt-in [pushed]

## S09 — Birth & Generation (in progress)

### Plan (2026-10-08)
Agents can now think; none can yet continue. This sprint implements
reproduction at the mechanism level: `create_child(parent)` (guide §10)
with lineage fields, a deterministic birth position, the minimal
parent → child inheritance package the guide prescribes, an `AGENT_BORN`
event on the timeline, and population membership persisted to the
database. The roadmap's verification is a sequential chain —
0 → 1 → 2 → … → 100 with every parent/child link and generation number
checked — so births are driven by `Engine.create_child` (engine-pure,
testable) and by an API route (`POST /worlds/{id}/births`) that makes
reproduction observable in a live world.

### Scope (2026-10-08)
In: `parent_id`/`generation`/`population_id` on the engine `Agent`;
`Engine.create_child` with deterministic adjacent-cell placement
(N → E → S → W first free floor) and `BirthError` when there is no
room; minimal inheritance — the child's goal is the parent's, and the
parent → child message is seeded into the child's short memory
(guide §10: "start with parent -> child message"); `AGENT_BORN` event
carrying parent/child/generation/position/inheritance;
`PopulationModel` + `AgentModel` persistence (new `AgentModel.local_id`
column + migration, engine-pure ids are per-world, DB ids are global);
`AgentRecorder` bus subscriber translating births into agent rows;
`AgentRepository` lineage queries; `POST /worlds/{id}/births` route;
the 0 → 100 chain verification (engine and database).
Out (S10+): real genetics / trait inheritance (S10 — Inheritance),
model-decision-driven birth intent and birth rejections as rejected
actions, population branching rules and capacity limits, death and
generational turnover, experiments-layer birth policies.

### Implementation
- Engine (pure, no DB): `Agent` carries `parent_id`/`generation`/
  `population_id`. `Engine.create_child(parent)` (guide §10's
  `create_child(parent)`) picks the first free floor cell adjacent to
  the parent in N → E → S → W order (or an explicit position), spawns
  the child with the next per-world id, and records one `AGENT_BORN`
  event with the full lineage payload. No room raises `BirthError`;
  nothing is half-applied. `ancestors()` walks a lineage to the root;
  `population()` lists a population's members.
- Minimal inheritance, exactly as the guide prescribes: the child's
  goal starts as the parent's, and the parent → child message is
  seeded into the child's short memory as its first recollection.
  Genetics and trait inheritance are S10.
- Persistence: engine ids are per-world while `AgentModel.id` is
  global (parent_id FKs reference it), so `AgentModel.local_id` plus
  an index and migration `a1c9e2f47b03` keep both identities. The
  registry writes one `PopulationModel` row per world (the row id IS
  the engine's population id) and `AgentModel` rows for the founding
  agents; `AgentRecorder` — a bus subscriber like the event recorder —
  persists every birth, keeping the local → global mapping so the
  next birth can link its parent's global id. `AgentRepository.
  lineage()` renders the chain as (local id, parent local id,
  generation) rows — the roadmap verification's readable form.
- API: `POST /worlds/{id}/births` — 201 with the child and its
  inheritance, 400 for an unknown parent, 409 when there is no room.
  A model world's child gets a fresh `ModelPolicy` on the world's
  provider; a scripted world's child gets the default scripted mind.
- What mind a child gets is the caller's decision, not the engine's:
  decision-driven birth intent (and birth rejections as rejected
  actions) is deliberately left for after inheritance exists (S10).

### Verification
- Tests: pytest **175 passed** (20 new: lineage fields, birth event
  payload, inheritance package, explicit position/policy, dead and
  unknown parents, boxed-in `BirthError` with nothing half-applied,
  population membership, the 0 → 1 → … → **100** chain with every
  generation and parent link checked, `ancestors`, founding-row
  persistence, births through the API and into the database, the
  409-when-boxed-in path, model-world children thinking, and the
  10-generation chain verified through `AgentRepository.lineage`).
- Roadmap S09 checklist: sequential lineage 0 → 1 → … → 100 with
  every parent/child relationship and generation number verified ✅
  (in-engine for 100 generations, in-database for 10 through the
  API — the recursive check is the same one).
- Live: world 22 (scripted) — three `POST .../births` calls produced
  the chain 1 → 2 → 3 → 4, generations 0-3, one population, each
  birth carrying its parent → child message; the 4-agent world kept
  ticking afterwards.
- E2E unchanged: headless Godot client → **FLOOD_SMOKE OK
  world=23 tick=2 agents=3**; client headless test `SMOKE OK`.
- Regression the suite caught: subscribing the event recorder after
  world generation (my reordering) silently stopped persisting
  WORLD_SEEDED/OBJECT_CREATED events — the S06B test failed, the
  recorder is subscribed first again, with the lineage recorder last
  (it only ever sees AGENT_BORN).

### Commits
- `378542c` — S09: birth & generation — create_child, lineage fields, AGENT_BORN events, population persistence, births API [pushed]



## S10 � Inheritance (in progress)

### Plan (2026-10-08)
S09 let a lineage continue; this sprint lets it carry culture. The
inheritance package (traits, knowledge, message, cultural artifacts �
the roadmap's four parts) is declared by the parent as *intent* in its
decision, travels through `create_child`, and lands on the child as
state the child can see in its observation. The guide's lineage
experiment (�11) needs exactly this: a child that receives, then
decides what to pass onward.

### Scope (2026-10-08)
In: `InheritancePackage` (the four parts, tolerant parse, deep-copy
transfer); parent intent — a decision's `inheritance` field stored as
the parent's pending inheritance and used by default at birth;
child state — `traits`, `knowledge`, `cultural_artifacts` on the
agent, all visible in the observation so the next decision can use
them; the package recorded on `AGENT_BORN` and persisted to
`AgentModel` (`inherited_traits`, `inherited_knowledge`,
`cultural_artifacts`, `working_memory`); `POST /worlds/{id}/births`
takes an `inheritance` package; the roadmap's four verification
items as tests.
Out (S11+): the 100-generation experiment itself (S11), knowledge
*acquisition* during life (agents today only carry what they were
given), semantic-similarity scoring of transmissions, death and
generational turnover, population branching rules.

### Implementation
- `backend/app/simulation/inheritance.py` — `InheritancePackage`:
  the four roadmap parts, a tolerant parse (wrong-typed parts are
  dropped, never fatal — same policy as the decision contract's
  optional fields) and a JSON-safe `as_dict`.
- Parent intent: a decision's `inheritance` field (validated by the
  S07 decision parser as "an object", meaningless to it on purpose)
  is stored by `Agent.act` as the parent's *pending* inheritance.
  `create_child` uses the explicit package when given, the parent's
  pending intent otherwise. A parent's own state the package does not
  carry never reaches the child.
- Child state: `traits`, `knowledge`, `cultural_artifacts` on the
  Agent, deep-copied in at birth and surfaced in the observation —
  deciding what to pass onward requires seeing what was passed to
  you (guide §11). The message keeps its S09 role as the child's
  first seeded recollection.
- Independence: every transfer is a deep copy — parent intent, child
  state and the recorded AGENT_BORN payload cannot alias each other,
  so later mutation of any of them is invisible to the others.
- Decision contract: `Decision.inheritance` (object or None), parsed
  and round-tripped.
- Persistence: new `agents.cultural_artifacts` JSON column (migration
  `b2f4a7c91d58`) beside the two columns S02 already had;
  `AgentRecorder` maps the package onto `inherited_traits` /
  `inherited_knowledge` / `cultural_artifacts` / `goals` /
  `working_memory`; founding rows get the empty parts explicitly.
- API: `POST /worlds/{id}/births` body is now
  `{"parent_id", "inheritance": {...}}` (S09's `message` shorthand is
  `inheritance.message`).

### Verification
- Tests: pytest **189 passed** (14 new: package normalize/tolerate/
  round-trip/JSON-safety; explicit package lands on the child;
  decision-declared intent used by default; inheritance visible in
  the observation; uninherited state stays with the parent; empty
  intent transmits only its message; child mutation cannot touch the
  parent's intent or the recorded event; decision-contract parsing of
  `inheritance`; founder observation's empty parts).
- Roadmap S10 checklist:
  - Child receives parent's intended inheritance ✅ (explicit package
    and decision-declared intent, both verified).
  - Uninherited memory does not magically appear ✅ (parent's
    knowledge/traits stay with the parent when the package omits them).
  - Inheritance is recorded ✅ (AGENT_BORN payload carries the full
    package; the agent row carries it in columns — verified live in
    the dev database).
  - Parent and child states remain independent after creation ✅
    (deep-copy transfer, verified against parent intent and the
    recorded event).
- Live: world 24 — a birth with a full package returned the child
  with all four parts; the AGENT_BORN event carried them; the
  database row (`local_id 2`, `generation 1`, `parent_id 8` — the
  founder's global id) stored traits, knowledge, artifacts and the
  seeded working memory; the 2-agent world kept ticking.
- E2E unchanged: headless Godot client → **FLOOD_SMOKE OK
  world=25 tick=2 agents=3**; client headless test `SMOKE OK`.

### Commits
- `d918bdd` — S10: inheritance — package (traits, knowledge, message, artifacts), parent intent, child state, persistence [pushed]

## S11 � 100-Generation Lineage Experiment (in progress)

### Plan (2026-10-08)
The first serious experiment (guide �11 / roadmap S11): a founder
receives 10 controlled facts, creates Agent 1, each child decides what
to pass onward, for 100 generations � measuring information drift.
S10 built the transmission mechanism; this sprint wraps it in a
repeatable runner with the roadmap's six measures (retained, lost,
altered, new facts, message length, semantic similarity), a replay
path that rebuilds the lineage from persisted events alone (replay
never re-calls a model), and JSON export of results.

### Scope (2026-10-08)
In: `app/experiments/` — the lineage runner (founder with the
controlled knowledge set, deterministic per-generation intent
extraction, `create_child` chain), scripted policies that produce
known transmission phenomena for calibration (full retention, lossy,
altering, negating, new-fact policies) and a model mode driven by
`ModelPolicy` refresh; per-generation + final metrics (exact retention,
loss, alteration, additions, contradictions via a documented negation
heuristic, token-Jaccard similarity, message lengths); an
`ExperimentModel` row recording the run (configuration + the original
fact set, status created → running → completed); replay from the
events table; JSON export; a `python -m app.experiments` CLI.
Out: semantic-similarity via embeddings (lexical Jaccard until an
embedding provider exists — `nomic-embed-text` is a later option),
automatic contradiction *detection* beyond the negation heuristic,
experiment scheduling/dashboards (S13+), statistical aggregation
across experiment runs, knowledge acquisition during life.

### Implementation
- `backend/app/experiments/lineage.py` — the experiment:
  - **Runner** (`run_lineage_experiment`): wires a world row, a
    population, a flat engine, a founder carrying the 10-fact
    controlled set, and the DB rows/subscribers — then drives 100
    generations of `Engine.create_child`. One *experiment mind*
    decides every generation's transmission against the current
    parent's observation (the lineage's agents are genetic carriers;
    calibration counters advance once per generation, not per agent).
  - **Scripted calibrations**: full retention (the control), and
    drift-producing policies (lossy staircase, re-wording, negating,
    new-fact) so metrics are checked against ground truth.
  - **Metrics** (roadmap S11): retained / lost / altered / new facts,
    contradictions (guide §11's negation heuristic — a transmitted
    fact whose tokens are an original's plus a negation token),
    message lengths, and best-match token-Jaccard similarity as the
    deterministic semantic proxy. Per generation and final.
  - **ExperimentModel** row per run: status created → running →
    completed, the original fact set and configuration recorded with
    it (guide: configuration is recorded with the experiment).
  - **Replay** (`replay_lineage_experiment`): the lineage rebuilt from
    persisted AGENT_BORN events and the experiment row alone — no
    engine, no model calls (guide §"replay").
  - **Export/CLI**: JSON export (`export_report`) and
    `python -m app.experiments --mode full|lossy|altering|negating|new|model`.
- The OpenAI-compatible provider's default system prompt now teaches
  the decision contract's `inheritance` field, so a real model knows
  it is authoring its child's culture.

### Verification
- Tests: pytest **202 passed** (13 new: control retains 10/10 with
  similarity 1.0; every generation exists (101 agent rows,
  generations 0-100); experiment row completes with timestamps and the
  fact set; model mode runs 25 generations through the refresh path
  with a stub provider; lossy staircase (10/10 lost, retention 10→9→0);
  altering (10 altered, 0 contradicted); negating (10 contradictions);
  new facts (10 new on top of 10 retained); message lengths measured;
  replay rebuilds the 25-generation chain from events; export writes
  valid JSON; unknown experiment/mode rejected).
- Roadmap S11 checklist:
  - Experiment completes without manual intervention ✅ (CLI run:
    experiment 1, 100/100 generations, no interaction).
  - Every generation exists ✅ (agent rows 0..100 + one AGENT_BORN
    event per generation).
  - Metrics are generated ✅ (all six roadmap measures in the report).
  - Experiment can be replayed ✅ (replay from events, no model).
  - Results can be exported ✅ (JSON round-trip verified; the live
    run exported to disk).
- **Live control run** (dev DB, `--mode full --seed control-1`):
  100 generations, 10/10 retained, 0 lost, similarity 1.0, exported.
- **Live model run** (`--mode model`, qwen2.5:7b-instruct via
  Ollama, seed `llm-run-4`, experiment 4 / world 29, ~50 min on a
  loaded machine): all **100 generations completed** — 100/100 births,
  no timeouts (request timeout raised to 120 s for the contended
  machine). Result — the first measured information drift in Flood:

  | measure | value |
  |---|---|
  | retained facts | **6/10** (verbatim) |
  | lost facts | 4 |
  | altered / contradicted / new | 0 / 0 / 0 |
  | avg similarity | 1.0 |
  | avg message length | 0.0 (the model omits the optional field) |

  The shape of the drift is the interesting part: transmission was
  **stable at 10/10 for 85 generations, then a single transmission at
  generation 86 dropped 4 facts at once**, and the reduced set then
  held stable to generation 100. Episodic attrition, not gradual decay
  — exactly the kind of result the experiment exists to surface. The
  lost four: "the void is dark", "water blocks the walker", "walls
  stop movement", "food restores strength".
- Earlier live attempts (seeds `llm-run-1`, `llm-run-2`) were
  interrupted by Ollama contention from other projects; their partial
  runs (15 and 63 generations) persisted correctly, are replayable, and
  their experiment rows are marked `aborted`.

### Commits
- `47463d6` — S11: 100-generation lineage experiment — runner, calibration policies, metrics, replay, export, CLI [pushed]

## S12 � 10,000-Generation Stress Test (in progress)

### Plan (2026-10-08)
The project's signature scale is 10,000 generations (roadmap S12).
S11 proved the mechanism at 100 with a real model; this sprint proves
the architecture survives 10,000 at mock speed � with the machinery
that scale demands: a bounded in-memory event log (retention policy),
checkpoints, and experiment resume. All scripted: no model calls, so
minutes, not the ~13 hours a model-driven run would cost.

### Scope (2026-10-08)
In: event retention on the world (opt-in; the durable record stays
the database — watched live worlds keep every event by default);
checkpoints (a `checkpoints` table: the transmission state needed to
continue a lineage — parent, position, knowledge, counter — not a full
world serialization, which S03's to_dict already is); experiment
resume (restore the parent and the recorder's local→global map from
the database, continue the chain); the S11 runner parameterized
(world size, checkpoint cadence, retention, batch size); a
10,000-generation stress test verifying: no generation gaps, no
orphaned lineage records, checkpoint/resume works, memory bounded
(event log capped, per-agent memory capped), database queryable
afterwards; CLI flags.
Out: replaying 10k generations through the API (dashboard concern,
S13+), event-log compaction/deletion from the database (only the
in-memory window is capped), world serialization of mid-run state
beyond checkpoints, multi-lineage stress (branching populations).

### Implementation
- **Lightweight agent lifecycle**: unchanged by design — agents are
  pure dataclasses and the engine holds no DB objects; the stress test
  proves the shape holds at 10,000 (10,001 agents, each with bounded
  16-entry memory).
- **Event retention policy** (`World.event_retention`): when set, the
  in-memory event list keeps only the most recent N events; sequence
  ids keep advancing, so client `since_id` windows stay coherent
  within the retained range. Bus subscribers still see everything,
  and the database remains the durable record. Live watched worlds
  keep the default (None) because clients stream the full timeline.
- **Snapshot strategy**: checkpoints are the experiment's snapshot —
  the transmission state needed to continue (parent, position,
  knowledge, goal, traits, artifacts, the mind's counter), written
  every N generations *and at the end of every run*. A full world
  serialization already exists (S03 `World.to_dict`); for lineage
  continuity it would be dead weight.
- **Checkpointing** (`checkpoints` table + `CheckpointRepository`):
  migration `c5d8e1b2049f`, indexed by (experiment, generation).
- **Experiment resume** (`resume_lineage_experiment`): the chain *head*
  — the highest-generation agent row — is restored as the current
  parent, its lineage link and carried inheritance read straight off
  its row (the recorder persisted the package at its birth), and the
  recorder's local → global map is rebuilt from the same rows so new
  children link to their real parents. Interrupted and completed
  runs both resume — the latter is how a pilot is extended ("run it
  to 10,000"). Resuming from the row (not the checkpoint) is what
  keeps the chain free of duplicate or orphaned ids.
- **Runner scale switches**: auto-sized world (interior fits the
  chain), row-major placement by generation (one distinct cell each,
  so the walk can never trap itself — the engine's adjacency walk
  demonstrably self-traps at some start positions), event retention,
  event-recorder batching (in-memory buffer, one transaction per
  batch, flushed at run end — no session held between events, so
  SQLite never locks out concurrent writers). The agent recorder
  still commits per birth by necessity: the next birth's parent is
  this child, so its global id must exist immediately.
- CLI: `--checkpoint-every`, `--retention`, `--resume ID`.

### Verification
- Tests: pytest **215 passed** (13 new: the 10,000-generation run
  itself with a wall-clock budget; no generation gaps (contiguous
  0..N in the DB); no orphaned lineage records (every parent row
  exists, exactly one founder); bounded memory (the retained-event
  window's footprint stops growing after the cap while 10,000 more
  events flow); retention caps the in-memory window with ids still
  advancing; database queryable afterwards (event counts, filtered
  queries, lineage); checkpoints on cadence; resume continues a
  chain from its head (contiguous 0..800 in the DB, no orphans,
  no duplicate ids); resume restores a calibration staircase
  (lossy drops continue rather than restart); resume extends a
  completed pilot; the no-checkpoint, unknown-experiment and
  already-at-target errors).
- Roadmap S12 checklist:
  - Run a small-model/mock version to 10,000 generations ✅ (test +
    live CLI run).
  - No generation gaps ✅. No orphaned lineage records ✅.
  - Checkpoint/resume works ✅ (unit + live on the dev DB: a 40-gen
    run resumed to 80 leaves exactly 81 contiguous rows).
  - Memory usage remains bounded ✅ (event window capped; per-agent
    memory capped).
  - Database remains queryable ✅ (repositories answer correctly
    after the run).
- Live stress run (dev DB, `--generations 10000 --checkpoint-every
  1000 --retention 500`): **10,000 generations in 47 seconds**, 10/10
  retained, 10 checkpoints, exported. For comparison, the same scale
  with a model per generation would be ~13 hours of Ollama time —
  this is the mock-scale proof the roadmap asked for.

### Commits
- `39f3fb2` — S12: 10,000-generation stress test — event retention, checkpoints, resume, batched recorder, row-major placement [pushed]

## S13 � Observer Dashboard (in progress)

### Plan (2026-10-08)
The Void has been watchable through curl since S06B and through the
Godot client since S06B; this sprint gives the human the web console
the architecture always promised � a dashboard over the Simulation API
that polls real backend events. Panels stay web (roadmap): a world
viewport rendered from the state snapshot, population stats
(generation, active agents), the event stream, and pause/resume/step
controls. The 3D experience stays Godot (D001); the viewport panel
links to launching it.

### Scope (2026-10-08)
In: `GET /api/worlds/{id}/agents` (the live population: identity,
generation, parent, status, position, policy kind — what the stats
panel needs); the React console rebuilt as the dashboard (world list
+ create, viewport canvas from snapshots, population stats, color-
coded event stream via since_id polling, pause/resume/step controls);
a poll-based api client; typecheck + production build green; live
verification against a running backend.
Out: WebSocket push (S06B deliberately deferred it; polling at 1-2 Hz
is the console's refresh for now), the agent inspector (S14), the
lineage explorer/replay timeline (S15+), Godot web export (the
client stays a desktop app per D001), auth.

### Implementation
- Backend: `GET /api/worlds/{id}/agents` — the live engine's
  population (id, generation, parent, status, position, goal, policy
  kind, knowledge count). The route reads the engine directly; detail
  like memory is the agent inspector's (S14).
- Frontend, grown from S01's health console (same Matrix-dark theme,
  still dependency-free beyond React — no UI kit):
  - `api.ts`: typed client over the Simulation API (health, worlds,
    create, state, agents, events with `since_id`, pause/resume/step,
    stop).
  - `WorldDashboard.tsx`: polls state + agents at 1 Hz and events at
    2 Hz, tracking `since_id`; resets cleanly when the selected world
    changes or is stopped.
  - `WorldViewport.tsx`: canvas grid drawn from the engine's
    render-ready `snapshot()` (terrain chars → colors, objects,
    entities) — the web-side eye, with the Godot client linked for the
    3D view (D001: world truth stays server-side).
  - `PopulationStats.tsx`: active agents, generation spread, model vs
    scripted minds, deepest lineage.
  - `EventStream.tsx`: newest-first, color-coded by event family
    (decision/error/message/born/action), per-event summaries,
    auto-scroll that holds when the human scrolls up.
  - `Controls.tsx`: pause/resume/step/stop mapped to the API routes.
- `vite.config.ts`: `vite preview` does **not** inherit
  `server.proxy`, so the same `/api` proxy is declared for preview
  too — watching the built dashboard in a browser works either way.
  (Found live: the built app served fine but every API call 500'd
  against an unreachable proxy target.)

### Verification
- Tests: pytest **219 passed** (4 new: the agents feed's shape,
  model-world policy kind, births appearing in the feed, 404 for
  unknown worlds).
- `npm run build` green (`tsc --noEmit` + production build).
- Live, end to end through the exact path the browser uses (backend
  on :8000, `vite preview` on :5173 proxying `/api`):
  - created a scripted world via the proxy → world 33, 3 agents;
  - state feed: tick advancing (0 → 17 within seconds) — real
    backend events, not fixtures;
  - agents feed: 3 agents, generation 0;
  - events feed: real ACTION_EXECUTED events streaming;
  - controls: pause froze the tick (215 → 215), manual step advanced
    it (215 → 216) while paused, resume let it climb again.
- Roadmap S13 checklist: a simulation started and confirmed to update
  from real backend events ✅ (the polling feeds verified live; the
  visual pass in your browser is the remaining human step — `npm run
  dev` or the built console via `npm run preview`).

### Commits
- `4a6f11c` — S13: observer dashboard — populations feed, viewport/stats/event-stream/controls console, preview proxy [pushed]
- `d3cb458` — gitignore: SQLite journal/wal artifacts (flood.db-journal committed by accident in S13) [pushed]

## S14 � Agent Inspector (in progress)

### Plan (2026-10-08)
The dashboard (S13) shows the population; this sprint lets the human
open an organism. Clicking an agent � in the world viewport or the
population list � shows its identity, lineage (generation, parent,
children), short memory, inherited knowledge/traits/artifacts, its
current action with outcome, and its compute state. One detail route
feeds the inspector; everything shown is real engine state.

### Scope (2026-10-08)
In: `GET /api/worlds/{id}/agents/{agent_id}` — the deep detail
(memory, knowledge, traits, artifacts, lineage both directions,
last action + outcome, provider/model, model-call count from the
live timeline, the configured request envelope); viewport canvas
clicking (screen-space picking, same idea as the Godot client's);
clickable population list; the inspector panel in the console
(polling while an agent is selected); tests.
Out: per-agent budget *enforcement* (guide §25 — the cognition
scheduler's job; here the envelope is displayed, not enforced),
full observation dumps in the UI (the memory list is the readable
summary), agent history across worlds, editing agent state.

### Implementation
- Backend: `GET /api/worlds/{id}/agents/{agent_id}` — reads the live
  engine agent: identity (status, position, goal, policy kind),
  lineage both directions (generation, parent, children, population),
  the last action with its ok/reason from memory, the full bounded
  memory ring, the inherited package (traits, knowledge, artifacts),
  and compute state — decisions this agent made in the retained
  timeline plus the provider it calls through and the configured
  envelope. Budget enforcement remains the scheduler's (guide §25);
  the envelope is reported, not policed.
- Frontend: `AgentInspector.tsx` — the panel, polling the detail route
  at 1 Hz while an agent stays selected, with lineage, current action,
  memory, inherited culture (knowledge listed verbatim), and compute.
- Selection: the viewport canvas does screen-space picking (click a
  cell; if an entity stands there the inspector opens — the web-side
  twin of the Godot client's picker, no physics needed), and the new
  roster panel lists every agent click-to-inspect. The third grid
  column appears only while an agent is selected; the selected agent
  renders amber in the viewport.

### Verification
- Tests: pytest **226 passed** (7 new: founder identity with empty
  history; different agents showing different state (distinct
  positions, per-agent memory, neither containing the other's);
  lineage both directions with the parent→child message as the
  child's first recollection; rejected/accepted last action shape;
  model-world provider reporting after a decision; 404s for unknown
  agent and world).
- Live: world 34 (scripted) — agents 1 and 2 inspected with distinct
  positions and separate memory rings; a birth produced child 3 whose
  detail showed generation 1, parent 1, two inherited facts, first
  memory "go on", and the parent now listing child 3. A model world
  (mock brains) reported policy=model, provider mock/mock-1, one
  decision counted, envelope temp 0.7 / max_tokens 512.
- Roadmap S14 checklist: selecting different agents shows correct
  state ✅ (unit + live; the browser pass is yours — click an agent in
  the viewport or the roster).

### Commits
- `24d0c36` — S14: agent inspector — detail route, viewport picking, roster, inspector panel [pushed]

## S15 � Lineage Explorer (in progress)

### Plan (2026-10-08)
The lineage is now long, structured and measured (S09�S12) but only
readable as rows. This sprint makes ancestry visual: select an agent,
see its full ancestor chain from the founder, walk it � the
roadmap's check is "select Agent 100, navigate to Agent 0 and
intermediate generations" � with inherited-information comparison and
drift indicators at every step.

### Scope (2026-10-08)
In: `GET /api/worlds/{id}/agents/{agent_id}/lineage` — the ancestor
chain (founder first) with per-generation state, plus drift metrics
computed against the lineage's originals (reusing S11's
classification: retained/lost/altered/new + similarity); the lineage
rail in the inspector — every ancestor click-to-navigate, so the
chain is both the view and the navigation; an inherited-information
comparison block for the inspected generation.
Out: the branching family tree (multiple children per node — the
chain view is one lineage; populations birth siblings), cross-world
lineage, semantic similarity beyond the S11 lexical proxy.

### Implementation
- Backend: `GET /api/worlds/{id}/agents/{agent_id}/lineage` — walks
  `Engine.ancestors` (founder first) and returns each member's state
  (id, generation, parent, children, position, policy, goal, status,
  knowledge, traits, artifacts, inheritance message) plus its *drift*
  — S11's `generation_metrics`/`tokens` promoted from private helpers
  and reused verbatim, so the explorer and the experiment measure
  drift by identical rules. The originals are the lineage's *earliest
  knowledge carrier* (the founder's set when it has one, else the
  first generation that did — live founders start empty).
- Frontend: `LineageExplorer.tsx` — the rail (founder at top,
  selected agent at the bottom) with per-generation drift chips
  (retained/lost/altered/new + similarity) and the parent→child
  message; clicking any ancestor re-selects that agent, so the chain
  is the navigation; below it, the inherited-information comparison
  for the inspected generation (the retained/lost/altered/new fact
  lists). Wired into the inspector where the plain lineage block was.
- **Engine fix found by the live check**: birth placement was the
  four-cell neighbourhood walk, which self-traps (the S12 experiment
  runner already worked around it with explicit positions; an API
  caller cannot). `Engine._free_adjacent` became
  `Engine._free_cell_near`: an expanding Chebyshev ring search from
  the parent, north-first clockwise — adjacent births unchanged in
  the common case, but a boxed-in parent now births at the nearest
  free cell instead of failing forever. `BirthError` now means "the
  world has no free cell at all" (tests updated: a genuinely full
  3×3 world, plus the new boxed-in-still-births case; the API test
  that expected a 409-from-boxing became a 201-at-ring-2 test).
  This is what made the roadmap's Agent-100 chain livable: 100 API
  births completed, chain 0..100.

### Verification
- Tests: pytest **234 passed** (8 new: the chain from the deepest
  agent with navigation links and children; founder-alone lineage;
  drift against the lineage's originals (the earliest carrier), with
  the founder's own row honest about its empty start; inheritance
  messages as first recollections; 404s; plus the reworked birth
  placement tests — full-world BirthError with nothing half-applied,
  and boxed-in-still-births at the deterministic nearest cell).
- Live (world 38): **100 API births, agent 101, chain 0..100** — the
  roadmap's check end to end. Drift reads correctly down the chain:
  generation 1 retains 10/10, generation 50 still 10, generation 100
  retains 6 with 4 lost (the transport set shrank at 51 by design).
- Roadmap S15 checklist: select Agent 100 and navigate to Agent 0 and
  intermediate generations ✅ (the rail is the navigation; every
  intermediate generation exists in the feed).

### Commits
- `72b7aa1` — S15: lineage explorer — ancestry feed with drift, navigable rail, expanding-ring birth placement fix [pushed]

## S16 � Word Seed Experiment (in progress)

### Plan (2026-10-08)
The first divergent-idea experiment (guide �12): agents receive seed
words, produce three associated concepts, and create one cultural
artifact � a story, theory, rule, invention, game, poem, or building
concept � stored as a cultural object. The verification is the
interesting part: run multiple populations from identical seeds and
compare outputs. Scripted calibrations give the control (identical
seeds -> identical artifacts) and a deterministic divergence case;
a live mode runs the same task through a real model, where identical
seeds are expected to genuinely diverge.

### Scope (2026-10-08)
In: `app/experiments/wordseed.py` — the runner (seeded agents,
concept generation, artifact creation, storage as world objects +
agent rows + `ARTIFACT_CREATED` timeline events), the comparison
across identically-seeded populations (distinct variants, kinds,
concept-set Jaccard), a JSON report + export, and a
`python -m app.experiments.wordseed` CLI; scripted / scatter / model
modes; tests.
Out: artifacts as world-building material (guide §13 is the next
experiment's), a dashboard artifacts panel, artifact lineage
(a child inheriting an artifact), semantic scoring of artifact text.

### Implementation
- `backend/app/experiments/wordseed.py` — the runner:
  - Seeded agents: one seed word per agent, spawned into a flat world
    (row-major), one agent per seed.
  - Concepts + artifact: the guide's task. Scripted calibrations
    derive deterministically (``scripted`` = pure function of the seed
    word — the control; ``scatter`` = the same shape salted per
    population — deterministic divergence). Model mode asks a live
    provider through the S07 seam, parsing concepts + artifact JSON
    with the same tolerance rules as decisions (``extract_json_object``
    promoted public in ``models/decision.py`` for exactly this reuse).
  - Storage as cultural objects: the artifact becomes a world object
    at the agent's cell (``kind`` as the object type, the full artifact
    in properties), an `ARTIFACT_CREATED` timeline event, and the
    agent row's ``cultural_artifacts`` — three durable forms, same as
    every other fact about the world.
  - Comparison: per-seed variants, kinds, concept-set Jaccard across
    the identically-seeded populations, plus identical/divergent seed
    lists and unique-artifact counts.
- Runner architecture note: one event loop for the whole run. The
  first live attempt crashed with ``Event loop is closed`` — the
  provider's long-lived ``httpx.AsyncClient`` cannot survive the
  per-agent ``asyncio.run`` calls the first draft made; the S11
  runner's single-loop shape was the correct pattern.

### Verification
- Tests: pytest **248 passed** (14 new: the control's identical
  artifacts across populations with per-seed jaccard 1.0; the guide's
  artifact shape (three concepts, one artifact); determinism of both
  calibrations; scatter divergence (9 variants over 3 populations,
  reproducible); storage as agent rows, timeline events and world
  objects; model mode through the provider seam with correct parsing;
  loud failure on unusable model output; unknown mode / zero
  populations rejected; the experiment row completed; JSON export).
- Live control (dev DB, scripted): 2 populations × 5 seeds = 10
  artifacts, 5 unique — **every identically-seeded pair identical**,
  each seed resolving to a distinct artifact kind.
- Live model run (`--mode model`, qwen2.5:7b-instruct, 10 provider
  calls): **10 artifacts, 10 unique — all five seeds divergent**,
  concept-set Jaccard 0.2–0.5. The guide's question answered: simple
  seeds *do* create divergent conceptual structures. Sampled: the
  seed "light" became the theory "The Luminous Path" (guidance,
  brightness, truth) in population 1 and the poem "The Lighthouse's
  Song" (brightness, guidance, hope) in population 2; "water" became
  the theory "The Hydrologic Cycle" and the game "EcoPond".
- Roadmap S16 checklist: multiple populations from identical seeds
  run and outputs compared ✅ (control: identical; live: divergent —
  both verified).

### Commits
- `4d30bb6` — S16: word seed experiment — seeded concepts, cultural artifacts, multi-population comparison, CLI [pushed]

## S17 � Resources (in progress)

### Plan (2026-10-08)
The Void has objects but nothing is scarce or useful yet. This sprint
adds meaningful environmental constraints (roadmap S17): wood, stone,
water and food as resource quantities on world objects (and water
terrain), a `gather` action that moves quantity from the world into
an agent's ledger, and scarcity that makes decisions matter. It is
the foundation the guide's World Building section starts with;
building actions (walls, doors, blocks, structures) are S18.

### Scope (2026-10-08)
In: resource quantities on generated objects (deterministic from the
world seed); the agent resource ledger + inventory reporting; the
`gather` action (adjacent source, per-source yield, depletion with an
`OBJECT_DEPLETED` event, water from adjacent water terrain);
quantities visible in observations and snapshots; a scripted
`GathererPolicy` so live worlds are visibly resource-driven; tests.
Out: spending resources to build (S18 — Building System), recipes and
structures, resource respawn/regrowth, trade, hunger/needs.

### Implementation
- `World`: objects carry `properties["quantity"]` (tree→wood 3,
  stone→stone 3, food→food 2, deterministic from the seed); a per-actor
  resource ledger (`credit_resource` / `spend_resource` /
  `resource_count` / `resources`) that the world alone writes;
  `remove_object` with an `OBJECT_DEPLETED` event; `total_resources()`
  — the conservation witness (world quantities + ledgers).
- `actions.py`: the `gather` action — an adjacent source of the right
  type (or adjacent water terrain for water), one unit per attempt, the
  source decremented and removed at zero. Rejections
  (`unknown_resource`, `no_source_nearby`, `no_water_nearby`) record
  like every other rule violation; nothing is half-applied.
- Observations and snapshots carry object quantities; the agent's own
  ledger rides in the observation like the goal (agent state a decision
  needs to see). The inspector's detail route reports the ledger.
- `GathererPolicy`: a resource-driven scripted mind — gathers an
  adjacent source, walks to the nearest visible one, sweeps otherwise
  (east then north then west: a pure function of the observation, so
  determinism holds). Registry spawn rotations now include it, at a
  wider observation radius (4), placed beside a tree — a blind local
  search on a 4%-density map finds nothing, so the gatherer starts at
  its resource and depletion is what drives it onward.
- Quantities persisted with artifacts and everything else that rides
  the object's properties; nothing new in the schema.

### Verification
- Tests: pytest **260 passed** (12 new: generated quantities are
  deterministic; quantities visible in snapshots and observations;
  gather wood from an adjacent tree; gather water from water terrain;
  depletion removes the source exactly once and later gathers are
  rejected; all three rejection reasons; conservation across gathers
  (single and multiple actors — world totals unchanged while ledgers
  grow); the gatherer gathering in a live world and walking to water
  on an island; unknown resource rejected by the policy).
- Live (world 46, 4 agents at 6 tps): the gatherer (agent 3) gathered
  **10 wood** across 10 gather actions, depleting 3 trees; every other
  agent's ledger stayed empty. Conservation holds by construction:
  the trees' units are exactly the ledger's units.
- Roadmap S17 checklist: agents can gather resources ✅ and resource
  quantities remain consistent ✅ (the conservation invariant is
  asserted directly).

### Commits
- `d0ee4e3` — S17: resources — quantities, gather action, depletion, ledger, conservation, GathererPolicy [pushed]

## S18 � Building System (in progress)

### Plan (2026-10-08)
Agents can gather (S17); now they can alter the Void with it (roadmap
S18). Blocks cost materials from the ledger, occupy cells (so a wall
is a wall), and group into structures by adjacency � the guide's
"a building is simply a collection of world objects with
relationships", with id, owner, components and purpose. The
verification is a scripted agent constructing a valid structure: a
builder mind that lays a wall of wood blocks it was granted.

### Scope (2026-10-08)
In: block placement (`build`) and removal (`remove`) actions with
material costs and validation; structure grouping (adjacency-based,
explicit-id override, purpose, owner); structures exposed to the API
(GET /worlds/{id}/structures) and to an agent-action injection route
(POST /worlds/{id}/actions — the operator seam S19's house
experiment will use); a scripted `BuilderPolicy`; tests including the
roadmap's scripted-construction check.
Out: architectural realism (guide: not initially), structure decay,
ownership enforcement between agents, door/window behaviour beyond
block types, the house experiment itself (S19).

### Implementation
- `world.py`: the `Structure` aggregate (id, owner, purpose,
  components — the guide's §13 shape) plus a registry: adjacency-based
  grouping (`structure_for_cell`), `create_structure` (emits
  `STRUCTURE_CREATED`), membership, and `remove_block`, which frees the
  cell, drops the component, and dissolves an emptied structure.
- `actions.py`: `build` — validates the block type, direction, target
  (floor, unoccupied), then spends the recipe from the ledger (S17's
  `spend_resource`) and places the block, which occupies its cell like
  any object (a wall is a wall). `remove` — refunds the block's
  material and unbuilds it. `purpose` designates a structure at
  creation *or* on joining. Rejections (`unknown_block`,
  `insufficient_materials`, `unknown_structure`, `not_a_block`,
  `cell_occupied`, `impassable_terrain`, `invalid_direction`) record
  like every other violation; nothing is half-applied.
- `policies.py`: `BuilderPolicy` — the scripted constructor. Blocks
  block movement, so it builds north when it can and walks the
  worksite otherwise: a single builder lays a contiguous wall over
  several ticks, which is exactly what structure grouping keys on.
- API: `POST /worlds/{id}/actions` (operator injection — the action
  travels the same validated path as an agent's own decisions) and
  `GET /worlds/{id}/structures` (the buildings, with components).

### Verification
- Tests: pytest **280 passed** (20 new: placement spends and occupies;
  all rejection reasons incl. insufficient materials and unknown block;
  stone blocks cost stone; adjacency grouping; explicit-id joins
  across gaps with purpose; dissolving structures; removal refunds and
  frees the cell; material conservation across build/remove — a block
  is spent ledger in object form; the scripted builder constructing a
  valid contiguous structure owned by itself; the builder stopping when
  materials run out; building through the agent lifecycle; and the API
  routes — gather-then-build producing a purpose-carrying structure,
  rejected actions reported not raised, 404s).
- Live (world 48, through the public API only): the agent walked to a
  tree, gathered **3 wood**, then built a wood block — `GET
  /worlds/48/structures` shows structure 1 ("shelter", owner 1, one
  wood_block at (10,5)). Gather → build → structure, end to end.
- Roadmap S18 checklist: a scripted agent can construct a valid
  structure ✅ (the BuilderPolicy test — contiguous, owned, all
  components on the grid, materials exactly accounted).

### Commits
- `736594c` — S18: building system — blocks with material costs, structures, build/remove actions, operator injection [pushed]

## S19 � House Experiment (in progress)

### Plan (2026-10-08)
The first scenario with a goal rather than a mechanic (roadmap S19 /
guide �14): a small population is told "Build a house." and nothing
else � no shape, size, material or room count. The scenario engine
grants materials, drives the tick, and scores the results: completion
(a structure that actually encloses space � the design-agnostic
definition of a house), material use, construction time, cooperation
(distinct builders on one structure), design, and failure. The
calibration is a scripted builder completing a known valid house;
the model mode then runs the identical scenario with real minds, so
we see what different populations build.

### Scope (2026-10-08)
In: `app/experiments/house.py` — the scenario engine (cleared lot,
granted materials, driven ticks, scoring across the six measures), a
scripted `HouseBuilderPolicy` that completes a known valid house (a
closed 4x4 ring), the model mode through the S07 seam, JSON report +
export, CLI, tests; roadblock: no.
Out: multi-room/house-quality judging beyond enclosure, persistence
of the finished structures beyond the run, population branching,
agents choosing *not* to build (a failure mode the scoring records,
not handles).

### Implementation
- `backend/app/experiments/house.py` — the scenario engine: a cleared
  lot (flat, object-free — the design is the agents' to invent and the
  scripted route cannot be blocked), a material grant of exactly a
  ring's worth per builder, a driven tick through `step_async`, and
  scoring across the roadmap's six measures.
- **Completion** is design-agnostic on purpose: a flood fill from
  beyond the structure's bounding box that cannot reach a cell means
  that cell is enclosed — a closed ring is a house, a wall line is
  not, and *how* the ring came to be (shape, size, material, rooms) is
  never prescribed. (The first definition — "all four neighbours are
  blocks" — was wrong: interior cells neighbour each other, not just
  walls.)
- `HouseBuilderPolicy`: the calibration. `_house_script` generates a
  move/build walk around the *outside* of the ring, building inward,
  with the start corner rotating — so one builder raises the house and
  two builders share it from opposite corners without fighting over
  cells. The scenario's cleared lot is what makes the exact script
  safe; the policy documents that it opts into that guarantee.
- **Structure merging** (engine): when a new block touches several
  structures they merge into the oldest — two walls that touch are one
  building, whichever order they were raised in. Without it, two
  builders approaching from opposite corners split the house in two.
- The model mode swaps only the policy: `ModelPolicy` with a
  house-system prompt, everything else identical — the scenario engine
  never changes (the roadmap's requirement).

### Verification
- Tests: pytest **292 passed** (12 new: the script's closed ring with
  no double-built cells; rotated corners laying the same ring from
  four stands; a wall enclosing nothing; the scripted agent completing
  a known valid house (12 blocks, 4 enclosed cells, owner, purpose,
  materials exactly); construction time measured first→last build
  tick; cooperation (two builders, one structure); the idler recorded
  as a failure; house size as a free parameter (5x5 → 16 blocks, 9
  enclosed); the policy unit path; model mode through a stub provider
  building through the unchanged scenario; unknown mode rejected;
  experiment row and export).
- Live control (dev DB, scripted): **1 house completed** — 12 wood
  blocks, 4 enclosed cells, 4x4, built by 2 cooperating agents over
  ticks 2..22, with the third (wanderer) recorded as a failure.
- Live model runs (qwen2.5:7b-instruct through the identical
  scenario): a 2-agent, 20-tick run placed 3 blocks (purpose-carrying
  structures, no enclosure); an interrupted 60-tick run had placed 11
  blocks across 9 structures before its timeout — the model builds
  on instruction but scatters rather than planning contiguity. Both
  are honest measurements of what the current prompt buys; longer
  runs and prompt work are the obvious next lever (the scenario engine
  needs no change).
- Roadmap S19 checklist: at least one scripted agent completes a known
  valid house ✅; LLM agents tested without changing the scenario
  engine ✅ (same runner, same scoring, only the policy swapped).

### Commits
- `eb4818c` — S19: house experiment — "Build a house." scenario engine, scripted calibration, structure merging, model mode [pushed]

## S20 � Human Avatar (in progress)

### Plan (2026-10-08)
The Void becomes enterable (roadmap S20). A participant is a first-
class entity in a live world � it joins, moves under the same
validated rules as agents, and is visible to them in their
observations � while the simulation keeps ticking without
interruption. The 3D client (Godot, per D001) gets a participant mode:
the operator joins, walks the avatar with WASD, and the camera
follows; the web console gets the mode switch and a movement pad.
Conversation with agents is S21.

### Scope (2026-10-08)
In: the participant entity (join/leave/move routes on the Simulation
API, movement through the same validated action dispatcher as
agents, presence in snapshots and agent observations); the Godot
client's participant mode (P to join/leave, WASD to walk, follow
camera); the console's Observer/Participant mode switch with a
movement pad; a headless participant smoke through the client; tests.
Out: talking to agents (S21), avatar appearance beyond the entity
marker, possession of agent bodies, permissions/ownership between
participants.

### Implementation
- Backend: `WorldHost` owns the participant — `PARTICIPANT_ENTITY_ID`
  (1001, above engine agent ids), join (idempotent, placed on the
  first free floor cell), leave, and a movement route that submits a
  normal `move` action through the world's dispatcher — walls, water
  and occupants all still apply. `GET /participant` reports presence
  and position. The participant is an ordinary entity: it appears in
  snapshots and in agents' observations (`entity` in cells, `kind:
  entity` in nearby), so the Void's inhabitants notice the human.
- Godot client: **P** joins/leaves; in participant mode WASD is mapped
  through the camera yaw onto the grid's cardinal directions (the
  client's +z is the world's south) and submitted at a rate-limited
  cadence; the camera freezes its own flight input and follows the
  participant node. The participant renders amber with a "you" label
  (`world_view.gd`). A `FLOOD_PARTICIPANT=1` headless mode drives the
  full join → move → leave cycle and asserts the avatar moved.
- Console: a participant panel (join/leave, N/E/S/W pad, live
  position) — the Observer/Participant mode switch the roadmap asks
  for.

### Verification
- Tests: pytest **301 passed** (9 new: join places the entity and it
  appears in the state snapshot; not-joined reports none; join is
  idempotent; leave removes the entity; move follows the world's
  rules and rejects bad directions; move without joining is a 409;
  the participant does not stop the simulation (the tick advances
  with the avatar present); agents see the participant in their
  observations; 404s for unknown worlds).
- Client: headless load clean; **PARTICIPANT_SMOKE OK world=68
  moved_to=(4,1)** — join, walk, verify, leave, through the real API;
  the observer smoke and the client unit test still pass (no
  regressions in the free-cam/follow/pick paths).
- Roadmap S20 checklist: the observer can enter Participant Mode and
  move around without stopping the simulation ✅ — the smoke proves
  the join/move/leave cycle on a live backend while the world keeps
  ticking, and the participant is visible to the agents.

### Commits
- `09d797a` — S20: human avatar — participant entity, Godot participant mode, console mode switch, participant smoke [pushed]

## S21 � Human-Agent Conversation (in progress)

### Plan (2026-10-08)
Talk to the Flood (roadmap S21). Speech becomes a real world action:
anyone (participant or agent) can say something, it lands on the
timeline as a SPEECH event, and it is heard only nearby � local
speech, in the world's own terms. The participant targets an agent
within earshot, the agent's next decision sees the message in its
observation, and its reply comes back through the same decision
contract's message field. Conversation logging is the timeline itself
plus a filtered view of it. The console gains a chat box on the
inspector; the Godot client speaks through the same API.

### Scope (2026-10-08)
In: the `say` action (participant or agent) with a SPEECH event and a
speech radius; messages surfacing in agent observations; the
`POST /worlds/{id}/chat` conversation route (targeting, earshot
validation, immediate model reply, response payload); a
`GET /worlds/{id}/conversations` log; the console's chat UI on the
inspector; event formatting for SPEECH/AGENT_MESSAGE in the Godot
client; tests.
Out: agent-initiated conversation (agents speaking first — that is
S22 social interaction), group chat and channels, translation or
memory of past conversations, agent-to-agent dialogue rules.

### Implementation
- `World`: `say` (a validated action for *any* entity) records a SPEECH
  event and enters a bounded rolling buffer; `messages_for` is the ear —
  recent speech within ``SPEECH_RADIUS`` (6 cells, Manhattan), never
  including the listener itself. The observation's `messages` list —
  a placeholder saying "communication arrives in later sprints" since
  S06 — is now real.
- `WorldHost.converse`: the conversation. The participant speaks
  through the same validated `say` action as anyone; the target must be
  within earshot (400 otherwise); the agent then decides *now*, its
  observation carrying what was said, and its reply — the decision
  contract's `message` field — is recorded as speech and returned.
  A scripted agent hears and has nothing to say; the speech is still
  recorded, the reply simply absent.
- The action-injection route now accepts any world entity (the
  participant included), since speech is not agent-only.
- The decision contract's system prompt gained the exchange rule: if
  the observation's `messages` carries someone speaking, the reply
  belongs in `message` — the first live run showed why (the model
  answered with only an action and the reply came back empty).

### Verification
- Tests: pytest **310 passed** (9 new: a SPEECH event recorded via the
  action route; empty messages rejected; hearing is local (near hears,
  far doesn't, nobody hears themselves); the speech buffer bounded;
  the full conversation — human message in, model reply out, both
  utterances on the timeline and in the log with the right kinds;
  chat without joining 409; out of earshot 400; unknown agent 404; a
  scripted agent records the speech with a null reply).
- Live, with a real mind (qwen2.5:7b-instruct, world 72): the
  participant asked "Who are you and what do you see around you?" and
  the agent answered *from its actual observation*: "Greetings! I am a
  small agent exploring this world. I see a wall to the north and a
  body of water to the east." A second exchange logged both ways. The
  reply repeats its surroundings rather than tracking the thread — a
  small-model trait; conversation memory is S22's business.
- Roadmap S21 checklist: human sends a message to an agent and
  receives a model-generated response ✅ (live, through the real API).

### Commits
- `4c20d14` — S21: human-agent conversation — say action, local speech, chat route with model replies, conversation log, console chat [pushed]

## S22 � Social Interaction (in progress)

### Plan (2026-10-08)
Participant mode becomes interactive rather than observational
(roadmap S22): entities can exchange things and move together. Give,
take and a genuinely atomic trade move objects and resources between
adjacent inventories, every transfer recorded on the timeline; follow
makes an entity walk with another (a directive the engine honors in
the tick); and the group route sweeps nearby agents into following
the participant � the Void's first retinue. The verification is the
trade: human hands an object to an agent, both sides validated
before anything moves, and the resulting inventory/world state is
exactly what the timeline says it is.

### Scope (2026-10-08)
In: `give`/`take`/`trade` actions (adjacent targets, whole objects or
resource amounts, atomic trades, TRANSFER events); `follow`/`unfollow`
(directives honored by the engine's tick, FOLLOW events); the group
route (agents within a radius start/stop following the participant);
participant-facing routes; tests.
Out: negotiated consent (an agent deciding whether to accept a trade
— the model's decision, a later sprint), theft rules, group
persistence across worlds, shared inventories.

### Implementation
- `actions.py`: `give` and `take` move one leg (an object by id, or a
  resource amount) between adjacent inventories; `trade` is the atomic
  two-leg swap — both legs are validated before either moves, so a
  failed trade never half-applies. All three require an adjacent
  target and record a TRANSFER event naming kind, what, and both
  parties. `follow`/`unfollow` set and clear directives (FOLLOW
  events); following starts adjacent.
- `world.py`: `transfer_object` (carried objects only — the grid and
  inventories stay distinct), and the follow registry with
  `step_toward`: one validated step per tick toward the target, or a
  no-op once adjacent.
- `engine.py`: a follow directive overrides cognition — a follower
  spends its tick walking with its target rather than deciding.
- The group route is the operator's sweep: agents within a radius
  start (or stop) following the participant, recorded on the
  timeline with `via: group`. It bypasses follow's adjacency
  requirement by design — the engine walks them over.

### Verification
- Tests: pytest **331 passed** (21 new: give/take move objects and
  record them; give requires carrying and adjacency (and refuses
  self-targeting); resource legs; the atomic trade swapping objects;
  a failed trade moving nothing; a mixed object-for-resource trade;
  insufficient offers rejected; follow walking the follower to the
  target; following overriding cognition; unfollow restoring autonomy;
  follow's adjacency rule; and through the API — the roadmap's
  headline (a human trades an object with an agent and the resulting
  inventories/world state are exactly what the timeline says), a
  trade the agent cannot back failing atomically, trade proximity,
  give/take of resources, give-without-joining 409, and the group
  sweep gathering, scattering and moving the group).
- Live (dev API, world 75/76/78): the participant gathered 2 wood,
  gave 1 to an agent, took 1 back (both TRANSFER events on the
  timeline with correct kinds); a world of 3 agents swept into
  following converged on the participant (1, 1 and 11 cells and
  closing), with 3 FOLLOW events recorded.
- Roadmap S22 checklist: human can trade an object with an agent and
  the resulting inventory/world state is correct ✅; participant mode
  is interactive rather than observational ✅ (give, take, trade,
  group — all live).

### Commits
- `688a5ac` — S22: social interaction — give/take/atomic trade, follow directives, group sweep, participant social routes [pushed]
