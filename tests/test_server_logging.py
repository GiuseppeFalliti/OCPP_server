"""Test dei dettagli estratti per i log del server OCPP."""

import unittest

from ocpp.v16.server import json_log_details


class ServerLoggingTest(unittest.TestCase):
    def test_stop_transaction_reason_is_exposed_in_json_log(self):
        frame = [2, "request-id", "StopTransaction", {"reason": "EVDisconnected"}]
        self.assertEqual(
            json_log_details("StopTransaction", frame), {"reason": "EVDisconnected"}
        )

    def test_stop_without_reason_is_explicitly_null(self):
        frame = [2, "request-id", "StopTransaction", {}]
        self.assertEqual(json_log_details("StopTransaction", frame), {"reason": None})

    def test_other_actions_do_not_add_stop_details(self):
        self.assertIsNone(json_log_details("Heartbeat", [2, "request-id", "Heartbeat", {}]))


if __name__ == "__main__":
    unittest.main()
