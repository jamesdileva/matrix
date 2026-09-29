# Flood: Artificial Agent Lineage & Simulation Platform
## Architecture Specification

**Status:** Baseline architecture  
**Version:** 0.1  
**Purpose:** Scope the technical foundation for a bounded artificial ecosystem in which AI agents reproduce through lineage, inherit information, interact with simulated environments, solve open-ended tasks, and can be observed or entered by a human participant.

---

## 1. Vision

Flood is a local-first experimental platform for creating a bounded "mini-Matrix": a simulated world inhabited by AI agents.

The system is deliberately different from a conventional multi-agent swarm.

A conventional swarm asks:

> How many agents can work on the same problem simultaneously?

Flood asks:

> What happens when agents form lineages, inherit information, develop strategies and culture, operate under finite computation, and inhabit a world that a human can observe or enter?

The platform should support both scientific/engineering experiments and playful interaction.

### Core modes

1. **Observer Mode**
   - Human watches the world from outside.
   - Inspect agents, generations, population statistics, construction, discoveries, communication, and lineage.

2. **Participant Mode**
   - Human enters the simulated world as an entity.
   - Human can talk, move, interact, trade, build, play games, issue challenges, and observe agent reactions.

3. **Experiment Mode**
   - Configure controlled scenarios.
   - Examples:
     - lineage/information drift
     - word-seed generation
     - house construction
     - resource gathering
     - prison escape
     - cooperative puzzles
     - builder-vs-escapee experiments
     - civilization emergence

4. **Replay/Analysis Mode**
   - Pause and replay history.
   - Compare generations and independent populations.
   - Trace the ancestry of information, concepts, behaviors, and objects.

---

## 2. Design Principles

### 2.1 Bounded by default

Agents operate inside a simulation boundary.

They should not have arbitrary access to:
- the host operating system
- arbitrary shell commands
- unrestricted network access
- credentials
- personal data
- uncontrolled external side effects

Simulation tools are explicit capabilities.

### 2.2 Lineage is a first-class primitive

Every agent has:
- unique ID
- generation
- parent
- optional children
- inherited state
- acquired state
- birth/death timestamps
- compute budget
- experiment/population membership

### 2.3 Separate identity from memory

An agent's:
- inherited information
- current working memory
- learned knowledge
- observations
- cultural information
- personality/behavior traits

must be represented separately.

This makes experiments reproducible.

### 2.4 Deterministic world, probabilistic agents

The simulation engine should be as deterministic as practical.

Agent decisions may be probabilistic.

This allows:
- reproducible world physics
- experiment seeds
- controlled model parameters
- replay
- A/B comparison

### 2.5 Compute is a resource

CPU time, model calls, tokens, memory and tool calls can be budgeted.

A future experiment may deliberately impose severe compute limits.

### 2.6 Human interaction is optional

The world must continue functioning without the human.

The participant is an observer/interloper, not the hidden dependency of the simulation.

---

## 3. High-Level Architecture

```text
+-------------------------------------------------------------+
|                         FLOOD UI                            |
|                                                             |
|  Observer | Participant | Experiments | Lineage | Replay   |
+-------------------------------+-----------------------------+
                                |
                                v
+-------------------------------------------------------------+
|                       Simulation API                        |
+-------------------------------+-----------------------------+
                                |
              +-----------------+------------------+
              |                 |                  |
              v                 v                  v
       Simulation Engine   Agent Runtime      Event Bus
              |                 |                  |
              v                 v                  v
       World State          Agent State       Event Log
       Physics              Memory            Metrics
       Objects              Tools             Replay
       Rules                Compute           Audit
              |                 |
              +--------+--------+
                       |
                       v
              Persistence Layer
          SQLite initially / Postgres later
                       |
                       v
              Model Provider Layer
        API model / local model / mock model
```

The UI layer is two clients over the same Simulation API:

- Godot world client — Observer and Participant modes, 3D
- Web research console — Experiments, Lineage, Replay, Metrics

---

## 4. Recommended Initial Technology Stack

### Frontend

Two clients over the same Simulation API.

**Godot 4 — 3D world client**

Use for:
- world rendering
- observer cameras (free-fly, agent follow-cam)
- participant mode (enter and walk the world)
- in-world interaction

