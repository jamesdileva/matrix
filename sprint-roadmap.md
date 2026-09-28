# Flood: Sprint Roadmap

**Status:** Baseline roadmap  
**Version:** 0.1

## Roadmap Philosophy

Flood should be built as an experimental platform, not as one giant simulation.

Each sprint ends with a runnable system and explicit verification.

The roadmap intentionally leaves some later details open. Once the core engine exists, actual experiments will tell us which mechanics deserve additional depth.

---

# Phase 0 — Foundation

## S01 — Repository & Development Baseline

### Goal
Create the project skeleton and local development workflow.

### Build
- Git repository
- backend
- frontend (web console)
- Godot 4 world client project
- environment configuration
- README
- initial architecture docs
- test framework
- basic FastAPI endpoint
- basic React page

### Verification
- Backend starts successfully.
- Frontend starts successfully.
- Godot project opens with an empty main scene.
- Frontend can call backend.
- Health endpoint returns success.
- Test suite runs.
- No secrets committed.

### End Goal
A clean empty Flood project exists and can be developed incrementally.

---

## S02 — Database & Persistence

### Goal
Establish the persistent data model.

### Build
- SQLite
- SQLAlchemy
- migrations
- World
- Agent
- Population
- Event
- Experiment tables

### Verification
- Database initializes from empty state.
- World can be inserted and retrieved.
- Agent can be inserted and retrieved.
- Parent ID can be stored.
- Events persist after process restart.
- Tests use isolated databases.

### End Goal
Flood has durable state.

---

# Phase 1 — The Void

## S03 — Deterministic World Engine

### Goal
Create the first version of the Void.

### Build
- grid world
- coordinates
- empty cells
- walls
- basic objects
- world seed
- simulation tick

### Verification
- Same seed creates same world.
- Tick counter advances correctly.
- Objects have valid positions.
- Invalid positions are rejected.
- World state can be serialized.

### End Goal
A deterministic empty simulation exists.

---

## S04 — Actions & Rules

### Goal
Allow entities to interact with the world.

### Build
Actions:
- move
- look
- inspect
- pick up
- drop
- place

### Verification
- Valid move succeeds.
- Wall collision fails.
- Pick-up works.
- Drop works.
- Invalid actions do not mutate world state.
- Every action creates an event.

### End Goal
The Void has a reliable rules engine.

---

## S05 — Event Bus & Timeline

### Goal
Make everything observable.

### Build
- event model
- event bus
- event persistence
- recent event query
- event filtering

### Verification
Perform a scripted sequence and confirm every expected event exists in the correct order.

### End Goal
Nothing important happens invisibly.

---

# Phase 2 — The First Organism

## S06 — Scripted Agent

### Goal
Create the simplest non-LLM agent.

### Build
- agent lifecycle
- location
- observation
- scripted decisions
- action execution

### Verification
- Agent spawns.
- Agent moves.
- Agent observes.
- Agent interacts with an object.
- Events identify the correct agent.

### End Goal
A non-intelligent agent can live in the Void.

---

## S06B — 3D World Client (Godot)

### Goal
Make the Void visible and enterable in 3D before intelligence arrives.

### Build
- Godot 4 project alongside the backend
- Simulation API client (REST + WebSocket)
- grid terrain rendering with instanced meshes
- agent figures with name labels
- free-fly camera and agent follow-cam
- state updates via snapshots plus interpolation

### Verification
- Client connects to a live simulation and renders real world state.
- Free-fly camera can observe the whole world.
- Selecting an agent locks the camera to it.
- World truth remains server-side; the client only renders and proposes actions.

### End Goal
You can jump into the Void in 3D and watch scripted agents at work.

Aesthetic target: the Matrix look. Dark world, green-tinted grid, glowing agents. Cheap to build, on-theme, no realism.

---

## S07 — Model Provider Abstraction

### Goal
Connect intelligence without coupling the simulation to one provider.

### Build
- ModelProvider interface
- mock provider
- API provider
- structured decision schema
- provider configuration

### Verification
- Mock model works with no network.
- Provider errors do not corrupt world state.
- Invalid model output is rejected.
- Model configuration is recorded with experiment.

### End Goal
Flood can swap brains without changing the world engine.

---

## S08 — First LLM Agent

### Goal
Put an actual language model inside the Void.

### Build
- bounded observations
- structured actions
- model decision loop
- short memory
- action validation

### Verification
- Agent can observe the Void.
- Agent can make a valid action.
- Invalid model action is safely rejected.
- Model response is logged.
- Simulation remains stable after model failure.

### End Goal
The first real AI organism exists inside the sandbox.

---

# Phase 3 — Lineage

## S09 — Birth & Generation

### Goal
Implement reproduction.

### Build
- parent_id
- generation
- child creation
- birth event
- population membership

