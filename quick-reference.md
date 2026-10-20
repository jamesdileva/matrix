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

# participant mode (S20): headless self-test — join, move, leave
FLOOD_PARTICIPANT=1 tools/godot.cmd --headless --path world-client

# full E2E smoke (needs backend running)
FLOOD_SMOKE=1 tools/godot.cmd --headless --path world-client
```

**Participant mode (S20):** press **P** to join a world as an entity
(or leave again) — the avatar is a real world entity (id 1001), moves
through the same validated actions as agents (walls, water and
occupants still apply), appears in agents' observations, and is
rendered amber and labelled "you". In participant mode WASD walks the
avatar (mapped through the camera's yaw onto the grid's cardinal
directions) and the camera follows; the simulation keeps ticking
throughout. The same join/leave/move is on the API:
`POST /api/worlds/{id}/participant/join|leave|move`.

## Talking to agents (S21+)

```bash
# join, walk up to an agent, then talk (the reply is the agent's own
# decision, generated from its observation — which carries what you said)
curl -s -X POST localhost:8000/api/worlds/1/chat \
     -H "Content-Type: application/json" \
     -d '{"agent_id": 1, "message": "Who are you?"}'
curl -s localhost:8000/api/worlds/1/conversations   # every utterance, oldest first
```

Speech is local: a voice carries 6 cells, lands on the timeline as a
SPEECH event, and shows up in nearby agents' observations (`messages`).
Out of earshot, the chat is refused (400). Scripted agents hear you but
have nothing to say; model minds reply through the decision contract's
`message` field.

## Social interaction (S22+)

```bash
# give/take between the participant and an adjacent agent (objects or
# resource amounts), and an atomic trade (both legs validate first)
curl -s -X POST localhost:8000/api/worlds/1/give \
     -H "Content-Type: application/json" -d '{"agent_id": 1, "leg": {"resource": "wood", "amount": 1}}'
curl -s -X POST localhost:8000/api/worlds/1/take \
     -H "Content-Type: application/json" -d '{"agent_id": 1, "leg": {"object_id": 5}}'
curl -s -X POST localhost:8000/api/worlds/1/trade \
     -H "Content-Type: application/json" \
     -d '{"agent_id": 1, "give": {"object_id": 5}, "want": {"resource": "stone", "amount": 2}}'

# gather a retinue: every agent within the radius starts (or stops)
# following the participant — the engine walks them over each tick
curl -s -X POST localhost:8000/api/worlds/1/group \
     -H "Content-Type: application/json" -d '{"radius": 200, "following": true}'
```

The same give/take/trade/follow actions are available to agents
through the decision contract.

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

## House experiment (S19+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.house                          # control: scripted builders
.venv/Scripts/python -m app.experiments.house --mode model --ticks 20  # live ModelPolicies
.venv/Scripts/python -m app.experiments.house --population 4 --house-size 5
.venv/Scripts/python -m app.experiments.house --export out.json
```

"Build a house." — shape, size, material and room count are the
agents' to decide. Each builder is granted exactly a ring's worth of
wood. Scored: completion (a flood-fill enclosure test — design-
agnostic), material use, construction time, cooperation, design, and
failure. The scripted control completes a 4x4 ring (12 blocks, 4
enclosed cells, 2 cooperating builders).

## Prison escape (S23+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.prison                          # the deterministic solution
.venv/Scripts/python -m app.experiments.prison --solver walker          # the control: solves nothing
```

An enclosed room with one door, the door blocked by a stone you can
carry away, and the destination sandbox beyond. Entering the sandbox
records an ESCAPED event on the world timeline. The scripted solver
proves the puzzle is solvable; S24 takes the script away and asks the
agents to solve it themselves.

## Agent escape (S24+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.escape --solver mock --ticks 40      # a control attempt
.venv/Scripts/python -m app.experiments.escape --solver scripted             # the known-solution reference
.venv/Scripts/python -m app.experiments.escape --solver model --ticks 40     # a live mind attempts it
```