The world client renders and proposes actions. It never owns world truth.

World state reaches the client as snapshots and events from the Simulation API.

The first version is deliberately blocky: instanced cubes for terrain, simple emissive figures for agents. The target aesthetic is the "jump into the Matrix" look: dark world, green-tinted grid, glowing agents. This is cheap to build and on-theme. Do not chase realism.

**React + Vite + TypeScript — research console**

Use for:
- observer dashboard
- lineage explorer
- experiment configuration
- event timeline
- metrics
- replay timeline

Godot is poor at data-dense UI. The web console is poor at inhabited 3D worlds. Use each for what it does well.

### Backend

**Python + FastAPI**

Reasons:
- excellent AI ecosystem
- easy simulation development
- straightforward API
- async support
- easy local deployment

### Database

**SQLite initially**

Use SQLAlchemy for persistence.

Move to PostgreSQL only if:
- concurrent simulation workers become necessary
- experiment datasets become large
- remote/multi-machine operation is introduced

### Agent/model abstraction

Create a provider interface:

```python
class ModelProvider:
    async def generate(self, request: ModelRequest) -> ModelResponse:
        ...
```

Possible providers:
- OpenAI-compatible API
- Anthropic-compatible provider
- local Ollama
- deterministic mock provider for tests

The simulation must not depend directly on one model vendor.

### Background execution

Start with Python asyncio/background workers.

Later:
- multiprocessing
- Redis
- Celery/RQ
- distributed worker architecture

Only add these when profiling demonstrates a need.

---

## 5. Repository Structure

```text
flood/
├── README.md
├── architecture.md
├── implementation-guide.md
├── sprint-roadmap.md
├── quick-reference.md
├── .env.example
├── .gitignore
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── api/
│   │   │   ├── agents.py
│   │   │   ├── worlds.py
│   │   │   ├── experiments.py
│   │   │   ├── events.py
│   │   │   ├── participant.py
│   │   │   └── lineage.py
│   │   │
│   │   ├── agents/
│   │   │   ├── agent.py
│   │   │   ├── lifecycle.py
│   │   │   ├── memory.py
│   │   │   ├── inheritance.py
│   │   │   ├── communication.py
│   │   │   ├── cognition.py
│   │   │   └── tools.py
│   │   │
│   │   ├── simulation/
│   │   │   ├── world.py
│   │   │   ├── errors.py
│   │   │   ├── events.py
│   │   │   ├── bus.py
│   │   │   ├── actions.py
│   │   │   ├── agent.py
│   │   │   ├── policies.py
│   │   │   ├── engine.py
│   │   │   ├── physics.py
│   │   │   ├── objects.py
│   │   │   ├── rules.py
│   │   │   └── scenarios/
│   │   │
│   │   ├── models/
│   │   │   ├── provider.py
│   │   │   ├── schemas.py
│   │   │   └── providers/
│   │   │
│   │   ├── persistence/
│   │   │   ├── database.py
│   │   │   ├── models.py
│   │   │   └── repositories.py
│   │   │
│   │   ├── experiments/
│   │   │   ├── runner.py
│   │   │   ├── seeds.py
│   │   │   ├── metrics.py
│   │   │   └── comparison.py
│   │   │
│   │   └── config/
│   │       └── settings.py
│   │
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── scenarios/
│   │
│   ├── alembic/
│   │   └── versions/
│   ├── alembic.ini
│   │
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── lineage/
│   │   ├── experiments/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── types/
│   │   └── App.tsx
│   └── package.json
│
├── world-client/
│   ├── project.godot
│   └── scenes/
│
├── simulation-data/
│   ├── experiments/
│   ├── replays/
│   └── exports/
│
└── docs/
    ├── experiments/
    ├── scenarios/
    └── research-notes/
```

---

## 6. Core Domain Model

### Agent

```text
Agent
- id
- generation
- parent_id
- population_id
- world_id
- status
- birth_tick
- death_tick
- inherited_traits
- inherited_knowledge
- acquired_knowledge
- working_memory
- goals
- compute_budget
- remaining_budget
- location
```

### Population

```text
Population
- id
- name
- world_id
- root_agent_id
- population_rules
- model_configuration
- resource_limits
- created_at
```

