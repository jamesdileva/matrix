"""Generate and display a deterministic Void.

    python -m app.simulation --seed matrix --width 32 --height 32
"""

import argparse

from app.simulation.world import World


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic Void")
    parser.add_argument("--seed", default="void", help="world seed")
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=32)
    args = parser.parse_args()

    world = World.generate(seed=args.seed, width=args.width, height=args.height)
    by_type: dict[str, int] = {}
    for obj in world.objects:
        by_type[obj.type] = by_type.get(obj.type, 0) + 1

    print(f"seed={world.seed!r} size={world.width}x{world.height} tick={world.tick}")
    print(f"objects: {len(world.objects)} {by_type}")
    print(world.render())


if __name__ == "__main__":
    main()