### Verification
Create:

```text
0 → 1 → 2 → 3 → ... → 100
```

Verify every parent/child relationship and generation number.

### End Goal
Flood has sequential lineage.

---

## S10 — Inheritance

### Goal
Allow information to survive between generations.

### Build
Inheritance package:
- traits
- knowledge
- message
- cultural artifacts

### Verification
- Child receives parent's intended inheritance.
- Uninherited memory does not magically appear.
- Inheritance is recorded.
- Parent and child states remain independent after creation.

### End Goal
The lineage can transmit culture.

---

## S11 — 100-Generation Lineage Experiment

### Goal
Run the first serious experiment.

### Experiment

```text
Agent 0
 ↓
Agent 1
 ↓
...
 ↓
Agent 100
```

Start with a controlled knowledge set.

### Measure
- retained facts
- lost facts
- altered facts
- new facts
- message length
- semantic similarity

### Verification
- Experiment completes without manual intervention.
- Every generation exists.
- Metrics are generated.
- Experiment can be replayed.
- Results can be exported.

### End Goal
We can measure information drift.

---

## S12 — 10,000-Generation Stress Test

### Goal
Test the architecture at the project's signature scale.

### Build
- lightweight agent lifecycle
- snapshot strategy
- event retention policy
- experiment resume
- checkpointing

### Verification
Run a small-model/mock version to 10,000 generations.

Confirm:
- no generation gaps
- no orphaned lineage records
- checkpoint/resume works
- memory usage remains bounded
- database remains queryable

### End Goal
10,000 generations is technically feasible before expensive intelligence experiments begin.

---

# Phase 4 — Observer

## S13 — Observer Dashboard

### Goal
Let the human watch the world.

### Build
- world viewport (embed or link the Godot client; panels stay web)
- population stats
- generation
- active agents
- event stream
- pause/resume

### Verification
Start a simulation and confirm UI updates from real backend events.

### End Goal
You can watch the Flood from outside.

---

## S14 — Agent Inspector

### Goal
Make individual agents inspectable.

### Build
Click agent:
- identity
- generation
- parent
- child
- memory
- knowledge
- current action
- compute budget

### Verification
Selecting different agents shows correct state.

### End Goal
Every organism can be examined.

---

## S15 — Lineage Explorer

### Goal
Visualize ancestry.

### Build
- ancestor chain
- generation navigation
- inherited information comparison
- mutation/drift indicators

### Verification
Select Agent 100 and navigate to Agent 0 and intermediate generations.

### End Goal
The lineage becomes visually understandable.

---

# Phase 5 — Culture & Creation

## S16 — Word Seed Experiment

### Goal
Explore divergent idea generation.

### Build
- seed word
- three-word response
- artifact generation
- artifact storage

### Verification
Run multiple populations from identical seeds.

Compare outputs.

### End Goal
Flood can produce and preserve cultural artifacts.

---

## S17 — Resources

### Goal
Add meaningful environmental constraints.

### Build
- wood
- stone
- water
- food
- resource quantities
- gathering
- inventory

### Verification
Agents can gather resources and resource quantities remain consistent.

### End Goal
Agents need to make decisions under scarcity.

---

## S18 — Building System

### Goal
Let agents construct things.

### Build
- place blocks
- remove blocks
- structure grouping
- material costs
- basic validation

### Verification
Scripted agent can construct a valid structure.

### End Goal
Agents can physically alter the Void.

---

## S19 — House Experiment

### Goal
Ask agents to build a house without prescribing the design.

### Experiment

> Build a house.

### Measure
- completion
- material use
- construction time
- design
- cooperation
- failure

### Verification
At least one scripted agent can complete a known valid house.

LLM agents can then be tested without changing the scenario engine.

### End Goal
We see what different populations build.

---

# Phase 6 — Participant

## S20 — Human Avatar

### Goal
Allow the operator to enter the world.

### Build
- participant entity
- camera and movement (provided by the Godot client)
- interaction
- UI mode switch

### Verification
Observer can enter Participant Mode and move around without stopping the simulation.

### End Goal
The operator can physically enter the Void.

---

## S21 — Human-Agent Conversation

### Goal
Talk to the Flood.

### Build
- participant chat
- agent targeting
- local speech
- response display
- conversation logging

### Verification
Human sends a message to an agent and receives a model-generated response.

### End Goal
You can walk up to an agent and talk to it.

---

## S22 — Social Interaction

### Goal
Expand interaction.

### Build
- trade
- give/take
- follow
- basic group interaction

### Verification
Human can trade an object with an agent and the resulting inventory/world state is correct.

### End Goal
Participant mode becomes interactive rather than observational.

---

# Phase 7 — Escape

## S23 — Prison Sandbox

### Goal
Create the first escape environment.

### Build
- enclosed room
- obstacles
- movable objects
- destination sandbox
- valid escape condition