Reported per attempt: escaped, escape tick, actions attempted, actions
rejected (failed attempts) and cells explored. No host-level escape is
possible — only the simulated transition into the sandbox fires
ESCAPED.

## Cooperative escape (S25+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.coop_escape --agents 2    # the cooperating pair
.venv/Scripts/python -m app.experiments.coop_escape --agents 1    # solo: cannot escape
.venv/Scripts/python -m app.experiments.coop_escape --solver model --agents 2
```

The door stone is too heavy to carry and sits over two pressure
plates; the door opens only while both plates are held. One agent can
never escape alone. Teammates' positions ride in every observation
(shared observations), and the pair's utterances are logged on the
timeline.

## Builder vs Escapee (S26+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.arms_race --rounds 4    # the arms race
```

Each round: Population A builds a prison (ring walls + door, wood
granted), Population B escapes it (removing the blocks in the way).
Every escape thickens the next round's prison by one layer — the
builder receives the outcome and the rules carry forward.

## Populations (S27+)

```bash
# a world with three groups, founded from their spawn rules
curl -s -X POST localhost:8000/api/worlds -H "Content-Type: application/json" \
  -d '{"seed": "many-groups", "autostart": false, "populations": [
    {"name": "builders", "members": 2, "policies": ["gather"], "stipend": {"wood": 3}},
    {"name": "wanderers", "members": 3, "policies": ["wander"]},
    {"name": "foragers", "members": 2, "policies": ["forage"], "max_members": 3, "top_up": true}]}'
# statistics + totals for every group in the world
curl -s localhost:8000/api/worlds/1/populations
# found a group in the live world (201)
curl -s -X POST localhost:8000/api/worlds/1/populations -H "Content-Type: application/json" \
  -d '{"name": "latecomers", "members": 2, "policies": ["wander"]}'
# how one agent stands to every other
curl -s localhost:8000/api/worlds/1/agents/1/relationships
```

A population is a group with a spawn rule: founding size, rotating
policies (`wander`/`forage`/`gather`/`model`), an optional spawn zone,
a member cap (births past it are refused), top-up regrowth, and a
resource stipend. Statistics are computed, relationships derived
(kin → following → teammates → population → strangers) — an agent
sees its own population's id and live size in every observation.

## Communication networks (S28+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.rumor --agents 6    # direct chain vs group announcement
```

```bash
# a named letter across the map (distance does not matter)
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "tell", "target": 4, "message": "come to town"}}'
# one message to the speaker's team or population
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "announce", "scope": "population", "message": "meeting at dusk"}}'
# one message to every entity in the world
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "broadcast", "message": "hear ye"}}'
```

Local `say` still travels by earshot; `tell` reaches one named
recipient anywhere, `announce` reaches the speaker's team or
population, `broadcast` reaches everyone but the speaker. Every
observed message carries its `kind`; the timeline records DIRECT,
ANNOUNCE and BROADCAST with their recipients.

## Technology & culture (S29+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.technology    # cumulative culture: a parent's discoveries, a descendant's use
```

```bash
# discover a recipe from your materials, craft it, invent with it
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "discover"}}'
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "craft", "recipe": "wood_axe"}}'
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "invent", "a": "recipe:wood_axe", "b": "recipe:wood_block"}}'
# what the world has ever known, and what one agent knows/carries
curl -s localhost:8000/api/worlds/1/technology
curl -s localhost:8000/api/worlds/1/agents/1
```

Recipes and construction patterns are data; `discover` learns one
from your materials, `craft` makes it, `invent` combines two known
items into something new. Knowledge is inheritable: a child of a
discoverer is born knowing its parent's recipes and patterns and can
use them without rediscovery. The first tool pays for itself — an
axe doubles a gather.

