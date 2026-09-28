"""Simulation rule violations. The world rejects; it never half-applies."""


class SimulationError(Exception):
    """Base class for simulation rule violations."""


class InvalidPositionError(SimulationError):
    """A position is out of bounds, non-integer, or on impassable terrain."""


class CellOccupiedError(SimulationError):
    """A cell already holds an object."""
