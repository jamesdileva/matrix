"""The ecosystem (S43): plants, animals, weather, and seasons.

The Void's terrain is inert; this module gives it a metabolism. A world
that opts in carries:

- **plants** as ordinary world objects (berry bushes yield food, trees
  yield wood) tagged ``regrows`` with a ``capacity``. Their biomass
  regrows toward that capacity and never past it, and patches spread to a
  hard cap.
- **animals** — grazers that eat plants and predators that eat grazers.
  Each has bounded energy, a lifespan, and a population cap; reproduction
  splits energy and respects the cap.
- **weather and seasons** derived purely from the seed and the tick, so a
  restored world resumes the same sky and a repeated run is identical.

Determinism contract: nothing here keeps a stateful RNG across ticks.
Weather is chosen by a hash-like seed of ``(seed, interval)`` and animal
choices by ``(seed, tick)``; animals are processed in id order. Given the
same world and seed, the ecosystem evolves identically.

Boundedness contract: plant quantity is clamped to ``[0, capacity]``,
the number of plants to ``max_plants``, each species to its cap, total
animals to ``max_total_animals``, and energy to ``[0, max_energy]``.
Nothing grows without a ceiling.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.simulation.events import EventTypes
from app.simulation.geometry import Position

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.simulation.world import World, WorldObject

SEASONS: tuple[str, ...] = ("spring", "summer", "autumn", "winter")
WEATHERS: tuple[str, ...] = ("clear", "rain", "storm", "snow")

# How much a regrowth pulse adds, by season and weather. Winter and snow
# deliberately add nothing: scarcity is a season, not a bug.
SEASON_GROWTH = {"spring": 2, "summer": 1, "autumn": 1, "winter": 0}
WEATHER_GROWTH = {"clear": 1, "rain": 2, "storm": 0, "snow": 0}

# Extra energy an animal spends per tick, on top of the base cost of 1.
SEASON_COST = {"spring": 0, "summer": 0, "autumn": 1, "winter": 2}
WEATHER_COST = {"clear": 0, "rain": 0, "storm": 1, "snow": 1}

# Weighted weather draws per season.
WEATHER_OPTIONS: dict[str, tuple[tuple[str, int], ...]] = {
    "spring": (("clear", 5), ("rain", 4), ("storm", 1)),
    "summer": (("clear", 7), ("rain", 2), ("storm", 1)),
    "autumn": (("clear", 4), ("rain", 3), ("storm", 3)),
    "winter": (("clear", 3), ("snow", 5), ("storm", 2)),
}

PLANT_SPECIES: dict[str, dict] = {
    "berry": {"object_type": "food", "capacity": 4},
    "tree": {"object_type": "tree", "capacity": 6},
}

ANIMAL_SPECIES: dict[str, dict] = {
    "grazer": {
        "diet": "plant",
        "start_energy": 6,
        "max_energy": 12,
        "gain": 4,
        "lifespan": 160,
        "sense": 8,
        "reproduce_at": 8,
        "cap": 12,
    },
    "predator": {
        "diet": "grazer",
        "start_energy": 14,
        "max_energy": 20,
        "gain": 0,
        "lifespan": 200,
        "sense": 8,
        "reproduce_at": 20,
        "cap": 2,
    },
}

DEFAULT_CONFIG = {
    "season_length": 60,
    "weather_interval": 8,
    "regrow_interval": 3,
    "spread_interval": 20,
    "max_plants": 24,
    "initial_berries": 10,
    "initial_trees": 6,
    "initial_grazers": 6,
    "initial_predators": 1,
    "max_total_animals": 16,
    "max_grazers": 12,
    "max_predators": 2,
}


def season_for(tick: int, season_length: int = 60) -> str:
    """The season at a tick — a pure function, so saves resume the sky."""
    return SEASONS[(tick // season_length) % len(SEASONS)]


def weather_for(seed: str, tick: int, season: str, weather_interval: int = 8) -> str:
    """The weather in force at a tick, seeded by world and interval."""
    interval = tick // weather_interval
    rng = random.Random(f"{seed}:weather:{interval}")
    options = WEATHER_OPTIONS[season]
    return rng.choices(
        [name for name, _ in options],
        weights=[weight for _, weight in options],
        k=1,
    )[0]


def _require_int(name: str, value, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


@dataclass
class Animal:
    """One animal: a position, bounded energy, and an age in ticks."""

    id: int
    species: str
    position: Position
    energy: int
    age: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "species": self.species,
            "position": self.position.to_dict(),
            "energy": self.energy,
            "age": self.age,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Animal":
        species = data.get("species")
        if species not in ANIMAL_SPECIES:
            raise ValueError(f"unknown animal species {species!r}")
        position = data.get("position") or {}
        return cls(
            id=int(data["id"]),
            species=species,
            position=Position(x=int(position["x"]), y=int(position["y"])),
            energy=int(data.get("energy", ANIMAL_SPECIES[species]["start_energy"])),
            age=int(data.get("age", 0)),
        )


@dataclass
class Ecosystem:
    """A world's living layer: cap-bounded plants, animals, and climate."""

    season_length: int = DEFAULT_CONFIG["season_length"]
    weather_interval: int = DEFAULT_CONFIG["weather_interval"]
    regrow_interval: int = DEFAULT_CONFIG["regrow_interval"]
    spread_interval: int = DEFAULT_CONFIG["spread_interval"]
    max_plants: int = DEFAULT_CONFIG["max_plants"]
    initial_berries: int = DEFAULT_CONFIG["initial_berries"]
    initial_trees: int = DEFAULT_CONFIG["initial_trees"]
    initial_grazers: int = DEFAULT_CONFIG["initial_grazers"]
    initial_predators: int = DEFAULT_CONFIG["initial_predators"]
    max_total_animals: int = DEFAULT_CONFIG["max_total_animals"]
    max_grazers: int = DEFAULT_CONFIG["max_grazers"]
    max_predators: int = DEFAULT_CONFIG["max_predators"]
    season: str = "spring"
    weather: str = "clear"
    animals: list[Animal] = field(default_factory=list)
    next_animal_id: int = 1
    stats: dict = field(
        default_factory=lambda: {
            "plants_eaten": 0,
            "grazers_eaten": 0,
            "births": 0,
            "deaths": 0,
        }
    )

    def __post_init__(self) -> None:
        if self.season not in SEASONS:
            self.season = "spring"
        if self.weather not in WEATHERS:
            self.weather = "clear"
        _require_int("season_length", self.season_length, 1)
        _require_int("weather_interval", self.weather_interval, 1)
        _require_int("regrow_interval", self.regrow_interval, 1)
        _require_int("spread_interval", self.spread_interval, 1)
        _require_int("max_plants", self.max_plants, 0)
        _require_int("initial_berries", self.initial_berries, 0)
        _require_int("initial_trees", self.initial_trees, 0)
        _require_int("initial_grazers", self.initial_grazers, 0)
        _require_int("initial_predators", self.initial_predators, 0)
        _require_int("max_total_animals", self.max_total_animals, 0)
        _require_int("max_grazers", self.max_grazers, 0)
        _require_int("max_predators", self.max_predators, 0)
        self.animals = [
            animal
            for animal in self.animals
            if animal.species in ANIMAL_SPECIES
        ]
        self.stats = {
            key: int(self.stats.get(key, 0))
            for key in ("plants_eaten", "grazers_eaten", "births", "deaths")
            if isinstance(self.stats.get(key, 0), int)
            and not isinstance(self.stats.get(key, 0), bool)
            and self.stats.get(key, 0) >= 0
        }
        for key in ("plants_eaten", "grazers_eaten", "births", "deaths"):
            self.stats.setdefault(key, 0)

    # --- configuration -------------------------------------------------

    def cap_for(self, species: str) -> int:
        if species == "grazer":
            return self.max_grazers
        if species == "predator":
            return self.max_predators
        raise ValueError(f"unknown animal species {species!r}")

    # --- seeding -------------------------------------------------------

    def seed(self, world: "World") -> None:
        """Place the initial patches and herds on free cells."""
        self.season = season_for(world.tick, self.season_length)
        self.weather = weather_for(
            world.seed, world.tick, self.season, self.weather_interval
        )
        rng = random.Random(f"{world.seed}:ecosystem:seed")
        cells = _free_cells(world)
        rng.shuffle(cells)

        def take() -> Position | None:
            return cells.pop() if cells else None

        planted = 0
        for species, count in (
            ("berry", self.initial_berries),
            ("tree", self.initial_trees),
        ):
            for _ in range(count):
                if planted >= self.max_plants:
                    break
                position = take()
                if position is None:
                    break
                self.add_plant(world, species, position)
                planted += 1

        placed = 0
        for species, count in (
            ("grazer", self.initial_grazers),
            ("predator", self.initial_predators),
        ):
            for _ in range(count):
                if placed >= self.max_total_animals:
                    break
                if self._count(species) >= self.cap_for(species):
                    break
                position = take()
                if position is None:
                    break
                self.add_animal(species, position)
                placed += 1

        world._add_event(
            EventTypes.ECOSYSTEM_SEEDED,
            payload={
                "season": self.season,
                "weather": self.weather,
                "plants": self._plant_count(world),
                "animals": len(self.animals),
            },
        )

    def add_plant(self, world: "World", species: str, position: Position) -> "WorldObject":
        """Place one plant patch as a regrowing world object."""
        if species not in PLANT_SPECIES:
            raise ValueError(f"unknown plant species {species!r}")
        spec = PLANT_SPECIES[species]
        return world.place_object(
            spec["object_type"],
            position,
            properties={
                "quantity": spec["capacity"],
                "capacity": spec["capacity"],
                "regrows": True,
                "species": species,
            },
        )

    def add_animal(
        self,
        species: str,
        position: Position,
        *,
        energy: int | None = None,
        age: int = 0,
    ) -> Animal:
        """Add an animal. Callers choose the cell (seeding or a test)."""
        if species not in ANIMAL_SPECIES:
            raise ValueError(f"unknown animal species {species!r}")
        spec = ANIMAL_SPECIES[species]
        value = spec["start_energy"] if energy is None else int(energy)
        animal = Animal(
            id=self.next_animal_id,
            species=species,
            position=position,
            energy=max(0, min(int(spec["max_energy"]), value)),
            age=max(0, int(age)),
        )
        self.animals.append(animal)
        self.next_animal_id += 1
        return animal

    # --- the tick ------------------------------------------------------

    def tick(self, world: "World") -> None:
        """Advance climate, plants, and animals by one world tick."""
        tick = world.tick
        season = season_for(tick, self.season_length)
        weather = weather_for(world.seed, tick, season, self.weather_interval)
        if season != self.season:
            world._add_event(
                EventTypes.SEASON_CHANGED,
                payload={"season": season, "previous": self.season},
            )
            self.season = season
        if weather != self.weather:
            world._add_event(
                EventTypes.WEATHER_CHANGED,
                payload={"weather": weather, "previous": self.weather, "season": season},
            )
            self.weather = weather
        if tick % self.regrow_interval == 0:
            self._grow_plants(world)
        if tick % self.spread_interval == 0:
            self._spread_plants(world, tick, season, weather)
        self._tick_animals(world, tick, season, weather)

    def _grow_plants(self, world: "World") -> None:
        growth = SEASON_GROWTH[self.season] + WEATHER_GROWTH[self.weather]
        if growth <= 0:
            return
        for obj in self._plants(world):
            capacity = int(obj.properties.get("capacity", 0))
            quantity = int(obj.properties.get("quantity", 0))
            if quantity < capacity:
                obj.properties["quantity"] = min(capacity, quantity + growth)

    def _spread_plants(
        self, world: "World", tick: int, season: str, weather: str
    ) -> None:
        if season == "winter" or weather in ("storm", "snow"):
            return
        plants = self._plants(world)
        if len(plants) >= self.max_plants:
            return
        rng = random.Random(f"{world.seed}:spread:{tick}")
        for parent in plants:
            if self._plant_count(world) >= self.max_plants:
                break
            spots = [
                cell
                for cell in _neighbours(parent.position)
                if world.is_floor(cell)
                and world.object_at(cell) is None
                and world.entity_at(cell) is None
            ]
            if not spots:
                continue
            species = parent.properties.get("species")
            if species not in PLANT_SPECIES:
                continue
            target = rng.choice(sorted(spots, key=lambda cell: (cell.y, cell.x)))
            self.add_plant(world, species, target)

    def _tick_animals(
        self, world: "World", tick: int, season: str, weather: str
    ) -> None:
        cost = 1 + SEASON_COST[season] + WEATHER_COST[weather]
        rng = random.Random(f"{world.seed}:animals:{tick}")
        dead: set[int] = set()
        newborns: list[Animal] = []
        occupied = {animal.position for animal in self.animals}
        counts = {species: self._count(species) for species in ANIMAL_SPECIES}

        for animal in sorted(self.animals, key=lambda item: item.id):
            if animal.id in dead:
                continue
            spec = ANIMAL_SPECIES[animal.species]
            animal.age += 1
            animal.energy -= cost
            if animal.energy <= 0:
                self._die(world, animal, "starvation", dead, counts, occupied)
                continue
            if animal.age > spec["lifespan"]:
                self._die(world, animal, "age", dead, counts, occupied)
                continue

            target = self._target(world, animal, dead)
            if target is not None and target != animal.position:
                step = _step_toward(animal.position, target)
            elif target is None:
                # No plant or prey in sight: graze the landscape instead
                # of standing still until starvation.
                step = self._wander_step(world, animal, occupied, rng)
            else:
                step = None
            if step is not None and world.is_floor(step):
                # A predator may step onto its prey; nothing else
                # stacks on an occupied cell.
                if step not in occupied or step == target:
                    occupied.discard(animal.position)
                    occupied.add(step)
                    animal.position = step

            if animal.species == "grazer":
                obj = world.object_at(animal.position)
                if (
                    obj is not None
                    and obj.properties.get("regrows")
                    and int(obj.properties.get("quantity", 0)) > 0
                ):
                    obj.properties["quantity"] = int(obj.properties["quantity"]) - 1
                    animal.energy = min(
                        int(spec["max_energy"]), animal.energy + int(spec["gain"])
                    )
                    self.stats["plants_eaten"] += 1
            else:
                prey = next(
                    (
                        other
                        for other in self.animals
                        if other.id not in dead
                        and other.species == "grazer"
                        and other.position == animal.position
                    ),
                    None,
                )
                if prey is not None:
                    dead.add(prey.id)
                    gained = max(2, prey.energy // 2 + int(spec["gain"]))
                    animal.energy = min(
                        int(spec["max_energy"]), animal.energy + gained
                    )
                    self.stats["grazers_eaten"] += 1
                    self._die(world, prey, "predation", dead, counts, occupied)
                    # The predator now stands where the prey stood.
                    occupied.add(animal.position)

            if (
                animal.energy >= int(spec["reproduce_at"])
                and counts[animal.species] < self.cap_for(animal.species)
                and sum(counts.values()) < self.max_total_animals
            ):
                spot = _free_adjacent(world, animal.position, occupied)
                if spot is not None:
                    child_energy = max(1, animal.energy // 2)
                    animal.energy -= child_energy
                    child = Animal(
                        id=self.next_animal_id,
                        species=animal.species,
                        position=spot,
                        energy=child_energy,
                    )
                    self.next_animal_id += 1
                    newborns.append(child)
                    counts[animal.species] += 1
                    occupied.add(spot)
                    self.stats["births"] += 1
                    world._add_event(
                        EventTypes.ANIMAL_BORN,
                        payload={
                            "animal_id": child.id,
                            "species": child.species,
                            "position": spot.to_dict(),
                            "parent_id": animal.id,
                        },
                    )

        self.animals = [
            animal for animal in self.animals if animal.id not in dead
        ] + newborns

    def _wander_step(
        self,
        world: "World",
        animal: Animal,
        occupied: set[Position],
        rng,
    ) -> Position | None:
        options = [
            cell
            for cell in _neighbours(animal.position)
            if world.is_floor(cell)
            and cell not in occupied
            and world.entity_at(cell) is None
        ]
        if not options:
            return None
        return rng.choice(options)

    def _die(
        self,
        world: "World",
        animal: Animal,
        reason: str,
        dead: set[int],
        counts: dict[str, int],
        occupied: set[Position],
    ) -> None:
        dead.add(animal.id)
        counts[animal.species] -= 1
        occupied.discard(animal.position)
        self.stats["deaths"] += 1
        world._add_event(
            EventTypes.ANIMAL_DIED,
            payload={
                "animal_id": animal.id,
                "species": animal.species,
                "position": animal.position.to_dict(),
                "reason": reason,
            },
        )

    def _target(
        self, world: "World", animal: Animal, dead: set[int]
    ) -> Position | None:
        spec = ANIMAL_SPECIES[animal.species]
        if animal.species == "grazer":
            candidates = {
                obj.position
                for obj in self._plants(world)
                if obj.position is not None
                and int(obj.properties.get("quantity", 0)) > 0
            }
        else:
            candidates = {
                other.position
                for other in self.animals
                if other.id not in dead
                and other.id != animal.id
                and other.species == "grazer"
            }
        reachable = [
            position
            for position in candidates
            if _manhattan(animal.position, position) <= int(spec["sense"])
        ]
        if not reachable:
            return None
        return min(
            reachable,
            key=lambda position: (
                _manhattan(animal.position, position),
                position.y,
                position.x,
            ),
        )

    # --- inspection ----------------------------------------------------

    def _plants(self, world: "World") -> list:
        return [
            obj
            for obj in world.objects
            if obj.position is not None and obj.properties.get("regrows")
        ]

    def _plant_count(self, world: "World") -> int:
        return len(self._plants(world))

    def _count(self, species: str) -> int:
        return sum(1 for animal in self.animals if animal.species == species)

    def summary(self, world: "World") -> dict:
        plants = self._plants(world)
        biomass = sum(int(obj.properties.get("quantity", 0)) for obj in plants)
        capacity = sum(int(obj.properties.get("capacity", 0)) for obj in plants)
        return {
            "enabled": True,
            "season": self.season,
            "weather": self.weather,
            "season_length": self.season_length,
            "weather_interval": self.weather_interval,
            "plants": {
                "count": len(plants),
                "biomass": biomass,
                "capacity": capacity,
                "max": self.max_plants,
                "detail": [
                    {
                        "id": obj.id,
                        "species": obj.properties.get("species"),
                        "position": obj.position.to_dict() if obj.position else None,
                        "quantity": int(obj.properties.get("quantity", 0)),
                        "capacity": int(obj.properties.get("capacity", 0)),
                    }
                    for obj in plants
                ],
            },
            "animals": {
                "count": len(self.animals),
                "max_total": self.max_total_animals,
                "by_species": {
                    species: self._count(species) for species in ANIMAL_SPECIES
                },
                "caps": {
                    species: self.cap_for(species) for species in ANIMAL_SPECIES
                },
                "detail": [animal.to_dict() for animal in self.animals],
            },
            "food_chain": {
                "plants_eaten": self.stats["plants_eaten"],
                "grazers_eaten": self.stats["grazers_eaten"],
            },
            "changes": {
                "births": self.stats["births"],
                "deaths": self.stats["deaths"],
            },
        }

    # --- serialization -------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "season_length": self.season_length,
            "weather_interval": self.weather_interval,
            "regrow_interval": self.regrow_interval,
            "spread_interval": self.spread_interval,
            "max_plants": self.max_plants,
            "initial_berries": self.initial_berries,
            "initial_trees": self.initial_trees,
            "initial_grazers": self.initial_grazers,
            "initial_predators": self.initial_predators,
            "max_total_animals": self.max_total_animals,
            "max_grazers": self.max_grazers,
            "max_predators": self.max_predators,
            "season": self.season,
            "weather": self.weather,
            "animals": [animal.to_dict() for animal in self.animals],
            "next_animal_id": self.next_animal_id,
            "stats": dict(self.stats),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ecosystem":
        data = data or {}
        config = {
            key: value
            for key, value in data.items()
            if key in DEFAULT_CONFIG and isinstance(value, int)
            and not isinstance(value, bool)
        }
        animals = []
        for item in data.get("animals") or []:
            try:
                animals.append(Animal.from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        return cls(
            **{**DEFAULT_CONFIG, **config},
            season=data.get("season", "spring"),
            weather=data.get("weather", "clear"),
            animals=animals,
            next_animal_id=max(
                int(data.get("next_animal_id", 1) or 1),
                max((animal.id for animal in animals), default=0) + 1,
            ),
            stats=stats,
        )


def ecosystem_catalog() -> dict:
    """The ecosystem shelf, as data — what a world can be founded with."""
    return {
        "seasons": list(SEASONS),
        "weathers": list(WEATHERS),
        "plants": {
            name: {"object_type": spec["object_type"], "capacity": spec["capacity"]}
            for name, spec in PLANT_SPECIES.items()
        },
        "animals": {
            name: {
                "diet": spec["diet"],
                "start_energy": spec["start_energy"],
                "max_energy": spec["max_energy"],
                "lifespan": spec["lifespan"],
                "sense": spec["sense"],
                "reproduce_at": spec["reproduce_at"],
                "cap": spec["cap"],
            }
            for name, spec in ANIMAL_SPECIES.items()
        },
        "defaults": dict(DEFAULT_CONFIG),
        "season_growth": dict(SEASON_GROWTH),
        "weather_growth": dict(WEATHER_GROWTH),
    }


def _free_cells(world: "World") -> list[Position]:
    from app.simulation.world import Terrain

    return [
        Position(x, y)
        for y in range(1, world.height - 1)
        for x in range(1, world.width - 1)
        if world.terrain_at(Position(x, y)) is Terrain.FLOOR
        and world.object_at(Position(x, y)) is None
        and world.entity_at(Position(x, y)) is None
    ]


def _neighbours(position: Position) -> list[Position]:
    return [
        Position(position.x, position.y - 1),
        Position(position.x + 1, position.y),
        Position(position.x, position.y + 1),
        Position(position.x - 1, position.y),
    ]


def _manhattan(left: Position, right: Position) -> int:
    return abs(left.x - right.x) + abs(left.y - right.y)


def _step_toward(start: Position, target: Position) -> Position | None:
    steps = []
    if target.x != start.x:
        steps.append(Position(start.x + (1 if target.x > start.x else -1), start.y))
    if target.y != start.y:
        steps.append(Position(start.x, start.y + (1 if target.y > start.y else -1)))
    return steps[0] if steps else None


def _free_adjacent(
    world: "World", position: Position, occupied: set[Position]
) -> Position | None:
    for cell in _neighbours(position):
        if (
            world.is_floor(cell)
            and cell not in occupied
            and world.object_at(cell) is None
            and world.entity_at(cell) is None
        ):
            return cell
    return None
