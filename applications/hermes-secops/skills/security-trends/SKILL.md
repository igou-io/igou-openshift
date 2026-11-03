---
name: security-trends
description: Compare comparable saved security evidence without mistaking coverage changes for improvements.
---

1. Locate a checksummed snapshot closest to seven days before the current collection and state the actual interval. With no comparable older snapshot, save a baseline and explain that a weekly trend is unavailable.

2. Join workload identities and image-digest/CVE findings. Separate introduced/removed workloads, newly scanned images, scan-age changes and source-access changes from genuine new/resolved findings.

3. Calculate finding age only from available observations; first observed is not first introduced. Report denominator and scope changes alongside vulnerability, fixability and hardening deltas.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write security-trends.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

