# VPS GitOps on OpenShift

The existing OCP instance reconciles this directory through Application
`vps-gitops` at wave 15. It creates the management namespaces, dedicated
`ArgoCD/vps` in `vps-gitops`, its root Application/`cluster-root` project,
and the existing instance's `openshift-gitops/vps-secrets` Application.

`clusters/ocp/vps/` contains the dedicated instance's child Applications and
remote `cluster-config` project. Their workload sources are
`igou-kubernetes/clusters/vps/`; only VPS resources live in that repository.
`clusters/ocp/vps-secrets/` contains the OpenShift connection/registration
ExternalSecrets, API egress Service, source ExternalSecrets and PushSecrets.
These are reconciled by the existing OCP instance.

The dedicated instance has namespace rights only in `vps-gitops`, with its
own processes, OpenShift OAuth and Route. Its remote VPS token is cluster-admin;
OpenShift pushes share that token. Local VPS ESO uses a separate read-only
mirror reader. Both GitOps source repositories are public; no repository
credential is needed for the new instance.

The VPS Application catalog preserves the manual-sync policies for the website
and Gotify with a scoped Kustomize patch, because the OCP app-of-apps chart
omits syncPolicy when auto-sync is disabled. Their ServerSideApply and retries
remain available during migration; auto-sync stays off until acceptance.

Durable architecture, diagrams and cutover/retirement acceptance live in
`igou-docs/kubernetes/VPS Kubernetes Architecture and Migration.md`.
