"""Exercise the real notification sender against a local HTTPS Gotify fixture."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import parse_qsl


SCRIPT = Path(__file__).resolve().parents[1] / "applications/qbittorrent/notify.sh"
TOKEN = "test-only-not-a-real-gotify-token"


class GotifyNotificationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="qbittorrent-gotify-test-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.certificate = cls.directory / "cert.pem"
        cls.key = cls.directory / "key.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
             "-keyout", str(cls.key), "-out", str(cls.certificate)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        (cls.directory / "token").write_text(TOKEN)

    def setUp(self):
        self.requests = []
        self.statuses = [200]
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                fixture.requests.append({
                    "method": self.command, "path": self.path,
                    "token": self.headers.get("X-Gotify-Key"),
                    "fields": dict(parse_qsl(body, keep_blank_values=True)),
                })
                status = fixture.statuses[min(len(fixture.requests) - 1, len(fixture.statuses) - 1)]
                if status == 0:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send_response(status)
                self.send_header("Content-Length", str(len(TOKEN)))
                if status == 302:
                    self.send_header("Location", "/redirected")
                self.end_headers()
                # Reflected credentials in any response must never enter logs.
                self.wfile.write(TOKEN.encode())

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate, self.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = f"https://127.0.0.1:{server.server_port}"

    def invoke(self, args=None, **overrides):
        environment = {
            "PATH": os.environ["PATH"], "CURL_CA_BUNDLE": str(self.certificate),
            "GOTIFY_URL": self.url, "GOTIFY_TOKEN_FILE": str(self.directory / "token"),
        }
        environment.update(overrides)
        result = subprocess.run(
            ["/bin/sh", str(SCRIPT), *(args if args is not None else ["finished", "Ubuntu ISO"])],
            env=environment, capture_output=True, text=True, timeout=35, check=False,
        )
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        return result

    def test_completion_preserves_metadata_and_sends_application_header(self):
        name = 'A "quoted" release & café\n$(touch /never-execute) `id`'
        self.assertEqual(self.invoke(["finished", name, "movies & TV"]).returncode, 0)
        self.assertEqual(self.requests, [{
            "method": "POST", "path": "/message", "token": TOKEN,
            "fields": {
                "title": "qBittorrent: download finished",
                "message": f"{name}\nCategory: movies & TV", "priority": "5",
            },
        }])

    def test_added_has_low_priority_and_no_empty_category_line(self):
        self.assertEqual(self.invoke(["added", "Example"]).returncode, 0)
        self.assertEqual(self.requests[0]["fields"], {
            "title": "qBittorrent: torrent added", "message": "Example", "priority": "0",
        })

    def test_temporary_server_failure_can_recover(self):
        self.statuses = [503, 200]
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(len(self.requests), 2)

    def test_rate_limit_is_retried(self):
        self.statuses = [429, 200]
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(len(self.requests), 2)

    def test_interrupted_transfer_is_retried(self):
        self.statuses = [0, 200]
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(len(self.requests), 2)

    def test_continued_failure_stops_after_three_attempts(self):
        self.statuses = [503]
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.requests), 3)
        self.assertIn("attempts=3, curl=0, HTTP=503", result.stderr)

    def test_invalid_application_token_is_not_retried(self):
        self.statuses = [401]
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.requests), 1)
        self.assertIn("attempts=1, curl=0, HTTP=401", result.stderr)

    def test_redirects_are_rejected(self):
        self.statuses = [302]
        self.assertEqual(self.invoke().returncode, 1)
        self.assertEqual(len(self.requests), 1)

    def test_http_is_rejected_even_with_endpoint_override(self):
        self.assertEqual(self.invoke(GOTIFY_URL="http://127.0.0.1:1").returncode, 1)
        self.assertEqual(self.requests, [])

    def test_untrusted_https_certificate_is_rejected_without_retries(self):
        result = self.invoke(CURL_CA_BUNDLE="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("attempts=1, curl=60", result.stderr)
        self.assertEqual(self.requests, [])

    def test_missing_token_does_not_issue_request(self):
        result = self.invoke(GOTIFY_TOKEN_FILE=str(self.directory / "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("token file is unavailable", result.stderr)
        self.assertEqual(self.requests, [])

    def test_header_configuration_injection_is_rejected(self):
        malformed = self.directory / "malformed-token"
        malformed.write_text('invalid"\nurl = "https://example.invalid')
        result = self.invoke(GOTIFY_TOKEN_FILE=str(malformed))
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid token file", result.stderr)
        self.assertEqual(self.requests, [])

    def test_invalid_event_and_missing_metadata_do_not_issue_requests(self):
        self.assertEqual(self.invoke(["unknown", "Example"]).returncode, 1)
        self.assertEqual(self.invoke(["finished"]).returncode, 1)
        self.assertEqual(self.requests, [])
