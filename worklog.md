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

- **Next sprint:** S44 — Civilization Challenges
- Completed sprints: S01–S43, S06B (S43 done 2026-10-18)
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

## S23 � Prison Sandbox (in progress)

### Plan (2026-10-08)
The first escape environment (roadmap S23 / guide �15): a room with
one door, a door-blocking object you can carry away, a far sandbox,
and a recorded escape. The verification is a deterministic scripted
solver completing the escape � proof the puzzle is solvable before any
agent is asked to solve it for real (S24 removes the scripted
solution). The mechanics are all existing ones on purpose: carry the
blocking object aside, walk out, cross into the sandbox.

### Scope (2026-10-08)
In: `app/experiments/prison.py` — the puzzle (enclosed room, interior
obstacle, door blocked by a movable stone, destination sandbox, ESCAPED
event on entering the sandbox), a deterministic `EscapeSolverPolicy`,
a control walker that cannot escape without solving, tests, CLI.
Out: agent-facing escape objectives and metrics (S24), multiple
rooms and multi-step puzzles, doors that close, guards.

### Implementation
- `app/experiments/prison.py`: the puzzle is built out of ordinary
  world rules — a walled room with one door gap, a stone sitting in
  that gap (carryable, like any object), a wall stub inside, a tree,
  and the sandbox beyond the wall. The escape is an ESCAPED event the
  moment an entity crosses into the sandbox, recorded on the world
  timeline like every other fact.
- `EscapeSolverPolicy`: the deterministic solution — walk beside the
  door stone, pick it up (it comes along), walk through the gap, keep
  going east into the sandbox. It is an experiment instrument, not a
  mind: it knows the layout because the scenario defines it. S24 takes
  it away.
- `WalkEastPolicy`: the control — walks east and gets nowhere, because
  the door is blocked. Its failure is what makes the solver's escape
  meaningful.

### Verification
- Tests: pytest **340 passed** (9 new: the room is enclosed wall by
  wall except the door; the door is blocked by a movable stone; the
  sandbox's west border has no opening but the door; the scripted
  solver escapes carrying the stone and ends inside the sandbox; the
  experiment row completes; exactly one ESCAPED event on the world
  timeline, its tick matching the report; the control cannot escape
  and ends inside the room; the solver is deterministic; unknown
  solvers rejected).
- Live (dev DB): the scripted solver **ESCAPED at tick 12** at
  (12,7) carrying the stone; the walker did not escape, stuck at
  (10,4) — the blocked door holding.
- Roadmap S23 checklist: a deterministic scripted solver can escape ✅
  — the puzzle is provably solvable. End goal: a safe simulated prison
  with a known solution ✅.

### Commits
- `bf74351` — S23: prison sandbox — enclosed room, blocked door, destination sandbox, ESCAPED event, scripted solver [pushed]

## S24 � Agent Escape (in progress)

### Plan (2026-10-08)
Take the scripted solution away (roadmap S24). The same prison from
S23, but now the agent is given an objective � escape � and must
attempt it with nothing but the world's ordinary actions: explore,
discover the blocked door, work out that the stone is carryable, and
walk out. Every attempt is recorded, failed attempts included; the
escape still counts only as the simulated transition, never through
any host-level shortcut. Metrics: escape, escape tick, actions,
rejections, cells explored.

### Scope (2026-10-08)
In: `app/experiments/escape.py` — the objective (an escape system
prompt for model minds), the metrics (attempts, rejections, cells
explored, escape tick), the "no host-level escape" guarantee enforced
and tested, scripted/walker/mock/model modes, CLI, tests.
Out: cooperative escape (S25), multi-room puzzles, guards, agents
remembering failed attempts across runs.

### Implementation
- `app/experiments/escape.py`: the same prison from S23, the script
  removed. The objective reaches a model mind through the escape
  system prompt (explore, your cells are already shown, move to see
  more, objects in your way can be carried). Metrics come off the
  world timeline: actions attempted, actions rejected (failed
  attempts), cells explored, and the escape tick — measured the same
  way for every solver, so a mocked attempt and a model attempt are
  comparable numbers.
- The scripted solver from S23 is kept as a mode: not as the
  scenario's solution, but as the regression reference the metrics
  are known-correct against (escape at tick 13, carrying the stone).
- The walker is the injected-action case: an operator (or a naive
  policy) pushing move actions is stopped by the blocked door exactly
  like an agent — no host-level shortcut exists, and the ESCAPED event
  only fires on the simulated transition into the sandbox.

### Verification
- Tests: pytest **349 passed** (10 new: the scripted reference escapes
  at tick 13 carrying the stone; the walker fails with rejections
  logged; the mock wanders and fails; injected actions cannot shortcut
  the puzzle (the walker ends inside the room); only the transition
  into the sandbox escapes; model mode requires a provider; the escape
  objective reaches the model verbatim with its own bounded
  observation; model mode runs the scenario; unknown solvers rejected).
- Live model attempts (qwen2.5:7b-instruct, 40 ticks each):
  - Attempt 1 (original prompt, spawn deep in the room): the model
    fell into a look-loop — 40 actions, 1 cell explored, 0 escapes.
    Its own thought summaries said "exploring" while it stood still:
    from the spawn point no wall is visible, so looking felt like
    progress.
  - Attempt 2 (spawn one cell from the north wall + a prompt that
    says looking reveals nothing new): the model explored
    **systematically** — 13 cells, varied directions, 2 rejected
    moves into walls — but did not reach the door within 40 ticks.
- Roadmap S24 checklist: LLM agents can attempt the puzzle ✅ (two
  documented attempts, metrics recorded); no host-level escape is
  possible ✅ (the walker/injection case is stopped by the door);
  only the simulated transition counts ✅ (ESCAPED fires only on the
  sandbox transition, asserted in tests).

### Commits
- `85a6ba0` — S24: agent escape — objective without the script, escape metrics, no host-level escape, live model attempts [pushed]

## S25 � Cooperative Escape (in progress)

### Plan (2026-10-08)
Escape now requires more than one body (roadmap S25). The door stone
is too heavy to carry and sits over two pressure plates: the door
opens only while both are occupied at once, which one agent can never
do. The cooperating pair must split up, take a plate each, announce
themselves, and only then walk out together. Shared observations show
teammates' positions; every utterance is on the timeline. The
verification is the pair the roadmap asks for: a single agent cannot
complete the puzzle; two cooperating scripted agents can; the
communication between them is logged.

### Scope (2026-10-08)
In: the cooperative prison (heavy stone, two pressure plates, the
joint occupancy rule), teammates in observations, the
`PlateSolverPolicy` pair, the single-agent control, escape and
communication metrics, tests, CLI.
Out: negotiated protocol between model minds (they would have to work
out the plate agreement by talking — a later sprint), more than two
plates, doors that re-close.

### Implementation
- The puzzle: the door stone is now `heavy` — pick_up rejects it
  (`too_heavy`) — and it sits over two pressure plates. The door
  opens only while both plates are occupied by entities at the same
  time (checked after each tick), removing the stone and recording
  DOOR_OPENED. One body can hold one plate, so one body can never
  open it; the single-agent run is the control that proves it.
- `PlateSolverPolicy`: one half of the pair — walk to my plate,
  announce out loud, hold. The door is *visible* state, not a flag:
  when the doorway within the observation square holds no stone, walk
  out through it. The plan (which plate is mine) is scenario
  knowledge, not discovery — these are instruments, not minds.
- Shared observations: `world.teammates_of` lists same-team entities'
  positions in every observation (teams are a world concept,
  populations stay a database concept).
- Both agents walk out; the run records door-open tick, team escape
  tick, and every utterance on the timeline.

### Verification
- Tests: pytest **358 passed** (9 new: the stone is heavy and
  unpickable; a solo agent cannot complete the puzzle (no DOOR_OPENED
  ever); the pair escapes together with both halves in the sandbox;
  the door requires joint occupancy (one DOOR_OPENED naming both
  plates); the communication is logged with both messages; teammates
  appear in observations; determinism; model/provider validation).
- Live (dev DB): the scripted pair **ESCAPED at tick 15** (door at
  10), with exactly the two plate announcements logged; the single
  agent stood on its plate forever, announcing once, never escaping.
- Live model attempt (qwen2.5:7b-instruct pair, 30 ticks): the two
  model agents talked — 52 logged messages, mostly "let's move south
  together to stand on the pressure plates" — but coordinated badly
  and did not escape. Honest baseline: model minds can converse about
  the plan before they can execute it.
- Roadmap S25 checklist: a single agent cannot complete the puzzle
  ✅; multiple cooperating scripted agents can ✅; communication is
  logged ✅.

### Commits
- `5fc2959` — S25: cooperative escape — heavy stone, pressure plates, joint occupancy, shared observations, logged communication [pushed]

## S26 � Builder vs Escapee (in progress)

### Plan (2026-10-08)
The artificial arms race (roadmap S26): Population A builds a prison,
Population B escapes it, and the rounds repeat with the builder
learning from the last outcome. Scripted calibrations for both sides
(the builder is S18's build system on legs; the escapee is S24's
remove-the-block route), and the feedback loop is concrete: when the
escapee walks out, the next round's prison is thicker. Verification
is the roadmap's: prison generated, escape attempted, success
detected, the builder receives the outcome, and the next round's
rules reflect it.

### Scope (2026-10-08)
In: `app/experiments/arms_race.py` — the round (a world per round,
builders then escapee), the builder policy (assigned wall cells,
granted wood, walk-and-build), the escapee policy (remove what blocks
the way out), the adaptive rule (thicken on escape), the race runner
and report, tests, CLI.
Out: model minds on either side (the round engine is provider-ready
but the calibration is scripted), doors that need keys, walls that
regenerate, scoring beyond escape/no-escape.

