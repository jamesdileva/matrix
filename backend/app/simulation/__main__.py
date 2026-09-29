"""Generate a deterministic Void and optionally let scripted agents live in it.

    python -m app.simulation --seed matrix --width 32 --height 32
    python -m app.simulation --seed matrix --agents 3 --ticks 40
"""

import argparse

from app.simulation.agent import Agent
from app.simulation.engine import Engine
from app.simulation.policies import WanderPolicy
from app.simulation.world import Position, World


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic Void")
    parser.add_argument("--seed", default="void", help="world seed")
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=32)
    parser.add_argument("--agents", type=int, default=0, help="scripted wander agents to spawn")
    parser.add_argument("--ticks", type=int, default=12, help="simulation ticks to run")
    args = parser.parse_args()

    world = World.generate(seed=args.seed, width=args.width, height=args.height)
    by_type: dict[str, int] = {}
    for obj in world.objects:
        by_type[obj.type] = by_type.get(obj.type, 0) + 1

    print(f"seed={world.seed!r} size={world.width}x{world.height}")
    print(f"objects: {len(world.objects)} {by_type}")

    if args.agents > 0:
        engine = Engine(world)
        spawned = 0
        for y in range(1, world.height - 1):
            for x in range(1, world.width - 1):
                if spawned >= args.agents:
                    break
                pos = Position(x, y)
                if world.is_floor(pos) and world.object_at(pos) is None:
                    engine.spawn_agent(Agent(agent_id=spawned + 1, policy=WanderPolicy()), pos)
                    spawned += 1

        engine.run(args.ticks)

        executed = sum(1 for e in world.events if e.type == "ACTION_EXECUTED")
        rejected = sum(1 for e in world.events if e.type == "ACTION_REJECTED")
        positions = ", ".join(
            f"agent {a.agent_id}@({a.position.x},{a.position.y})" for a in engine.agents
        )
        print(f"agents: {spawned} (wander) | ticks: {args.ticks} | events: {executed} executed, {rejected} rejected")
        print(positions)

    print(world.render())


if __name__ == "__main__":
    main()
