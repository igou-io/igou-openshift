# AMT health monitoring

This exporter authenticates to MS-01, HP G5, and P330 every five minutes and
uses only WS-Management Enumerate/Pull operations. It reads control mode,
consent policy, and KVM state. Prometheus scrapes cached results every minute;
no scrape opens a console, changes configuration, or changes power state.

Credentials are projected from the existing `lab_agents` 1Password items via
three ExternalSecrets. Only each item's `password` field is mounted. The pod
has no service-account token, runs with the restricted SCC, and can reach only
the three AMT endpoints. MS-01's legacy TLS connection pins its certificate
before sending HTTP; certificate rotation requires updating `targets.json`.

KVM EnabledState 2 (enabled/active) and 6 (enabled but offline/idle) are both
healthy. Failed reads set `amt_up` to zero and omit policy values. Alerts
cover authentication/read failures, consent enabled, control mode drift,
disabled KVM, and checks older than 15 minutes. The client uses the firmware's
supported SOAP operation timeout while bounding each network call to 10 seconds.

Run the protocol/failure tests with a project-local Python interpreter:

```bash
python -m unittest discover -s components/user-workload-monitoring/exporters/amt-monitor/tests -v
```

Operational endpoints, credential references, recovery limits, and verification
history belong to `igou-docs/openshift/OpenShift Node and Cluster Maintenance.md`.
