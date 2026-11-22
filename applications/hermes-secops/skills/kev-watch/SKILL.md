---
name: kev-watch
description: Report changes in running workloads exposed to known-exploited CVEs.
---

1. The monitor already compared every live workload (ACS inactive=false and replicas>0) and image against CISA's Known Exploited Vulnerabilities (KEV) list and only wakes you when something changed. Read the supplied diff.

2. Check the CISA or vendor advisory. Say which workloads are newly affected, which images changed, which matches went away and whether scan coverage got worse. Check exposure and vendor backports before saying a CVE applies.

3. A KEV listing means the CVE is exploited somewhere, not that this workload is exploitable. Say what is unknown, and say so if the KEV feed or ACS data was incomplete.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save kev-watch.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
