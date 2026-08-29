"""Test delle operazioni repository che non devono alterare l'anagrafica al runtime."""

import unittest

from ocpp.v16.db.repository import OcppRepository


class ExistingChargePointPool:
    def __init__(self):
        self.fetchrow_calls = 0
        self.acquire_called = False

    async def fetchrow(self, query, *args):
        self.fetchrow_calls += 1
        self.identity = args[0]
        return {"id": 10, "chargepointorigin": args[0], "serial_number": "SER-01"}

    def acquire(self):
        self.acquire_called = True
        raise AssertionError("Non deve eseguire upsert per un CP già esistente")


class OcppRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_boot_reuses_existing_chargepoint(self):
        pool = ExistingChargePointPool()
        repository = OcppRepository(pool)

        chargepoint = await repository.ensure_chargepoint("CP-01")

        self.assertEqual(chargepoint["serial_number"], "SER-01")
        self.assertEqual(pool.identity, "CP-01")
        self.assertFalse(pool.acquire_called)

    async def test_status_passes_connector_id_only_once(self):
        repository = StatusRepository()

        await repository.update_status(
            "CP-02",
            {
                "connector_id": 1,
                "status": "Available",
                "error_code": "NoError",
            },
        )

        self.assertEqual(repository.connector_id, 1)
        self.assertEqual(
            repository.connector_values,
            {"status": "Available", "error_code": "NoError"},
        )

    async def test_stop_transaction_preserves_reason_or_null(self):
        repository = StopRepository()
        for reason in ("EVDisconnected", "OtherError", None):
            with self.subTest(reason=reason):
                await repository.stop_transaction(
                    "CP-03",
                    {
                        "transaction_id": 7,
                        "meter_stop": 42,
                        "timestamp": "2026-08-29T10:00:00Z",
                        "reason": reason,
                    },
                )
                self.assertEqual(repository.pool.last_execute[1][3], reason)

    async def test_message_response_uses_correlated_action(self):
        pool = CapturePool()
        repository = OcppRepository(pool)

        await repository.record_message(
            "CP-04", '[3,"request-id",{"currentTime":"2026-08-29T10:00:00Z"}]',
            "outgoing", "Heartbeat"
        )

        self.assertEqual(pool.last_execute[1][1], "Heartbeat")


class StatusRepository(OcppRepository):
    def __init__(self):
        self.pool = StatusPool()
        self.connector_id = None
        self.connector_values = None

    async def ensure_chargepoint(self, identity, boot=None, remote_ip=None):
        return {"id": 10, "station_id": 20, "chargepointorigin": identity}

    async def ensure_connector(self, chargepoint, connector_id, **values):
        self.connector_id = connector_id
        self.connector_values = values
        return {"id": 30}


class StatusPool:
    async def execute(self, *args):
        return "UPDATE 1"


class StopRepository(OcppRepository):
    def __init__(self):
        self.pool = CapturePool()

    async def get_transaction(self, transaction_id):
        return {"id": 15, "connector_id": 30}


class CapturePool:
    def __init__(self):
        self.last_execute = None

    async def execute(self, query, *args):
        self.last_execute = (query, args)
        return "UPDATE 1"


if __name__ == "__main__":
    unittest.main()
