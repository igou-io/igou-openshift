"""Check safe native task registration and fixed Slack reporting."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("register_automations", ROOT / "scripts/register_automations.py")

    def test_new_tasks_are_parked_then_paused_before_real_schedule(self):
        calls = []
        tasks = self.module.load_definitions()[1]

        def fake_api(base, path, token, method="GET", body=None):
            calls.append((path, method, body))
            if path == "/auth/login":
                return {"token": "session-token"}
            if path.startswith("/v1/agents"):
                return {"data": [{"name": "igou-sre", "builtin": True, "id": "agent-1"}]}
            if path == "/v1/scheduled-tasks" and method == "GET":
                return {"scheduled_tasks": []}
            if path == "/v1/scheduled-tasks" and method == "POST":
                return {"id": "task-1"}
            if body and "rrule" in body:
                return {"state": "paused", "rrule": body["rrule"]}
            return {"state": "paused"}

        with mock.patch.object(self.module, "api", side_effect=fake_api), mock.patch.object(
            self.module.getpass, "getpass", return_value="password"
        ), mock.patch("builtins.print"):
            self.module.reconcile("https://example.invalid", "igou")
        creates = [i for i, (_, method, _) in enumerate(calls) if method == "POST" and i > 0]
        self.assertEqual(len(creates), 4)
        for index, task in zip(creates, tasks):
            self.assertEqual(calls[index][2]["rrule"], self.module.PARKED_RRULE)
            self.assertEqual(calls[index + 1][2], {"state": "paused"})
            self.assertEqual(calls[index + 2][2]["rrule"], task["rrule"])
            self.assertEqual(calls[index + 2][2]["state"], "paused")


class SlackToolTests(unittest.TestCase):
    def setUp(self):
        sys.modules["omnigent_client"] = types.SimpleNamespace(tool=lambda function: function)
        self.module = load_module("sre_slack", ROOT / "agents/igou-sre/tools/python/sre_slack.py")

    def test_only_fixed_channel_and_known_sweep_are_sent(self):
        class Response:
            def __enter__(self):
                return io.BytesIO(b'{"ok": true, "ts": "123.4"}')

            def __exit__(self, *args):
                return False

        with mock.patch.object(self.module.TOKEN_FILE.__class__, "read_text", return_value="secret"), mock.patch.object(
            self.module.urllib.request, "urlopen", return_value=Response()
        ) as send:
            result = self.module.post_sre_sweep_digest("SRESweepDailyHealth", "SRESweepDailyHealth\nFinding")
            self.assertIn("123.4", result)
            self.assertEqual(json.loads(send.call_args.args[0].data)["channel"], "C0BTMS7AV34")
            self.assertIn("no message sent", self.module.post_sre_sweep_digest("other", "other"))
            self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