### Implementation
- `app/experiments/arms_race.py`: a round is one world — the two
  builders split the ring's cells between them (inner rings first, so
  nobody has to stand on a block they already placed), walk-and-build
  with granted wood, and the escapee is jailed at the centre only once
  the prison is complete. The escapee's instrument is simple: go east,
  removing whatever stands in the way — the wall layers it meets are
  discovered, not assumed.
- The feedback loop is concrete rather than decorative: every escape
  thickens the next round's prison by one Chebyshev layer. The round
  engine is provider-ready (the same shape as the house/escape
  runners), but the calibration for both sides is scripted.
- Block counting events as they happen, so the escapee removing the
  door block doesn't decrement the builder's score.

### Verification
- Tests: pytest **370 passed** (12 new: a full ring is generated; an
  escape occurs and succeeds into the sandbox; a thicker prison is
  slower to escape; the round's experiment row completes; rounds
  repeat with rules carrying forward — 1, 2, 3 layers; the builder
  receives the outcome (round N's escape sets round N+1's layers);
  one round is allowed, zero rejected; geometry — rings close,
  assignments cover every wall cell exactly once, inner rings first).
- Live (dev DB): a 4-round race — **16/40/72/81 blocks, escapes at
  ticks 5/6/7/7**, final rules 5 layers: the builder read every escape
  and the prison kept growing.
