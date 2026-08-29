"""Server applicativo OCPP 1.6J con persistenza PostgreSQL."""

import asyncio
import logging
import os
from datetime import datetime, timezone

import asyncpg
import websockets
from dotenv import load_dotenv

from ocpp.charge_point import extract_charge_point_id
from ocpp.routing import on
from ocpp.v16 import ChargePoint as BaseChargePoint
from ocpp.v16 import call_result
from ocpp.v16.db.repository import OcppRepository
from ocpp.v16.enums import (
    Action,
    AuthorizationStatus,
    DataTransferStatus,
    RegistrationStatus,
)

LOGGER = logging.getLogger("ocpp.v16.server")


class ChargePoint(BaseChargePoint):
    """Handler OCPP 1.6J che registra messaggi e dati normalizzati."""

    def __init__(self, charge_point_id, connection, repository, remote_ip=None):
        super().__init__(charge_point_id, connection)
        self.repository = repository
        self.remote_ip = remote_ip

    async def route_message(self, raw_msg):
        await self.repository.record_message(self.id, raw_msg, "incoming")
        await super().route_message(raw_msg)

    async def _send(self, message):
        await self.repository.record_message(self.id, message, "outgoing")
        await super()._send(message)

    @on(Action.boot_notification)
    async def on_boot_notification(self, **payload):
        await self.repository.ensure_chargepoint(self.id, payload, self.remote_ip)
        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=int(os.getenv("HEARTBEAT_INTERVAL", "60")),
            status=RegistrationStatus.accepted,
        )

    @on(Action.heartbeat)
    async def on_heartbeat(self):
        await self.repository.ensure_chargepoint(self.id, remote_ip=self.remote_ip)
        await self.repository.update_heartbeat(self.id)
        return call_result.Heartbeat(
            current_time=datetime.now(timezone.utc).isoformat()
        )

    @on(Action.status_notification)
    async def on_status_notification(self, **payload):
        await self.repository.update_status(self.id, payload)
        return call_result.StatusNotification()

    @on(Action.authorize)
    async def on_authorize(self, id_tag, **_):
        is_valid = await self.repository.valid_tag(id_tag)
        if not is_valid:
            await self.repository.record_invalid_tag(self.id, id_tag)
        return call_result.Authorize(
            id_tag_info={
                "status": (
                    AuthorizationStatus.accepted
                    if is_valid
                    else AuthorizationStatus.invalid
                )
            }
        )

    @on(Action.start_transaction)
    async def on_start_transaction(self, id_tag, connector_id, **payload):
        if not await self.repository.valid_tag(id_tag):
            await self.repository.record_invalid_tag(self.id, id_tag, connector_id)
            return call_result.StartTransaction(
                transaction_id=0, id_tag_info={"status": AuthorizationStatus.invalid}
            )
        transaction = await self.repository.start_transaction(
            self.id, {"id_tag": id_tag, "connector_id": connector_id, **payload}
        )
        return call_result.StartTransaction(
            transaction_id=transaction["transaction_id"],
            id_tag_info={"status": AuthorizationStatus.accepted},
        )

    @on(Action.meter_values)
    async def on_meter_values(
        self, connector_id, meter_value, transaction_id=None, **_
    ):
        await self.repository.store_meter_values(
            self.id, connector_id, meter_value, transaction_id
        )
        return call_result.MeterValues()

    @on(Action.stop_transaction)
    async def on_stop_transaction(self, **payload):
        await self.repository.stop_transaction(self.id, payload)
        return call_result.StopTransaction()

    @on(Action.firmware_status_notification)
    async def on_firmware_status_notification(self, status, **payload):
        if "Failed" in str(status):
            await self.repository.record_failure_event(
                self.id, "FirmwareStatusNotification", {"status": status, **payload}
            )
        return call_result.FirmwareStatusNotification()

    @on(Action.diagnostics_status_notification)
    async def on_diagnostics_status_notification(self, status, **payload):
        if "Failed" in str(status):
            await self.repository.record_failure_event(
                self.id, "DiagnosticsStatusNotification", {"status": status, **payload}
            )
        return call_result.DiagnosticsStatusNotification()

    @on(Action.log_status_notification)
    async def on_log_status_notification(self, status, request_id, **payload):
        if "Failed" in str(status):
            await self.repository.record_failure_event(
                self.id,
                "LogStatusNotification",
                {"status": status, "request_id": request_id, **payload},
            )
        return call_result.LogStatusNotification()

    @on(Action.security_event_notification)
    async def on_security_event_notification(self, type, timestamp, **payload):
        await self.repository.record_failure_event(
            self.id,
            "SecurityEventNotification",
            {"type": type, "timestamp": timestamp, **payload},
        )
        return call_result.SecurityEventNotification()

    @on(Action.data_transfer)
    async def on_data_transfer(self, **_):
        return call_result.DataTransfer(status=DataTransferStatus.rejected)


async def on_connect(websocket, repository: OcppRepository):
    """Valida il sottoprotocollo e avvia un handler per la connessione CP."""
    if not websocket.subprotocol:
        LOGGER.warning("Sottoprotocollo OCPP non negoziato; chiusura connessione")
        return await websocket.close()
    charge_point_id = extract_charge_point_id(websocket.request.path)
    if not charge_point_id:
        LOGGER.warning("ID charge point mancante nel path %s", websocket.request.path)
        return await websocket.close()
    remote_ip = getattr(websocket, "remote_address", (None,))[0]
    LOGGER.info("Charge point %s connesso", charge_point_id)
    await ChargePoint(charge_point_id, websocket, repository, remote_ip).start()


async def main() -> None:
    """Avvia il listener OCPP e mantiene aperto il pool PostgreSQL."""
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL non e' impostata.")
    host = os.getenv("OCPP_HOST", "0.0.0.0")
    port = int(os.getenv("OCPP_PORT", "9000"))
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=10)
    try:
        repository = OcppRepository(pool)
        async with websockets.serve(
            lambda websocket: on_connect(websocket, repository),
            host,
            port,
            subprotocols=["ocpp1.6"],
        ):
            LOGGER.info("Server OCPP 1.6J in ascolto su %s:%s", host, port)
            await asyncio.Future()
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(main())
