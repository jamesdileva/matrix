# Flood: Worklog

Working log for the Flood project: what was built, when, and why.

Roadmap: `sprint-roadmap.md` · Architecture: `architecture.md` · Implementation guide: `implementation-guide.md`

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

- **Next sprint:** S01 — Repository & Development Baseline
- Completed sprints: none yet
- Full roadmap: `sprint-roadmap.md`

## Sprint Log

(no entries yet — the first entry lands with S01)
