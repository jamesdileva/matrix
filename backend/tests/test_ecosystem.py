"""S43 — Ecosystem: deterministic environment, bounded regeneration.

The roadmap asks for two properties, and the tests here hold them:
the same seed produces the same living world, and nothing — plant
biomass, patch count, herd size, energy — grows without a ceiling.
"""

import pytest

from app.simulation.ecosystem import (
    ANIMAL_SPECIES,
    DEFAULT_CONFIG,
    PLANT_SPECIES,
    SEASONS,
    WEATHER_OPTIONS,
    Ecosystem,
    ecosystem_catalog,
    season_for,
    weather_for,
)
from app.simulation.events import EventTypes
from app.simulation.geometry import Position
from app.simulation.world import World


def eco_world(seed="ecosystem", *, width=14, height=14, **config) -> World:
    world = World.generate(seed, width, height)
    world.enable_ecosystem(**config)
    return world


def plants(world: World) -> list:
    return [obj for obj in world.objects if obj.properties.get("regrows")]


def _standable(world: World, cell: Position) -> bool:
    return (
        world.is_floor(cell)
        and world.object_at(cell) is None
        and world.entity_at(cell) is None
    )


def free_cell(world: World) -> Position:
    for y in range(1, world.height - 1):
        for x in range(1, world.width - 1):
            cell = Position(x, y)
            if _standable(world, cell):
                return cell
    raise AssertionError("no free floor cell")


def free_cell_with_neighbour(world: World) -> tuple[Position, Position]:
    for y in range(1, world.height - 1):
        for x in range(1, world.width - 1):
            cell = Position(x, y)
            if not _standable(world, cell):
                continue
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                neighbour = Position(x + dx, y + dy)
                if _standable(world, neighbour):
                    return cell, neighbour
    raise AssertionError("no free adjacent floor cells")


# --- climate ------------------------------------------------------------


def test_seasons_cycle_deterministically():
    assert [season_for(tick, 10) for tick in (0, 9, 10, 20, 30, 40)] == [
        "spring", "spring", "summer", "autumn", "winter", "spring",
    ]
    assert season_for(0, 1) == "spring"
    assert season_for(4, 1) == "spring"


def test_weather_is_a_pure_function_of_seed_tick_and_season():
    first = weather_for("seed", 17, "summer", 5)
    second = weather_for("seed", 17, "summer", 5)
    assert first == second
    assert first in {name for name, _ in WEATHER_OPTIONS["summer"]}
    # Same interval -> same weather even as the tick advances within it.
    assert weather_for("seed", 15, "summer", 5) == weather_for("seed", 19, "summer", 5)


def test_season_change_is_recorded():
    world = World.generate("climate", 12, 12)
    ecosystem = world.enable_ecosystem(season_length=5)
    for _ in range(5):
        world.step()

    assert ecosystem.season == "summer"
    changes = [e for e in world.events if e.type == EventTypes.SEASON_CHANGED]
    assert changes and changes[-1].payload == {"season": "summer", "previous": "spring"}


# --- plants -------------------------------------------------------------


def test_plants_regrow_but_never_past_capacity():
    world = eco_world("grow", width=10, height=10, initial_berries=2, initial_trees=2)
    eco = world.ecosystem
    assert eco is not None
    for obj in plants(world):
        obj.properties["quantity"] = 0

    for _ in range(40):
        world.step()

    assert plants(world)
    for obj in plants(world):
        capacity = obj.properties["capacity"]
        assert 0 <= obj.properties["quantity"] <= capacity
    summary = eco.summary(world)
    assert summary["plants"]["biomass"] <= summary["plants"]["capacity"]
    assert summary["plants"]["count"] <= summary["plants"]["max"]


def test_plant_patches_spread_to_a_cap():
    world = eco_world(
        "spread", width=12, height=12,
        initial_berries=1, initial_trees=0, max_plants=3,
        spread_interval=1,
    )
    for _ in range(200):
        world.step()
    assert len(plants(world)) <= 3


def test_gathering_a_regrowing_plant_leaves_it_and_it_regrows():
    world = World(seed="harvest", width=8, height=8)
    eco = world.enable_ecosystem(
        initial_berries=0, initial_trees=0, initial_grazers=0, initial_predators=0,
        regrow_interval=1,
    )
    plant_cell, agent_cell = free_cell_with_neighbour(world)
    plant = eco.add_plant(world, "berry", plant_cell)
    plant.properties["quantity"] = 1
    world.add_entity(1, agent_cell)

    first = world.execute_action(1, {"action": "gather", "resource": "food"})

    assert first.ok and first.data["amount"] == 1
    assert first.data["depleted"] is False
    assert first.data["source_object_id"] == plant.id
    assert world.get_object(plant.id) is plant  # still rooted
    assert plant.properties["quantity"] == 0

    world.step()

    assert plant.properties["quantity"] > 0


# --- animals and the food chain ----------------------------------------


