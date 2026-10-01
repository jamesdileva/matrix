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

- **Next sprint:** S07 — Model Provider Abstraction
- Completed sprints: S01–S06, S06B (2026-09-28)
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
- (this commit) — S06B: 3D world client — Simulation API, Godot client, E2E smoke
