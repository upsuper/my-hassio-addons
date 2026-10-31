import http.client
import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pypowerwall

from powerwall.rootfs import server


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.config = self.directory / "config"
        self.config.mkdir()
        self.key = self.config / "custom.pem"
        self.key.write_text("private key placeholder", encoding="utf-8")
        self.options = {
            "host": "192.168.1.50",
            "gw_pwd": "gateway-secret",
            "rsa_key_filename": "custom.pem",
        }
        self.options_path = self.directory / "options.json"

    def load(self):
        self.options_path.write_text(json.dumps(self.options), encoding="utf-8")
        return server.load_options(self.options_path, self.config)

    def test_loads_configurable_key_and_credentials(self):
        self.assertEqual(self.load(), {
            "host": self.options["host"],
            "gw_pwd": self.options["gw_pwd"],
            "rsa_key_path": str(self.key),
        })

    def test_rejects_empty_missing_or_non_string_options(self):
        for name in self.options:
            original = self.options[name]
            for value in ("", "  ", None, False, 123):
                with self.subTest(name=name, value=value):
                    self.options[name] = value
                    with self.assertRaises(ValueError):
                        self.load()
            self.options[name] = original
            del self.options[name]
            with self.assertRaises(ValueError):
                self.load()
            self.options[name] = original

    def test_rejects_paths_and_missing_files(self):
        for filename in ("../custom.pem", "/tmp/key.pem", ".", "..", "missing.pem"):
            with self.subTest(filename=filename):
                self.options["rsa_key_filename"] = filename
                with self.assertRaises((ValueError, OSError)):
                    self.load()

    def test_rejects_symlink_outside_config(self):
        outside = self.directory / "outside.pem"
        outside.write_text("key", encoding="utf-8")
        (self.config / "link.pem").symlink_to(outside)
        self.options["rsa_key_filename"] = "link.pem"
        with self.assertRaises(ValueError):
            self.load()

    def test_rejects_empty_file(self):
        self.key.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.load()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.options = {
            "host": "192.168.1.50",
            "gw_pwd": "gateway-secret",
            "rsa_key_path": "/config/key.pem",
        }
        self.controller = server.BatteryController(self.options)
        self.body = {"power_watts": -1500, "duration_seconds": 60}

    def client(self):
        return Mock(tedapi_mode="v1r", cloudmode=False, fleetapi=False, failover=False)

    def test_explicit_strict_v1r_configuration(self):
        client = self.client()
        client.dispatch_battery_power.return_value = self.body
        with patch.object(pypowerwall, "Powerwall", return_value=client) as factory:
            self.assertEqual(
                self.controller.execute("dispatch_battery_power", self.body), self.body
            )
            factory.assert_called_once_with(
                **self.options, cloudmode=False, fleetapi=False, auto_select=False,
                retry_modes=False, failover=False, wifi_host=None,
                wifi_v1r_fallback=False, timeout=10, cachefile="/data/.powerwall",
            )
        client.dispatch_battery_power.assert_called_once_with(**self.body)

    def test_connect_does_not_issue_battery_commands_and_reuses_client(self):
        client = self.client()
        with patch.object(pypowerwall, "Powerwall", return_value=client) as factory:
            self.controller.connect()
            self.controller.connect()
            factory.assert_called_once()
        self.assertIs(self.controller.client, client)
        client.dispatch_battery_power.assert_not_called()
        client.resume_battery_operation.assert_not_called()

    def test_blocks_wrong_transport(self):
        for attribute, value in (
            ("tedapi_mode", "full"), ("cloudmode", True),
            ("fleetapi", True), ("failover", True),
        ):
            with self.subTest(attribute=attribute):
                client = self.client()
                setattr(client, attribute, value)
                self.controller.client = client
                with self.assertRaises(server.GatewayError):
                    self.controller.execute("resume_battery_operation", {})
                client.resume_battery_operation.assert_not_called()
                self.assertIsNone(self.controller.client)

    def test_failure_discards_client_and_next_request_reconnects(self):
        broken = self.client()
        broken.dispatch_battery_power.return_value = None
        healthy = self.client()
        healthy.resume_battery_operation.return_value = {"resume_battery_operation": True}
        with patch.object(pypowerwall, "Powerwall", side_effect=[broken, healthy]) as factory:
            with self.assertRaises(server.GatewayError):
                self.controller.execute("dispatch_battery_power", self.body)
            broken.dispatch_battery_power.assert_called_once()
            self.assertEqual(
                self.controller.execute("resume_battery_operation", {}),
                {"resume_battery_operation": True},
            )
            self.assertEqual(factory.call_count, 2)

    def test_exception_is_sanitized(self):
        with (
            patch.object(pypowerwall, "Powerwall", side_effect=RuntimeError("secret")),
            self.assertRaises(server.GatewayError) as raised,
        ):
            self.controller.execute("resume_battery_operation", {})
        self.assertNotIn("secret", str(raised.exception))

    def test_real_library_never_constructs_cloud_on_local_failure(self):
        with (
            patch.object(pypowerwall.Powerwall, "_check_if_dir_is_writable"),
            patch.object(pypowerwall, "PyPowerwallTEDAPI") as local,
            patch.object(pypowerwall, "PyPowerwallCloud") as cloud,
            patch.object(pypowerwall, "PyPowerwallFleetAPI") as fleet,
            patch.object(pypowerwall, "PyPowerwallLocal") as legacy,
        ):
            local.return_value.authenticate.side_effect = ConnectionError("offline")
            with self.assertRaises(server.GatewayError):
                self.controller.execute("dispatch_battery_power", self.body)
            self.assertTrue(local.call_args.kwargs["v1r"])
            self.assertFalse(local.call_args.kwargs["failover"])
            cloud.assert_not_called()
            fleet.assert_not_called()
            legacy.assert_not_called()
            local.return_value.dispatch_battery_power.assert_not_called()


