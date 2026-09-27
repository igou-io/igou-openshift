"""Send one SRE sweep digest to the existing, fixed Slack destination."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from omnigent_client import tool


TOKEN_FILE = Path("/mnt/credentials/slack/SLACK_BOT_TOKEN")
CHANNEL = "C0BTMS7AV34"
SWEEPS = frozenset(
    {"SRESweepDailyHealth", "SRESweepHygiene", "SRESweepCapacity", "SRESweepPRFollowup"}
)


@tool
def post_sre_sweep_digest(sweep: str, digest: str) -> str:
    """Post a completed sweep digest to the fixed SRE Slack channel once."""
    if sweep not in SWEEPS:
        return "Invalid sweep name; no message sent."
    lines = digest.strip().splitlines()
    if not lines or lines[0] != sweep or len(lines) > 20 or len(digest) > 3000:
        return "Digest must start with the sweep name and fit within 20 lines / 3000 characters."
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token:
            return "Slack credential is empty; no message sent."
        body = json.dumps({"channel": CHANNEL, "text": digest}).encode("utf-8")
        request = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except (OSError, urllib.error.URLError, ValueError):
        return "Slack delivery failed; outcome may be ambiguous. Do not retry automatically."
    if not result.get("ok"):
        return "Slack rejected the digest; no successful delivery was confirmed."
    return f"Slack delivery confirmed (timestamp {result.get('ts', 'unknown')})."
