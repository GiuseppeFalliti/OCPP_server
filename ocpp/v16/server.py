"""Server applicativo OCPP 1.6J con persistenza PostgreSQL."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import websockets
import uvicorn
from dotenv import load_dotenv

from ocpp.charge_point import extract_charge_point_id
from ocpp.routing import on
from ocpp.v16 import ChargePoint as BaseChargePoint
from ocpp.v16 import call_result
from ocpp.v16.db.repository import OcppRepository
from ocpp.v16.admin import ActiveChargePoints, create_admin_app
from ocpp.v16.json_logger import ChargePointJsonLogger, JsonLogStore, decode_frame
from ocpp.v16.enums import (
    Action,
    AuthorizationStatus,
    DataTransferStatus,
    RegistrationStatus,
)

LOGGER = logging.getLogger("ocpp.v16.server")


def json_log_details(action, frame) -> dict | None:
    """Espone nei log locali i campi operativi principali di alcuni messaggi."""
    if action != Action.stop_transaction.value:
        return None
    if not isinstance(frame, list) or len(frame) < 4 or not isinstance(frame[3], dict):
        return {"reason": None}
    return {"reason": frame[3].get("reason")}


class ChargePoint(BaseChargePoint):
    """Handler OCPP 1.6J che registra messaggi e dati normalizzati."""

    def __init__(
        self, charge_point_id, connection, repository, json_logger, remote_ip=None
    ):
        super().__init__(charge_point_id, connection)
        self.repository = repository
        self.json_logger: ChargePointJsonLogger = json_logger
        self.remote_ip = remote_ip
        self._request_actions: dict[str, str] = {}

    async def route_message(self, raw_msg):
        action, frame = decode_frame(raw_msg)
        if isinstance(frame, list) and len(frame) > 2 and frame[0] == 2:
            self._request_actions[str(frame[1])] = action
        await self.json_logger.event(
            "message",
            direction="incoming",
            raw=raw_msg,
            action=action,
            details=json_log_details(action, frame),
        )
        await self.repository.record_message(self.id, raw_msg, "incoming", action)
        await super().route_message(raw_msg)

    async def _send(self, message):
        action, frame = decode_frame(message)
        if isinstance(frame, list) and len(frame) > 1 and frame[0] in (3, 4):
            action = self._request_actions.pop(str(frame[1]), action)
        await self.json_logger.event(
            "message", direction="outgoing", raw=message, action=action
        )
        await self.repository.record_message(self.id, message, "outgoing", action)
        await super()._send(message)

    @on(Action.boot_notification)
    async def on_boot_notification(self, **payload):
        chargepoint = await self.repository.ensure_chargepoint(
            self.id, payload, self.remote_ip
        )
        await self.repository.ensure_default_connector(chargepoint)
        await self.json_logger.set_serial_number(chargepoint["serial_number"])
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


async def on_connect(websocket, repository: OcppRepository, log_store: JsonLogStore,
                     active_chargepoints: ActiveChargePoints):
    """Valida il sottoprotocollo e avvia un handler per la connessione CP."""
    if not websocket.subprotocol:
        LOGGER.warning("Sottoprotocollo OCPP non negoziato; chiusura connessione")
        return await websocket.close()
    charge_point_id = extract_charge_point_id(websocket.request.path)
    if not charge_point_id:
        LOGGER.warning("ID charge point mancante nel path %s", websocket.request.path)
        return await websocket.close()
    remote_ip = getattr(websocket, "remote_address", (None,))[0]
    serial_number = await repository.get_chargepoint_serial(charge_point_id)
    json_logger = ChargePointJsonLogger(
        log_store, charge_point_id, remote_ip, serial_number
    )
    await json_logger.event("connected")
    LOGGER.info("Charge point %s connesso", charge_point_id)
    chargepoint = ChargePoint(charge_point_id, websocket, repository, json_logger, remote_ip)
    await active_chargepoints.add(charge_point_id, chargepoint)
    try:
        await chargepoint.start()
    finally:
        await active_chargepoints.remove(charge_point_id, chargepoint)
        await json_logger.event("disconnected")


async def main() -> None:
    """Avvia il listener OCPP e mantiene aperto il pool PostgreSQL."""
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL non e' impostata.")
    host = os.getenv("OCPP_HOST", "0.0.0.0")
    port = int(os.getenv("OCPP_PORT", "9000"))
    ui_host = os.getenv("UI_HOST", "0.0.0.0")
    ui_port = int(os.getenv("UI_PORT", "8080"))
    log_store = JsonLogStore(
        os.getenv("OCPP_LOG_DIR") or None,
        int(os.getenv("OCPP_LOG_RETENTION_DAYS", "30")),
    )
    await log_store.cleanup()
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=10)
    try:
        repository = OcppRepository(pool)
        active_chargepoints = ActiveChargePoints()
        static_dir = Path(__file__).resolve().parents[2] / "ui" / "dist"
        app = create_admin_app(repository, active_chargepoints, static_dir)
        http_server = uvicorn.Server(uvicorn.Config(app, host=ui_host, port=ui_port, log_level="info"))
        http_task = asyncio.create_task(http_server.serve())
        async with websockets.serve(
            lambda websocket: on_connect(websocket, repository, log_store, active_chargepoints),
            host,
            port,
            subprotocols=["ocpp1.6"],
        ):
            LOGGER.info("Server OCPP 1.6J in ascolto su %s:%s", host, port)
            LOGGER.info("Console amministrativa in ascolto su %s:%s", ui_host, ui_port)
            await asyncio.Future()
    finally:
        if "http_server" in locals():
            http_server.should_exit = True
            await http_task
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(main())
