# Flood: Implementation Guide

## 1. Implementation Philosophy

Build this in layers.

Do not start by building "the Flood."

Start with:

1. a deterministic world
2. one simulated agent
3. one model call
4. one action
5. parent/child lineage
6. event logging
7. multiple agents
8. scenarios
9. observer UI
10. participant UI

Every sprint should leave a runnable system.

---

# 2. Phase 0: Repository and Environment

## Backend

Recommended:

```text
Python 3.12+
FastAPI
SQLAlchemy
Pydantic
Uvicorn
pytest
```

Create:

```text
backend/app/
```

Install dependencies in a virtual environment.

## Frontend

Two clients:

```text
Godot 4          3D world client (world, cameras, participant mode)
Vite + React     research console (dashboard, lineage, experiments)
TypeScript
```

Keep both first versions intentionally simple.

---

# 3. Database First

Create SQLAlchemy models for:

```text
World
Population
Agent
AgentRelationship
WorldObject
Event
Experiment
ExperimentMetric
Message
WorldSnapshot
```

Do not store huge prompt/response payloads directly in every frequently queried row.

Separate large transcripts or artifacts if necessary.

---

# 4. World Engine

Implement:

```python
World
WorldObject
Position
Action
Rule
```

The world owns truth.

Example:

```python
result = world.execute_action(
    agent_id,
    action
)
```

The model should never execute:

```python
world.objects[x].position = ...
```

Instead it proposes:

```json
{
  "action": "move",
  "direction": "north"
}
```

The engine validates it.

---

# 5. Tick Loop

Start with a simple loop:

```text
tick
 ↓
update world
 ↓
select agents needing cognition
 ↓
agent observes
 ↓
agent decides
 ↓
validate action
 ↓
apply action
 ↓
emit events
 ↓
repeat
```

Avoid giving every agent a model call every tick.

That becomes extremely expensive.

Use a scheduler.

---

# 6. Agent Observation

Create a bounded observation object.

Example:

```json
{
  "self": {
    "position": [10, 4],
    "energy": 87
  },
  "nearby": [
    {"type": "tree", "distance": 2},
    {"type": "stone", "distance": 4}
  ],
  "messages": [],
  "current_goal": "build shelter"
}
```

Do not send the entire world to the model.

Observation radius should be configurable.

---

# 7. Agent Decision Contract

Use structured output.

Example:

```json
{
  "thought_summary": "A short externally-visible rationale if enabled",
  "action": {
    "type": "move",
    "direction": "north"
  },
  "message": null,
  "goal_update": null
}
```

The production system should not depend on hidden chain-of-thought.

Store:
- action
- concise rationale/decision summary if provided
- observation
- outcome

rather than attempting to capture private reasoning.

---

# 8. Model Provider

Create an interface:

```python
class ModelProvider:
    async def generate(self, request):
        raise NotImplementedError
```

Implement:

```text
MockProvider
OpenAICompatibleProvider
OllamaProvider
```

The MockProvider is critical for tests.

A simulation should be able to run without an LLM.

---

# 9. The First Agent

Implement an agent that can:

```text
observe
decide
move
speak
```

Do not implement reproduction yet.

Verify that one agent can survive several hundred simulation ticks.

---

# 10. Lineage

Add:

```text
parent_id
generation
population_id
```

Implement:

```python
create_child(parent)
```

The child receives an inheritance package.

Start with:

```text
parent -> child message
```

before implementing complex genetics.

---

# 11. First Lineage Experiment

Scenario:

```text
Agent 0 receives 10 facts.

Agent 0 creates Agent 1.

Agent 1 receives the inheritance.

Agent 1 decides what to pass onward.

Repeat to Generation 100.
```

Record every generation.

Calculate:
- exact retention
- semantic similarity
- omissions
- additions
- contradictions

This is the first real Flood experiment.

---

# 12. Word Seed Experiment

Input:

```text
100 agents
1 seed word each
```

Each agent has to produce three associated concepts.

Then ask it to create one artifact:

