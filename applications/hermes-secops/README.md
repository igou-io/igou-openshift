# hermes-secops

Security assessment Hermes instance managed by ArgoCD, using `gpt-6.1-sol`
through the `openai-codex` OAuth provider. Its Codex authentication is seeded
directly into private persistent agent storage, outside Git and terminal pods.
It requests SBOMs for nine explicitly listed `igou-io/igou-*` repositories and
reads existing ACS vulnerability inventories, deployment attribution, policies,
and violations. Reports stay in its workspace and authenticated dashboard;
its dedicated Slack app provides scoped assessment requests and summaries.
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
Image, Deployment, WorkflowAdministration (policy definitions), CVE, Alert,
Cluster, Namespace, and Node, across the
clusters already ingested by Central (`Unrestricted` is the data scope, not an
administrative permission). No scan, suppression, policy change, access-control,
integration, token-management, or enforcement writes are granted. Scheduled
report creation and other operations requiring write permissions are outside
this scaffold. It does not reuse the CI token's image write permissions.

No infrastructure bundle, SSH keys, 1Password token, registry API credentials,
AAP, Forgejo, webhook ingress, scheduled investigations, terminal OAuth
identities, or remediation tools are configured. Image pull credentials
remain kubelet inputs, although gateway pod creation could mount namespace-local
Secrets; they must therefore be pull-only.

Operational access, credential renewal, coverage gaps, and verification evidence
are documented in `igou-docs/security/Hermes SecOps Operations.md`.
Dedicated dashboard, ACS reader/CA, and pull-only registry credentials are
referenced through ExternalSecrets. A copied Codex OAuth grant shares its
refresh-token lineage with its source machine; a separate login is required
for independent renewal. Authentication remains writable on the agent's data
PVC and is never reconciled from Git or mounted in terminal sessions.

## Slack

The dedicated **Hermes SecOps** app uses Socket Mode, following Hermes SRE's
one-app-per-instance setup. `slack-app-manifest.yaml` is the Slack setup
manifest, not a Kustomize resource. The `hermes-slack` ExternalSecret maps only
`slack_app_token` and `slack_bot_token` from `lab_agents/hermes-secops`; the
operator injects them through `spec.gateways.slack` into the gateway, not the
dashboard or terminal pod. Neither token is copied into the broad env Secret.

`SLACK_ALLOWED_USERS`, `SLACK_ALLOWED_CHANNELS` and `SLACK_HOME_CHANNEL`
come from required keys in the separate `hermes-slack-routing` Secret,
populated from concealed fields in `lab_agents/hermes-secops`. They limit the
runtime to the existing authorized user, `#igoucloud-hermes-secops` and that user's DMs.
Channel requests require a mention. The Slack toolset remains file, skills,
terminal and web; it adds no generic messaging, scheduling or remediation
tools. Summaries reply in the requesting thread/DM with status, collection
time, priorities, coverage gaps and the authenticated report location.
Seven operator-provisioned schedules deliver briefs to the configured home
channel. The agent cannot create additional schedules or message other channels.

## Scheduled assessments

`schedules/jobs.yaml` defines the seven native Hermes jobs, all explicitly in UTC:

| Skill | Schedule |
|---|---|
| `security-brief` | Weekdays 13:00 |
| `kev-watch` | Every 48 hours |
| `scan-coverage` | Daily 12:30 |
| `hardening-review` | Monday 14:00 |
| `runtime-triage` | Wednesday 14:00 |
| `security-trends` | Friday 14:00 |
| `access-health` | Friday 15:00 |

The KEV watch uses an elapsed 48-hour interval across month boundaries.
Reconciliation preserves its next fire when the interval is unchanged.

Skills are read-only ConfigMap mounts. The `secops-schedules` init container
reconciles operator-owned job definitions with native `create_job`/`update_job`
APIs, preserving IDs, execution history, unchanged next fires and operator pauses.
No job-store JSON is edited directly. `cron.max_parallel_jobs: 1` serializes
scheduled work. Hashed skill/script ConfigMaps are referenced through Kustomize
name-reference configuration so definition changes roll the pod and rerun reconciliation.
Missed occurrences are skipped rather than replayed in bulk.
Gateway delivery uses `deliver: slack` and `failure_deliver: slack`, resolving the
home channel from private runtime configuration. Terminals receive no Slack tokens.

