"""Reconcile operator-owned schedules through native Hermes APIs, preserving run state."""

import argparse
import json
from pathlib import Path

import yaml


def install(paused=False):
    from cron.jobs import create_job, list_jobs, parse_schedule, update_job

    definitions = yaml.safe_load(Path(__file__).with_name("jobs.yaml").read_text())["jobs"]
    existing = list_jobs(include_disabled=True)
    for definition in definitions:
        schedule = parse_schedule(definition["schedule"])
        fields = {"model": "gpt-6.1-sol", "provider": "openai-codex",
                  "enabled_toolsets": ["file", "skills", "terminal", "web"],
                  "timezone": "UTC", "catch_up": False,
                  "grace_minutes": 15 if schedule["kind"] == "cron" else None,
                  "deliver": "slack", "failure_deliver": "slack", "workdir": "/workspace",
                  "skills": ["assess", definition["skill"]],
                  "script": "secops/" + definition["skill"] + ".py",
                  **{key: definition[key] for key in ("name", "schedule", "prompt")}}
        if definition["skill"] == "kev-watch":
            fields["monitor_script"] = "secops/kev-monitor.py"
        matches = [job for job in existing if job.get("name") == definition["name"]]
        if len(matches) > 1:
            raise RuntimeError("Duplicate operator-owned schedule: " + definition["name"])
        if matches:
            # Native APIs preserve next-run counters, monitor state and operator pauses.
            current = matches[0]
            updates = {}
            for key, value in fields.items():
                previous = current.get(key)
                expected = parse_schedule(value) if key == "schedule" else value
                if previous != expected:
                    updates[key] = value
            job = update_job(current["id"], updates) if updates else current
        else:
            job = create_job(**fields, paused=paused,
                             paused_reason="SecOps rollout verification" if paused else None)
        if not job:
            raise RuntimeError("Schedule reconciliation failed: " + definition["name"])
        print(json.dumps({"name": job["name"], "timezone": job.get("timezone"),
                          "next_run_at": job.get("next_run_at"), "state": job.get("state")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paused", action="store_true", help="Create new jobs paused for rollout verification")
    install(parser.parse_args().paused)
