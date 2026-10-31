import json
import logging
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pypowerwall

LOGGER = logging.getLogger("powerwall")
ROUTES = {
    "/battery/dispatch": "dispatch_battery_power",
    "/battery/resume": "resume_battery_operation",
}
MAX_BODY_SIZE = 4096


def load_options(options_path="/data/options.json", config_path="/config"):
    with open(options_path, encoding="utf-8") as options_file:
        options = json.load(options_file)
    for name in ("host", "gw_pwd", "rsa_key_filename"):
        if not isinstance(options.get(name), str) or not options[name].strip():
            raise ValueError(f"{name} must be configured")

    filename = options["rsa_key_filename"]
    if filename in (".", "..") or Path(filename).name != filename:
        raise ValueError("rsa_key_filename must be a filename, not a path")
    config_directory = Path(config_path).resolve()
    key_path = (config_directory / filename).resolve(strict=True)
    if key_path.parent != config_directory or not key_path.is_file():
        raise ValueError("RSA key must be a file inside the app configuration directory")
    with key_path.open("rb") as key_file:
        if not key_file.read(1):
            raise ValueError("RSA key file is empty")
    return {
        "host": options["host"].strip(),
        "gw_pwd": options["gw_pwd"],
        "rsa_key_path": str(key_path),
    }


def validate_dispatch(body):
    if not isinstance(body, dict) or set(body) != {"power_watts", "duration_seconds"}:
        raise ValueError("Expected power_watts and duration_seconds only")
    power = body["power_watts"]
    duration = body["duration_seconds"]
    try:
        valid_power = type(power) in (int, float) and math.isfinite(power)
    except OverflowError:
        valid_power = False
    if not valid_power:
        raise ValueError("power_watts must be a finite number, not a boolean")
    if type(duration) is not int or not 1 <= duration <= 86400:
        raise ValueError("duration_seconds must be an integer from 1 to 86400")


class GatewayError(Exception):
    pass


class RequestError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class BatteryController:
    def __init__(self, options):
        self.options = options
        self.lock = threading.Lock()
        self.client = None

    def connect(self):
        try:
            if self.client is None:
                self.client = pypowerwall.Powerwall(
                    **self.options,
                    cloudmode=False,
                    fleetapi=False,
                    auto_select=False,
                    retry_modes=False,
                    failover=False,
                    wifi_host=None,
                    wifi_v1r_fallback=False,
                    timeout=10,
                    cachefile="/data/.powerwall",
                )
            if (
                self.client.tedapi_mode != "v1r"
                or self.client.cloudmode
                or self.client.fleetapi
                or self.client.failover
            ):
                raise GatewayError()
        except Exception as error:
            self.client = None
            LOGGER.warning("Local v1r connection failed")
            raise GatewayError() from error

    def execute(self, operation, body):
        self.connect()
        try:
            result = getattr(self.client, operation)(**body)
            if not isinstance(result, dict) or not result:
                raise GatewayError()
            return result
        except Exception as error:
            # Reconnect locally on the next request; never retry a battery command.
            self.client = None
            LOGGER.warning("Local v1r operation failed or was not acknowledged")
            raise GatewayError() from error


class BatteryHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send_json(self, status, body):
        data = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding is not supported")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length") from None
        if not 0 <= length <= MAX_BODY_SIZE:
            raise RequestError(413, "Request body too large or invalid length")
        if not length:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "Expected application/json")
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("Incomplete request body")
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ValueError("Invalid JSON body") from None

    def do_POST(self):
        operation = ROUTES.get(urlsplit(self.path).path)
        if operation is None:
            self.send_json(404, {"error": "Not found"})
            return
        try:
            body = self.read_body()
            if operation == "dispatch_battery_power":
                validate_dispatch(body)
            elif not isinstance(body, dict) or body:
                raise ValueError("Resume expects an empty JSON object or no body")
        except RequestError as error:
            self.send_json(error.status, {"error": str(error)})
            return
        except (ValueError, TimeoutError) as error:
            self.send_json(400, {"error": str(error)})
            return

        self.request_parameters = body
        controller = self.server.controller
        if not controller.lock.acquire(blocking=False):
            self.send_json(409, {"error": "Another battery operation is in progress"})
            return
        try:
            try:
                result = controller.execute(operation, body)
            except GatewayError:
                self.send_json(502, {"error": "Local v1r operation failed or was not acknowledged"})
                return
            self.send_json(200, result)
        finally:
            controller.lock.release()

    def do_GET(self):
        if urlsplit(self.path).path in ROUTES:
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_json(404, {"error": "Not found"})

    def log_message(self, message, *args):
        parameters = getattr(self, "request_parameters", None)
        suffix = (
            " params=" + json.dumps(parameters, separators=(",", ":"), allow_nan=False)
            if parameters is not None else ""
        )
        LOGGER.info("%s - %s%s", self.address_string(), message % args, suffix)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    logging.getLogger("pypowerwall.tedapi.tedapi_v1r").addFilter(
        lambda record: not (
            record.levelno == logging.WARNING
            and record.getMessage().startswith("Battery dispatch accepted:")
        )
    )
    try:
        options = load_options()
    except (OSError, ValueError):
        LOGGER.error(
            "Cannot start: check host, gw_pwd, and the RSA key filename/file in /config"
        )
        raise SystemExit(1) from None
    controller = BatteryController(options)
    LOGGER.info("Connecting to Powerwall using local v1r")
    try:
        controller.connect()
    except GatewayError:
        LOGGER.error("Cannot start: unable to establish a local v1r connection")
        raise SystemExit(1) from None
    server = ThreadingHTTPServer(("0.0.0.0", 8080), BatteryHandler)
    server.controller = controller
    LOGGER.info("Starting internal v1r-only Powerwall API on port 8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