### World

```text
World
- id
- name
- seed
- tick
- dimensions
- ruleset
- environment_state
```

### Object

```text
WorldObject
- id
- type
- position
- properties
- owner_id
- created_by_agent_id
- created_tick
```

### Event

Everything important should produce an event.

```text
Event
- id
- world_id
- tick
- timestamp
- type
- actor_id
- target_id
- payload
```

Examples:
- AGENT_BORN
- AGENT_DIED
- MESSAGE_SENT
- KNOWLEDGE_INHERITED
- KNOWLEDGE_CHANGED
- ACTION_ATTEMPTED
- OBJECT_CREATED
- OBJECT_MOVED
- DISCOVERY_MADE
- GOAL_CREATED
- GOAL_COMPLETED
- HUMAN_ENTERED
- HUMAN_MESSAGE
- ESCAPE_ATTEMPT
- SANDBOX_TRANSITION

---

## 7. Agent Architecture

Each agent follows a constrained lifecycle:

```text
OBSERVE
   ↓
UPDATE MEMORY
   ↓
DECIDE
   ↓
ACT
   ↓
REFLECT
   ↓
COMMUNICATE
   ↓
REPRODUCE / CONTINUE
```

The system should not require every agent to execute every phase on every tick.

A scheduler decides when cognition is necessary.

### Parent-child interaction

Default lineage experiment:

```text
Parent
  |
  | inheritance package
  v
Child
```

The inheritance package may contain:

```json
{
  "knowledge": [],
  "stories": [],
  "rules": [],
  "skills": [],
  "traits": [],
  "language": [],
  "message": ""
}
```

The child should not automatically receive the complete database.

---

## 8. Information Categories

Keep these separate:

### Genetic/trait layer
Slow-changing characteristics.

Examples:
- curiosity
- risk tolerance
- cooperation tendency
- memory capacity
- communication preference

### Cultural layer
Information acquired through agents.

Examples:
- stories
- words
- recipes
- construction practices
- traditions
- games

### Episodic layer
Recent experiences.

Examples:
- "The west wall collapsed."
- "Agent 31 helped me."
- "There is water near the hill."

### World knowledge
Facts discovered about the simulation.

Examples:
- water is drinkable
- stone can support structures
- certain resources respawn

### Identity
Agent-specific information.

Examples:
- name
- relationships
- current goals
- personal history

---

## 9. Communication

Initial implementation should support direct messages.

```text
sender -> receiver -> message
```

Later add:

- broadcast
- local speech
- group communication
- cultural artifacts
- symbolic languages

Communication should be logged.

A future compression experiment can measure:
- message length
- semantic similarity
- information retention
- vocabulary growth
- invented symbols

---

## 10. World Simulation

The initial world should be intentionally simple.

### Base primitives

- grid coordinates
- empty space
- walls
- floor
- water
- trees
- stone
- food
- containers
- doors
- switches
- buildable blocks

### Actions

```text
move
look
inspect
pick_up
drop
use
place
build
destroy
speak
listen
trade
```

Every action is validated by the simulation engine.

The model proposes actions; the world decides whether they are legal.

This is important. The LLM should never directly mutate world state.

---

## 11. Observer Mode

Observer mode provides:

- world map
- population count
- active agents
- generation
- world time
- resource statistics
- agent locations
- current actions
- recent events
- lineage overlay
- communication stream

Clicking an agent should show:

```text
Agent #1234
Generation 82

Parent: #1198
Child: #1270

Current goal:
Build shelter

Known concepts:
wood, stone, fire, shelter

Recent memory:
...

Compute remaining:
...
```

---

## 12. Participant Mode

The human becomes a simulated entity.

Capabilities should include:

- move
- speak
- inspect
- pick up
- place
- build
- trade
- play games
- give challenges

The human should have an explicit identity such as:

```text
Participant #1
```

Agents should not automatically know that the participant is the developer/operator.

---

## 13. Scenario System

Scenarios are plugins/configurations over the same engine.

Example:

```python
class Scenario:
    def setup(self, world): ...
    def validate(self, world): ...
    def is_complete(self, world): ...
    def metrics(self, world): ...
```

Initial scenarios:

