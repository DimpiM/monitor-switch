"""A tiny fan-out bus so browsers can be told about changes instead of polling.

Each subscriber gets its own bounded queue. Bounded matters: a browser tab that
stops reading must not grow the service's memory on a machine with 415 MB of RAM.
When a queue fills, the oldest event is dropped — the next full state push will
repair whatever that client missed.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

MAX_QUEUED_EVENTS = 32


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def publish(self, event: str, data: Any) -> None:
        payload = (event, data)
        with self._lock:
            targets = list(self._subscribers)
        for target in targets:
            try:
                target.put_nowait(payload)
            except queue.Full:
                try:
                    target.get_nowait()      # drop oldest, keep newest
                    target.put_nowait(payload)
                except queue.Empty:          # drained concurrently, fine
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=MAX_QUEUED_EVENTS)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def sse_stream(bus: EventBus, *, keepalive: float = 20.0) -> Iterator[str]:
    """Render a subscription as a text/event-stream body.

    The keepalive comment is not decoration: without traffic, proxies and phone
    radios drop idle connections, and the browser would silently stop updating.
    """
    q = bus.subscribe()
    try:
        yield ": connected\n\n"
        while True:
            try:
                event, data = q.get(timeout=keepalive)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
    except GeneratorExit:
        raise
    finally:
        bus.unsubscribe(q)
