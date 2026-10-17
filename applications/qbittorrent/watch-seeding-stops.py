#!/usr/bin/env python3
"""Forward qBittorrent's explicit automatic-stop log events to Gotify."""

import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


API_URL = "http://127.0.0.1:8080"
CREDENTIALS = Path("/var/run/secrets/qbittorrent-api")
CURSOR = Path("/state/.gotify-notifications/seeding-stop-cursor.json")
STOP_EVENT = re.compile(
    r'Torrent reached the (share ratio|seeding time|inactive seeding time) limit\. '
    r'Torrent stopped\. Torrent: "(.*)"\.', re.DOTALL,
)
EVENTS = {
    "share ratio": "ratio-limit",
    "seeding time": "seeding-time-limit",
    "inactive seeding time": "inactive-seeding-time-limit",
}


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class LogAPI:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirects(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self.opener.addheaders = [("Origin", API_URL), ("Referer", API_URL + "/")]

    def login(self):
        # Credentials stay in request bodies, never process arguments or logs.
        data = urllib.parse.urlencode({
            key: (CREDENTIALS / key).read_text() for key in ("username", "password")
        }).encode()
        with self.opener.open(API_URL + "/api/v2/auth/login", data=data, timeout=8) as response:
            if response.read().strip() != b"Ok.":
                raise PermissionError("qBittorrent authentication failed")

    def logs(self):
        url = API_URL + "/api/v2/log/main?normal=true&info=false&warning=false&critical=false&last_known_id=-1"
        try:
            with self.opener.open(url, timeout=8) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (401, 403):
                raise
            self.login()
            with self.opener.open(url, timeout=8) as response:
                return json.load(response)


def load_cursor():
    try:
        state = json.loads(CURSOR.read_text())
    except FileNotFoundError:
        return None
    return int(state["timestamp"]), int(state["id"])


def checkpoint(position):
    CURSOR.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = CURSOR.with_suffix(".tmp")
    with temporary.open("w") as output:
        os.chmod(temporary, 0o600)
        json.dump({"timestamp": position[0], "id": position[1]}, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, CURSOR)
    return position


def stop(_signal, _frame):
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, stop)
    api = LogAPI()
    cursor_loaded = False
    cursor = None
    last_error = None
    while True:
        try:
            if not cursor_loaded:
                cursor = load_cursor()
                cursor_loaded = True
            entries = sorted(
                ((int(entry["timestamp"]), int(entry["id"])), entry["message"])
                for entry in api.logs()
            )
            if cursor is None:
                cursor = checkpoint(entries[-1][0] if entries else (0, -1))
                print("seeding-stop-watcher: initialized at current log tail", flush=True)
            else:
                for position, message in entries:
                    if position <= cursor:
                        continue
                    match = STOP_EVENT.fullmatch(message)
                    if match:
                        # Best effort: persist before sending to avoid replay on restart.
                        cursor = checkpoint(position)
                        result = subprocess.run(
                            ["/bin/sh", "/notifications/notify.sh", EVENTS[match[1]], match[2]],
                            timeout=32, check=False,
                        )
                        status = "sent" if result.returncode == 0 else "failed; event checkpointed"
                        print(f"seeding-stop-watcher: notification {status}", flush=True)
                if entries and entries[-1][0] > cursor:
                    cursor = checkpoint(entries[-1][0])
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, subprocess.TimeoutExpired) as error:
            # Never echo response bodies, torrent metadata, or credentials.
            reason = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else type(error).__name__
            if reason != last_error:
                print(f"seeding-stop-watcher: retrying after {reason}", flush=True)
            last_error = reason
        else:
            if last_error:
                print("seeding-stop-watcher: recovered", flush=True)
            last_error = None
        time.sleep(15)


if __name__ == "__main__":
    main()
