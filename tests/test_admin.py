"""Test essenziali dell'API amministrativa."""

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ocpp.v16.api import ActiveChargePoints, create_admin_app


class RepositoryStub:
    async def dashboard(self): return {"chargepoints": 1, "online": 1, "open_transactions": 0, "recent_activity": []}
    async def list_chargepoints(self): return [{"chargepointorigin": "CP-01", "status": "Available"}]
    async def get_chargepoint(self, identity): return None
    async def create_manual_chargepoint(self, **payload): return {"chargepointorigin": payload["identity"]}
    async def get_chargepoint_detail(self, identity): return None
    async def list_logs(self, **kwargs): return [], 0


class AdminApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_active_registry_replaces_and_removes_session(self):
        registry = ActiveChargePoints(); first = object(); second = object()
        await registry.add("CP-01", first); await registry.add("CP-01", second)
        await registry.remove("CP-01", first)
        self.assertIs(await registry.get("CP-01"), second)
        await registry.remove("CP-01", second)
        self.assertIsNone(await registry.get("CP-01"))

    async def test_remote_transaction_markers_are_consumed_once(self):
        registry = ActiveChargePoints()
        await registry.mark_remote_start("CP-01", "RFID-01", 1)
        await registry.mark_remote_stop("CP-01", 42)

        self.assertTrue(await registry.consume_remote_start("CP-01", "RFID-01", 1))
        self.assertFalse(await registry.consume_remote_start("CP-01", "RFID-01", 1))
        self.assertTrue(await registry.consume_remote_stop("CP-01", 42))
        self.assertFalse(await registry.consume_remote_stop("CP-01", 42))


class AdminHttpTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_admin_app(RepositoryStub(), ActiveChargePoints(), Path("missing-dist")))

    def test_dashboard_is_public(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 200)

    def test_dashboard_and_manual_chargepoint(self):
        self.assertEqual(self.client.get("/api/dashboard").json()["online"], 1)
        response = self.client.post("/api/charge-points", json={"identity":"CP-02", "serial_number":"SER-02", "vendor":"Vendor", "model":"Model"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["chargepointorigin"], "CP-02")


if __name__ == "__main__":
    unittest.main()
