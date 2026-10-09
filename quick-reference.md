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

## Web console (S01 → S13 dashboard)

```bash
cd frontend && npm install          # first time / after deps change
cd frontend && npm run dev          # http://localhost:5173 — /api proxied to :8000
cd frontend && npm run build        # typecheck + production build
cd frontend && npm run preview      # serve the built console (proxies /api too)
```

The dashboard watches live worlds: viewport from state snapshots,
population stats (generation, active agents, model vs scripted minds),
the event stream, and pause/resume/step controls. Create scripted or
`brains: "model"` worlds from the sidebar.

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

# births (S09): one agent reproduces — child placed adjacent,
# lineage + inheritance recorded as an AGENT_BORN event
curl -s -X POST localhost:8000/api/worlds/1/births \
     -H "Content-Type: application/json" \
     -d '{"parent_id": 1,
          "inheritance": {"traits": {}, "knowledge": ["fact"],
                          "message": "go east",
                          "cultural_artifacts": []}}'
#   201: {"id": 2, "parent_id": 1, "generation": 1, ...}
#   409: the world has no free cell at all (the child is placed at the
#        nearest free cell by expanding ring — a full neighbourhood
#        alone does not block a birth)
#   S10: omit "inheritance" to use the parent's pending intent
#        (declared by its last decision)

# ancestry (S15): the lineage explorer's feed — chain from the founder,
# drift per generation, click-to-navigate in the console
curl -s localhost:8000/api/worlds/1/agents/100/lineage
```

## Model providers (S07+)

```bash
# .env (copy from .env.example): mock | openai | ollama | openai_compatible
FLOOD_MODEL_PROVIDER=mock          # default: deterministic, no network
FLOOD_MODEL_NAME=                  # e.g. gpt-4o-mini, llama3.1, qwen2.5:7b-instruct
FLOOD_MODEL_BASE_URL=              # required for openai_compatible
FLOOD_MODEL_API_KEY=               # never recorded on experiments
```

`mock` runs the full provider → parser → decision path offline
(tests, headless worlds). The OpenAI-compatible provider also covers
Ollama (`http://127.0.0.1:11434/v1`) — they differ only by base_url.
Construction lives in `app/models/config.py`; the bridge between
providers and agents is `ModelPolicy` (`app/simulation/model_policy.py`).

## LLM worlds (S08+)

```bash
# model brains are an explicit opt-in — a configured provider alone
# never starts a model world
curl -s -X POST localhost:8000/api/worlds -H "Content-Type: application/json" \
     -d '{"seed": "llm", "agents": 2, "brains": "model"}'   # uses FLOOD_MODEL_*

curl -s "localhost:8000/api/worlds/1/events?since_id=0&limit=50"
#   watch MODEL_DECISION / MODEL_ERROR / AGENT_MESSAGE events
```

Ollama quickstart (local-first): `ollama pull qwen2.5:7b-instruct`,
`ollama run qwen2.5:7b-instruct` once to **preload** it (a cold model
load can exceed the 30 s request timeout and logs a MODEL_ERROR the
first tick — self-healing, but preloading avoids it), then
`FLOOD_MODEL_PROVIDER=ollama FLOOD_MODEL_NAME=qwen2.5:7b-instruct` on
the backend. `phi4-mini` is the speed-first alternative; qwen3.x
defaults to slow "thinking" mode and is not recommended for the live
loop.

## Resources (S17+)

Objects carry quantities (tree→wood 3, stone→stone 3, food→food 2);
water is gathered from adjacent water terrain. The `gather` action
moves one unit per attempt into the gatherer's ledger; a source that
hits zero is depleted and leaves the world (OBJECT_DEPLETED event).
Live scripted worlds rotate wander/forager/gatherer minds; the
gatherer starts beside a tree and looks further (radius 4). Total
resources are conserved: world object quantities + agent ledgers.

## Building (S18+)

`build` places a block on an adjacent cell, spending its recipe from the
agent's resource ledger (wood_block/stone_block: 1 of wood/stone; door:
1 wood) and occupying the cell — a wall is a wall. Blocks group into
structures by adjacency (or an explicit `structure` id), each with id,
owner, components and purpose. `remove` takes an adjacent block back,
refunding its material; an emptied structure dissolves.

```bash
# command an agent directly (the console's seam; same validated path):
curl -s -X POST localhost:8000/api/worlds/1/actions \
     -H "Content-Type: application/json" \
     -d '{"agent_id": 1, "action": {"action": "build", "block": "wood_block",
          "direction": "north", "purpose": "shelter"}}'
curl -s localhost:8000/api/worlds/1/structures     # the world's buildings
```

## Lineage experiment (S11+)

```bash
cd backend
.venv/Scripts/python -m app.experiments                          # control: full retention, 100 generations
.venv/Scripts/python -m app.experiments --mode lossy             # calibrations: lossy|altering|negating|new
.venv/Scripts/python -m app.experiments --mode model --seed r1   # live ModelPolicy from FLOOD_MODEL_* (preload the model!)
.venv/Scripts/python -m app.experiments --export out.json        # JSON report

# S12 scale switches (mock minds; 10k generations takes ~50s)
.venv/Scripts/python -m app.experiments --generations 10000 --checkpoint-every 1000 --retention 500
.venv/Scripts/python -m app.experiments --resume 6 --generations 10000   # continue from the chain head

# replays from persisted events alone (no model calls):
#   app.experiments.replay_lineage_experiment(SessionLocal, experiment_id)
```

## Word-seed experiment (S16+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.wordseed                          # control: 5 seeds, 2 populations
.venv/Scripts/python -m app.experiments.wordseed --mode scatter           # deterministic divergence
.venv/Scripts/python -m app.experiments.wordseed --mode model --seeds light,water,stone,echo,void
.venv/Scripts/python -m app.experiments.wordseed --export out.json
```

Each agent gets a seed word, produces three associated concepts, and
creates one cultural artifact (story/theory/rule/invention/game/poem/
building concept) — stored as a world object, a timeline
(`ARTIFACT_CREATED`) event, and on the agent's row. Multiple
populations from identical seeds are compared: the scripted control
agrees exactly; the live model diverges (measured by per-seed variants
and concept-set Jaccard).

Measures retained/lost/altered/new facts, contradictions, message
lengths, and token-Jaccard similarity per generation. `--mode model`
takes ~1 model call per generation (100 calls for the full run) —
preload the Ollama model first; a contended Ollama makes it slow.

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