```text
story
theory
rule
invention
game
poem
building concept
```

Store the artifact as a cultural object.

This tests whether simple seeds create divergent conceptual structures.

---

# 13. World Building

Add:

```text
wood
stone
water
food
walls
doors
blocks
```

Implement building actions.

A building is simply a collection of world objects with relationships.

Example:

```text
Structure
- id
- owner
- components
- purpose
```

Do not attempt architectural realism initially.

---

# 14. House Scenario

Spawn a small population.

Give them:

> Build a house.

Do not specify:
- shape
- size
- material
- room count

Measure:
- completion
- material use
- construction time
- cooperation
- design diversity

Allow the human to inspect the finished structures.

---

# 15. Prison Escape

Create two connected but separate simulation spaces.

```text
Sandbox A
- agents
- resources
- obstacles

Sandbox B
- destination
```

Create a valid route or exploitable puzzle inside the simulation.

Possible mechanisms:

```text
weak wall
movable block
switch
lever
stackable objects
cooperative gate
hidden passage
```

The engine should know the intended solution exists, but agents should not receive it.

Measure discovery.

---

# 16. Escape Arms Race

Implement two populations:

```text
Builders
Escapees
```

Builder population creates a prison.

Escapee population receives the completed prison and attempts escape.

Repeat:

```text
Builder → Prison
Escapee → Escape
Builder → Improve Prison
Escapee → Improve Escape
...
```

This becomes an evolutionary scenario.

---

# 17. Observer UI

Build the UI around panels.

```text
+------------------------------------------------+
| FLOOD | World | Experiment | Lineage | Replay |
+----------------------+-------------------------+
|                      |                         |
|      WORLD           |    SELECTED AGENT       |
|                      |                         |
|                      |                         |
+----------------------+-------------------------+
| Events / Messages / Metrics                    |
+------------------------------------------------+
```

The world viewport is the Godot 3D world client.

It should be deliberately blocky at first.

Dashboard panels are simple 2D web.

Do not spend time on graphics before the simulation works.

---

# 18. Lineage Explorer

Implement a visual ancestry view.

For a selected agent:

```text
Ancestor
  |
  +-- Parent
       |
       +-- Grandparent
            |
            +-- Current Agent
```

For large chains, render a compressed timeline rather than thousands of DOM nodes.

Allow:
- generation jump
- parent lookup
- child lookup
- inherited knowledge comparison

---

# 19. Participant Mode

Create a human entity.

The frontend switches from observer camera to participant camera.

The participant should see:
- nearby agents
- world objects
- messages
- available actions

Add a chat interface.

Example:

```text
YOU:
Why are you building this?

AGENT:
We need shelter before night.
```

---

# 20. Simulation Control

Add:

```text
Pause
Resume
Step
Speed 0.25x
Speed 1x
Speed 10x
```

This is essential for debugging and observation.

---

# 21. Event Architecture

Emit an event for every meaningful state transition.

Example:

```python
event_bus.emit(
    Event(
        type="OBJECT_CREATED",
        actor_id=agent.id,
        payload={...}
    )
)
```

The event stream drives:
- UI updates
- metrics
- replay
- debugging
- audit logs

---

# 22. Replay

Do not attempt perfect replay of an external model unless deterministic settings are available.

Instead preserve enough state/events to replay the world state and show what happened.

Mark model decisions as recorded decisions.

Replay should never call the model again.

---

# 23. Experiment Runner

Create:

```python
ExperimentRunner
```

It receives:

```text
scenario
world seed
agent count
model provider
model settings
compute budget
generation limit
time limit
```

Output:

```text
experiment_id
status
metrics
event log
snapshots
artifacts
```

---

# 24. Compute Accounting

Wrap model calls:

```python
with compute_budget.consume_model_call():
    response = await provider.generate(...)
```

Track:

```text
input tokens
output tokens
calls
elapsed CPU time
tool calls
```

Later add:
- dollar cost
- GPU time
- energy estimates

The first version only needs reliable counters.

---