1. Empty Void
2. Word Seeds
3. Build a House
4. Resource Gathering
5. Cooperative Construction
6. Prison Escape
7. Builder vs Escapee
8. Human Contact
9. Civilization
10. Lineage Drift

---

## 14. Prison Escape Architecture

The prison is a simulated structure.

The "escape" target is another simulated sandbox.

```text
Sandbox A
   |
   | valid simulated transition
   v
Sandbox B
```

Important constraint:

The escape challenge is entirely contained within the simulation.

Agents cannot escape into the host machine.

Metrics:

- time to discovery
- generations to discovery
- attempts
- failed strategies
- successful strategy
- number of agents involved
- information inherited
- cooperation level

---

## 15. Compute Budget

Compute should be abstracted.

```text
ComputeBudget
- model_tokens
- model_calls
- cpu_ms
- tool_calls
- memory_limit
```

The engine decrements resources.

When exhausted:

```text
Agent cannot perform additional cognition
```

The agent can still exist in the world if the scenario permits.

This enables controlled experiments.

---

## 16. Persistence

Persist enough information to reconstruct experiments.

At minimum:

- experiment configuration
- random seed
- model configuration
- world state snapshots
- agent metadata
- lineage relationships
- important memories
- messages
- actions
- discoveries
- metrics
- scenario completion state

Use periodic snapshots plus event logs rather than storing every full world state every tick.

---

## 17. Replay

Replay should reconstruct:

```text
World at Tick 0
    ↓
Tick 1
    ↓
Tick 2
    ↓
...
```

User controls:

- play
- pause
- step
- speed
- jump to event
- jump to generation
- inspect event
- inspect agent

---

## 18. Metrics

Core metrics:

### Lineage
- generation depth
- surviving concepts
- concept drift
- mutation rate
- information loss

### Population
- population size
- births/deaths
- cooperation
- communication volume
- resource consumption

### Problem solving
- attempts
- successful actions
- time to solution
- unique strategies
- solution diversity

### Efficiency
- tokens per successful outcome
- compute per discovery
- messages per successful task
- CPU time per generation

### Civilization
- structures
- technologies
- settlements
- vocabulary
- games
- traditions
- trade relationships

---

## 19. API Baseline

### Worlds

```http
POST /api/worlds
GET  /api/worlds
GET  /api/worlds/{id}
POST /api/worlds/{id}/pause
POST /api/worlds/{id}/resume
```

### Agents

```http
GET /api/worlds/{world_id}/agents
GET /api/agents/{id}
GET /api/agents/{id}/lineage
GET /api/agents/{id}/memory
POST /api/agents/{id}/message
```

### Experiments

```http
POST /api/experiments
GET  /api/experiments
GET  /api/experiments/{id}
POST /api/experiments/{id}/start
POST /api/experiments/{id}/stop
GET  /api/experiments/{id}/metrics
```

### Participant

```http
POST /api/worlds/{id}/participant
POST /api/participant/{id}/move
POST /api/participant/{id}/message
POST /api/participant/{id}/action
```

### Events

```http
GET /api/worlds/{id}/events
GET /api/worlds/{id}/events/stream
```

WebSocket/SSE can be added for live updates.

---

## 20. Security Boundaries

The simulation must be treated as untrusted agent-generated behavior.

Default:
- no shell
- no arbitrary subprocess
- no arbitrary filesystem access
- no unrestricted network
- no credentials
- no host-level automation

All tools are explicit allowlisted functions.

---

## 21. Future Expansion

Potential later systems:

- distributed simulation workers
- multiple worlds
- persistent civilizations
- agent genetics
- agent aging/death
- economy
- language evolution
- diplomacy
- weather
- ecosystems
- animals
- procedural terrain
- multi-model populations
- model-vs-model experiments
- distributed hardware experiments
- VR/3D world
- human multiplayer participation

Do not build these during the MVP.

---

## 22. Architectural Success Criteria

The architecture is successful when the same engine can run:

```text
10,000-generation lineage experiment
        +
100-agent house experiment
        +
prison escape experiment
        +
human participant session
```

without requiring separate simulation implementations.

The central abstraction should remain:

> **Agents exist inside bounded worlds, consume finite resources, communicate, act, inherit information, and generate descendants.**
