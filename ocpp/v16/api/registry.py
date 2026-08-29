"""Registro delle connessioni OCPP e delle operazioni remote pendenti."""

import asyncio
import time
from typing import Any


class ActiveChargePoints:
    """Registro concorrente dei CP connessi e dei comandi API già accettati."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self._remote_starts: dict[tuple[str, str, int], float] = {}
        self._remote_stops: dict[tuple[str, int], float] = {}
        self._lock = asyncio.Lock()

    async def add(self, identity: str, chargepoint: Any) -> None:
        async with self._lock:
            self._items[identity] = chargepoint

    async def remove(self, identity: str, chargepoint: Any) -> None:
        async with self._lock:
            if self._items.get(identity) is chargepoint:
                self._items.pop(identity, None)

    async def get(self, identity: str) -> Any | None:
        async with self._lock:
            return self._items.get(identity)

    async def identities(self) -> set[str]:
        async with self._lock:
            return set(self._items)

    async def mark_remote_start(self, identity: str, id_tag: str, connector_id: int) -> None:
        async with self._lock:
            self._remote_starts[(identity, id_tag, connector_id)] = time.monotonic()

    async def mark_remote_stop(self, identity: str, transaction_id: int) -> None:
        async with self._lock:
            self._remote_stops[(identity, transaction_id)] = time.monotonic()

    async def consume_remote_start(self, identity: str, id_tag: str, connector_id: int) -> bool:
        async with self._lock:
            return self._consume(self._remote_starts, (identity, id_tag, connector_id))

    async def consume_remote_stop(self, identity: str, transaction_id: int) -> bool:
        async with self._lock:
            return self._consume(self._remote_stops, (identity, transaction_id))

    @staticmethod
    def _consume(items: dict[tuple, float], key: tuple) -> bool:
        timestamp = items.pop(key, None)
        return timestamp is not None and time.monotonic() - timestamp <= 600
