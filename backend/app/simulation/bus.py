"""Synchronous in-process event bus.

Subscribers are called in subscription order, on the thread that records
the event. The bus never influences world state — it is a read-only
announcement channel — so determinism is unaffected. Outer layers
subscribe to react: the database recorder today, the API/WebSocket
stream later.
"""

from __future__ import annotations

from typing import Callable

from app.simulation.events import Event

EventHandler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def publish(self, event: Event) -> None:
        for handler in list(self._subscribers):
            handler(event)
