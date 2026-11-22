---
name: scan-coverage
description: Report what the security scans could and could not see, and whether the data is fresh.
---

1. Check `acs_integrity` and each source: completeness, matching before/after counts, duplicates, missing details and when each cluster last reported. Compare with the previous scan-coverage report.

2. List images with no scan time separately from images last scanned more than seven days ago. Group workloads by image where possible. An old scan does not mean the image is unsafe.

3. Name unavailable SBOMs, disabled alert APIs, denied repositories and unknown credential expiry. Do not start scans, rescans, exports that need write access or ACS report generation, or change credentials.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save scan-coverage.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
