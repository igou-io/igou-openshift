---
name: runtime-triage
description: Separate repository dependency alerts from vulnerabilities in deployed images.
---

1. Match CVE and advisory IDs, package versions, repository SBOMs and deployed image findings. Record the source commit, snapshot time, image digest and scan time. A similar package name alone does not link a repository to a running image.

2. Put each finding in one group: confirmed in a running image, repository only, or unknown. Keep embedded tools and base-image packages apart from application dependencies, and respect vendor backports.

3. Check fixes against the primary advisory. Label each action as a dependency update, tool or vendor update, image rebuild, rollout of a verified rebuilt image, blocked upstream, or needs investigation. Do not invent fixed versions or open PRs.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save runtime-triage.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
