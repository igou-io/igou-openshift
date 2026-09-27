#!/usr/bin/env python3
"""Local smoke check for the pinned server and SRE runner images (requires Podman)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
deployment = yaml.safe_load((ROOT / "omnigent-deployment.yaml").read_text())
container = deployment["spec"]["template"]["spec"]["containers"][0]
server_path = next(entry["value"] for entry in container["env"] if entry["name"] == "PATH")
server_image = container["image"]
sandbox = yaml.safe_load((ROOT / "omnigent-sandbox-config-configmap.yaml").read_text())
runner_image = yaml.safe_load(sandbox["data"]["config.yaml"])["sandbox"]["kubernetes"]["image"]


def run(*args: str) -> None:
    result = subprocess.run(args, text=True, capture_output=True, timeout=90, check=False)
    if result.returncode:
        raise RuntimeError(f"Podman smoke failed ({result.returncode}): {result.stderr[-1000:]}")
    print(result.stdout.strip())


run(
    "podman", "run", "--rm", "--env", f"PATH={server_path}",
    "--entrypoint", "/bin/sh", server_image, "-c",
    "python -c " + shlex.quote(
        "import sys, omnigent.server.app; "
        "assert sys.executable == '/opt/venv/bin/python'; print(sys.executable)"
    ),
)

run(
    "podman", "run", "--rm", "--env", f"PATH={server_path}",
    "--entrypoint", "/bin/bash", runner_image, "-lc",
    "command -v omnigent && command -v opencode && omnigent --version && opencode --version",
)

tool_smoke = """
import json
from pathlib import Path
from omnigent.spec.parser import parse
from omnigent.tools.local import load_local_python_tools
from omnigent.tools.base import ToolContext
root = Path('/tmp/igou-sre')
spec = parse(root)
tools = load_local_python_tools(spec.local_tools, root, srt_available=False, agent_name='igou-sre')
slack = next(tool for tool in tools if tool.name() == 'post_sre_sweep_digest')
result = slack.invoke(json.dumps({'sweep': 'invalid', 'digest': 'invalid'}), ToolContext(task_id='smoke', agent_id='igou-sre', workspace=None))
assert 'Invalid sweep name' in result, result
print('bundled Slack tool discovered and invoked as a subprocess')
"""
run(
    "podman", "run", "--rm",
    "-v", f"{ROOT / 'agents/igou-sre'}:/tmp/igou-sre:ro",
    "--entrypoint", "/opt/omnigent/bin/python", runner_image, "-c", tool_smoke,
)
