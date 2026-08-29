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


if __name__ == "__main__":
    unittest.main()
