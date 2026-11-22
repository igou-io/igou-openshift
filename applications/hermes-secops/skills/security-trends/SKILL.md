---
name: security-trends
description: Compare this week's security evidence with last week's without mistaking coverage changes for progress.
---

1. Find the checksummed snapshot closest to seven days before this collection and state the actual gap. If there is none, save a baseline and say a weekly trend is not available yet.

2. Compare by workload and by image digest plus CVE. Keep added or removed workloads, newly scanned images, scan-age changes and source-access changes apart from real new or fixed findings.

3. Measure finding age only from what was observed; first seen is not first introduced. Say how much was covered each time and when the scope changed, next to the changes in vulnerabilities, fixes available and hardening.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save security-trends.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