class StartupTests(unittest.TestCase):
    def test_only_dispatch_acceptance_warning_is_suppressed(self):
        logger = logging.getLogger("pypowerwall.tedapi.tedapi_v1r")
        with (
            patch.object(logger, "addFilter") as add_filter,
            patch.object(server, "load_options", side_effect=ValueError),
            self.assertRaises(SystemExit),
        ):
            server.main()
        log_filter = add_filter.call_args.args[0]
        for level, message, args, expected in (
            (logging.WARNING, "Battery dispatch accepted: %s", ("charge 500 W",), False),
            (logging.WARNING, "Battery dispatch failed", (), True),
            (logging.ERROR, "Battery dispatch accepted: unexpected error", (), True),
        ):
            with self.subTest(level=level, message=message):
                record = logger.makeRecord(logger.name, level, "", 0, message, args, None)
                self.assertEqual(log_filter(record), expected)

    def test_connects_before_opening_http_server(self):
        with (
            patch.object(server, "load_options", return_value={}),
            patch.object(server, "BatteryController") as controller_factory,
            patch.object(server, "ThreadingHTTPServer") as http_factory,
        ):
            controller = controller_factory.return_value
            http_server = Mock()

            def create_http_server(*args):
                controller.connect.assert_called_once_with()
                return http_server

            http_factory.side_effect = create_http_server
            server.main()
            self.assertEqual(http_factory.call_count, 1)
            self.assertIs(http_server.controller, controller)
            http_server.serve_forever.assert_called_once_with()
            controller.execute.assert_not_called()

    def test_failed_startup_connection_does_not_open_http_server(self):
        with (
            patch.object(server, "load_options", return_value={}),
            patch.object(server, "BatteryController") as controller_factory,
            patch.object(server, "ThreadingHTTPServer") as http_factory,
        ):
            controller_factory.return_value.connect.side_effect = server.GatewayError()
            with self.assertRaises(SystemExit) as raised:
                server.main()
            self.assertEqual(raised.exception.code, 1)
            http_factory.assert_not_called()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.controller = Mock(lock=threading.Lock())
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.BatteryHandler)
        self.httpd.controller = self.controller
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def request(self, path="/battery/dispatch", body=None, method="POST", headers=None):
        connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None
        finally:
            connection.close()

    def post_json(self, body, path="/battery/dispatch"):
        return self.request(path, json.dumps(body), headers={"Content-Type": "application/json"})

    def test_dispatch_signs_zero_and_duration_boundaries(self):
        for power, duration in ((-1500, 60), (0, 1), (1500.5, 86400)):
            with self.subTest(power=power, duration=duration):
                body = {"power_watts": power, "duration_seconds": duration}
                self.controller.execute.return_value = body
                self.assertEqual(self.post_json(body), (200, body))
                self.controller.execute.assert_called_with("dispatch_battery_power", body)

    def test_invalid_dispatch_never_calls_gateway(self):
        invalid = [None, [], {}, {"power_watts": 1}, {"power_watts": 1, "duration_seconds": 1, "extra": 1}]
        for power in (True, False, "100", None, float("nan"), float("inf"), 10**400):
            invalid.append({"power_watts": power, "duration_seconds": 60})
        for duration in (True, False, "60", None, 1.5, 0, -1, 86401):
            invalid.append({"power_watts": 100, "duration_seconds": duration})
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.post_json(body)[0], 400)
        self.controller.execute.assert_not_called()

    def test_resume_with_or_without_json(self):
        result = {"resume_battery_operation": True}
        self.controller.execute.return_value = result
        self.assertEqual(self.request("/battery/resume"), (200, result))
        self.assertEqual(self.post_json({}, "/battery/resume"), (200, result))
        self.controller.execute.assert_called_with("resume_battery_operation", {})
        self.assertEqual(self.post_json({"extra": 1}, "/battery/resume")[0], 400)
        self.assertEqual(self.post_json(None, "/battery/resume")[0], 400)

    def test_request_errors(self):
        cases = [
            ("/unknown", None, "POST", {}, 404),
            ("/battery/dispatch", None, "GET", {}, 405),
            ("/battery/resume", None, "GET", {}, 405),
            ("/battery/dispatch", "{", "POST", {"Content-Type": "application/json"}, 400),
            ("/battery/dispatch", b"\xff", "POST", {"Content-Type": "application/json"}, 400),
            ("/battery/dispatch", "{}", "POST", {}, 415),
            ("/battery/dispatch", "x" * 4097, "POST", {}, 413),
            ("/battery/dispatch", None, "POST", {"Content-Length": "-1"}, 413),
            ("/battery/dispatch", None, "POST", {"Content-Length": "bad"}, 400),
            ("/battery/dispatch", None, "POST", {"Transfer-Encoding": "chunked"}, 400),
        ]
        for path, body, method, headers, expected in cases:
            with self.subTest(expected=expected, headers=headers):
                self.assertEqual(self.request(path, body, method, headers)[0], expected)
        self.controller.execute.assert_not_called()

    def test_busy_returns_conflict_without_gateway_call(self):
        with self.controller.lock:
            self.assertEqual(self.request("/battery/resume")[0], 409)
        self.controller.execute.assert_not_called()

    def test_failure_returns_bad_gateway_and_releases_lock(self):
        self.controller.execute.side_effect = server.GatewayError("secret")
        status, body = self.request("/battery/resume")
        self.assertEqual(status, 502)
        self.assertNotIn("secret", body["error"])
        self.assertFalse(self.controller.lock.locked())
        self.controller.execute.side_effect = None
        self.controller.execute.return_value = {"resume_battery_operation": True}
        self.assertEqual(self.request("/battery/resume")[0], 200)


if __name__ == "__main__":
    unittest.main()
