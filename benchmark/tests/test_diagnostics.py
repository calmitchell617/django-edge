import unittest

from edge.diagnostics import error_details


class DiagnosticsTests(unittest.TestCase):
    def test_cause_locations_exclude_messages_and_local_values(self):
        try:
            try:
                raise ValueError("password=private-value")
            except ValueError as cause:
                raise RuntimeError("dsn=private-dsn") from cause
        except RuntimeError as error:
            details = error_details(error)
        self.assertEqual(details["error"], "RuntimeError")
        self.assertEqual(len(details["locations"]), 2)
        self.assertNotIn("private", str(details))

    def test_rpc_traceback_retains_only_locations(self):
        class JsException(Exception):
            pass

        details = error_details(
            JsException(
                'File "/bundle/maintenance.py", line 50, in seed\n'
                '    password = "secret"\nValueError: password=secret'
            )
        )
        self.assertEqual(details["locations"], ["maintenance.py:50:seed"])
        self.assertNotIn("secret", str(details))
