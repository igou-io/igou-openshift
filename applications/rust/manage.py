"""Rust startup, A2S readiness and local WebRCON administration."""

import json
import os
from pathlib import Path
import socket
import struct
import sys
from urllib.parse import quote

from websocket import create_connection, WebSocketConnectionClosedException


def query(host="127.0.0.1", port=28017):
    request = b"\xff\xff\xff\xffTSource Engine Query\x00"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(3)
        client.connect((host, port))
        client.send(request)
        response = client.recv(65535)
        if response[:5] == b"\xff\xff\xff\xffA":
            client.send(request + response[5:9])
            response = client.recv(65535)
    if response[:5] != b"\xff\xff\xff\xffI":
        raise RuntimeError("Expected an A2S_INFO response")
    fields = response[6:].split(b"\x00", 4)
    name, map_name, folder, game = [s.decode(errors="replace") for s in fields[:4]]
    app_id, players, maximum, bots = struct.unpack_from("<HBBB", fields[4])
    return dict(name=name, map=map_name, folder=folder, game=game,
                players=players, maxplayers=maximum, bots=bots, app_id=app_id)


def rcon(command):
    password = Path("/run/rcon/rcon-password").read_text().strip()
    # Keep the credential in memory; never include a URL/password in errors.
    try:
        with create_connection("ws://127.0.0.1:28016/" + quote(password, safe=""),
                               timeout=15) as connection:
            connection.send(json.dumps(dict(Identifier=1, Message=command,
                                            Name="OpenShift")))
            while True:
                response = connection.recv()
                if not response:
                    if command == "quit":
                        return "Shutdown requested"
                    raise RuntimeError("RCON closed before responding")
                message = json.loads(response)
                if message.get("Identifier") == 1:
                    return message.get("Message", "")
    except WebSocketConnectionClosedException:
        if command == "quit":
            return "Shutdown requested"
        raise RuntimeError("RCON closed before responding") from None
    except Exception:
        raise RuntimeError("Local RCON command failed") from None


def start():
    os.umask(0o077)
    config = Path("/runtime/server.cfg")
    password = Path("/run/rcon/rcon-password").read_text().strip()
    # The generated credential stays on emptyDir, outside persistent backups.
    config.write_text(Path("/opt/rust/server.cfg").read_text()
                      + '\nrcon.password "' + password + '"\n')
    target = Path("/data/rust/server/homelab/cfg/server.cfg")
    target.unlink(missing_ok=True)
    target.symlink_to(config)
    os.chdir("/data/rust")
    os.execv("./RustDedicated", ["./RustDedicated", "-batchmode", "-nographics",
             "-logfile", "/dev/stdout", "+server.identity", "homelab",
             "+server.ip", "0.0.0.0", "+server.port", "28015",
             "+server.queryport", "28017", "+rcon.ip", "127.0.0.1",
             "+rcon.port", "28016", "+rcon.web", "1"])


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "start":
        start()
    elif action == "query":
        print(json.dumps(query(*sys.argv[2:])))
    elif action == "rcon":
        print(rcon(" ".join(sys.argv[2:])))
    elif action == "stop":
        print(rcon("server.save"))
        print(rcon("quit"))
    else:
        raise SystemExit("Expected start, query, rcon or stop")
