---
name: security-brief
description: Summarize what changed in the lab's security since the last brief and what to do about it.
---

1. Find the previous security-brief.md and its evidence directory. Compare findings by image digest and CVE, not by totals or tags.

2. Lead with up to five priorities backed by evidence. Keep new problems, ongoing problems, confirmed fixes and lost visibility apart. An image or source that disappeared is not a fixed vulnerability unless coverage is comparable.

3. A fix being available is different from a fix being deployed. For each priority give the workload, image, advisory, confidence and the decision the owner needs to make.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save security-brief.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
