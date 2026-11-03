---
name: access-health
description: Check the existing read-only security sources and ACS reader expiry.
---

1. Use the current preflight source outcomes and acs_token_expires metadata. Enumerate broker-allowed repositories and classify each SBOM/alert source as readable, disabled, denied or unknown. Record the collection time.

2. Flag ACS expiry within 14 days or an unknown expiry. Explain that broker read success is not an audit of the GitHub App's full permissions, and this skill cannot verify 1Password or OAuth refresh independence.

3. Use no alternate identity and do not request broad permissions. Do not test write APIs, retrieve credential values, rotate tokens or change App installations. Propose the precise operator action needed.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write access-health.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

