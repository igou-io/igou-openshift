# hermes-secops

Security assessment Hermes instance under `inactive/`, scaffolded with ArgoCD
`enabled: false`. Move it to `applications/hermes-secops` and update the source
path before enabling it.
It exports SBOMs for nine explicitly listed `igou-io/igou-*` repositories and
reads existing ACS vulnerability inventories, deployment attribution, policies,
and violations. Reports stay in its workspace and authenticated dashboard.
Public OSV, CISA KEV, FIRST EPSS, and vendor advisories provide enrichment.

The `HermesInstance` uses the shared Hermes operator and root-bootstrap SCC.
Its gateway can create/get/list/delete pods and exec only in `hermes-secops`;
this is a namespace trust boundary, not a guarantee that arbitrary pod creation
cannot access Secrets in that namespace. Its token is needed for terminal
orchestration. Sessions have no service-account token, use the scoped `none`
profile, and carry only the dedicated ACS reader token and CA. They run as
non-root tenant-worker pods with capabilities dropped. The namespace quota
bounds pod and PVC counts and requested storage. The existing workspace pattern
uses a dedicated 10Gi RWX NFS claim because gateway and session pods can run on
different nodes; agent state uses a separate 10Gi NVMe-oF claim.

`broker/` deliberately deploys into **hermes-secops-auth**. The gateway has no
RBAC there and cannot mount its GitHub App private key. The broker has no
service-account token. Its unauthenticated listener accepts only SecOps gateway
and session pods through NetworkPolicy, and its ceiling permits only
`contents`, `vulnerability_alerts`, and `security_events` **read** tokens for
the exact allowlist. The default token has only `contents: read`. No wildcard
repository access, issue/PR writes, workflow execution, or alert dismissal is
granted. The shared `igou-hermes` App remains behind this separate broker;
its selected repositories and granted permissions must also permit each read.
Public repositories remain publicly readable regardless of this private-token
allowlist. Broker policy changes require a broker restart after deployment.

Default-deny policies cover both namespaces. Gateway egress permits DNS, Squid,
SearXNG, its broker, and the OCP API for session orchestration. Session egress
permits DNS, Squid, its broker, and Central's `app: central` pods on TCP/8443
(the Service's TCP/443 is translated before OVN policy evaluation). The
RHACS component supplies the matching ingress policy. The shared proxy denies
private destinations but permits public HTTP/HTTPS; it is not a domain
allowlist or data-loss-prevention system. The hosted model receives relevant
investigation context. Context instructions constrain public advisory queries
to package coordinates/versions and CVE IDs.

The declarative ACS `hermes-secops-reader` role grants only `READ_ACCESS` on
Image, Deployment, Policy, Alert, Cluster, Namespace, and Node, across the
clusters already ingested by Central (`Unrestricted` is the data scope, not an
administrative permission). No scan, suppression, policy change, access-control,
integration, token-management, or enforcement writes are granted. Scheduled
report creation and other operations requiring write permissions are outside
this scaffold. It does not reuse the CI token's image write permissions.

No infrastructure bundle, SSH keys, 1Password token, registry API credentials,
AAP, Forgejo, Slack, webhook ingress, scheduled investigations, coding-agent
OAuth identities, or remediation tools are configured. Image pull credentials
remain kubelet inputs, although gateway pod creation could mount namespace-local
Secrets; they must therefore be pull-only.

Operational access setup and activation requirements are documented in
`igou-docs/security/Fleet Vulnerability Assessment.md`, under Hermes SecOps.
Do not enable the app until those prerequisites and live positive/negative
authorization checks are satisfied. Nothing in this scaffold creates the
missing credentials or deploys the instance.

Validate with `kustomize build inactive/applications/hermes-secops` and `make test`.
GitHub's current [SBOM API](https://docs.github.com/en/rest/dependency-graph/sboms)
uses `contents: read`; the assessment skill prefers its asynchronous export
flow ahead of the synchronous endpoint's 2026-11-13 retirement.