Each preflight reuses a checksummed collection at most 45 minutes old, or invokes
the existing tokenless Kubernetes terminal with a 540-second collector budget,
600-second foreground timeout and a shared collection lock. Exit 2 retains partial
evidence; background-start acknowledgements and missing/corrupted artifacts fail
the job. The KEV monitor compares all live image/workload joins and configured
exposure plus coverage; unchanged results skip the model and Slack notification.
Its first run establishes a baseline. Native monitor detection advances before
analysis, so inspect failed-run notices before considering a changed baseline
successfully reported. Reports use `<skill>.md` beside the shared evidence.

Native cron records execution and delivery outcomes on the data PVC. This is not
checkpoint/resume of model reasoning: container restart can interrupt a run, and
abandoned attempts become `unknown` rather than silently replaying. Use native
`hermes cron runs`, `hermes cron incidents` and `hermes cron run <job-name>` for
inspection or an explicit retry. Final delivery and failure notices use the
scheduler; it does not promise periodic Slack heartbeats during analysis.

The Slack manifest preserves SRE's scopes and events, including channel/DM
history, assistant UI and file APIs. Runtime allowlists do not narrow the
Slack token's API grants. Invite this bot only to its intended channel, keep
its two tokens separate from SRE's, and verify channel/user checks and token
absence from a fresh investigation session after rollout. Public Slack HTTP
and WebSocket traffic uses the existing proxy; no network policy is widened.

## Collection and artifacts

`collector/secops-collect` is maintained here and mounted read-only into each
fresh terminal pod as `/usr/local/bin/secops-collect`. The existing pinned
terminal image supplies Python and ghapp; no extra runtime dependencies, image,
or investigation permissions are required. The ConfigMap name is stable because
its reference is inside the operator's raw PodSpec. Create a fresh session after
collector changes; the evidence records the script's SHA-256.

```sh
flock -n /output/.secops-collect.lock secops-collect --budget-seconds 540
```

The command uses only the broker's explicit allowlist, separate read tokens for
SBOMs and optional alerts, verified Central TLS, and public advisory APIs. It
does not scan, remediate, execute source code, or invoke the model. Retry counts,
page counts, response size, request timeouts, and overall collection time are
bounded. A run ID is never overwritten. Completed collection stages survive a
later deadline failure. Exit 0 means complete coverage; exit 2 publishes partial
evidence and explicit gaps, including unavailable GitHub grants and sources.

ACS `/v1/images` counts **named references**, such as both `image:tag` and
`image@sha256:digest`. The collector reconciles distinct `(digest, name)` pairs
against before/after server counts, while vulnerability details and workload
joins use each digest once. Exact duplicate rows and count churn trigger one
bounded traversal retry and remain incomplete if unresolved. `acs_integrity`
describes enumeration/detail joins independently from overall coverage status;
missing scans and optional GitHub access must not make a valid inventory look
like a clean vulnerability assessment. Lists are not transactional snapshots.

Each run writes private `summary.json`, `evidence.json`, `requests.json`, `report.md`, and
`sha256.json` under `/output/<run-id>/`. The assessment skill adds its analysis as
`assessment.md`. Request logs exclude headers, raw errors and download URLs;
workload evidence excludes environment-variable values and alert message bodies.
Only versioned package coordinates and public advisory identifiers are sent to
OSV/EPSS; RPM findings retain vendor/backport caveats.

The workspace's output subdirectory is shared at:

- Terminal: `/output` (writable).
- Gateway document delivery: `/opt/data/cache/documents`.
- Dashboard Files browser: `/opt/data/dashboard-files` (read-only mount).

The dashboard is locked to that artifact root, separate from private agent
authentication and state. `HERMES_WRITE_SAFE_ROOT=/workspace/reports:/output`
allows the file tools' remote I/O only in report/output directories. This is
a file-tool policy, not an OS sandbox for arbitrary terminal commands. Network
and credential boundaries remain those described above. Terminal pods do not
contact the dashboard to publish artifacts.

Validate with `kustomize build applications/hermes-secops` and `make test`.
`make test-secops-collector` runs the standard-library regression checks next to
the collector; these are included in the repository's normal CI validation gate.
Start analysis with the bounded summary and query the full evidence selectively;
summary examples are triage heuristics, not an exhaustive risk ranking.
GitHub's current [SBOM API](https://docs.github.com/en/rest/dependency-graph/sboms)
uses `contents: read`; the collector uses its asynchronous export
flow ahead of the synchronous endpoint's 2026-11-13 retirement.
