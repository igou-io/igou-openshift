---
name: access-health
description: Check that each read-only security source still works and when the ACS reader token expires.
---

1. From the preflight results and `acs_token_expires`, list each allowed repository and say whether its SBOM, Dependabot and code-scanning data could be read, is disabled, was denied, or is unknown.

2. Flag an ACS token expiring within 14 days, or with an unknown expiry. A successful read through the broker does not audit the GitHub App's full permissions, and this check cannot see 1Password or the Codex login.

3. For each problem, give the exact operator action that fixes it. Do not use another identity, request broader access, test writes, read credential values, rotate tokens or change the App installation.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save access-health.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
