# VPS GitOps on OpenShift

The existing OCP instance reconciles this directory through Application
`vps-gitops` at wave 60, after the local platform and workloads. It creates
the management namespaces, dedicated
`ArgoCD/vps` in `vps-gitops`, its root Application/`cluster-root` project,
and the existing instance's `openshift-gitops/vps-secrets` Application.

`clusters/ocp/vps/` contains the dedicated instance's child Applications and
remote `cluster-config` project. Their workload sources are
`igou-kubernetes/clusters/vps/`; only VPS resources live in that repository.
`clusters/ocp/vps-secrets/` contains the OpenShift ExternalSecrets for connection
and registration, API egress Service, source ExternalSecrets and PushSecrets,
plus the dedicated `vps-acme` Issuer and `vps-public-tls` Certificate.
These are reconciled by the existing OCP instance.

OpenShift cert-manager performs Cloudflare DNS-01 issuance and renewal for
`igou.io` and `*.igou.io`. The zone token and dedicated ACME account stay
in `openshift-gitops`. ESO pushes only a single JSON certificate/private-key
bundle to the VPS mirror pool; local VPS ESO creates the Gateway TLS Secret.
There is no cert-manager Application or Cloudflare-token push to the VPS.
Renewal delivery depends on OpenShift/Tailscale; retained certificates keep
public HTTPS serving until expiry during an outage.

The dedicated instance has namespace rights only in `vps-gitops`, with its
own processes, OpenShift OAuth and Route. Its remote VPS token is cluster-admin;
OpenShift pushes share that token. Local VPS ESO uses a separate read-only
mirror reader. Both GitOps source repositories are public; no repository
credential is needed for the new instance.

The VPS Application catalog preserves the manual-sync policies for the website
and Gotify with a scoped Kustomize patch, because the OCP app-of-apps chart
omits syncPolicy when auto-sync is disabled. Their ServerSideApply and retries
remain available during migration; auto-sync stays off until acceptance.

The architecture, diagrams and cutover/retirement checks are in
`igou-docs/kubernetes/VPS Kubernetes Architecture and Migration.md`.