### Verification
A deterministic scripted solver can escape.

This proves the puzzle is solvable.

### End Goal
There is a safe simulated prison with a known solution.

---

## S24 — Agent Escape

### Goal
Remove the scripted solution.

### Build
- escape objective
- exploration
- failed attempts
- solution detection
- escape metrics

### Verification
LLM agents can attempt the puzzle.
No host-level escape is possible.
Only the simulated transition counts as escape.

### End Goal
The Flood attempts to escape the sandbox.

---

## S25 — Cooperative Escape

### Goal
Make escape require multiple agents.

### Build
- cooperation
- shared observations
- group actions
- communication

### Verification
- Single agent cannot complete puzzle.
- Multiple cooperating scripted agents can.
- Communication is logged.

### End Goal
The Flood can solve a problem through cooperation.

---

## S26 — Builder vs Escapee

### Goal
Create the artificial arms race.

### Build
Population A:
> Build a prison.

Population B:
> Escape.

Repeat multiple rounds.

### Verification
- Prison generated.
- Escape attempt occurs.
- Successful escape is detected.
- Builder receives outcome.
- Next round can use updated rules.

### End Goal
A self-contained evolutionary game exists.

---

# Phase 8 — Civilization

## S27 — Population Manager

### Goal
Move beyond one lineage.

### Build
- populations
- spawn rules
- population statistics
- relationships

### Verification
Run multiple populations simultaneously.

### End Goal
Multiple artificial groups can inhabit one world.

---

## S28 — Communication Networks

### Goal
Support richer communication.

### Build
- local speech
- broadcast
- group communication
- message routing

### Verification
Compare direct communication against group communication.

### End Goal
Information can travel through populations.

---

## S29 — Technology & Cultural Objects

### Goal
Allow useful discoveries to persist.

### Build
- recipes
- construction patterns
- tools
- inventions
- cultural artifacts

### Verification
An agent discovers an object/recipe and a descendant can use it.

### End Goal
Culture becomes cumulative.

---

## S30 — Settlements

### Goal
Allow agents to form persistent communities.

### Build
- homes
- shared storage
- roads
- settlement identity
- resource zones

### Verification
A population can construct and maintain a small settlement.

### End Goal
The Void begins to look inhabited.

---

## S31 — Games

### Goal
Let agents create and play games.

### Build
- rules as data
- game sessions
- players
- scoring
- human participation

### Experiment

> Create a game for the human.

### Verification
Agent-created rules can be represented by the game engine and played without arbitrary code execution.

### End Goal
You can play a game invented by the Flood.

---

# Phase 9 — Experimental Science

## S32 — Multiple Independent Lineages

### Goal
Compare divergent histories.

### Build
Run identical starting conditions with different seeds/models.

### Measure
- cultural convergence
- divergence
- information loss
- strategies
- vocabulary

### Verification
Results are exportable and statistically comparable.

### End Goal
Flood becomes an experimental platform rather than a single simulation.

---

## S33 — Compute-Constrained Lineages

### Goal
Make computation a scarce resource.

### Build
- token budget
- model-call budget
- CPU accounting
- action budget
- experiment-wide compute budget

### Verification
An agent cannot exceed configured resources.

### End Goal
We can compare intelligence under constrained computation.

---

## S34 — Compute Efficiency

### Goal
Measure what agents accomplish per unit of computation.

### Metrics

```text
tokens / discovery
CPU seconds / solution
messages / successful task
compute / surviving concept
```

### Verification
Identical scenarios can be run under different compute budgets.

### End Goal
Flood can answer:

> What can an agent lineage accomplish with limited compute?

---

## S35 — Cultural Compression

### Goal
Test whether lineages develop efficient communication.

### Experiment

Restrict inheritance bandwidth.

Compare:
- verbose transmission
- compressed transmission
- symbolic transmission

### Measure
- bits/tokens transmitted
- retained knowledge
- reconstruction accuracy

### End Goal
Determine whether repeated scarcity encourages communication efficiency.

---

## S36 — Reconstruction Experiment

### Goal
Ask descendants to reconstruct their ancestor.

### Procedure

1. Hide Agent 0.
2. Allow lineage to reach Generation 10,000.
3. Give final descendants limited records.
4. Ask them to reconstruct the original information.

### Measure
- exact recovery
- semantic recovery
- invented history
- confidence

### End Goal
Quantify historical reconstruction failure.

---

# Phase 10 — Mature Flood

## S37 — Replay & Time Machine

### Goal
Make the entire simulation explorable as history.

### Build
- timeline
- generation scrubber
- event jumping
- state snapshots
- comparison view

### Verification
Jump from Generation 10,000 back to Generation 0 and inspect intermediate events.

### End Goal
The world behaves like a time machine.

---