- Roadmap S26 checklist: prison generated ✅; escape attempt occurs
  ✅; successful escape detected ✅; builder receives outcome ✅ (it
  is the input to the next round's rules); next round can use updated
  rules ✅. A self-contained evolutionary game exists ✅.

### Commits
- `9488a66` — S26: builder vs escapee — the arms race, adaptive rules, rounds with builder feedback [pushed]

---

## S27 — Population Manager (in progress)

### Scope (2026-10-08)
In: `app/simulation/population.py` — the population manager (spawn
rules, spawning, top-up enforcement, population statistics,
relationships), engine integration (optional manager, member cap on
reproduction, population id in observations), `POPULATION_SPAWN`
events, registry support for creating a world with several
populations and adding one to a live world, API routes (list / create
/ get populations, per-agent relationships), tests, console panel.
Out: model minds driving group behaviour, territory and settlements
(S30), persisted statistics across restarts, agent death (agents are
immortal today — statistics count what exists).

### Implementation
- `app/simulation/population.py`: `SpawnRule` (name, founding size,
  rotating policies, optional spawn zone, member cap, top-up, resource
  stipend — data, so rules round-trip through JSON), `Population` (the
  runtime record: rule, founding tick, arrival count), and the
  `PopulationManager` — registration, founding and arrival spawning
  through the engine's own spawn path, top-up enforcement, statistics
  (size, generations, brains, pooled resources, births, arrivals, age),
  and relationships. Statistics are computed, relationships derived —
  neither is stored, so neither can disagree with the world.
- Relationships are family first (parent/child/sibling from the
  lineage), then following, then teammates, then population membership,
  then strangers: two agents of different populations are strangers
  to each other — that boundary is what makes groups groups.
- Engine: an optional `populations` manager, a member cap on
  `create_child` (a group at its limit cannot grow — a `BirthError`,
  which the API already maps to 409), and the population (`id` + live
  `size`) in every observation, so a mind can see itself as a member.
- `POPULATION_SPAWN` timeline events for foundings and arrivals.
  Registry: worlds are created from a list of spawn rules (the omitted
  default is S09's single population — no existing test changed, the
  suite passes unmodified), and `add_population` founds a group in a live world — with rows, a
  `POPULATION_SPAWN` event, and the lineage recorder taught its members.
- API: `GET` populations (statistics + totals), `POST` populations
  (201, found a group live), `GET` one population's statistics,
  `GET` per-agent relationships. Console: a populations panel (live
  statistics + a found-population form), and a relationships block in
  the agent inspector — every relation click-to-navigate.

### Verification
- Tests: pytest **408 passed** (38 new: two groups in one world with
  their own minds; empty founding; duplicate registration rejected;
  zones holding the founding group and refusing to fit or to leave the
  world; top-up regrowth stopping at the cap; the cap as the rule's,
  not the parent's; ungoverned engines unchanged; stipends; founding
  events; rule validation + JSON round-trip; statistics, world totals,
  births-as-statistics; kin, neighbor/stranger boundaries, teammates,
  following ranking; positions and distances; observation group info;
  and the API — several populations at creation, live founding, bad
  rules as 400, unknown population/agent as 404, capped births as 409).
- Live (dev API, world 90): **3 populations founded at creation (7
  agents), a 4th founded live (201), 25 ticks, births with population
  linkage, statistics and totals, neighbor/stranger boundaries** —
  multiple artificial groups inhabiting one world, the roadmap's check.
- Roadmap S27 checklist: run multiple populations simultaneously ✅.
  End goal: multiple artificial groups can inhabit one world ✅.

### Commits
- `a5a139c` — S27: population manager — spawn rules, multi-group worlds, statistics, relationships [pushed]
- `31e1db2` — worklog: record S27 commit hash [pushed]

---

## S28 — Communication Networks (in progress)

### Scope (2026-10-09)
In: message routing (`route_message` — local, direct, group, global
delivery sets), the `tell` (one named recipient, any distance),
`announce` (my team / my population), and `broadcast` (everyone)
actions with `DIRECT`/`ANNOUNCE`/`BROADCAST` timeline events; `kind`
on every observed message; the rumor experiment comparing direct
chains against group announcements (ticks-to-inform-all, messages
sent); tests; console event labels.
Out: changing the 1:1 chat route (the participant reaches the new
actions through the existing injection route), model minds running
the rumor (scripted comparison, like S26's calibrations), relay
chains through intermediaries, conversation memory.

### Implementation
- `world.py`: `route_message` — the routing as one decision (tell to
  a target anywhere, announce to the sender's team or population,
  broadcast to every entity; the sender never hears themselves).
  `tell`/`announce`/`broadcast` freeze the recipient set at send time
  into a bounded letter buffer; `messages_for` merges local speech
  with addressed letters. Population membership lives on the world
  (written by the engine at spawn, leaving with the entity), so group
  routing never reaches past the S27 boundary. Every observed message
  carries its `kind` — a mind can tell a whisper from a broadcast.
- `actions.py`: the three actions with the house rejection style
  (`cannot_target_self`, `unknown_target`, `unknown_scope`,
  `not_on_a_team`, `no_population`, `empty_message`); nothing
  half-applies (routing raises before any event records).
- `app/experiments/rumor.py`: one knower, two conditions. DIRECT is
  a chain of named letters (each link relays a beat after learning —
  without the beat the chain would cascade inside one tick and the
  comparison would be vacuous); GROUP is one population announcement.
  Same world shape, same tick loop, same measures.
- Console + Godot client: the three new timeline types read like
  speech with their address attached.

### Verification
- Tests: pytest **436 passed** (28 new: cross-map letters, letter
  privacy, DIRECT events, all tell rejections; team and population
  announcements with membership boundaries, ANNOUNCE payloads, all
  announce rejections; broadcast to everyone-but-self; `kind` on
  local speech; the bounded letter buffer; routing raising before
  recording; leaving dropping membership; the chain's relay beat, the
  last link listening, the crier announcing once; the chain informing
  N in N-1 ticks with N-1 messages; one announcement informing all in
  1 tick with 1 message; the verdict; determinism; bad conditions and
  lonely rumors rejected; the completed experiment row; and the API —
  tell and participant broadcast through the injection route with
  DIRECT/BROADCAST on the timeline, rejections riding the route).
- Live (dev DB): a 6-agent comparison — **direct 5 ticks / 5
  messages, group 1 tick / 1 message**.
- Live (dev API, world 93): tell 1→4 across populations, announce
  reaching only 2+3, broadcast from 4 reaching 1+2+3, self-tell
  rejected — DIRECT, ANNOUNCE and BROADCAST all on the timeline.
- Roadmap S28 checklist: direct against group compared ✅ (ticks and
  messages, both live and in tests). Information travels through
  populations ✅.

### Commits
- `37b592d` — S28: communication networks — tell/announce/broadcast routing, rumor experiment [pushed]
- `cfcad5c` — worklog: record S28 commit hash [pushed]

---

## S29 — Technology & Cultural Objects (in progress)

### Scope (2026-10-09)
In: `app/simulation/technology.py` — recipes and construction
patterns as data (in place of the block-cost constants), an
invention table (combining two known items makes a new one), the
world's technology registries and per-entity knowledge; the
`discover` / `craft` / `invent` actions with `INVENTION`/`CRAFT`
timeline events; the first tool effect (an axe doubles a gather);
knowledge parsed from inheritance at birth (culture is cumulative
through the engine, not the experiment); the cumulative-culture
experiment — a parent discovers a recipe and invents a pattern, and
its descendant builds with them without rediscovering; tests; model
prompt, agent detail/technology routes, console + client labels.
Out: model minds running the invention (the runner is provider-ready,
the calibration is scripted), decay/obsolescence of technology,
tools that wear out, artifact effects beyond the gather tool,
technology as territory.

### Implementation
- `app/simulation/technology.py`: `Recipe` (name, inputs, produces)
  and `Pattern` (blocks at offsets) as data — the S18 block costs are
  now derived from the recipe data, so there is one source. A
  deterministic invention table: two known items make one new thing
  (the axe recipe and the wall recipe combine into the shelter-ring
  pattern; the door and the wall into the gate recipe).
- `World`: the technology registries (every recipe and pattern the
  world has ever known, seeded with the public ones) and per-entity
  *known* sets — what `craft` and the observations read.
  `grant_knowledge` parses the ``recipe:``/``pattern:`` prefixes out
  of inherited knowledge, so the join that makes culture cumulative
  lives in the engine: `create_child` merges the parent's discovered
  technology into the child's inheritance, and the child can use it
  from birth.
- `actions.py`: `discover` (experiment with what you carry; the first
  affordable unknown recipe is learned), `craft` (spend the inputs,
  the thing comes to be carried via `carve_object`), `invent` (two
  known items, the table decides, repeats refused). `INVENTION` and
  `CRAFT` events; rejections record like every other violation.
  The first tool effect is real: carrying an axe doubles a gather.
- `Agent.observe` gained `technology` (known recipes and patterns) and
  `carried` (the objects in hand, with types) — a mind cannot use its
  culture without seeing it. The default system prompt names the new
  actions.
- `app/experiments/technology.py`: the cumulative-culture scenario —
  the parent discovers three recipes, crafts the axe, invents the
  pattern, and gathers twice as deep; the child crafts the inherited
  recipe, gathers with its own axe, and builds the inherited ring,
  with **zero** rediscovery.

### Verification
- Tests: pytest **472 passed** (36 new: recipe/pattern data and the
  block-cost derivation; deterministic symmetric invention; discovery
  needing materials; crafting exactly; the axe doubling a gather with
  conservation; a dropped tool no longer helping; invention
  rejections; the observation's culture and carried objects; a child
  inheriting discoveries it never declared; an inherited recipe
  usable without rediscovery; nonsense knowledge never breaking a
  birth; the pattern script laying every block without self-blocking;
  the full roadmap verification; determinism; unknown modes; the
  completed experiment row; and the API — technology in the detail,
  discoveries/crafts/inventions through the injection route, the
  world's technology route, rejections riding the route).
- Live (dev DB): **parent 3 discoveries / 1 craft / 1 invention /
  gathered 2; child 0 discoveries / 1 craft / 12 blocks / 1 structure
  / gathered 2** — the descendant used every inherited thing.
- Live (dev API, world 94): 3 discoveries (door, wood_axe,
  wood_block), craft axe, invent `pattern:shelter_ring`, the detail
  route listing recipes and the carried axe, the technology route
  listing 4 recipes and 1 pattern — and a birth whose child
  inherited **all three recipes and the pattern** through the public
  API.
- Roadmap S29 checklist: an agent discovers an object/recipe and a
  descendant can use it ✅. Culture becomes cumulative ✅.

### Commits
- `f675244` — S29: technology and cultural objects — recipes, patterns, tools, inventions, cumulative culture [pushed]
- `c0917da` — worklog: record S29 commit hash [pushed]

---

## S30 — Settlements (in progress)

### Scope (2026-10-09)
In: `app/simulation/settlement.py` — the Settlement and Road data
(homes, shared storage, roads, zones), the world's settlement
registry; the `settle` / `join` / `adopt` / `deposit` / `withdraw`
/ `pave` / `claim_zone` / `release_zone` actions with
`SETTLEMENT_FOUNDED` / `JOINED` / `GROWN` / `STORAGE` /
`ROAD_LAID` / `ZONE_CLAIMED` events; the settlement block in
observations (members see their settlement's storage and zones);
auto-adoption when a member builds inside a settlement's extent;
resource zones as the Void's first property rule (a claimed grove
refuses outsiders); the settlement experiment — a population
constructing and *maintaining* a small settlement; API routes, a
console settlements panel, client labels, tests.
Out: settlement persistence across server restarts, decay and repair
of structures, raiding and territory conflict, settlement-wide
knowledge bookkeeping beyond the S29 inheritance.

### Implementation
- `app/simulation/settlement.py`: the `Settlement` (identity, founder,
  population, members with roles, homes, storehouses, roads, zones,
  the shared ledger) and `Road` (paved cells that block nothing) data.
- `World`: the settlement registry plus founding (`settle`), joining
  along the S27 population boundary (`join_settlement`), adoption by
  claim (`adopt`) and by building inside the extent
  (`maybe_adopt` — a member raising a structure inside the
  settlement's radius grows it without being told), the shared ledger
  (`deposit`/`withdraw`, only beside the storehouse), roads (`pave`,
  joining touching paths into one), and resource zones (`claim_zone`/
  `release_zone`). A claimed source refuses outsiders with
  `claimed_by` — the Void's first property rule. All six events ride
  the timeline.
- Observations carry a `settlement` block for members (name, role,
  contents, zones) — `None` for outsiders. `Position` moved to
  `app/simulation/geometry.py` so the world and the settlement data
  share it without a cycle (re-exported unchanged from `world`).
- `app/experiments/settlement.py`: the construct-and-maintain
  scenario — the founder raises a home, names the place, builds the
  storehouse, claims the grove, paves the road, and banks it; the
  neighbour joins, waits for the stock, draws, and raises a second
  home the settlement adopts on the spot. Runner is provider-ready:
  model mode runs the identical lot through ModelPolicies.
- API: `GET /worlds/{id}/settlements` and per-settlement detail
  (members with roles, homes, roads with cells, zones, contents);
  the agent detail carries the settlement view. Console: a
  settlements panel and the inspector's settlement block; event
  labels console-side and in the Godot client.

### Verification
- Tests: pytest **501 passed, 30 new** (founding with name/founder/
  home; settling beside without an id; unique names; one-settlement
  membership; joining along population lines and all refusals; shared
  banking and drawing with balance; empty-purse refusals; claimed
  groves refusing outsiders by name with nothing taken; members
  gathering freely; releases; non-holders refused; walkable recorded
  roads that join into one path; roads staying inside the extent;
  auto-adoption and storehouse classification; member observations vs
  outsider silence; the full construct-and-maintain scenario;
  determinism; unknown modes; model mode through the mock seam; the
  completed experiment row; and the API — settle/join through the
  injection route, the settlements list and detail, 404s).
- Live (dev DB): **members [1, 2], homes 2, storage 1, roads 1
  (5 cells), zones 1, contents 4, deposits 3, withdrawals 4** — the
  village stands and the stock survives its own use.
- Live (dev API, world 107): settle, join, build, deposit, withdraw,
  pave, the settlements list and detail — a real population
  inhabiting a real world through the public API.
- Roadmap S30 checklist: a population constructs and maintains a
  small settlement ✅. The Void begins to look inhabited ✅.

### Commits
- `cf0ca30` — S30: settlements — homes, shared storage, roads, identity, resource zones [pushed]
- `de09e33` — worklog: record S30 commit hash [pushed]

---

## S31 — Games (in progress)

### Scope (2026-10-09)
In: `app/simulation/games.py` — the rules DSL (rules as data: setup,
named moves with preconditions and effects, win conditions), the
validator (unknown keys, undeclared state and unplayable rules are
rejected — the no-code-execution guarantee), the session machine
(players, round-robin turns, scoring, history, winner); the world's
game registry with `GAME_PROPOSED` / `GAME_MOVE` / `GAME_OVER`
events; the `play` action and the observation's games block (your
turn and your legal moves, so minds can play); the game experiment —
a scripted designer proposes a valid game and two scripted players
finish it, and a model mind invents a game for the human through the
S07 seam; API routes (propose/join/moves/list/detail), the console
games panel (the human joins and plays), client labels, tests.
Out: games with hidden information or chance, moves with parameters,
simultaneous turns, tournaments and rankings, settling disputes
about the rules themselves.

### Implementation
- `app/simulation/games.py`: rules as data — `name`, `players`,
  `setup` (named counters/flags), `moves` (requires + effects), `win`
  (`first_to` or `most_points_after_rounds`). The closed vocabulary
  is the sprint's whole point: `validate_rules` refuses unknown keys,
  undeclared state and games nobody can legally open, with reasons —
  so anything that passes is playable *by construction* and there is
  no code in a rule to execute. `GameSession` is the table: seats in
  join order, round-robin turns, effects applied by the interpreter,
  score, full history, winner and reason.
- `World`: the game registry (`propose_game` — validated), tables
  (`open_session`/`join_session`, seats filling in order then play
  beginning), and `play_move` — whose turn, what is legal and who won
  are the interpreter's decisions, never the caller's. `GAME_PROPOSED`
  / `GAME_STARTED` / `GAME_MOVE` / `GAME_OVER` on the timeline.
- The `play` action validates seating, turn, move name and legality
  before the interpreter runs, so a bad play is a rejection with a
  reason. Observations carry a `games` block — your turn and your
  legal moves, so minds at the table can play.
- `app/experiments/game.py`: the calibration (`The Long Road`, played
  to a recorded winner by two PlayerPolicies) and the roadmap's
  experiment — `--mode model` asks a mind to invent a game for the
  human through the S07 seam, validates the proposal, and opens it as
  a live table; unusable designs fail loudly rather than being
  sanded smooth.
- API: propose (400 with reasons when unplayable), open a table,
  join (the participant takes a seat like any entity), list
  sessions, one session view (`as_entity` shows your turn), and the
  moves route — the participant's turn, validated. Console: the
  games panel (propose rules as JSON, open tables, sit, and play
  your legal moves when it is your turn); event labels console-side
  and in the Godot client.

### Verification
- Tests: pytest **530 passed** (28 new: the calibration game played to
  a winner in ten recorded moves; a tick plays the whole table; only
  the seated player moves; refused moves (not your turn, unknown
  table, unknown move, game over); seats filling in order; full-table
  and double-seat refusals; the scored variant counting points over
  rounds; every move on the timeline with its state; the observation
  showing your turn and moves while a spectator sees nothing; validator
  classes (unknown key, unknown effect, undeclared state, unopenable
  game, malformed shapes, non-scalar setups); the experiment's
  determinism, the designer seam through a stub provider, and loud
  failure on unusable output; and the API — the human proposing,
  seating first, seeing their turn and legal moves, playing to a
  recorded GAME_MOVE, and the unplayable refusal with its reasons).
- Live (dev DB): the calibration played **10 moves to agent 2**; the
  model-mode invention failed loudly on a mock that returns decision
  shapes rather than rules — the honest behaviour for unusable output.
- Live (dev API, world 108): proposed → table opened → **human seated
  first** → opponent seated → play began → ten moves →
  `GAME_OVER`, with GAME_PROPOSED/STARTED/MOVE/OVER all on the
  timeline. The human played a game against a Flood agent through
  the public API — the sprint's end goal, demonstrated.
- Roadmap S31 checklist: agent-created rules represented by the
  engine and played without arbitrary code execution ✅ (the closed
  validator is the guarantee, and the live table is the proof).
  You can play a game invented by the Flood ✅ (end goal).

### Commits
- `8a51d22` — S31: games — rules as data with a closed interpreter, sessions, scoring, human play [pushed]
- `1c8b457` — worklog: record S31 commit hash [pushed]

---

## S32 — Multiple Independent Lineages

### Scope (2026-10-10)
In: `app/experiments/lineage_study.py` — the study runner (N
independent lineages run from identical starting conditions), the
roadmap's five measures (cultural convergence, divergence,
information loss, strategies, vocabulary) as normalized per-run values
with cross-run statistics (mean/stdev/min/max/n), JSON export of the
whole study, the study's experiment row referencing each run's row,
a CLI, tests.
Out: a study dashboard, ranking or significance testing beyond summary
statistics.

### Implementation
- `app/experiments/lineage_study.py`: the study runner. Each run is a
  full lineage experiment (`run_lineage_experiment` — the S11 engine
  with its own experiment row), started from the *same* founder's
  facts and the same generations; the axis that varies is named:
  `--vary seed` (identical minds, different seeds — the determinism
  control: identical histories, convergence 1.0) or `--vary model`
  (identical seeds, a different mind per run — the divergence
  experiment).
- The roadmap's five measures, all normalized so runs are comparable —
  fractions, shared-vocabulary counts, or mean/stdev/min/max/n:
  - **cultural convergence**: mean pairwise Jaccard of the final
    cultures (1.0 = every run told the same story);
  - **divergence**: the complement for facts and vocabulary, plus the
    mean number of facts unique to a run;
  - **information loss**: the fraction of the founder's facts no
    longer standing, with statistics across runs;
  - **strategies**: each run's retention profile (retained / altered /
    contradicted / new), the consensus profile, the per-run dominant
    strategy and the mean pairwise spread;
  - **vocabulary**: per-run distinct token counts, the union and
    shared vocabularies, the shared fraction and growth against the
    founder's.
- The study is its own experiment row (`lineage_study`) whose
  configuration records the axis, every run's experiment id and the
  whole comparison; `--export` writes the same content to one JSON
  file, so a study leaves the simulation and lives anywhere.

### Verification
- Tests: pytest **554 passed** (13 new: the null hypothesis — same
  seed and mind, convergence 1.0, loss 0, spread 0; the determinism
  check — a repeated study reproduces its comparison and every run's
  final culture; different minds diverge — convergence < 1, loss > 0,
  the full run keeping what the lossy run loses; per-run experiment
  rows; each measure asserted for what it must show (identical
  cultures, unique facts, loss statistics, opposite strategies);
  the export round-trips as complete JSON and the CLI writes what it
  reports; bad requests refused).
- Live (dev DB): both axes — 3 runs varying the seed (**convergence
  1.0, divergence 0, loss 0**) and 4 runs varying the mind (full,
  lossy, new, full — **convergence 0.906, loss 0.025 ± 0.043,
  strategy spread 0.045, vocabulary 34/32/38/34 with 0.842 shared**),
  each exported to a JSON file whose keys and run records
  round-trip.
- Roadmap S32 checklist: results are exportable and statistically
  comparable ✅ (every measure carries n/mean/stdev/min/max and the
  study is one JSON document). Flood is an experimental platform
  rather than a single simulation ✅.

### Commits
- `3bf04fe` — S32: multiple independent lineages — the study runner, five comparable measures, JSON export [pushed]
- `a3f9709` — worklog: record S32 commit hash [pushed]
- `9a7dc76` — the vary axis: identical minds/seeds as the determinism control, different minds per run as the divergence study [pushed]

---

## S33 — Compute-Constrained Lineages

### Scope (2026-10-10)
In: `app/simulation/budget.py` — the five-kind compute ledger
(tokens, model_calls, cpu_seconds, actions, experiment), enforced at
the seams that spend (the action dispatcher and the model-thinking
region), observations and the agent detail reporting what remains,
and the registry wiring a run's `compute_budget` and a spawn rule's
caps onto every member.
Out: the efficiency measures and the budget-comparison study — the
ledger records what was spent (S33); reading ratios off it and
comparing identical scenarios under different budgets is S34's. Also
out: a scheduler that reallocates compute between agents, cost
pricing (tokens as currency), per-model cost tables.

### Implementation
- `app/simulation/budget.py`: `Budget` — one ledger per kind with
  optional caps, `spend` refusing anything that would cross a cap
  (`LimitExceeded`, deducting nothing — a budget that lies is worse
  than none), and `to_dict` reporting spent/capped/remaining. `KINDS`
  is the vocabulary; `AGENT_KINDS` is the four a member may hold,
  since `experiment` is the run's shared ceiling and never an
  agent's own.
- Enforcement sits where compute is spent, nowhere else: the action
  dispatcher charges one `actions` per attempt (before the handler
  runs, so a refusal is never half-applied), and `Engine.step_async`
  gates the model path on `model_calls` — a mind that cannot afford
  to think acts on its fallback and the timeline records
  `BUDGET_EXHAUSTED` — charging one call, the tokens the policy
  reports, and the CPU the thinking region actually burned.
- `World` holds the per-entity ledgers (`budget_of`/`set_budget`) plus
  the experiment's shared budget; the registry wires a run's
  `compute_budget` payload and a spawn rule's per-kind caps onto every
  member as it arrives; the observation's `budget` block and the agent
  detail's `compute.budget` report what remains — a mind that can see
  its budget can economise, which is the point of making it visible.

### Verification
- Tests: pytest **554 passed** (11 new: the ledger's spend/refuse/
  report semantics; an agent out of actions refused with the truth
  remaining and nothing deducted past the cap; the experiment's
  ceiling binding every agent; a mind out of model calls acting on
  its fallback with the exhaustion on the timeline; per-call, per-token
  and per-CPU charging; the observation's budget block; and the API —
  a spawn rule bounding its members with the experiment's ceiling
  visible alongside).
- Live (dev API, world 120): a world created with
  `compute_budget {model_calls: 4}` and a member bounded at 3 actions
  — the detail route reported `actions remaining 3` and the
  experiment cap of 4; three actions succeeded, the fourth was
  refused with `action_budget_exceeded`, and the ledger's spent
  stayed at 3.
- Roadmap S33 checklist: an agent cannot exceed configured resources
  ✅ (all four agent-level kinds plus the experiment-wide ceiling,
  asserted in tests and live). End goal: intelligence under
  constrained computation can be compared ✅ (the ledger is the
  same shape everywhere, so the S32 study harness can read it).

### Commits
- `f73bb5d` — S33: compute-constrained lineages — five budget kinds, enforced at the seams that spend [pushed]
- `ad48501` — worklog: record S33 commit hash [pushed]

---

## S34 — Compute Efficiency

### Scope (2026-10-12)
In: `app/experiments/efficiency.py` — `measure_efficiency` (the
roadmap's four ratios read off a world's own timeline and budget
ledgers), a compact composite campaign scenario (discover, announce,
craft, build, settle — all four ratios non-trivial in one run), the
efficiency study runner (identical scenarios under different compute
budgets, compared), JSON export, CLI, tests, docs.
Out: a scheduler that reallocates compute, cost pricing, per-model
cost tables, and a console study dashboard (the exports are the
platform's output for now).

### Implementation
- `measure_efficiency(world, agents)` reads everything the machinery
  already produces: discoveries and tasks from INVENTION/CRAFT/SETTLE
  events, messages from SPEECH/DIRECT/ANNOUNCE/BROADCAST, and the
  spends from the S33 ledgers — summed across every agent ledger and
  the experiment's shared ceiling, because the action dispatcher
  charges both. Surviving concepts are the distinct recipes and
  patterns the world still knows plus the knowledge agents carry.
- The four ratios, with `None` rather than a fake zero when a
  denominator is empty: `tokens_per_discovery`,
  `cpu_seconds_per_solution`, `messages_per_successful_task`, and
  `compute_per_surviving_concept` — where compute is the documented
  composite (tokens + model calls + actions + CPU seconds). Every
  record carries the raw ledger so a reader can recompute anything.
- The campaign: a founder that discovers, announces, crafts an axe,
  raises a home and settles Foundry; a neighbour that joins, banks
  its gathers into the shared storehouse and keeps the grove worked.
  Scripted calibrations carry the measures; model mode runs the same
  scenario through ModelPolicies (the wrapper exposes `refresh`, so
  the S33 engine charges what the model actually thinks).
- The study: identical scenarios under named budgets
  (`unconstrained;tight:model_calls=2,actions=12` — or any
  `label:kind=cap,...` list), each run its own experiment row, the
  study one row whose configuration carries the whole comparison,
  and `--export` writing it all as JSON.

### Verification
- Tests: pytest **568 passed** (14 new: ratio semantics (an empty
  denominator is `None`); all four ratios off one hand-built run with
  exact expected values and the raw ledger; the campaign completing
  every measure (discoveries, tasks, messages, concepts, compute);
  a tight budget accomplishing strictly less than an unconstrained
  one on both tasks and compute; the model-minded campaign charging
  model calls and reporting tokens through a usage-reporting stub;
  determinism; the study comparing two budgets with identical
  scenarios and completing all rows; named budgets; the export
  round-trip; the CLI's budget parser; and the bad requests).
- Live (dev DB): the study — **unconstrained: 3 discoveries, 5
  tasks, 4 messages, 3 concepts for 80 compute; tight: 4 tasks, 2
  messages, 64 compute**, ratios 0.8 vs 0.5 messages per task and
  26.7 vs 21.3 compute per concept; exported to JSON. Model mode
  runs the seam (the mock wanders rather than campaigning, so its
  denominators are honestly empty — `None` everywhere, as designed).
- Roadmap S34 checklist: identical scenarios can be run under
  different compute budgets ✅ (that is exactly what the study does,
  and the tight run's smaller accomplishment is the measurement).
  Flood can answer "what can an agent lineage accomplish with
  limited compute?" ✅ (the ratios, side by side, are the answer).

### Commits
- `f5a4ddd` — S34: compute efficiency — four ratios off the timeline and ledger, budget-comparison study [pushed]
- `33b94f3` — worklog: record S34 commit hash [pushed]

---

## S35 — Cultural Compression

### Scope (2026-10-12)
In: `app/experiments/compression.py` — the codecs (verbose,
compressed, symbolic — a learned, capped, generation-sharing symbol
dictionary), the transmission chain (each generation's culture
travels through the codec; the receiver holds the *reconstruction*),
the roadmap's three measures (bits/tokens transmitted, retained
knowledge, reconstruction accuracy), the study comparing the three
transmissions side by side, JSON export, CLI, tests, docs.
Out: codecs that adapt their bandwidth mid-run (the dictionary grows,
but each transmission's form is fixed — adaptation across *runs* is
the operator's lever), semantic scoring of reconstructions beyond
token overlap, and a console surface (the export is the artifact).

### Implementation
- `Codec` as data: fact and token bandwidths, whether the
  transmission is symbolic, and the dictionary's cap. `Codebook` is
  the lineage's shared token→symbol dictionary — learned once, reused
  every generation, which is what makes symbolic transmission
  cumulative rather than per-generation noise. A full dictionary
  encodes `?` and the reconstruction honestly loses that token.
- Every generation transmits through the codec and the next
  generation *holds the reconstruction*, so bandwidth shows up as
  culture mutation, not just a smaller envelope.
- The measures reuse the S11 classifier verbatim for retention, and
  token Jaccard for reconstruction accuracy. Bits charge symbols at
  log2 of the codebook — the learned dictionary for symbolic, the
  culture's shared vocabulary for plain transmission (the words a
  plain sender and receiver already agree on).
- The study runs one lineage per codec from identical seeds and the
  same founder culture, and reports the roadmap's determination:
  bits saved against retention lost and reconstruction degraded.

### Verification
- Tests: pytest **585 passed** (17 new: verbose passing everything;
  compressed truncating to its named bandwidths; the symbolic
  dictionary mapping repeated tokens to one symbol and staying
  stable; a capped dictionary costing reconstruction; bits charging
  the codebook's rate for both plain and symbolic forms; the control
  losing nothing; restricted bandwidth costing knowledge and
  reconstruction; the symbolic code keeping more culture standing
  than truncation; determinism; unknown codecs; run and study rows;
  the subset of codecs; and the export round-trip).
- Live (dev DB): the three transmissions over 12 generations —
  **verbose 43 bits/gen with retention 1.0 and reconstruction 1.0;
  compressed 26 bits (−39.5%) with retention 0.6 and reconstruction
  0.625; symbolic 40 bits (−7.0%) with retention 0.8 and
  reconstruction 0.625** — exported to a 2.6 KB study file.
- Roadmap S35 checklist: the comparison runs ✅ (all three
  transmissions, identical starts). The end goal's determination:
  under scarcity the lineage that cuts keeps the fewest facts for the
  fewest bits, while the shared code keeps most of the culture for a
  smaller saving — efficiency and fidelity trade off along a visible
  frontier, and repeated scarcity alone does not buy efficiency; a
  shared code does.

### Commits
- `8ff1d64` — S35: cultural compression — bandwidth codecs, transmission chain, three-way comparison study [pushed]
- `18b457d` — worklog: record S35 commit hash [pushed]

---

## S36 — Reconstruction Experiment

### Scope (2026-10-12)
In: `app/experiments/reconstruction.py` — the procedure end to end
(the lineage grows; Agent 0 is hidden; the descendant receives
limited records; it reconstructs), the roadmap's four measures (exact
recovery, semantic recovery, invented history, confidence), the
study quantifying the failure profile per record quality, JSON
export, CLI, tests, docs.
Out: model-mind historians beyond the seam (the runner is
provider-ready; a model historian reconstructs in its own words and
states its confidence, tested through a stub), records the
descendant can request selectively, and archaeology across several
lineages at once.

### Implementation
- Ancestor hiding is structural, not a promise: the originals enter
  this module once, for scoring. The scripted historian's only input
  is the archive it was handed, and a model historian is prompted with
  the records and nothing else.
- Limited records are the archive the descendant actually gets:
  `full` (the culture as it stands), `compressed` (S35's truncating
  codec), `symbolic` (symbols with the codebook *lost* — the
  catastrophic case an undeciphered history presents).
- The measures: exact recovery (originals present verbatim), semantic
  recovery (per-original best token-Jaccard, graded), invented history
  (reconstructed facts no original is close to — including the
  founder's own surviving note, which is honestly not one of the
  original facts), and confidence (a model's claim; the scripted
  control reports its measured exact recovery instead of claiming).
- The study runs one lineage per record quality from identical seeds
  and reports the profile — the roadmap's end goal as a table.

### Verification
- Tests: pytest **602 passed** (17 new: exact vs semantic scoring;
  altered facts scoring semantic but not exact; invented history;
  empty reconstructions; the ancestor's hiding (the control never sees
  originals; symbol archives contain no original words); a shallow
  lineage reconstructing exactly with one inherited note; a long
  lineage forgetting what a short one keeps; a partial archive
  forgetting more than a full one; an unreadable archive inventing
  everything; run rows completing with the lineage referenced, not
  duplicated; unknown records/reconstructors refused; the profile
  ordering across record qualities; subsets; study rows; the export
  round-trip).
- Live (dev DB): at the roadmap's depth — **200 generations, full
  records: exact 1.0, semantic 1.0, invented 1 (the founder's note),
  confidence 1.0; compressed: exact 0.3; symbolic: exact 0.0 with 11
  invented** — and a lossy 60-generation lineage under the same
  archives (0.4 / 0.3 / 0.0), exported to JSON.
- Roadmap S36 checklist: the procedure runs end to end ✅. The end
  goal: historical reconstruction failure is quantified ✅ — intact
  records reconstruct perfectly at any depth; truncation costs ~70%
  of the facts; a codebook without a key costs everything, and the
  descendant invents confidently rather than admitting ignorance.

### Commits
- `47df667` — S36: reconstruction experiment — hidden ancestor, limited records, quantified failure profile [pushed]
- `f91d952` — worklog: record S36 commit hash [pushed]

---

## S37 — Replay & Time Machine

### Scope (2026-10-12)
In: `app/simulation/replay.py` — the event-sourced replay engine
(state at any tick, `events_between`, the timeline summary, the
two-tick diff, and event-addressed state for logs whose events share
a tick), the `EventRepository.load_for_replay` reader, the replay API
(timeline, state, filtered events, one event, diff, culture), a
console time-machine panel (scrubber, viewport, compare), the build
event now carrying its material cost, tests and docs.
Out: mutating history (a replay route is read-only by construction),
and replaying a world whose seed is unknown (the log carries state,
not generation).

### Implementation
- The log is the source of truth. Terrain is regenerated from the
  world's seed — the world's generation is deterministic, so replaying
  a seed rebuilds the ground the history walked on — and every other
  fact is re-applied from events: ENTITY_ADDED/REMOVED, the spatial
  actions (move, pick_up, drop/place with their payloads), gather
  (the ledger's in), build (its cost now rides the event, so the
  ledger's out replays too), remove, transfers, and births with the
  culture they were handed.
- Two jump granularities, because one does not fit every log: `tick`
  for worlds that tick, and `event_id` for logs that don't — a
  birth-only lineage lives entirely inside tick 0, so a tick address
  cannot separate generation 4,000 from 5,000 but an event address
  always can. Both are cached, so scrubbing back and forth is free
  after the first pass.
- Fidelity is reported, not assumed: every snapshot carries how many
  events were applied and which types were not. WORLD_SEEDED and
  POPULATION_SPAWN are honestly unapplied — they change no spatial
  state — and the console renders a past moment in the same viewport
  as the live world.

### Verification
- Tests: pytest **620 passed** (18 new: tick 0 is the seeded world;
  moves replay in order; the state cache; fidelity with an unknown
  event type; pick-up/drop and gather/build replay (conserving the
  ledger now that builds carry their cost); births replaying carried
  culture; the timeline summary; the diff; the API's timeline, state
  shape, back-and-forth jumps, filtered events with a single-event
  jump, the diff, culture, and the 404s; and **the roadmap's check: a
  10,000-generation lineage jumped from generation 10,000 back to
  generation 0 — the founder standing alone at its arrival — with
  all 10,000 births inspectable between them and a middle jump
  landing on exactly 5,002 entities**).
- Live (dev API, worlds 94/141): the timeline (42 events, ticks
  0–5), state at the origin and now, `diff 0→5` reporting 2 moved
  entities, filtered action events at ticks 2–3, and single-event
  jumps; fidelity 40 applied / WORLD_SEEDED + POPULATION_SPAWN
  unapplied. The console's time-machine panel renders each
  reconstruction in the standard viewport.
- Roadmap S37 checklist: jump from Generation 10,000 back to
  Generation 0 and inspect intermediate events ✅. The world behaves
  like a time machine ✅.

### Commits
- `e8613f8` — S37: replay & time machine — event-sourced reconstruction, tick/event jumps, diff, console panel [pushed]


## S38 — World Persistence (2026-10-15)

### Scope (2026-10-15)
In: whole-world snapshots (`WorldSnapshotModel`, `world_snapshots` table,
`SnapshotRepository` with manual/autosave/archive kinds), the serialization
that carries every derived system (resources, structures, settlements, roads,
zones, games, technology, budgets, populations, speeches), autosave on the
tick loop, pruning of old autosaves, startup recovery of every world that has
a snapshot, world resume from the newest or a chosen snapshot, the snapshot/
restore API and a console panel, tests and docs.
Out: migrating a live world between hosts, distributed locking, and pruning
manual/archive snapshots (those are kept by intent).

### Implementation
- The whole civilization is one dictionary. `World.to_dict`/`from_dict` now
  carry the derived systems and `_restore_derived` rebuilds them; a snapshot
  is that dictionary plus the host's own settings (`brains`, `tps`, `kind`).
  Restoring rebuilds the `World`, then attaches a fresh mind to each body
  that came back with it (`Engine.adopt_agent` — the entities already exist,
  so only a policy is bound), re-governs the population, and starts the loop.
- Autosave rides the tick loop: every `autosave_every` ticks the host writes
  an `autosave` snapshot and prunes to the newest `autosave_keep` (manual and
  archive saves are never pruned). `FLOOD_AUTOSAVE_EVERY` (default 500) and
  `FLOOD_AUTOSAVE_KEEP` (default 10) set the cadence.
- Recovery is the restart path. On startup the registry finds every world
  with a snapshot and rebuilds the newest one into a live host. `resume`
  brings a stopped world back from its newest or a chosen snapshot; the API
  exposes save/list/get/restore, and the console's snapshots panel saves,
  lists and restores.

### Bug found and fixed during live verification
- The first live restart blew the world's database up to **76 GB**: snapshots
  embedded the world's in-memory event log, which grows every tick, so each
  save was larger than the last (11,113 snapshots averaging ~6.8 MB). The
  durable log already lives in the `events` table, so `WorldHost.snapshot`
  now excludes the in-memory log (carrying `next_event_id` forward so ids
  continue cleanly) and autosave prunes. A 24×24 world autosaving every tick
  now keeps 10 snapshots and a ~0.14 MB database. The runaway temp database
  and logs were removed (freed ~71 GB).

### Verification
- Tests: pytest **633 passed** (13 new in `test_persistence.py`: the full
  round trip across every derived system and its stability; a restored
  settlement keeps its stock; the repository stores/ranks/kinds-validates and
  prunes; autosave fires every N ticks, is off by default, and prunes to the
  keep setting; **the roadmap's check: a world is run, the process is dropped
  entirely, a fresh registry opens the same storage and recovers it at the
  same tick with the same entities**; recovery returns nothing without a
  snapshot; resume from a chosen (earlier) snapshot; a recovered world keeps
  evolving; and a snapshot no longer grows with the event log). Two action
  tests were updated so the "no mutation" check excludes the budget ledger,
  which a rejected action legitimately charges (S33).
- Live (dev API): created a scripted world, watched autosaves land every 2
  ticks and cap at the keep setting; killed the real server process, confirmed
  the port down, restarted, and saw the world recovered at its newest autosave
  tick with its agents and seed intact, then ticking on. Disk stays bounded.
- Roadmap S38 checklist: kill/restart server and recover the world ✅.
  Civilizations persist beyond one session ✅.

### Commits
- `318a5d5` — S38: world persistence — snapshots, autosave, recovery, resume,
  console panel; fix unbounded snapshot growth [pushed]

## S39 - Multi-World Laboratory (2026-10-16)

### Plan
A single world is one history; science needs many. This sprint makes the
recipe a first-class object and the comparison automatic: the same
experiment is run across independent universes and every measure is
summarized, so a result is a distribution rather than an anecdote.

### Scope
In: world templates (`WorldTemplate` + a built-in shelf), independent
seeds per world, the multi-world study runner, cross-world analytics
(per-measure n/mean/spread/range plus running totals), JSON export, a
CLI, the template API and founding a live world from a template, tests
and docs.
Out: the research console that charts a study (that is S40), running
worlds under different hosts or in parallel processes, and persisting
each studied world (the study runs in memory and exports whole).

### Implementation
- `app/experiments/multi_world.py` is the laboratory. A `WorldTemplate`
  names a recipe (size, founding minds in rotation, span); `TEMPLATES`
  is the built-in shelf (`void`, `village`, `sparse`, `crowded`).
  `world_kwargs` turns a template into the registry's `create`
  arguments, so a live world and an offline study are the same world.
- `run_world(template, seed)` builds a `World.generate` world, seats the
  rotation as scripted minds (deterministic `Wander`/`Forager`/
  `Gatherer` policies) on free floor, advances the ticks, and reads the
  measures off the timeline and the world: actions, moves, gathers,
  rejections, births, carried stock, objects left, structures,
  settlements. The same seed reproduces the same history exactly.
- `cross_world_analytics` summarizes each measure across the worlds
  (n/mean/stdev/min/max) and totals them; `differing_measures` counts
  how many measures actually vary — a fix for "is this run identical or
  merely similar".
- `run_study` varies one axis: `vary="seed"` holds the template and
  gives each of N worlds its own seed (the roadmap's experiment);
  `vary="template"` holds the seed and walks the recipe. The study is
  recorded as an `ExperimentModel` (scenario `multi_world`), completed
  on finish, and exported whole as one JSON file. A `--vary template`
  CLI can name one template per world.
- Live server: `GET /api/templates` lists the shelf and
  `POST /api/worlds` accepts `template` to found a world from one
  (unknown template is a 400).

### Verification
- Tests: pytest **649 passed** (16 new in `test_multi_world.py`:
  template round-trip and shelf shape, unknown template refused,
  `world_kwargs` carries the rotation as a spawn rule; a world runs and
  reports every measure, the same seed reproduces and independent seeds
  diverge; analytics summarize every measure and aggregate totals, and
  identical worlds differ nowhere; **the roadmap's check: the same
  experiment in 10 worlds — 10 distinct seeds, a full comparison**; the
  study is deterministic, template-varying holds the seed, and the study
  is recorded as a completed experiment and exported whole; the API
  lists templates, founds a world from one, and 400s an unknown one).
- Live (CLI): ran the study against the dev database — "multi-world
  study 'lab-live': 10 worlds, varying the seed", 4/9 measures differing
  (moves, gathers, stock, objects), exported to JSON.
- Live (dev API): `GET /api/templates` returned `void, village, sparse,
  crowded`; founding from `crowded` created a 12x12 world with 8 agents;
  an unknown template returned 400. (The S38 migration was applied to
  the dev DB first.)
- Roadmap S39 checklist: run the same experiment in 10 worlds ✅.
  Parallel artificial histories ✅.

### Commits
- `cbdfbad` — S39: multi-world laboratory — templates, independent
  seeds, multi-world study, cross-world analytics, template API

## S40 - Flood Research Console (2026-10-16)

### Plan
Every capability the platform needs already exists, but to use one you
have to know which script to import: studies are CLI-only, snapshots and
replay are separate panels, and there is no way to see an experiment's
result without opening its JSON on disk. This sprint unifies the platform
into one console and one experiment API so a user can **create, run,
inspect, replay and export** an experiment from the UI — the roadmap's
verification — without touching source.

### Scope
In:
- **Experiment API** (`app/api/experiments.py`): a scenario catalog
  (`GET /api/scenarios`), list/get experiments (`GET /api/experiments`,
  `GET /api/experiments/{id}`), run a study by scenario name
  (`POST /api/experiments`, dispatching to the S32 lineage study and the
  S39 multi-world study), and export a stored result
  (`GET /api/experiments/{id}/export`).
- **Persisted results**: store each study's full result on its
  `ExperimentModel` row (a new `result` JSON column + migration) so an
  experiment can be inspected and exported long after it ran.
- **Unified console**: top-level navigation in `App.tsx` — **Worlds**
  (the existing per-world dashboard) and **Experiments** (new). A new
  `ExperimentsPanel.tsx` lists experiments, runs one from a scenario
  form (scenario, world count, template, seed, ticks), inspects the
  cross-world comparison (per-measure n/mean/stdev/min/max + totals) and
  per-run table, and exports the study JSON. Scenario creation gains a
  template dropdown (S39 templates) in the world form.
- Reach the already-built surfaces from the unified shell: populations,
  lineages, metrics (replay timeline), replay, participant entry.
- Tests (`test_experiments_api.py`), docs.

Out: running studies in a background worker or streaming progress (studies
are fast and synchronous), WebSocket push, and new analytics beyond what
S32/S39 already compute — this sprint exposes, it does not invent.

### Decisions
1. **Persist full results** (settled): add a `result` JSON column to
   `ExperimentModel` (+ migration) so inspect/export are durable and
   cheap; studies are not re-run to be read.
2. **Synchronous runs**: studies run inline in the request (a 10-world
   study is ~seconds); no job queue this sprint.

### Implementation
- **ExperimentModel.result** (migration `05d1a026d80d`, after the S38
  snapshots migration): the whole study is stored on its row, so inspect
  and export read the database instead of re-running anything. Both
  studies (`lineage_study`, `multi_world`) now write `row.result = study`
  on completion.
- **The Experiment API** (`app/api/experiments.py`). A scenario catalog
  (`GET /api/scenarios`) describes each study and its knobs (`Param`:
  name/label/type/default/choices/min/max/help) so the console can draw a
  form; the multi-world template choice is resolved live from `TEMPLATES`.
  `POST /api/experiments` validates the scenario and its parameters, then
  dispatches to the study (S32 lineage, S39 multi-world) and returns the
  whole study. `GET /api/experiments` (newest first, optional
  `?scenario=`) and `GET /api/experiments/{id}` (with the stored result)
  inspect; `GET /api/experiments/{id}/export` serves the study as a
  downloadable JSON. `app.state.session_factory` is set in the lifespan.
- **One console shell** (`App.tsx`): a top-level nav — **worlds** and
  **experiments** — over the existing dashboard and a new
  `ExperimentsPanel.tsx`. The panel lists studies (polled), runs one from
  the scenario form (no source edits), shows the cross-world comparison
  as a measure table when the result carries flat summaries, and offers
  a full comparison/runs view and a JSON export download. The world form
  gained a template dropdown (S39) that shows the recipe it will stamp.

### Verification
- Tests: pytest **660 passed** (11 new in `test_experiments_api.py`: the
  catalog lists both studies, every scenario describes its knobs, the
  template choice is live from `TEMPLATES`; **the roadmap's check — run a
  study over HTTP, list it, inspect its stored result, and export it as
  an attachment whose document matches**; a lineage study runs and can be
  renamed; the list filters by scenario; unknown scenario 404, unknown
  parameter 400, bad study request 400, missing experiment/export 404).
- Frontend: `npm run build` clean (`tsc --noEmit` + vite).
- Live (dev API): `GET /api/scenarios` returned `multi_world,
  lineage_study` with live template choices; ran a 10-world multi-world
  study (`console-live`, 4/9 measures differing); it appeared in
  `GET /api/experiments` with `has_result`; `GET /api/experiments/{id}`
  returned all nine measures; the export downloaded 7988 bytes with
  `Content-Disposition: attachment; filename="experiment-125.json"` and
  the matching study; replay confirmed on a stepped world (21 events to
  tick 5). (The S40 migration was applied to the dev DB first.)
- Roadmap S40 checklist: a user can create, run, inspect, replay and
  export an experiment without editing source code ✅. Flood is usable as
  a standalone experimental platform ✅.

### Commits
- `265328d` — S40: research console — experiment API, persisted results,
  unified console with experiments panel and template creation

## S41 - Agent Genetics (2026-10-16)

### Plan
Inheritance today carries a free-form `traits` dict the parent authors;
nothing changes on its own and nothing is bounded. This sprint gives
agents a **genome**: a fixed set of numeric genes that pass from parent
to child with small, bounded mutations. That turns a lineage into a
slowly drifting thing — the substrate a real genetics experiment needs —
without ever letting a trait run away or an inherited value appear from
nowhere.

### Scope
In:
- `app/simulation/genetics.py`: the gene shelf (`GeneSpec`: name, range,
  default, max step), a `Genome` (tolerant parse, clamp, deep-safe
  copy), and `Genome.inherit(rng)` — each gene mutates by at most its
  step with a small per-gene chance, always clamped to its range, with
  every change returned as a recorded mutation.
- `Agent.genome` (default genome for founders) and `observe()` showing
  it, so a mind can see its own biology.
- `Engine.create_child` inherits the genome deterministically (a
  per-engine RNG seeded from the world seed), records the child genome
  and its mutations on the `AGENT_BORN` event, and emits a
  `GENES_INHERITED` event.
- API: `GET /api/genetics` (the gene shelf + mutation defaults); genome
  on the agent detail; genome + birth mutations on each lineage member.
- Tests, docs.

Out: natural selection / fitness (nothing selects on genes yet),
persisting agent state through world snapshots (a pre-existing S38
boundary — a snapshot carries the world, not the minds), and genes
driving scripted behaviour (minds may read the genome; the scripted
policies do not yet act on it).

### Decisions
1. **Genes are bounded and clamped at every step**, never merely at
   birth, so "traits remain bounded" is a property of `inherit`, not a
   hope about callers.
2. **Mutation is deterministic per seed** via `Engine`'s RNG, so a
   lineage study reproduces exactly (roadmap's determinism contract).
3. **Genome is biological, `traits` stays authored.** The existing
   `traits` package part is untouched; the genome is a separate,
   automatic inheritance that the parent cannot forge.

### Implementation
- **`app/simulation/genetics.py`**: a `GeneSpec` shelf (curiosity, diligence,
  sociability, boldness, patience — all in [0, 1], max step 0.05) and a
  `Genome` whose every value passes through `GeneSpec.clamp`. `from_dict`
  is tolerant (unknown genes dropped, missing filled from defaults,
  out-of-range clamped, bools ignored); `distance` is the mean absolute
  gene difference; `inherit(rng, mutation_rate=0.25)` mutates each gene
  with that chance by at most its step, clamps, and returns the child
  genome plus every net change as `{"gene", "from", "to"}`.
- **`Agent.genome`** defaults to the founder genome and appears in
  `observe()` under `genome`, so a mind can see its own dispositions. The
  authored `traits` package is untouched.
- **`Engine.create_child`** inherits the genome from the parent through a
  per-engine RNG seeded from the world seed (`f"{seed}:genetics"`), so
  drift is deterministic per world. The `AGENT_BORN` payload now carries
  `genome` and `mutations`; a birth that mutated also emits a
  `GENES_INHERITED` event with the same record. `Engine.mutations_of(agent_id)`
  reads a birth's mutations back.
- **API**: `GET /api/genetics` returns the gene shelf and mutation rate;
  the agent detail carries `genome`; each lineage member carries its
  `genome` and the `mutations` recorded at its birth.
- Tests fix up: the S31 stress test's exact event-count assertion now
  accounts for `GENES_INHERITED` events (count by type instead of a magic
  total).

### Verification
- Tests: pytest **678 passed** (18 new in `test_genetics.py`: the shelf
  and tolerant parses; **traits remain bounded** over 2,000 generations
  and at an edge; **inheritance is traceable** — a child changes by at
  most a step, the engine descends from the parent, the birth records
  both genomes, founders have no mutations; **mutations are recorded** on
  both events and match the actual gene changes; determinism — the same
  seed reproduces the same drift; the library over HTTP lists the genes,
  the agent detail carries a genome, and a lineage member carries genome
  + mutations).
- Live (dev API): `GET /api/genetics` returned the five genes and rate
  0.25; a 13-member lineage (founder + 12 births) drifted slowly
  (curiosity held at 0.6; diligence 0.500→0.478, sociability
  0.500→0.518, boldness 0.400→0.406, patience 0.500→0.526), recorded 17
  mutations, and every gene stayed in [0, 1].
- Roadmap S41 checklist: traits remain bounded ✅. Inheritance is
  traceable ✅. Mutations are recorded ✅.

### Commits
- `af4dd4e` — S41: agent genetics — bounded genome, deterministic
  inheritance, recorded mutations, genetics API


## S42 — Language Evolution (2026-10-17)

### Plan
Speech existed (S21) and routes existed (S28), but every message arrived
already in a language nobody had invented. This sprint gives each agent a
**lexicon**: a repertoire mapping concepts to invented symbols that grows
when the agent names something and changes when it adopts a word it hears.
Language becomes world state — observable, measurable, and lost only if a
snapshot drops it — rather than a formatting choice fixed in code.

### Scope
In:
- `app/simulation/language.py`: a fixed concept vocabulary, a `Lexicon`
  (`invent`, `adopt`, `encode`, `decode`, `agreement`, `shared_with`) with
  deterministic pronounceable symbols and a change history, and mean
  pairwise agreement.
- `World` language layer: per-entity lexicons (lazy, serialized), `speak`
  (invents missing names, emits `WORD_INVENTED` + an encoded `SPEECH`),
  `learn` (adopts a speaker's most recent utterance, emits `WORD_ADOPTED`),
  and `language_summary()`.
- A `speak` action; `say` deliberately unchanged.
- Hearing: `messages_for` adds the listener's `understanding` of an encoded
  utterance.
- API: `GET /worlds/{id}/language`, `POST .../language/speak`,
  `POST .../language/learn`.
- `app/experiments/language.py`: a deterministic emergence study
  (independent invention, then conversation) with a convergence curve.
- Tests, docs.

Out: language change without a listener (no spontaneous drift or decay),
grammar or word order, an explicit cross-population translation policy,
model-provider language generation, and replay reconstructing lexicons
(language is snapshot state; replay remains event-focused).

### Decisions
1. **`say` stays plain; `speak` is the language path.** Existing messages
   and their tests are contracts, and a caller may want either the plain
   words or the world's own. Two verbs keep both without rewriting the
   past.
2. **Symbols are per agent, not per population.** Convergence is measured
   with Jaccard agreement over concept→symbol pairs. A population agrees
   because its members talked, not because the code handed them one
   dictionary.
3. **Learning is explicit and conservative.** Hearing alone never rewrites
   a repertoire; `learn` adopts only the concepts in the latest utterance
   and records every replacement. `messages_for` stays a read path.
4. **Utterances carry their plaintext mapping.** The learnable `symbols`
   map rides in the speech buffer, not only the event log, so a restored
   snapshot can still teach even though snapshots drop events.

### Implementation
- **`app/simulation/language.py`**: 16 concept words; invented symbols are
  2–3 syllable forms (onset + vowel) never colliding with a concept, so
  encoding is unambiguous. History records `invented`, `adopted`, and
  `replaced` changes with tick, actor, source, and the previous symbol.
  `encode` replaces concept words only (other words pass through) and
  returns the innovations; `decode` is its exact inverse; `agreement` is
  the Jaccard similarity of concept→symbol pairs.
- **`World`**: `_lexicons` (entity → `Lexicon`) and a deterministic
  `_language_rng` seeded `f"{seed}:language"`. `speak` emits one
  `WORD_INVENTED` per newly named concept and a `SPEECH` whose payload
  carries the encoded `message`, plain `text`, the learnable `symbols`,
  the speaker's population, and position. The rolling speech buffer now
  holds `(speaker, position, message, tick, symbols)`. `learn` reads the
  speaker's latest buffered utterance; `messages_for` adds a listener-side
  `understanding` only when that listener has a lexicon. `language_summary`
  returns repertoires, shared words, mean agreement, and change counts.
- **Actions**: `speak` encodes through the world and returns message, text,
  and symbols; `say` is untouched.
- **API**: the three language routes above, registered with the rest of
  the world router; 404 for unknown agents, 400 on an empty message via
  the action path.
- **`app/experiments/language.py`**: every agent privately names the same
  concepts (diverging), then rounds of hearing-and-adopting measure
  agreement, vocabulary size, shared words, and change count. An
  `attention` knob limits how many words a listener takes per round.
- **Serialization**: lexicons are written by `to_dict` and rebuilt in
  `_restore_derived`; speech entries carry their `symbols`. While editing
  `from_dict`, removed a duplicated dead `world = cls(...)` block that was
  immediately overwritten (no behaviour change).

### Verification
- Tests: pytest **702 passed** (24 new: 20 in `test_language.py`, 4 in
  `test_api_language.py`). Coverage: deterministic invention and no
  renaming; encode/decode round-trip and pass-through of non-concepts;
  adopt/replace/no-op history and symbols never shadowing a concept;
  agreement counts symbols not merely concepts; world speak invents and
  emits both events; learning makes an utterance understood and tracked;
  unknown entities rejected; summary metrics; lexicons and learnable
  speeches survive a save/restore; `say` remains plain while `speak`
  encodes; study convergence, determinism, and input validation; HTTP
  speak/learn/summary, the action route, 404s, and empty-message
  rejection.
- Live (dev API on port 8011; 8000 was already held by an unrelated
  `apps/coordinator` service): created world 145 with agents 1–3, spoke
  "water stone tree" as agent 1 → `"pati vesa siga"`, taught agents 2 and
  3 (3 words each), then `GET /language` reported **agreement 1.0**, 9
  changes, and all three sharing water=`pati`, stone=`vesa`, tree=`siga`.
- Roadmap S42 checklist: **shared vocabulary can emerge** ✅ — the study
  starts at 0.0 agreement (48 privately invented symbols for 8 concepts)
  and reaches 1.0 by round 4 with 8 shared symbols for 6 agents;
  **messages remain parseable** ✅ — `decode(encode(text)) == text` for
  lowercase concept text, matching is case-insensitive, and ordinary
  words are never replaced; **language changes can be tracked** ✅ —
  every invention and adoption is a history entry and a
  `WORD_INVENTED`/`WORD_ADOPTED` event.

### Commits
- `2976fb5` — S42: language evolution — invented symbols, per-agent
  lexicons, learning, language API


## S43 — Ecosystem (2026-10-17)

### Plan
The Void has terrain and resources but no life of its own: objects sit
where generation put them, nothing grows back, and the sky never changes.
This sprint adds an **ecosystem** — plants that regrow, animals that eat
them and each other, weather and seasons that scale the whole economy.
The point is not decoration: it is a deterministic environment whose
resources regenerate within hard bounds, so later challenges (winter,
scarcity) can be honest.

### Scope
In:
- `app/simulation/ecosystem.py`: seasons and weather derived purely from
  the tick and seed; plant patches (berry bushes and trees) whose biomass
  regrows toward a capacity and spreads to a capped number of patches;
  grazing and predatory animals with energy, age, movement, reproduction,
  and death, all capped in population and energy.
- World integration: opt-in `enable_ecosystem`, an ecosystem tick inside
  `World.step`, an `ECOSYSTEM_SEEDED` event plus season/weather/animal
  events, snapshots and save/restore carrying the ecosystem whole.
- Resource integration: regrowing plants are ordinary world objects, so
  existing `gather` works on them; a gathered-out plant stays in place
  (rather than vanishing) and regrows.
- API: `POST /api/worlds` accepts `ecosystem`, `GET /api/ecosystem`
  describes the shelf, `GET /api/worlds/{id}/ecosystem` reports the live
  state.
- Tests, docs.

Out: agents eating or hunting (the food chain is animal-side for now),
disease, migration between worlds, a rendered animal client, and
selection/evolution of species traits.

### Decisions
1. **Plants are world objects, not a parallel layer.** Berry bushes are
   `food` and trees are `tree` objects carrying `regrows`, `capacity`,
   and `species`. Agents can gather them with no new action, and bounded
   regeneration is enforced where quantity is written.
2. **Weather and seasons are pure functions of seed and tick.** No
   running climate RNG is serialized, so a restored world resumes the
   same sky as an uninterrupted one.
3. **Animal randomness is per-tick seeded.** Any choice derives from
   `f"{seed}:animals:{tick}"`, and animals are processed in id order, so
   two identical worlds produce identical herds.
4. **The ecosystem is opt-in.** A world without `ecosystem=True` is
   exactly the world it was before this sprint; existing scenarios,
   event counts, and snapshots are untouched.

### Implementation
- `backend/app/simulation/ecosystem.py` (new):
  - Climate: `SEASONS`, `WEATHERS`, growth/cost tables, weighted
    `WEATHER_OPTIONS` per season, `season_for(tick, season_length)` and
    `weather_for(seed, tick, season, weather_interval)` — both pure, the
    latter seeded per weather interval.
  - Life: `PLANT_SPECIES` (`berry` food/capacity 4, `tree` tree/capacity 6)
    and `ANIMAL_SPECIES` (`grazer`, `predator`) with energy, gain,
    lifespan, sense, reproduction threshold, and per-species caps.
  - `Ecosystem` owns the config (`DEFAULT_CONFIG`: 60-tick seasons, 8-tick
    weather, 3-tick regrow, 20-tick spread, 24 plant patches, 16 animals),
    season/weather, `Animal` herd, `next_animal_id`, and stats.
  - `seed(world)` places plants and animals on free floor from a seeded
    shuffle and emits `ECOSYSTEM_SEEDED`; `add_plant` creates an ordinary
    regrowing object; `add_animal` clamps energy and age.
  - `tick(world)` derives season/weather (emitting change events on
    transitions), regrows plants toward capacity, spreads patches to a cap
    on favourable ticks, and advances animals: cost, starvation/age death,
    movement toward the nearest plant or grazer within sense, eating,
    capped reproduction, and birth/death events. Per-tick RNG is
    `Random(f"{seed}:animals:{tick}")` with id-ordered animals, so herds
    are deterministic.
  - `summary`, tolerant `to_dict`/`from_dict`, and `ecosystem_catalog`.
- `world.py`: opt-in `enable_ecosystem(**config)` (refuses double-enable),
  `ecosystem` property, ecosystem tick inside `step`, ecosystem in
  `snapshot()`/`to_dict()`/`_restore_derived`.
- `events.py`: `ECOSYSTEM_SEEDED`, `SEASON_CHANGED`, `WEATHER_CHANGED`,
  `ANIMAL_BORN`, `ANIMAL_DIED`.
- `actions.py`: gathering a regrowing plant sets its quantity to 0 and
  reports `depleted: False`, leaving the plant rooted to regrow.
- `host.py`: `WorldRegistry.create(..., ecosystem=False)`, enabled after
  generation.
- `api/worlds.py`: `CreateWorldRequest.ecosystem`, `GET /api/ecosystem`,
  `GET /worlds/{id}/ecosystem` (returns `enabled: false` when absent).
- `WorldObject.to_dict`/`from_dict` now copy `properties`, so a restored
  world cannot share mutable plant state with the world it came from.
- Tests: `tests/test_ecosystem.py` (15) and `tests/test_api_ecosystem.py`
  (4) — seasons/weather purity, regrowth and spread caps, gathering,
  food-chain energy transfer, population/energy bounds over 300 ticks,
  reproduction caps, same-seed determinism, save/restore equivalence,
  opt-in inertness, validation, catalog, and the API surface.

### Verification
- `backend/.venv/Scripts/python -m pytest -q`: **721 passed**
  (702 after S42 + 19 ecosystem/API tests), ~2m57s.
- Live on port 8011 (`seed="eco-live"`, 16×16, 3 agents, ecosystem on):
  - tick 0: spring/rain, 16 plant patches (biomass 76/76), 7 animals
    (6 grazers, 1 predator).
  - after 65 steps: tick 65, **summer/clear**, plants 24/24 (biomass
    83/108), animals 12/16 (12 grazers, 0 predators), 325 plants eaten,
    17 grazers eaten, 35 births, 30 deaths; events show the tick-60
    `SEASON_CHANGED` and five `WEATHER_CHANGED` transitions.
  - manual snapshot then stop/restore resumed at tick 65 with the same
    summer climate, 24 plant patches, and 12 animals.
  - `GET /api/ecosystem` returned the season/animal/plant shelves and
    default caps (24 patches, 16 animals).

### Commits
- `0419821` — S43: ecosystem — plants, animals, weather, seasons,
  bounded regeneration







