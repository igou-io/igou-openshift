# VPS management and metrics

The primary OpenShift Argo CD instance owns this bundle. Connection/source
Secrets and pushes are in `openshift-gitops`; the private API egress Service
is in `vps-secrets`, and the remote registration is in `vps-gitops`.

The metrics Service, five ServiceMonitors and imported monitoring credential
live in OpenShift `tailscale`, where the API egress proxy pods run. UWM ignores
cross-namespace monitor selectors and enforces `namespace=tailscale`, so remote
workload namespace labels are preserved as `vps_namespace`. Target pod/container
labels from the egress proxy are dropped before scraping remote metrics.

`ClusterSecretStore/vps-monitoring` uses the existing management credential to
read the VPS `monitoring` namespace. It is consumable only from `tailscale`.
ESO imports the generated `metrics-reader-token` into `tailscale/vps-metrics`;
UWM uses that dedicated credential and validates the VPS API certificate.
No Secret values or administrator credential are declared in these manifests.

The public probes live in the existing UWM blackbox-exporter component.
Architecture, permission limits and verification evidence belong in
`igou-docs/monitoring/User Workload Monitoring, Exporters, and Alerting.md`.