## S38 — World Persistence

### Goal
Allow worlds to live for long periods.

### Build
- autosave
- recovery
- snapshots
- archival
- world resume

### Verification
Kill/restart server and recover the world.

### End Goal
Civilizations can persist beyond one session.

---

## S39 — Multi-World Laboratory

### Goal
Run multiple universes.

### Build
- world templates
- independent seeds
- experiment comparison
- cross-world analytics

### Verification
Run the same experiment in 10 worlds.

### End Goal
Flood becomes a laboratory for parallel artificial histories.

---

## S40 — Flood Research Console

### Goal
Unify the platform.

### Dashboard
- worlds
- populations
- lineages
- experiments
- metrics
- replay
- participant entry
- scenario creation

### Verification
A user can create, run, inspect, replay and export an experiment without editing source code.

### End Goal
Flood is usable as a standalone experimental platform.

---

# Phase 11 — Optional Advanced Experiments

These should only be pursued after the core platform is stable.

## S41 — Agent Genetics

Introduce slowly changing inherited traits.

Verification:
- traits remain bounded
- inheritance is traceable
- mutations are recorded

---

## S42 — Language Evolution

Allow populations to invent shared symbols.

Verification:
- shared vocabulary can emerge
- messages remain parseable
- language changes can be tracked

---

## S43 — Ecosystem

Add:
- animals
- plants
- food chains
- weather
- seasons

Verification:
- deterministic environment
- bounded resource regeneration

---

## S44 — Civilization Challenges

Examples:
- build a bridge
- establish a settlement
- transport resources
- survive a simulated winter
- invent a game
- discover a hidden region

Each challenge gets explicit completion metrics.

---

## S45 — Human Intervention Experiments

Allow the participant to:
- provide information
- remove information
- introduce objects
- give tasks
- join a population
- leave

Measure how intervention changes outcomes.

---

## S46 — Observer vs Participant

Run two otherwise identical worlds:

```text World A
Human never enters

World B
Human participates
```

Compare:
- development
- culture
- behavior
- technology
- communication

---

# Phase 12 — Scaling & Infrastructure

## S47 — Experiment Worker

Separate simulation execution from the API process.

Verification:
- simulation can run independently
- API remains responsive

---

## S48 — Parallel Experiments

Run multiple worlds concurrently.

Verification:
- experiments remain isolated
- resource budgets are respected
- results remain attributable

---

## S49 — Hardware Profiles

Define:

```text Tiny
Desktop
GPU
Cloud
```

Compare identical experiments across hardware.

Verification:
- same experiment configuration
- different compute environment
- comparable metrics

---

## S50 — Distributed Laboratory

Only if justified.

Potential architecture:

```text Controller
   ↓
Queue
   ↓
Workers
 ├── World A
 ├── World B
 ├── World C
 └── World D
```

Verification:
- workers can be added/removed
- failed jobs recover
- experiment state remains consistent

---

# Final Milestone — The Flood

After the core roadmap, the platform should support the following scenario:

```text
                    THE VOID

                 ┌─────────────┐
                 │   SANDBOX   │
                 │             │
                 │  Population │
                 │      ●      │
                 │    ●   ●    │
                 │             │
                 │   Village   │
                 └─────────────┘

                         ▲
                         │
                     PARTICIPANT
                         │

Outside:
──────────────────────────────────────
Observer dashboard
Lineage explorer
Population metrics
Experiment controls
Replay/time machine
──────────────────────────────────────
```

The operator can:

- create worlds
- spawn populations
- seed lineages
- impose compute limits
- create challenges
- observe
- enter the world
- talk to agents
- play games
- inspect ancestors
- compare civilizations
- run escape experiments
- replay history
- measure information drift
- compare resource constraints

The agents remain bounded by the simulation.

---

# Ultimate Definition of Done

Flood has achieved its original vision when all of these can happen using the same engine:

### Lineage

```text
Agent 0
 ↓
Agent 1
 ↓
...
 ↓
Agent 10,000
```

### Construction

```text
"Build a house."
```

### Escape

```text
"Get from Sandbox A to Sandbox B."
```

### Civilization

```text
100+ agents
 ↓
communication
 ↓
resources
 ↓
construction
 ↓
settlement
```

### Games

```text
"Create a game."
 ↓
Flood invents rules
 ↓
Human plays
```

### Observer

```text
Human outside the world
 ↓
watches everything
```

### Participant

```text
Human enters the world
 ↓
talks to Flood
 ↓
interacts with Flood
```

### Research

```text
Fixed compute
 ↓
10,000 generations
 ↓
measure what survived
 ↓
measure what emerged
```

The final product is not intended to answer one predetermined question.

It is a **sandbox for asking questions about artificial lineage, culture, cooperation, problem solving, communication, resource constraints, and human-agent interaction.**