def test_food_chain_transfers_energy_and_records_it():
    world = World.generate("chain", 6, 6)
    eco = world.enable_ecosystem(
        initial_berries=0, initial_trees=0,
        initial_grazers=0, initial_predators=0,
        max_plants=4, max_grazers=1, max_predators=1, max_total_animals=2,
    )
    cell = free_cell(world)
    plant = eco.add_plant(world, "berry", cell)
    grazer = eco.add_animal("grazer", cell, energy=8)
    predator = eco.add_animal("predator", cell, energy=14)
    grazer_start = grazer.energy
    plant_start = plant.properties["quantity"]

    world.step()

    assert plant.properties["quantity"] == plant_start - 1
    assert eco.stats["plants_eaten"] == 1
    assert eco.stats["grazers_eaten"] == 1
    assert [animal.species for animal in eco.animals] == ["predator"]
    assert eco.animals[0].energy > 14
    assert grazer.energy > grazer_start or grazer not in eco.animals
    got = [e for e in world.events if e.type == EventTypes.ANIMAL_DIED]
    assert any(e.payload["reason"] == "predation" for e in got)


def test_energy_and_populations_stay_bounded():
    world = eco_world(
        "bounds", width=14, height=14,
        initial_grazers=6, initial_predators=2,
        max_grazers=4, max_predators=2, max_total_animals=6,
        max_plants=20,
    )
    eco = world.ecosystem
    for _ in range(300):
        world.step()
        if len(eco.animals) > 6:
            raise AssertionError("population exceeded the total cap")
        assert sum(1 for a in eco.animals if a.species == "grazer") <= 4
        assert sum(1 for a in eco.animals if a.species == "predator") <= 2
        for animal in eco.animals:
            assert 0 <= animal.energy <= ANIMAL_SPECIES[animal.species]["max_energy"]
            assert world.is_floor(animal.position)
        assert len(plants(world)) <= 20

    summary = eco.summary(world)
    assert summary["animals"]["count"] <= 6
    assert summary["plants"]["count"] <= 20


def test_reproduction_respects_caps():
    world = World.generate("family", 8, 8)
    eco = world.enable_ecosystem(
        initial_berries=0, initial_trees=0,
        initial_grazers=0, initial_predators=0,
        max_grazers=2, max_predators=0, max_total_animals=2,
        max_plants=0,
    )
    eco.add_animal("grazer", Position(1, 1), energy=12)
    for _ in range(5):
        world.step()
    assert sum(1 for a in eco.animals if a.species == "grazer") == 2
    for _ in range(20):
        world.step()
    assert sum(1 for a in eco.animals if a.species == "grazer") <= 2


# --- determinism and persistence ---------------------------------------


def test_same_seed_produces_the_same_ecosystem():
    first = eco_world("identical")
    second = eco_world("identical")
    for _ in range(120):
        first.step()
        second.step()

    assert first.ecosystem.to_dict() == second.ecosystem.to_dict()
    assert [
        (obj.id, obj.type, obj.position, obj.properties) for obj in plants(first)
    ] == [
        (obj.id, obj.type, obj.position, obj.properties) for obj in plants(second)
    ]
    assert [event.to_dict() for event in first.events] == [
        event.to_dict() for event in second.events
    ]


def test_ecosystem_survives_a_save_and_restore():
    world = eco_world("resume")
    for _ in range(45):
        world.step()

    restored = World.from_dict(world.to_dict())
    assert restored.ecosystem is not None
    assert restored.ecosystem.to_dict() == world.ecosystem.to_dict()

    for _ in range(25):
        world.step()
        restored.step()
    assert restored.ecosystem.to_dict() == world.ecosystem.to_dict()
    assert [
        (obj.id, obj.properties) for obj in plants(restored)
    ] == [(obj.id, obj.properties) for obj in plants(world)]


def test_ecosystem_is_opt_in():
    world = World.generate("inert", 10, 10)
    before = len(world.objects)
    world.step()
    assert world.ecosystem is None
    assert len(world.objects) == before
    assert world.snapshot()["ecosystem"] is None
    assert world.to_dict()["ecosystem"] is None


def test_enable_twice_and_bad_config_are_rejected():
    world = World.generate("once", 8, 8)
    world.enable_ecosystem()
    with pytest.raises(ValueError):
        world.enable_ecosystem()

    other = World.generate("bad", 8, 8)
    with pytest.raises(ValueError):
        other.enable_ecosystem(max_plants=-1)
    with pytest.raises(TypeError):
        other.enable_ecosystem(unknown_knob=1)


def test_catalog_describes_the_shelf():
    catalog = ecosystem_catalog()
    assert catalog["seasons"] == list(SEASONS)
    assert set(catalog["plants"]) == set(PLANT_SPECIES)
    assert set(catalog["animals"]) == set(ANIMAL_SPECIES)
    assert catalog["defaults"] == DEFAULT_CONFIG
    assert catalog["animals"]["grazer"]["cap"] == ANIMAL_SPECIES["grazer"]["cap"]


def test_ecosystem_constructor_validates_and_restores_tolerantly():
    eco = Ecosystem(season="monsoon", weather="hail")
    assert eco.season == "spring" and eco.weather == "clear"

    tolerant = Ecosystem.from_dict(
        {
            "season": "winter",
            "weather": "snow",
            "max_plants": 4,
            "animals": [{"id": 3, "species": "grazer", "position": {"x": 1, "y": 2}}],
            "next_animal_id": 1,
            "stats": {"births": 2, "junk": 9},
        }
    )
    assert tolerant.season == "winter" and tolerant.weather == "snow"
    assert tolerant.max_plants == 4
    assert tolerant.next_animal_id == 4
    assert tolerant.animals[0].energy == ANIMAL_SPECIES["grazer"]["start_energy"]
    assert tolerant.stats["births"] == 2 and "junk" not in tolerant.stats