## Settlements (S30+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.settlement    # construct and maintain a village
```

```bash
# found a settlement on the structure beside you, then join it
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "settle", "name": "First Hollow"}}'
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 2, "action": {"action": "join_settlement", "settlement_id": 1}}'
# bank into the shared storehouse, claim the grove, pave the road
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "deposit", "resource": "wood", "amount": 3}}'
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "claim_zone", "resource": "wood", "target": 7}}'
curl -s -X POST localhost:8000/api/worlds/1/actions -H "Content-Type: application/json" \
  -d '{"agent_id": 1, "action": {"action": "pave", "direction": "east"}}'
# what stands in the world
curl -s localhost:8000/api/worlds/1/settlements
```

`adopt` claims a standing structure; `withdraw` draws from the shared
stock; `release_zone` lets a grove go. A member building inside the
settlement's extent grows it without asking; a claimed grove refuses
outsiders. Members see their settlement — its storage, zones and
people — in every observation.

## Games (S31+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.game                       # the calibration, played to a winner
.venv/Scripts/python -m app.experiments.game --mode model          # a model mind invents a game for the human
```

```bash
# propose rules (validated data — never code), open a table, take a seat
curl -s -X POST localhost:8000/api/worlds/1/games -H "Content-Type: application/json" \
  -d '{"name":"Stride Race","players":2,"setup":{"track":0},
       "moves":{"stride":{"requires":{"track":"<8"},"effect":{"add":{"track":1}}}},
       "win":{"first_to":{"track":8}}}'
curl -s -X POST localhost:8000/api/worlds/1/games/1/sessions        # open the table
curl -s -X POST localhost:8000/api/worlds/1/participant/join        # the human joins the world
curl -s -X POST localhost:8000/api/worlds/1/games/sessions/1/join \
  -H "Content-Type: application/json" -d '{"entity_id":1001}'       # and takes the first seat
# the human's turn (the participant is seated)
curl -s -X POST localhost:8000/api/worlds/1/games/sessions/1/moves \
  -H "Content-Type: application/json" -d '{"move":"stride"}'
curl -s "localhost:8000/api/worlds/1/games/sessions/1?as_entity=1001"   # your turn and legal moves
```

Rules are data with a closed vocabulary: named counters in
`setup`, moves with `requires` (comparisons like `"<8"`) and
`effect`s (`add`/`set`/`award`/`again`), and a `win` of `first_to`
or `most_points_after_rounds`. Anything the engine does not
understand — an unknown key, undeclared state, an unopenable game —
is refused with its reasons, which is why agent-invented rules are
safe to play. Agents at a table see their turn and legal moves in
every observation.

## Compute budgets (S33+)

```bash
# a run whose every member is bounded at 3 actions, with a
# study-wide ceiling of 4 model calls
curl -s -X POST localhost:8000/api/worlds -H "Content-Type: application/json" \
  -d '{"seed": "frugal", "autostart": false,
       "compute_budget": {"model_calls": 4},
       "populations": [{"name": "ants", "members": 2, "actions": 3}]}'
# what an agent may still spend
curl -s localhost:8000/api/worlds/1/agents/1 | grep -o '"budget".*'   # or read the whole detail
```

Five kinds — `tokens`, `model_calls`, `cpu_seconds`, `actions`, and
the experiment-wide `experiment` ceiling. Caps are opt-in per member
(a spawn rule field) or per run (`compute_budget`); an uncapped kind
is unlimited. Spending past a cap is refused at the seam that spends
— one `actions` per attempted action, one `model_calls` + tokens +
CPU per model call — and refuses nothing half-applied: a mind that
cannot afford to think acts on its fallback and the timeline records
`BUDGET_EXHAUSTED`. Every observation and agent detail carries the
remaining ledger.

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

## Lineage study — multiple independent lineages (S32+)

```bash
cd backend
# the determinism control: identical minds, different seeds (a null hypothesis)
.venv/Scripts/python -m app.experiments.lineage_study --runs 3 --generations 12 --seed null
# the divergence study: identical starts, a different mind per run
.venv/Scripts/python -m app.experiments.lineage_study --runs 5 --vary model \
  --models full,lossy,altering,negating,new --generations 15 --export study.json
```