# 25. Resource-Constrained Experiments

Create configurable profiles:

```yaml
minimal:
  max_model_calls: 10
  max_tokens: 1000

normal:
  max_model_calls: 100
  max_tokens: 10000

abundant:
  max_model_calls: 1000
  max_tokens: 100000
```

Do not equate token limits with CPU limits. Track them separately.

---

# 26. Multiple Models

Once the architecture is stable, allow:

```text
Population A = Model A
Population B = Model B
Population C = Model C
```

Keep world/scenario parameters identical.

This lets us compare:
- strategy
- communication
- efficiency
- cultural drift
- construction
- escape performance

---

# 27. Local Hardware Mode

The initial deployment should run on one PC.

Possible configuration:

```text
Frontend
   ↓
FastAPI
   ↓
Simulation worker
   ↓
Model provider
   ↓
SQLite
```

If a local model is used, it can sit behind the same provider interface.

The system should work with API models too.

---

# 28. Scaling Later

Only after profiling:

```text
Controller
   ↓
Experiment Queue
   ↓
Worker 1
Worker 2
Worker 3
...
```

Each worker can run an independent experiment.

A single lineage does not necessarily need distributed execution.

---

# 29. Testing Strategy

## Unit tests

Test:
- movement
- collision
- object creation
- resource rules
- inheritance
- generation numbers
- budget accounting
- event creation

## Integration tests

Test:

```text
world -> agent -> action -> event -> database
```

## Scenario tests

A prison scenario should have a deterministic fixture in which a known scripted agent can escape.

A house scenario should have a scripted builder that creates a valid structure.

This verifies the environment independently of model intelligence.

---

# 30. Deterministic Test Agents

Create fake agents:

```text
AlwaysMoveNorthAgent
RandomAgent
ScriptedBuilderAgent
ScriptedEscapeAgent
ScriptedCommunicatorAgent
```

These let us test the world without expensive model calls.

---

# 31. Important MVP Boundary

Do NOT initially build:

- realistic 3D graphics
- VR
- sophisticated physics
- persistent civilization
- complex economics
- autonomous internet access
- distributed compute
- genetic algorithms
- large language evolution
- thousands of simultaneous model calls

The first milestone is:

> **One agent can exist, act, communicate, reproduce, and leave a fully inspectable lineage inside a deterministic sandbox.**

Everything else builds on that.

---

# 32. Recommended Development Order

```text
1. Repository
2. Database
3. World
4. Actions
5. Event system
6. One scripted agent
7. Godot 3D world client
8. Model provider
9. One LLM agent
10. Lineage
11. Inheritance
12. Lineage experiment
13. Observer UI (web console)
14. Building
15. House scenario
16. Prison scenario
17. Participant mode
18. Replay
19. Metrics
20. Multiple populations
21. Civilization experiments
```

This order minimizes debugging ambiguity.

---

# 33. Definition of Done for the Core Engine

The core engine is complete when:

- A world can be created from a seed.
- An agent can be created.
- An agent can observe its environment.
- An agent can select an allowed action.
- The engine validates actions.
- Actions produce events.
- Events are persisted.
- An agent can create one descendant.
- The descendant receives inherited information.
- Generation numbers are correct.
- Parent/child relationships are queryable.
- A complete lineage can be replayed.
- Compute consumption is measured.
- The system can run without an LLM using scripted agents.

---

# 34. Long-Term Vision

The mature Flood platform should feel like:

```text
                 FLOOD
                   |
       +-----------+-----------+
       |           |           |
    OBSERVE    PARTICIPATE   EXPERIMENT
       |           |           |
       +-----------+-----------+
                   |
                THE VOID
                   |
       +-----------+-----------+
       |           |           |
   LINEAGES    POPULATIONS   WORLDS
       |           |           |
       +-----------+-----------+
                   |
             EMERGENT SYSTEMS
```

The goal is not to prescribe what the agents become.

The goal is to create a controlled environment in which their behavior can be observed, measured, interacted with, and reproduced as an experiment.
