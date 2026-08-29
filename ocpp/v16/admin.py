"""API HTTP amministrativa per la console OCPP."""

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ocpp.v16 import call
from ocpp.v16.db.repository import OcppRepository


class ActiveChargePoints:
    """Registro concorrente delle connessioni OCPP attive."""
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def add(self, identity: str, chargepoint: Any) -> None:
        async with self._lock: self._items[identity] = chargepoint

    async def remove(self, identity: str, chargepoint: Any) -> None:
        async with self._lock:
            if self._items.get(identity) is chargepoint: self._items.pop(identity, None)

    async def get(self, identity: str) -> Any | None:
        async with self._lock: return self._items.get(identity)

    async def identities(self) -> set[str]:
        async with self._lock: return set(self._items)


class ManualChargePoint(BaseModel):
    identity: str = Field(min_length=1, max_length=100)
    serial_number: str = Field(min_length=1, max_length=100)
    vendor: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)


class RemoteStart(BaseModel):
    id_tag: str = Field(min_length=1, max_length=20)
    connector_id: int = Field(default=1, ge=1)


class RemoteStop(BaseModel):
    transaction_id: int = Field(gt=0)


def serialize(value: Any) -> Any:
    if is_dataclass(value): return asdict(value)
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, dict): return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [serialize(item) for item in value]
    try: return {key: serialize(item) for key, item in dict(value).items()}
    except (TypeError, ValueError): return value


def create_admin_app(repository: OcppRepository, active: ActiveChargePoints,
                     static_dir: Path) -> FastAPI:
    app = FastAPI(title="OCPP Server Admin", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    async def health(): return {"status": "ok"}

    @app.get("/api/dashboard")
    async def dashboard():
        data = await repository.dashboard(); data["online_identities"] = sorted(await active.identities())
        return serialize(data)

    @app.get("/api/charge-points")
    async def chargepoints():
        online = await active.identities()
        return [serialize({**dict(item), "connected": item["chargepointorigin"] in online})
                for item in await repository.list_chargepoints()]

    @app.post("/api/charge-points", status_code=201)
    async def create_chargepoint(payload: ManualChargePoint):
        try: item = await repository.create_manual_chargepoint(**payload.model_dump())
        except ValueError as error: raise HTTPException(409, str(error)) from error
        return serialize(item)

    @app.get("/api/charge-points/{identity}")
    async def chargepoint_detail(identity: str):
        detail = await repository.get_chargepoint_detail(identity)
        if not detail: raise HTTPException(404, "Charge Point non trovato")
        detail["connected"] = identity in await active.identities()
        return serialize(detail)

    async def connected_chargepoint(identity: str):
        cp = await active.get(identity)
        if not cp: raise HTTPException(409, "Charge Point non connesso")
        return cp

    @app.post("/api/charge-points/{identity}/remote-start")
    async def remote_start(identity: str, payload: RemoteStart):
        cp = await connected_chargepoint(identity)
        try: response = await cp.call(call.RemoteStartTransaction(payload.id_tag, payload.connector_id), suppress=False)
        except asyncio.TimeoutError as error: raise HTTPException(504, "Timeout della risposta OCPP") from error
        except Exception as error: raise HTTPException(502, str(error)) from error
        return serialize(response)

    @app.post("/api/charge-points/{identity}/remote-stop")
    async def remote_stop(identity: str, payload: RemoteStop):
        cp = await connected_chargepoint(identity)
        try: response = await cp.call(call.RemoteStopTransaction(payload.transaction_id), suppress=False)
        except asyncio.TimeoutError as error: raise HTTPException(504, "Timeout della risposta OCPP") from error
        except Exception as error: raise HTTPException(502, str(error)) from error
        return serialize(response)

    @app.get("/api/logs")
    async def logs(identity: str | None = None, action: str | None = None, way: str | None = None,
                   search: str | None = None, from_date: datetime | None = None, to_date: datetime | None = None,
                   limit: int = 100, offset: int = 0):
        rows, total = await repository.list_logs(identity=identity, action=action, way=way,
                                                  search=search, from_date=from_date, to_date=to_date,
                                                  limit=min(limit, 200), offset=max(offset, 0))
        return {"items": serialize(rows), "total": total, "limit": min(limit, 200), "offset": max(offset, 0)}

    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        @app.get("/{path:path}")
        async def spa(path: str): return FileResponse(static_dir / "index.html")
    return app
