#!/usr/bin/env python3

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

OPTIONS_PATH = "/data/options.json"
RESULT_PATH = "/data/speedtest-result.json"
SPEEDTEST_PATH = "/usr/local/bin/speedtest"
run_lock = threading.Lock()


def load_server_id():
    try:
        with open(OPTIONS_PATH, encoding="utf-8") as options_file:
            server_id = json.load(options_file).get("server_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return server_id


class SpeedtestHandler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path != "/speedtest":
            self.send_json(404, {"error": "not found"})
            return

        try:
            with open(RESULT_PATH, "rb") as result_file:
                data = result_file.read()
        except FileNotFoundError:
            self.send_json(404, {"error": "no measurement available"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if urlsplit(self.path).path != "/speedtest":
            self.send_json(404, {"error": "not found"})
            return
        if not run_lock.acquire(blocking=False):
            self.send_json(409, {"error": "measurement already in progress"})
            return

        try:
            command = [
                SPEEDTEST_PATH,
                "--accept-license",
                "--accept-gdpr",
                "--format=json",
            ]
            server_id = load_server_id()
            if server_id is not None:
                command.extend(["--server-id", str(server_id)])

            try:
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                measurement = json.loads(result.stdout)
            except subprocess.TimeoutExpired:
                self.send_json(504, {"error": "measurement timed out"})
                return
            except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
                print(f"Speedtest failed: {error}", flush=True)
                self.send_json(502, {"error": "measurement failed"})
                return

            temporary_path = f"{RESULT_PATH}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as result_file:
                json.dump(measurement, result_file, separators=(",", ":"))
            os.replace(temporary_path, RESULT_PATH)
            self.send_response(204)
            self.end_headers()
        finally:
            run_lock.release()

    def log_message(self, message, *args):
        print(f"{self.address_string()} - {message % args}", flush=True)


def main():
    ThreadingHTTPServer(("0.0.0.0", 8080), SpeedtestHandler).serve_forever()


if __name__ == "__main__":
    main()