Every run is a full lineage experiment with its own row; the study is
one row referencing them, and `--export` writes the whole thing —
configuration, every run, and the roadmap's measures (cultural
convergence, divergence, information loss, strategies, vocabulary) as
normalized values with n/mean/stdev/min/max, so runs are statistically
comparable and the study can leave the simulation.

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

## Compute efficiency (S34+)

```bash
cd backend
# the composite campaign under two budgets: unconstrained and tight
.venv/Scripts/python -m app.experiments.efficiency --ticks 40
# name your own budgets (label:kind=cap,...;label:...)
.venv/Scripts/python -m app.experiments.efficiency --budgets "open;capped:model_calls=4,actions=25"
.venv/Scripts/python -m app.experiments.efficiency --mode model --export eff.json   # real minds, real tokens
```

The four ratios are read off the world's own timeline and the S33
ledger: `tokens / discovery`, `cpu_seconds / solution`,
`messages / successful task`, `compute / surviving concept` (compute =
tokens + model calls + actions + CPU seconds, a documented composite).
A ratio with an empty denominator is `None`, not a fake zero. Each
campaign run is its own row; the study is one row and one exported
JSON, so identical scenarios under different budgets are directly
comparable.

## Cultural compression (S35+)

```bash
cd backend
.venv/Scripts/python -m app.experiments.compression                       # all three transmissions
.venv/Scripts/python -m app.experiments.compression --codecs verbose,symbolic --generations 20
.venv/Scripts/python -m app.experiments.compression --export compression.json
```

