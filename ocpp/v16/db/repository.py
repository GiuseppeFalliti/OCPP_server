"""Accesso asincrono ai dati persistiti dal server OCPP 1.6J."""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg


def parse_timestamp(value: str | None) -> datetime:
    """Converte un timestamp OCPP in un datetime UTC."""
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def as_json(value: Any) -> str:
    """Serializza payload OCPP ed enum in JSON compatibile con JSONB."""
    return json.dumps(value, default=str, separators=(",", ":"))


def stable_code(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


class OcppRepository:
    """Operazioni PostgreSQL usate dagli handler del Central System."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def record_message(self, identity: str, raw: str, way: str) -> None:
        action = "Unknown"
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list) and len(decoded) > 2:
                action = str(decoded[2]) if decoded[0] == 2 else str(decoded[0])
        except (json.JSONDecodeError, IndexError, TypeError):
            action = "InvalidFrame"
        await self.pool.execute(
            """INSERT INTO ocpp_message_log
               (chargepointorigin, message_type, body, way)
               VALUES ($1, $2, $3, $4)""",
            identity,
            action,
            raw,
            way,
        )

    async def get_chargepoint_serial(self, identity: str) -> str | None:
        """Restituisce il seriale già registrato per l'identità OCPP."""
        return await self.pool.fetchval(
            "SELECT serial_number FROM ocpp_chargepoint WHERE chargepointorigin = $1",
            identity,
        )

    async def get_chargepoint(self, identity: str) -> asyncpg.Record | None:
        """Restituisce il Charge Point già censito, se presente."""
        return await self.pool.fetchrow(
            "SELECT * FROM ocpp_chargepoint WHERE chargepointorigin = $1", identity
        )

    async def ensure_chargepoint(
        self,
        identity: str,
        boot: dict[str, Any] | None = None,
        remote_ip: str | None = None,
    ) -> asyncpg.Record:
        boot = boot or {}
        # Heartbeat e StatusNotification non devono sovrascrivere vendor/modello
        # con i valori predefiniti quando il CP è già stato creato al Boot.
        if not boot:
            existing = await self.get_chargepoint(identity)
            if existing:
                return existing
        vendor_name = str(boot.get("charge_point_vendor") or "Unknown vendor")
        model_name = str(boot.get("charge_point_model") or "Unknown model")
        vendor_code = stable_code("vendor", vendor_name)
        model_code = stable_code("model", f"{vendor_name}:{model_name}")
        station_name = f"Auto station {identity}"
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO ocpp_vendor (code, name, ocpp_id)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name""",
                    vendor_code,
                    vendor_name,
                    vendor_name,
                )
                await connection.execute(
                    """INSERT INTO ocpp_chargepointmodel (code, description, vendor_id)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description""",
                    model_code,
                    model_name,
                    vendor_code,
                )
                station = await connection.fetchrow(
                    """INSERT INTO ocpp_station (name, nickname, charge_network_id, metadata)
                       VALUES ($1, $1, (SELECT id FROM ocpp_network WHERE slug = 'auto-created'), $2::jsonb)
                       ON CONFLICT (name) DO UPDATE SET metadata = ocpp_station.metadata
                       RETURNING id""",
                    station_name,
                    as_json({"auto_created": True, "ocpp_identity": identity}),
                )
                return await connection.fetchrow(
                    """INSERT INTO ocpp_chargepoint
                       (chargepoint_id, name, nickname, serial_number, firmware, iccid, imsi,
                        meter_sn, meter_type, model_id, station_id, chargepointorigin, vendor_id,
                        remote_ip, metadata)
                       VALUES (nextval('ocpp_chargepoint_number_seq'), $1, $1, $2, $3, $4, $5,
                               $6, $7, $8, $9, $10, $11, $12::inet, $13::jsonb)
                       ON CONFLICT (chargepointorigin) DO UPDATE SET
                           serial_number = COALESCE(EXCLUDED.serial_number, ocpp_chargepoint.serial_number),
                           firmware = COALESCE(EXCLUDED.firmware, ocpp_chargepoint.firmware),
                           iccid = COALESCE(EXCLUDED.iccid, ocpp_chargepoint.iccid),
                           imsi = COALESCE(EXCLUDED.imsi, ocpp_chargepoint.imsi),
                           meter_sn = COALESCE(EXCLUDED.meter_sn, ocpp_chargepoint.meter_sn),
                           meter_type = COALESCE(EXCLUDED.meter_type, ocpp_chargepoint.meter_type),
                           model_id = EXCLUDED.model_id, vendor_id = EXCLUDED.vendor_id,
                           remote_ip = COALESCE(EXCLUDED.remote_ip, ocpp_chargepoint.remote_ip),
                           metadata = EXCLUDED.metadata
                       RETURNING *""",
                    identity,
                    boot.get("charge_point_serial_number")
                    or boot.get("charge_box_serial_number"),
                    boot.get("firmware_version"),
                    boot.get("iccid"),
                    boot.get("imsi"),
                    boot.get("meter_serial_number"),
                    boot.get("meter_type"),
                    model_code,
                    station["id"],
                    identity,
                    vendor_code,
                    remote_ip,
                    as_json(boot),
                )

    async def update_heartbeat(self, identity: str) -> None:
        await self.pool.execute(
            "UPDATE ocpp_chargepoint SET last_heartbeat = NOW() WHERE chargepointorigin = $1",
            identity,
        )

    async def ensure_connector(
        self, chargepoint: asyncpg.Record, connector_id: int, **values: Any
    ) -> asyncpg.Record:
        return await self.pool.fetchrow(
            """INSERT INTO ocpp_connector
               (connector_id, chargepoint_id, station_id, plug_type_id, status,
                "errorCode", "vendorErrorCode", metadata)
               VALUES ($1, $2, $3, 'UNKNOWN', $4, $5, $6, $7::jsonb)
               ON CONFLICT (station_id, chargepoint_id, connector_id) DO UPDATE SET
                   status = EXCLUDED.status,
                   "errorCode" = EXCLUDED."errorCode",
                   "vendorErrorCode" = EXCLUDED."vendorErrorCode",
                   metadata = EXCLUDED.metadata,
                   last_heartbeat = NOW()
               RETURNING *""",
            connector_id,
            chargepoint["id"],
            chargepoint["station_id"],
            values.get("status", "Unknown"),
            values.get("error_code"),
            values.get("vendor_error_code"),
            as_json(values),
        )

    async def update_status(
        self, identity: str, payload: dict[str, Any]
    ) -> asyncpg.Record:
        cp = await self.ensure_chargepoint(identity)
        connector_id = payload["connector_id"]
        connector_payload = {
            key: value for key, value in payload.items() if key != "connector_id"
        }
        connector = await self.ensure_connector(cp, connector_id, **connector_payload)
        await self.pool.execute(
            """UPDATE ocpp_chargepoint SET status = $2, last_status = $2,
               last_heartbeat = NOW() WHERE id = $1""",
            cp["id"],
            str(payload["status"]),
        )
        if str(payload["status"]) == "Faulted":
            await self.upsert_alert(cp, connector, "Faulted", payload)
        return connector

    async def upsert_alert(
        self,
        cp: asyncpg.Record,
        connector: asyncpg.Record | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        await self.pool.execute(
            """UPDATE ocpp_alertlog SET last_seen_at = NOW(), updated_at = NOW(),
               status_text = $3, error_code = $4, vendor_error_code = $5, payload = $6::jsonb
               WHERE chargepointorigin = $1 AND event_type = $2 AND active = TRUE""",
            cp["chargepointorigin"],
            event_type,
            str(payload.get("status") or payload.get("status_text")),
            payload.get("error_code"),
            payload.get("vendor_error_code"),
            as_json(payload),
        )
        exists = await self.pool.fetchval(
            "SELECT 1 FROM ocpp_alertlog WHERE chargepointorigin = $1 AND event_type = $2 AND active = TRUE",
            cp["chargepointorigin"],
            event_type,
        )
        if not exists:
            await self.pool.execute(
                """INSERT INTO ocpp_alertlog
                   (chargepointorigin, connectorid, event_type, title, status_text, error_code,
                    vendor_error_code, payload, occurred_at, station_id, network_id)
                   VALUES ($1, $2, $3, $3, $4, $5, $6, $7::jsonb, NOW(), $8,
                       (SELECT charge_network_id FROM ocpp_station WHERE id = $8))""",
                cp["chargepointorigin"],
                connector["id"] if connector else None,
                event_type,
                str(payload.get("status") or payload.get("status_text")),
                payload.get("error_code"),
                payload.get("vendor_error_code"),
                as_json(payload),
                cp["station_id"],
            )

    async def valid_tag(self, id_tag: str) -> bool:
        return bool(
            await self.pool.fetchval(
                """SELECT 1 FROM ocpp_rfid_tag WHERE tag = $1 AND status = 'Accepted'
               AND locked = FALSE AND (expires_at IS NULL OR expires_at > NOW())""",
                id_tag,
            )
        )

    async def record_invalid_tag(
        self, identity: str, id_tag: str, connector_id: int | None = None
    ) -> None:
        cp_id = await self.pool.fetchval(
            "SELECT id FROM ocpp_chargepoint WHERE chargepointorigin = $1", identity
        )
        await self.pool.execute(
            """INSERT INTO ocpp_invalid_id_tag (ocpp_identity, chargepoint_id, connector_id, id_tag, note)
               VALUES ($1, $2, $3, $4, 'RFID non presente, bloccato, scaduto o non Accepted')""",
            identity,
            cp_id,
            connector_id,
            id_tag,
        )

    async def start_transaction(
        self, identity: str, payload: dict[str, Any]
    ) -> asyncpg.Record:
        cp = await self.ensure_chargepoint(identity)
        connector = await self.ensure_connector(cp, payload["connector_id"])
        return await self.pool.fetchrow(
            """INSERT INTO ocpp_transaction
               (transaction_id, id_tag, meter_start, ts_start, reservation_id, connector_id)
               VALUES (nextval('ocpp_transaction_id_seq'), $1, $2, $3, $4, $5) RETURNING *""",
            payload["id_tag"],
            payload["meter_start"],
            parse_timestamp(payload["timestamp"]),
            payload.get("reservation_id"),
            connector["id"],
        )

    async def get_transaction(
        self, transaction_id: int | None
    ) -> asyncpg.Record | None:
        if transaction_id is None:
            return None
        return await self.pool.fetchrow(
            "SELECT * FROM ocpp_transaction WHERE transaction_id = $1", transaction_id
        )

    async def store_meter_values(
        self,
        identity: str,
        connector_id: int,
        meter_values: list[dict[str, Any]],
        transaction_id: int | None = None,
    ) -> None:
        cp = await self.ensure_chargepoint(identity)
        transaction = await self.get_transaction(transaction_id)
        last_meter: int | None = None
        for meter_value in meter_values:
            sampled_at = parse_timestamp(meter_value["timestamp"])
            for sampled in meter_value["sampled_value"]:
                value_text = str(sampled["value"])
                try:
                    value = Decimal(value_text)
                except InvalidOperation:
                    value = None
                if value is not None and value == value.to_integral_value():
                    last_meter = int(value)
                await self.pool.execute(
                    """INSERT INTO ocpp_metervalues
                       (charge_point_id, ocpp_identity, connector_id, transaction_db_id,
                        ocpp_transaction_pk, sampled_at, measurand, context, unit, value,
                        value_text, format, phase, location, raw)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)""",
                    cp["id"],
                    identity,
                    connector_id,
                    transaction["id"] if transaction else None,
                    transaction_id,
                    sampled_at,
                    sampled.get("measurand"),
                    sampled.get("context"),
                    sampled.get("unit"),
                    value,
                    value_text,
                    sampled.get("format"),
                    sampled.get("phase"),
                    sampled.get("location"),
                    as_json(
                        {
                            "timestamp": meter_value["timestamp"],
                            "sampled_value": sampled,
                        }
                    ),
                )
        if transaction:
            await self.pool.execute(
                """UPDATE ocpp_transaction SET ts_last_meter = NOW(),
                   last_meter = COALESCE($2, last_meter) WHERE id = $1""",
                transaction["id"],
                last_meter,
            )

    async def record_failure_event(
        self, identity: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Crea o aggiorna un alert per un evento operativo fallito."""
        cp = await self.ensure_chargepoint(identity)
        await self.upsert_alert(cp, None, event_type, payload)

    async def stop_transaction(self, identity: str, payload: dict[str, Any]) -> None:
        transaction = await self.get_transaction(payload["transaction_id"])
        if not transaction:
            return
        await self.pool.execute(
            """UPDATE ocpp_transaction SET meter_stop = $2, ts_stop = $3, reason = $4,
               ts_last_meter = $3, last_meter = $2 WHERE id = $1""",
            transaction["id"],
            payload["meter_stop"],
            parse_timestamp(payload["timestamp"]),
            str(payload.get("reason")) if payload.get("reason") else None,
        )
        if payload.get("transaction_data"):
            connector_id = await self.pool.fetchval(
                "SELECT connector_id FROM ocpp_connector WHERE id = $1",
                transaction["connector_id"],
            )
            await self.store_meter_values(
                identity,
                connector_id,
                payload["transaction_data"],
                payload["transaction_id"],
            )
