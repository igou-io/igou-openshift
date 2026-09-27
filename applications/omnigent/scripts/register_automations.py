#!/usr/bin/env python3
"""Reconcile Git-owned SRE definitions to paused, user-owned Omnigent tasks."""

from __future__ import annotations

import argparse
import getpass
import json
import urllib.error
import urllib.request
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
# Create is active in Omnigent 0.15.0. This recurrence cannot fire before the
# immediate pause; the real recurrence is installed only after pause succeeds.
PARKED_RRULE = "DTSTART:20990101T000000Z\nRRULE:FREQ=DAILY;BYHOUR=7;BYMINUTE=0"


def api(base: str, path: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base + path,
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Omnigent {method} {path} returned HTTP {error.code}") from None


def load_definitions() -> tuple[str, list[dict]]:
    config = yaml.safe_load((ROOT / "automations.yaml").read_text(encoding="utf-8"))
    if config["execution_target"] != "managed_sandbox":
        raise ValueError("Automations must use managed_sandbox")
    desired = []
    for entry in config["automations"]:
        prompt_path = (ROOT / entry["prompt_file"]).resolve()
        if not prompt_path.is_relative_to(ROOT):
            raise ValueError("Prompt must be inside applications/omnigent")
        desired.append(
            {
                "name": entry["name"],
                "prompt": prompt_path.read_text(encoding="utf-8").strip(),
                "rrule": entry["rrule"],
                "timezone": config["timezone"],
                "execution_target": config["execution_target"],
            }
        )
    if len(desired) != 4 or len({task["name"] for task in desired}) != 4:
        raise ValueError("Expected four unique Automations")
    return config["agent"], desired


def reconcile(base: str, user: str) -> None:
    password = getpass.getpass(f"Omnigent password for {user}: ")
    login = api(base, "/auth/login", "", "POST", {"username": user, "password": password})
    token = login["token"]
    agent_name, desired = load_definitions()
    agents = api(base, "/v1/agents?limit=1000", token)["data"]
    matches = [agent for agent in agents if agent["name"] == agent_name and agent["builtin"]]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one seeded {agent_name} agent")
    agent_id = matches[0]["id"]
    existing = api(base, "/v1/scheduled-tasks", token)["scheduled_tasks"]
    for task in desired:
        name = task["name"]
        matches = [row for row in existing if row["name"] == name]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate Automation name: {name}")
        if matches:
            current = matches[0]
            task_id = current["id"]
            if current["state"] != "paused":
                api(base, f"/v1/scheduled-tasks/{task_id}", token, "PATCH", {"state": "paused"})
        else:
            created = api(
                base,
                "/v1/scheduled-tasks",
                token,
                "POST",
                {**task, "agent_id": agent_id, "rrule": PARKED_RRULE},
            )
            task_id = created["id"]
            api(base, f"/v1/scheduled-tasks/{task_id}", token, "PATCH", {"state": "paused"})
        updated = api(
            base,
            f"/v1/scheduled-tasks/{task_id}",
            token,
            "PATCH",
            {**task, "agent_id": agent_id, "state": "paused"},
        )
        if updated["state"] != "paused" or updated["rrule"] != task["rrule"]:
            raise RuntimeError(f"Automation did not reconcile: {name}")
        print(f"{name}: paused ({task_id})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://omnigent.apps.ocp.igou.systems")
    parser.add_argument("--user", default="igou")
    parser.add_argument("--apply", action="store_true", help="register/update tasks; otherwise print definitions")
    args = parser.parse_args()
    if not args.url.startswith("https://"):
        parser.error("--url must use HTTPS")
    _, desired = load_definitions()
    if args.apply:
        reconcile(args.url.rstrip("/"), args.user)
    else:
        for task in desired:
            print(f"{task['name']}: {task['rrule']} ({task['timezone']}, paused on registration)")


if __name__ == "__main__":
    main()