Three transmissions of one seed culture under restricted inheritance
bandwidth: **verbose** (everything passes — the control), **compressed**
(first few facts, first few tokens — a hard cut), **symbolic** (a
learned, capped symbol dictionary shared across generations). The
roadmap's three measures per generation: bits transmitted (symbols ×
log2 codebook), retained knowledge (S11's classifier), reconstruction
accuracy (token Jaccard of the original message). The study's
comparison is the determination the sprint asks for: how much
bandwidth each saves, and what it costs.

## Reconstruction experiment (S36+)

```bash
cd backend
# hide the ancestor; hand the descendant intact, truncated or unreadable records
.venv/Scripts/python -m app.experiments.reconstruction --generations 200
.venv/Scripts/python -m app.experiments.reconstruction --mode lossy --generations 60
.venv/Scripts/python -m app.experiments.reconstruction --records full,compressed --export rec.json
```

The procedure: a lineage grows from the founder's culture (any S11
mode, any depth), Agent 0 is hidden — the originals exist only for
scoring — and the final descendant receives *limited records*: the
archive intact, truncated (S35's compressed codec), or symbols with
the codebook lost. The measures are exact recovery, semantic recovery
(token-Jaccard), invented history (what no original explains), and
confidence (a model's claim, or the scripted control's measured
exact recovery). The study's profile is the sprint's end goal:
historical reconstruction failure, quantified per record quality.

## Replay & the time machine (S37+)

```bash
# the log's shape: ticks, event counts, births, generations
curl -s "localhost:8000/api/worlds/1/replay/timeline"
# jump: the world reconstructed at a tick, or immediately after one event
curl -s "localhost:8000/api/worlds/1/replay/state?tick=500"
curl -s "localhost:8000/api/worlds/1/replay/state?event_id=37"
# inspect the intermediate history, and compare two moments
curl -s "localhost:8000/api/worlds/1/replay/events?from_tick=100&to_tick=200&type=ACTION_EXECUTED"
curl -s "localhost:8000/api/worlds/1/replay/diff?a=100&b=200"
curl -s "localhost:8000/api/worlds/1/replay/event/37"
```

The log is the source of truth: terrain is regenerated from the
world's seed (generation is deterministic), everything else is
replayed from events — moves, pick-ups, drops, gathers (the build
event carries its material cost), builds, births with the culture
they carried. Fidelity is reported, not assumed: every snapshot says
how many events were applied and which types were not. A console
panel scrubs the timeline event by event and renders each
reconstruction in the same viewport as the live world.

## World persistence (S38+)

```bash
# save the world now (kind=manual), or archive it
curl -s -X POST "localhost:8000/api/worlds/1/snapshots?kind=manual"
# the world's saves, newest first (bounded by ?limit, default 50)
curl -s "localhost:8000/api/worlds/1/snapshots"
# one snapshot's header
curl -s "localhost:8000/api/worlds/1/snapshots/7"
# bring a stopped world back - newest snapshot, or a chosen one
curl -s -X POST "localhost:8000/api/worlds/1/restore"
curl -s -X POST "localhost:8000/api/worlds/1/restore?snapshot_id=7"
```

A snapshot is the whole world as one row: `World.to_dict` plus the
host's settings. The in-memory event log is deliberately excluded —
the durable log lives in the `events` table — so a snapshot stays
small however long the world runs. A running world autosaves every
`FLOOD_AUTOSAVE_EVERY` ticks (default 500; 0 disables) and keeps only
the newest `FLOOD_AUTOSAVE_KEEP` (default 10) autosaves; manual and
archive saves are never pruned. On startup the server recovers every
world that has a snapshot and resumes it at the newest save.

## Multi-world laboratory (S39+)

```bash
# from backend/ — the roadmap's check: the same experiment in 10 worlds
.venv/Scripts/python -m app.experiments.multi_world --worlds 10 --template void --seed lab --export study.json
# hold the seed, vary the recipe instead (one template per world)
.venv/Scripts/python -m app.experiments.multi_world --vary template --templates void,village,crowded

# the shelf, and founding a live world from one
curl -s localhost:8000/api/templates
curl -s -X POST localhost:8000/api/worlds -H "Content-Type: application/json" -d '{"seed":"a1","template":"crowded"}'
```

A `WorldTemplate` names a recipe (size, founding minds in rotation, span);
`TEMPLATES` holds `void`, `village`, `sparse`, `crowded`. `run_world`
stamps one out under a seed and reports a fixed set of measures; the same
seed reproduces the history exactly and a new seed is a new universe.
`run_study` varies one axis — the seed (default) or the template — runs N
worlds, compares them with `cross_world_analytics` (per-measure
n/mean/stdev/min/max plus totals) and exports the whole study as one JSON
file.

## Experiment API (S40+)

```bash
# the scenario catalog (each study and its knobs)
curl -s localhost:8000/api/scenarios
# run a study over HTTP (multi_world or lineage_study)
curl -s -X POST localhost:8000/api/experiments -H "Content-Type: application/json" \
  -d '{"scenario":"multi_world","name":"my-study","params":{"worlds":10,"template":"void","seed":"lab","ticks":30}}'
# list studies (newest first; optional ?scenario=)
curl -s localhost:8000/api/experiments
# inspect one, with its stored result
curl -s localhost:8000/api/experiments/1
# export the whole study as a downloadable JSON
curl -s -OJ localhost:8000/api/experiments/1/export
```

Every study is an `experiments` row that now keeps its whole result, so
inspect and export read the database — nothing is re-run to be read. The
console's **experiments** tab lists studies, runs one from the scenario
form, shows the cross-world comparison and downloads the export.

## Agent genetics (S41+)

```bash
# the gene shelf: names, bounds, defaults, max step, mutation rate
curl -s localhost:8000/api/genetics
# an agent's genome (and its birth mutations via the lineage route)
curl -s localhost:8000/api/worlds/1/agents/1 | jq .genome
curl -s localhost:8000/api/worlds/1/agents/1/lineage | jq '.chain[] | {id, genome, mutations}'
```

Every agent has a bounded genome (curiosity, diligence, sociability,
boldness, patience). A child inherits the parent's genome mutated by at
most 0.05 per gene with a 0.25 chance, always clamped to [0, 1]; every
net change is recorded on the `AGENT_BORN` and `GENES_INHERITED` events.
Drift is deterministic per world seed.

## Language (S42+)

```bash
# every repertoire, the shared words, agreement and change count
curl -s localhost:8000/api/worlds/1/language | jq
# speak in agent 1's own language (invents names for unknown concepts)
curl -s -X POST localhost:8000/api/worlds/1/language/speak \
  -H "Content-Type: application/json" \
  -d '{"speaker_id":1,"message":"water stone tree"}'
# agent 2 adopts the words from agent 1's latest utterance
curl -s -X POST localhost:8000/api/worlds/1/language/learn \
  -H "Content-Type: application/json" \
  -d '{"listener_id":2,"speaker_id":1}'
# the same, through the generic action path
curl -s -X POST localhost:8000/api/worlds/1/actions \
  -H "Content-Type: application/json" \
  -d '{"agent_id":1,"action":{"action":"speak","message":"water"}}'
```

Each agent has its own lexicon. `speak` replaces concept words with that
speaker's invented symbols (naming missing ones on the spot) and emits
`WORD_INVENTED` + `SPEECH`; `learn` adopts the symbols in the speaker's
latest utterance and emits `WORD_ADOPTED`. `messages_for` shows the
listener's `understanding`, which is the plain text only for words that
listener knows. `say` remains plain speech. Agreement is mean pairwise
Jaccard over concept→symbol pairs, so it rises only when agents agree on
the actual symbol. The S42 study:

```bash
cd backend
.venv/Scripts/python -c "from app.experiments.language import run_language_experiment as r; print(r()['agreement_by_round'])"
```

## Ecosystem (S43+)

```bash
# create a living world (opt-in; without this flag nothing changes)
curl -s -X POST localhost:8000/api/worlds \
  -H "Content-Type: application/json" \
  -d '{"seed":"eden","width":16,"height":16,"agents":3,"ecosystem":true}'
# what life can exist
curl -s localhost:8000/api/ecosystem | jq
# live climate, plant biomass, herd, and food-chain stats
curl -s localhost:8000/api/worlds/1/ecosystem | jq
```

Seasons cycle every 60 ticks (spring → summer → autumn → winter) and
weather changes every 8, both derived only from the seed and tick, so a
restored world resumes the same sky. Berry bushes and trees are ordinary
world objects with `regrows`/`capacity`/`species`; they regrow toward
capacity and spread to at most 24 patches. Grazers eat plants; predators
eat grazers; animals have energy, age, and per-species caps (12 grazers,
2 predators, 16 total). Gathering a plant leaves it rooted at quantity 0
to regrow. The whole ecosystem is in snapshots and `to_dict`, and the
same seed always produces the same climate, herds, plants, and events.

```bash
cd backend
.venv/Scripts/python -c "from app.simulation.ecosystem import ecosystem_catalog; import json; print(json.dumps(ecosystem_catalog(), indent=2))"
```

## Civilization challenges (S44+)

```bash
# every kind, its completion rule, unit, and requirements
curl -s localhost:8000/api/challenges | jq
# ask a world to do something measurable
curl -s -X POST localhost:8000/api/worlds/1/challenges \
  -H "Content-Type: application/json" \
  -d '{"kind":"settlement","target":2,"name":"Our home"}'
# every challenge and its live metric
curl -s localhost:8000/api/worlds/1/challenges | jq
# one challenge (an active discovery hides its center)
curl -s localhost:8000/api/worlds/1/challenges/1 | jq
```

Kinds: `bridge` (planks on a deterministic water span), `settlement`
(members in one settlement), `transport` (storage above the start
baseline), `winter` (survivors when the next spring arrives; requires an
ecosystem), `game` (a newly proposed game), `discovery` (any entity
enters a hidden region). One challenge per kind per world. Wood and stone
blocks can be built over water and walked on; `remove` refuses a plank
under a standing entity. Discovery reports `{"hidden": true}` until it is
completed, then reveals its center. Verdicts are `active`, `completed`,
or `failed`, with `completed_tick`/`failed_reason` and metrics in
`value`/`target`/`unit` form.

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
