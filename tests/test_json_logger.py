"""Test del logging locale JSON Lines OCPP."""

import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from ocpp.v16.json_logger import ChargePointJsonLogger, JsonLogStore


class JsonLogStoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "Logs"
        self.store = JsonLogStore(self.root, retention_days=30)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_temporary_directory_is_renamed_to_serial(self):
        logger = ChargePointJsonLogger(self.store, "CP-01", "203.0.113.10")
        await logger.event("message", direction="incoming", raw='[2,"a","Heartbeat",{}]')
        temporary = self.store.directory_for("CP-01", temporary=True)
        self.assertTrue(temporary.exists())

        await logger.set_serial_number("SER/01")
        directory = self.store.directory_for("SER/01")
        self.assertEqual(logger.directory, directory)
        self.assertFalse(temporary.exists())
        records = self._records(directory)
        self.assertEqual(records[0]["action"], "Heartbeat")
        self.assertIsNone(records[0]["serial_number"])

    async def test_known_serial_uses_serial_directory_and_json_lines(self):
        logger = ChargePointJsonLogger(
            self.store, "CP-02", "203.0.113.11", serial_number="SER-02"
        )
        await asyncio.gather(
            *[
                logger.event("message", direction="outgoing", raw='[3,"a",{}]')
                for _ in range(10)
            ]
        )
        records = self._records(self.store.directory_for("SER-02"))
        self.assertEqual(len(records), 10)
        self.assertTrue(all(record["serial_number"] == "SER-02" for record in records))
        self.assertTrue(all(record["action"] == "CallResult" for record in records))

    async def test_cleanup_removes_only_files_older_than_retention(self):
        directory = self.store.directory_for("SER-03")
        directory.mkdir(parents=True)
        old = directory / f"{(date.today() - timedelta(days=31)).isoformat()}.json"
        current = directory / f"{date.today().isoformat()}.json"
        old.write_text('{"old":true}\n', encoding="utf-8")
        current.write_text('{"current":true}\n', encoding="utf-8")

        await self.store.cleanup()

        self.assertFalse(old.exists())
        self.assertTrue(current.exists())

    async def test_invalid_frame_and_non_json_details_are_preserved(self):
        logger = ChargePointJsonLogger(self.store, "CP-04", None, "SER-04")
        await logger.event(
            "message",
            direction="incoming",
            raw="not-json",
            details={"value": object()},
        )

        record = self._records(self.store.directory_for("SER-04"))[0]
        self.assertEqual(record["action"], "InvalidFrame")
        self.assertIsNone(record["frame"])
        self.assertIsInstance(record["details"]["value"], str)

    def _records(self, directory: Path) -> list[dict]:
        log_file = directory / f"{date.today().isoformat()}.json"
        return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
