# OpenShift Pipelines as Code — design

**Status:** draft, awaiting user review
**Date:** 2026-05-09
**Author:** David Igou (with Claude)

## Goals

- Stand up GitHub-driven CI on the homelab OCP cluster using OpenShift Pipelines as Code (PaC), the `.tekton/`-per-repo model. Goal is to displace the GitHub Actions workflows that are burning the user's free GHA minutes.
- **Initial migration scope (verified by org survey):** 5 active repos with workflows worth moving to PaC — `igou-inventory` (lint), `igou-ansible` (lint + syntax-check; the three EE publishers stay in GHA), `igou-openshift` (validate), `igou-containers` (PR-side image builds; the publish path stays in GHA), and `igou-devenv` (stays entirely in GHA — devcontainer build is recursive). The system is sized for growth (chart defaults assume up to ~20 tenants), but the immediate fleet is 4 tenants.
- Tune the OpenShift Pipelines operator deliberately (TektonConfig, pruner, resolvers, Chains, PaC settings) rather than running stock defaults.
- Hybrid CI model: PRs and working-branch pushes run on PaC; `push:main` keeps running on GitHub Actions to handle release/publish/deploy steps that need GH-side secrets or external integrations.
- Hardened-by-default per-repo namespace: zero secrets on PR runs, default-deny NetworkPolicies, ResourceQuota, restricted SCC, no privileged builds.
- Two Claude skills to make onboarding mechanical: `/scaffold-pac-tenant` (per-repo entry in this repo) and `/convert-gha-workflow` (per-repo `.tekton/` generation in the target repo).

## Non-goals

- Running PaC across multiple clusters. Single cluster (`ocp.igou.systems`) only; the chart is cluster-pinned.
- Migrating release/publish workflows. Those stay in GitHub Actions, scoped to `push: branches: [main]`.
- Self-hosted GitHub Actions runners. Different problem; PaC is the chosen path.
- Trigger-based PaC (the legacy webhook+PAT model). GitHub App only.
- Auto-onboarding new repos. PaC's `auto-configure-new-github-repo` is explicitly disabled — onboarding is always a deliberate commit.

## Architecture overview

```
┌──────────────────┐                     ┌─────────────────────────────┐
│  github.com      │                     │  ocp.igou.systems (SNO)     │
│                  │                     │                             │
│  GitHub App      │                     │  openshift-pipelines ns     │
│  "ocp-pac"       │   webhook (HMAC)    │   ├─ pac-controller         │
│  Installed on    ├────────────────────►│   ├─ pac-watcher            │
│  ~20 repos       │   via Funnel URL    │   ├─ pac-webhook            │
│                  │                     │   ├─ tekton-* controllers   │
│                  │                     │   └─ chains-controller      │
│                  │◄────────────────────┤                             │
│                  │   Checks API        │  tailscale-operator         │
│                  │   (App JWT)         │   exposes pac-controller    │
└──────────────────┘                     │   Service via Funnel        │
                                         │   → pac-ocp.<tailnet>.ts.net│
                                         │                             │
                                         │  ci-<repo> ns (× ~20)       │
                                         │   ├─ Repository CR          │
                                         │   ├─ pipeline-sa (no creds) │
                                         │   ├─ NetworkPolicies        │
                                         │   ├─ ResourceQuota          │
                                         │   └─ PipelineRuns (PRs)     │
                                         └─────────────────────────────┘
```

**Trigger flow.** Developer pushes a PR branch → GitHub App fires webhook to the Funnel URL → PaC controller validates HMAC + GitHub App JWT → checks `Repository.spec.policy.pull_request` allowlist → resolves `.tekton/pull-request.yaml` from the PR HEAD → creates `PipelineRun` in `ci-<repo>` namespace → run uses `pipeline-sa` (zero credentials) → Tasks come from Tekton Hub via the Hub Resolver → status reported back to the PR via the Checks API. PR merges to main → no PaC run; GitHub Actions fires its pruned `publish.yml` (trigger restricted to `push: branches: [main]` only).

## Per-repo `ci-<repo>` namespace hardening

### Threat model

The PR run executes attacker-controlled code from the PR. Shared Tasks come from Tekton Hub (or inline Task specs), but user `script:` blocks and the build itself run whatever the PR contains. The build pod is treated as hostile. The `policy.pull_request` allowlist on the Repository CR keeps strangers from triggering it; the hardening below assumes a trusted user's PR is still capable of running malicious code (a compromised dev account, a bad merge, a copy-pasted build step).

### `pipeline-sa` ServiceAccount

One SA per `ci-<repo>` namespace. Used by every PR PipelineRun. Designed to be as close to powerless as possible.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pipeline-sa
  namespace: ci-<repo>
automountServiceAccountToken: false   # token never lands in the build pod
imagePullSecrets: []                  # default: no registry creds (overridable per-tenant)
```

- **No RBAC.** No Role, no RoleBinding, no ClusterRoleBinding. The OpenShift Pipelines operator binds its standard `pipelines-scc` to the SA via the operator-shipped ClusterRoleBinding; we don't touch that.
- **SCC: `pipelines-scc`** (≈ `restricted-v2` plus minor tweaks). Never `pipelines-scc-privileged`.
- Container image builds use rootless Buildah (`--isolation=chroot --storage-driver=vfs`) — no privileged required.
- Belt-and-suspenders at the pod-template default level (set in `TektonConfig`):
  ```yaml
  spec:
    pipeline:
      default-pod-template:
        securityContext:
          runAsNonRoot: true
          seccompProfile: { type: RuntimeDefault }
        automountServiceAccountToken: false
        enableServiceLinks: false
        priorityClassName: tekton-ci-low
  ```

PR runs never publish. There is no second SA in `ci-<repo>` for pushing images — that work happens in GHA on `push:main`, with a GitHub-side secret that never enters the cluster.

### NetworkPolicies — default-deny + three explicit allows

```yaml
# 1. default-deny — everything below has to opt in
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: ci-<repo>
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# 2. allow DNS (openshift-dns)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: ci-<repo>
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-dns
      ports:
        - { port: 53, protocol: UDP }
        - { port: 53, protocol: TCP }
---
# 3. allow egress to public internet (HTTPS + HTTP), block intra-cluster + LAN
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-egress
  namespace: ci-<repo>
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.128.0.0/14         # OCP pod CIDR — verify on cluster
              - 172.30.0.0/16         # OCP service CIDR — verify on cluster
              - 169.254.169.254/32    # cloud metadata IP
              - 192.168.0.0/16        # home LAN (TrueNAS, router)
              - 10.0.0.0/8            # other RFC1918
      ports:
        - { port: 443, protocol: TCP }
        - { port: 80,  protocol: TCP }
```

**No ingress rule.** The Tekton TaskRun controller in `openshift-pipelines` reads pod logs/status via the K8s API server, not by dialing the build pod. The build pod is a sink, not a server.

**Why HTTP/80.** Apt mirrors and a handful of legacy package mirrors. If the migrated repos don't actually need it, drop it before commit.

**Why we block 192.168.0.0/16 and 10.0.0.0/8.** Workspace PVCs go through CSI in the kubelet's mount namespace — the build pod talks to the kernel, not to the storage box's network IP — so blocking `192.168.x.x` doesn't break storage. This blocks LAN scanning from a compromised PR run.

**Pod/service CIDR values must be verified on the live cluster** before commit:
```
oc get network.config/cluster -o jsonpath='{.spec.clusterNetwork}'
oc get network.config/cluster -o jsonpath='{.spec.serviceNetwork}'
```

### ResourceQuota + LimitRange

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: ci-quota
  namespace: ci-<repo>
spec:
  hard:
    requests.cpu:    "8"
    requests.memory: 16Gi
    limits.cpu:      "16"
    limits.memory:   32Gi
    pods:            "20"
    persistentvolumeclaims: "5"
    requests.storage: 50Gi
---
apiVersion: v1
kind: LimitRange
metadata:
  name: ci-limits
  namespace: ci-<repo>
spec:
  limits:
    - type: Container
      defaultRequest: { cpu: 100m, memory: 256Mi }
      default:        { cpu: 500m, memory: 1Gi   }
      max:            { cpu: 4,    memory: 8Gi   }
```

PaC-side concurrency cap on `Repository.spec.concurrency_limit: 2` per repo. With `pods: 20` quota and 2 concurrent runs of ≤10 steps each, we stay well within limits.

### PriorityClass (cluster-wide, shipped with the operator component)

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: tekton-ci-low
value: 100   # below user-workload (1000) and system (10k+)
globalDefault: false
description: "PR PipelineRun pods. Preempted under cluster pressure."
```

Pinned as the default in `TektonConfig.spec.pipeline.default-pod-template.priorityClassName`. CI yields to user-facing apps under pressure.

### Namespace-level Pod Security Admission

```yaml
metadata:
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
```

Belt-and-suspenders: even if the SCC story slips, PSA blocks privileged pods at admission.

## Operator install + TektonConfig tuning

`components/openshift-pipelines/openshift-pipelines-operator-subscription.yaml` already exists and is wired into `clusters/ocp/values.yaml` at sync-wave 10. We add three new files plus a PriorityClass:

```
components/openshift-pipelines/
├── kustomization.yaml
├── openshift-pipelines-operator-subscription.yaml   # existing
├── tektonconfig.yaml                                # NEW
├── chains-signing-externalsecret.yaml               # NEW
├── pac-github-app-externalsecret.yaml               # NEW
├── pac-controller-funnel-service.yaml               # NEW
└── tekton-ci-low-priorityclass.yaml                 # NEW
```

### `tektonconfig.yaml`

```yaml
apiVersion: operator.tekton.dev/v1alpha1
kind: TektonConfig
metadata:
  name: config            # must be 'config' — the operator only reconciles this name
  annotations:
    argocd.argoproj.io/sync-wave: "11"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true,ServerSideApply=true
spec:
  profile: all                         # installs Pipelines + Triggers + PaC + Chains
  targetNamespace: openshift-pipelines
  pruner:
    disabled: false
    schedule: "0 4 * * *"
    keep: 20
    keep-since: 10080                  # 7 days in minutes
    resources: [pipelinerun, taskrun]
  pipeline:
    enable-bundles-resolver: true
    enable-cluster-resolver: true
    enable-git-resolver: true
    enable-hub-resolver: true
    default-service-account: pipeline-sa
    default-timeout-minutes: 60
    default-pod-template:
      securityContext:
        runAsNonRoot: true
        seccompProfile: { type: RuntimeDefault }
      automountServiceAccountToken: false
      enableServiceLinks: false
      priorityClassName: tekton-ci-low
    enable-step-actions: true
  chain:
    artifacts.taskrun.format: in-toto
    artifacts.taskrun.storage: oci
    artifacts.pipelinerun.format: in-toto
    artifacts.pipelinerun.storage: oci
    artifacts.oci.storage: oci
    transparency.enabled: false        # no Rekor for now
    signers.x509.fulcio.enabled: false # static cosign key, not keyless
  platforms:
    openshift:
      pipelinesAsCode:
        enable: true
        settings:
          application-name: "OpenShift Pipelines (homelab)"
          auto-configure-new-github-repo: false
          secret-auto-create: true
          remote-tasks: true
          max-keep-runs: 10
          enable-cancel-in-progress: true
          custom-console-name: "OpenShift Console"
          custom-console-url: "https://console-openshift-console.apps.ocp.igou.systems"
          custom-console-url-pr-details: |
            {{.openshift_console_url}}/k8s/ns/{{.namespace}}/tekton.dev~v1~PipelineRun/{{.pr}}
          custom-console-url-pr-tasklog: |
            {{.openshift_console_url}}/k8s/ns/{{.namespace}}/tekton.dev~v1~PipelineRun/{{.pr}}/logs/{{.task}}
```

Key settings rationale:

- **`profile: all`** — installs Pipelines, Triggers, PaC, Chains, Dashboard. Triggers ships free; Dashboard is suppressed in the OCP console plugin (built-in Pipelines tab).
- **Pruner: 20 runs / 7 days.** With ~20 repos × ~5 runs/week, steady-state ~400 runs is comfortable.
- **`default-service-account: pipeline-sa`** — every PipelineRun in any namespace defaults to this SA name. Per-repo namespaces all create a SA called `pipeline-sa`, so no per-PipelineRun `serviceAccountName` is needed.
- **All four resolvers enabled** — Cluster + Git + Hub + Bundles. Hub and Git are the primary path; Cluster is a future option (if we ever need shared local Tasks); Bundles is for OCI-distributed Task catalogs.
- **`auto-configure-new-github-repo: false`** — critical security setting. Stops PaC from auto-creating Repository CRs for repos it's never seen. Onboarding is always an explicit `clusters/ocp/pac-tenants/values.yaml` commit.
- **`enable-cancel-in-progress: true`** — global default; per-repo override available.
- **Chains in `oci` storage mode** — attestations push to the same registry as the image. `transparency.enabled: false` skips Rekor (would require external Rekor infra).

### Cosign keypair for Chains

Generate once: `cosign generate-key-pair k8s://tekton-chains/signing-secrets`. Put the resulting `cosign.key`, `cosign.password`, `cosign.pub` into 1Password as item `tekton-chains-signing`. ExternalSecret materializes the in-cluster `signing-secrets` Secret:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: signing-secrets
  namespace: tekton-chains
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: signing-secrets
  data:
    - { secretKey: cosign.key,      remoteRef: { key: tekton-chains-signing, property: cosign.key } }
    - { secretKey: cosign.password, remoteRef: { key: tekton-chains-signing, property: cosign.password } }
    - { secretKey: cosign.pub,      remoteRef: { key: tekton-chains-signing, property: cosign.pub } }
```

The `tekton-chains` namespace is created by the operator when Chains is enabled — we add the ExternalSecret into it.

## Tailscale Funnel exposure

GitHub needs to reach the PaC controller webhook from the public internet without us opening a port on the home router. The existing `tailscale-operator` does this via Service annotations.

The PaC operator owns `Service/pipelines-as-code-controller` in `openshift-pipelines` (port 8080, HTTP). We don't modify it (the operator would revert changes on reconcile). Instead, a parallel Service points at the same selector and carries the Tailscale annotations:

```yaml
# components/openshift-pipelines/pac-controller-funnel-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: pac-controller-funnel
  namespace: openshift-pipelines
  annotations:
    tailscale.com/expose: "true"
    tailscale.com/funnel: "true"
    tailscale.com/hostname: "pac-ocp"      # → pac-ocp.<tailnet>.ts.net
    argocd.argoproj.io/sync-wave: "12"
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: controller
    app.kubernetes.io/part-of: pipelines-as-code
  ports:
    - name: http
      port: 8080
      targetPort: 8080
      protocol: TCP
```

The Tailscale proxy terminates TLS using a Tailscale-issued cert (Funnel hostnames get them automatically). Inside the tunnel, traffic to the backend is HTTP on 8080, which is fine — it never leaves the cluster network.

**Webhook URL GitHub will hit:** `https://pac-ocp.<tailnet>.ts.net/`

### Funnel constraints

- Funnel external ports are restricted to **443, 8443, 10000**. We use 443.
- Tailnet ACL must grant `funnel` to the operator's device tag. One-time admin change:
  ```
  "nodeAttrs": [
    { "target": ["tag:k8s"], "attr": ["funnel"] }
  ]
  ```
  This is called out as a manual prerequisite in the implementation plan.
- The proxy is one Tailscale device; doesn't scale per repo.
- **No fallback exposure.** If Funnel breaks, GitHub webhooks fail and PaC stops working. Acceptable for a homelab.

### GitHub App webhook secret

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: pipelines-as-code-secret
  namespace: openshift-pipelines
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: pipelines-as-code-secret      # exact name PaC controller looks for
  data:
    - { secretKey: github-application-id, remoteRef: { key: pac-github-app, property: app-id } }
    - { secretKey: github-private-key,    remoteRef: { key: pac-github-app, property: private-key } }
    - { secretKey: webhook.secret,        remoteRef: { key: pac-github-app, property: webhook-secret } }
```

## Per-tenant onboarding — Helm chart

Tenants are defined declaratively in a single values file. A Helm chart templates the per-tenant resources.

### Layout

```
.helm/charts/pac-tenant/                  # NEW chart, follows existing .helm/charts pattern
├── Chart.yaml
├── values.yaml                           # schema + defaults, empty tenants list
└── templates/
    ├── _helpers.tpl
    ├── namespace.yaml                    # range over .Values.tenants
    ├── serviceaccount.yaml               # range
    ├── networkpolicies.yaml              # range
    ├── resourcequota.yaml                # range
    ├── limitrange.yaml                   # range
    ├── repository.yaml                   # range
    └── externalsecrets.yaml              # range over .secrets.* for tenants that have them

clusters/ocp/pac-tenants/                 # cluster-specific instantiation
├── Chart.yaml                            # depends on ../../../.helm/charts/pac-tenant
└── values.yaml                           # the entire CI fleet lives here
```

### Single ArgoCD app — wiring in `clusters/ocp/values.yaml`

```yaml
# Added once, never edited again.
pac-tenants:
  annotations:
    argocd.argoproj.io/sync-wave: '20'
  source:
    path: clusters/ocp/pac-tenants
```

All future onboarding lives inside `clusters/ocp/pac-tenants/values.yaml`. No new ArgoCD apps per repo.

### Example `clusters/ocp/pac-tenants/values.yaml`

```yaml
defaults:
  concurrencyLimit: 2
  cancelInProgress: true

  policy:
    pullRequest: ["igou-david"]
    okToTest:    ["igou-david"]

  quota:
    requests.cpu:    "8"
    requests.memory: "16Gi"
    limits.cpu:      "16"
    limits.memory:   "32Gi"
    pods:            "20"
    persistentvolumeclaims: "5"
    requests.storage: "50Gi"

  limitRange:
    defaultRequest: { cpu: 100m, memory: 256Mi }
    default:        { cpu: 500m, memory: 1Gi   }
    max:            { cpu: 4,    memory: 8Gi   }

  egressBlockedCIDRs:
    - 10.128.0.0/14
    - 172.30.0.0/16
    - 169.254.169.254/32
    - 192.168.0.0/16
    - 10.0.0.0/8

tenants:
  - name: igou-openshift
    url:  https://github.com/igou-io/igou-openshift

  - name: gitea-config
    url:  https://github.com/igou-io/gitea-config

  - name: llmkube
    url:  https://github.com/igou-io/llmkube

  # Per-tenant overrides — only specify what differs from defaults.
  - name: heavy-image-builder
    url:  https://github.com/igou-io/heavy-image-builder
    quota:
      requests.cpu:    "16"
      requests.memory: "32Gi"
      limits.cpu:      "32"
      limits.memory:   "64Gi"
    concurrencyLimit: 1

  # Tenant with secrets — chart enforces stricter okToTest (see Secret access section).
  - name: image-builder-repo
    url:  https://github.com/igou-io/image-builder-repo
    secrets:
      imagePullSecrets:
        - name: ghcr-readonly
          onepasswordItem: ci-ghcr-readonly
      workspaceSecrets:
        - name: snyk-org-token
          onepasswordItem: ci-snyk-org
```

### Defaults-merge logic

`templates/_helpers.tpl`:

```yaml
{{- define "pac-tenant.merged" -}}
{{- $defaults := .root.Values.defaults -}}
{{- $tenant := .tenant -}}
{{- $merged := mergeOverwrite (deepCopy $defaults) $tenant -}}
{{- toYaml $merged -}}
{{- end -}}
```

Templates iterate `.Values.tenants`, computing the merged config per tenant. Tenant entries only specify what differs from defaults.

### Trade-off: single ArgoCD app for the whole fleet

A YAML mistake in one tenant entry breaks the sync of all tenants until fixed. Mitigation: the `/scaffold-pac-tenant` skill always runs `helm template | kubeconform` before writing. ArgoCD's auto-sync halts on render failure rather than half-applying — previous good state stays running.

## Secret access for tenants

The default — zero secrets on PR runs — covers most repos. Cases that legitimately need PR-time secrets are accommodated by two opt-in modes.

### Allowed secret types

| Need | Examples | Risk if leaked |
|---|---|---|
| Private base image pull | private GHCR/quay.io org pulls | Read access to one registry path |
| Private package index | private npm/pip/Go proxy tokens | Read access to packages |
| Test fixtures | Stripe test-mode key, sandbox API tokens | Bounded — test-scoped accounts |
| Linter / scanner tokens | SonarCloud, Snyk org token | Reporting auth |
| Read-only SaaS for integration tests | sandbox AWS keys, dev-DB password | Variable — depends on scope |

**Never allowed on PR runs:** production credentials, registry write tokens, deploy SSH keys, signing keys, OIDC client secrets that mint elevated tokens. Those stay in GHA `push:main` workflows.

### Two modes

**Mode A: imagePullSecrets** (registry credentials for pulling base images). Attached to `pipeline-sa.imagePullSecrets` because the kubelet uses them at pod creation, before workspaces mount.

**Mode B: workspaceSecrets** (everything else). Chart provisions the ExternalSecret; the PipelineRun explicitly mounts it as a workspace volume. The SA itself has no permission — the binding is "this PipelineRun mounts this Secret as a volume by name." Preferred because the secret usage is visible in the target repo's git history.

### What the chart renders per secret entry

For each `imagePullSecrets[*]`:
- `ExternalSecret` of `type: kubernetes.io/dockerconfigjson` syncing the 1Password item.
- An entry appended to `pipeline-sa.imagePullSecrets`.

For each `workspaceSecrets[*]`:
- `ExternalSecret` of `type: Opaque` syncing the 1Password item.
- Nothing on the SA. The `.tekton/pull-request.yaml` PipelineRun must mount it explicitly.

### Auto-collapsed `okToTest` when secrets present

A tenant with secrets must not allow `/ok-to-test` to expand the trust circle — it would let an arbitrary user exfiltrate every secret in the namespace via a PR that mounts and `cat`s them. The chart computes `okToTest` per tenant:

```yaml
{{- define "pac-tenant.okToTest" -}}
{{- if or .tenant.secrets.imagePullSecrets .tenant.secrets.workspaceSecrets -}}
  {{- toYaml (.tenant.policy.pullRequest | default .root.Values.defaults.policy.pullRequest) -}}
{{- else -}}
  {{- toYaml (.tenant.policy.okToTest | default .root.Values.defaults.policy.okToTest) -}}
{{- end -}}
```

If a tenant declares any secret, `okToTest` ≡ `pullRequest` allowlist. Adding a contributor to a secret-bearing tenant is a kustomization commit, not a chat command.

## Conversion skill — `/convert-gha-workflow`

Skill at `.claude/skills/convert-gha-workflow/SKILL.md`. Frontmatter:

```yaml
---
name: convert-gha-workflow
description: Convert a target repo's .github/workflows/*.yml into .tekton/*.yaml for OpenShift Pipelines as Code, prune the GHA workflows to publish-on-main only, and emit a secret-migration report.
argument-hint: [path-to-target-repo] [--auto|-y]
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash(yq *), Bash(find *), Bash(ls *), Bash(cat *), Bash(git *)
---
```

### What it does

1. **Discover** all `.github/workflows/*.{yml,yaml}` in the target repo.
2. **Parse** each (`yq '.'`) into structured form: triggers, jobs, steps, matrix, secrets references, action references.
3. **Categorize** each job:

   | Bucket | Examples | Destination |
   |---|---|---|
   | PR-checkable | lint, format, vet, type-check, unit test | `.tekton/pull-request.yaml` |
   | Build/test artifact-producing, non-publishing | `go build`, `npm build`, image build (no push) | `.tekton/pull-request.yaml` |
   | Publish/release/deploy | docker push, GitHub Release, deploy ssh, npm publish, helm push | stays in GHA, pruned to `push:main` |
   | Unsupported | self-hosted-runner-only, GHA-specific actions with no Tekton analog | flagged in report, left in GHA with TODO |

4. **Transform** PR-bucket jobs to Tekton Tasks (see mapping table below).
5. **Prune** the original workflow file: remove migrated jobs, restrict trigger to `on: push: branches: [main]`, rename file from `ci.yml` to `publish.yml` if all migrated jobs were CI.
6. **Emit** `.tekton/pull-request.yaml`, `.tekton/README.md`, and a terminal migration report.

### Action mapping table (`.claude/skills/convert-gha-workflow/mappings.yaml`)

Initial set:

| GHA action | Tekton replacement |
|---|---|
| `actions/checkout@v4` | (drop — implicit; PaC pre-populates `source` workspace) |
| `actions/setup-go@v5` | `image: docker.io/golang:<v>` |
| `actions/setup-node@v4` | `image: docker.io/node:<v>-bookworm` |
| `actions/setup-python@v5` | `image: docker.io/python:<v>` |
| `actions/setup-java@v4` | `image: docker.io/eclipse-temurin:<v>` |
| `actions/cache@v4` | volumeClaimTemplate or workspace PVC + cache key script |
| `docker/setup-buildx-action@v3` | (drop — buildah handles natively) |
| `docker/login-action@v3` | imagePullSecrets on SA (Mode A) — flagged for tenant config |
| `docker/build-push-action@v6` | Hub task `buildah` with `--isolation=chroot` |
| `golangci/golangci-lint-action@v6` | `image: docker.io/golangci/golangci-lint:v<x>-alpine` |
| `pre-commit/action@v3` | `image: docker.io/python:3.12` + `pip install pre-commit && pre-commit run --all-files` |
| `azure/setup-helm@v5` | `image: alpine/helm:<v>` |
| `imranismail/setup-kustomize@v3` | `image: registry.k8s.io/kustomize/kustomize:v5.4.3` |
| `yannh/kubeconform@v1` | inline `curl + tar` install in alpine, or custom step |
| `actions/github-script@v7` | UNMAPPED (flag — would need GH App API call from cluster, not in scope) |
| `actions/upload-artifact@v4` | flagged — Tekton has no native artifact storage; user picks workspace persistence or skips |
| `redhat-actions/podman-login@v1` | imagePullSecrets on SA (Mode A) — same flow as `docker/login-action`, just different registry target |
| `redhat-actions/push-to-registry@v2` | flagged PUBLISH — stays in GHA per the hybrid split |
| `docker/setup-qemu-action@v4` | UNMAPPED (flag — multi-arch buildah is non-trivial; out of scope for v1) |
| `docker/metadata-action@v6` | inline `script:` step deriving tags from `$(params.revision)` / `$(params.git-ref)` / git-tag lookup |
| `bjw-s-labs/action-changed-files@v0.6.0` | inline `git diff --name-only $(params.base-revision)...$(params.revision)` exported via `results.changed-files` |
| `anchore/sbom-action@v0` | Hub task `syft-sbom`, or inline `syft` on `docker.io/anchore/syft:latest` |
| `devcontainers/ci@v0.3` | UNMAPPED — recursive devcontainer build; stays in GHA |

Stored as data, not embedded in the prompt — grow-able without skill edits.

### Reusable workflows (`uses: ./.github/workflows/foo.yml`)

`igou-ansible` has three publisher workflows that all `uses: ./.github/workflows/ee-build.yml`. The Tekton analog is a shared Pipeline definition referenced from multiple PipelineRuns via the git resolver. v1 of the conversion skill **does not** auto-migrate this pattern — when it encounters a workflow-call reference, it:

1. Logs the reference in the migration report.
2. Leaves the calling workflow in GHA with a TODO comment.
3. Does not attempt to inline the called workflow.

For `igou-ansible` specifically, the EE-build workflows are publish-side anyway (per the GHA-stays-on-main split), so they all stay in GHA. The reusable-workflow → shared-Pipeline migration is a v2 skill enhancement, only relevant when a *PR-side* workflow chains to a reusable.

### Output structure

Target repo after running the skill:

```
target-repo/
├── .github/workflows/
│   └── publish.yml                # was ci.yml; pruned to publish-only,
│                                  # trigger restricted to push:main
└── .tekton/
    ├── pull-request.yaml          # PR PipelineRun
    └── README.md                  # generated: how to test, what was migrated
```

### Migration report (printed to terminal)

```
Migration of github.com/igou-io/foo:
  ✓ Job 'lint' → .tekton/pull-request.yaml (Task: lint)
  ✓ Job 'test' → .tekton/pull-request.yaml (Task: test, matrix: go-version)
  ✓ Job 'build-image' → .tekton/pull-request.yaml (Task: image-build, no push)
  ↩ Job 'publish' → stays in .github/workflows/publish.yml (push:main only)
  ⚠ Job 'release-notes' uses actions/github-script — left in GHA with TODO

Secret migration:
  GHCR_TOKEN  → tenant.secrets.imagePullSecrets (1Password: ci-ghcr-readonly)
  CODECOV_TOKEN → tenant.secrets.workspaceSecrets (1Password: ci-codecov)

Next steps:
  1. Review .tekton/pull-request.yaml for unmapped steps (search 'UNMAPPED ACTION')
  2. In igou-openshift: /scaffold-pac-tenant igou-io/foo  (if not already onboarded)
  3. Add secret entries to clusters/ocp/pac-tenants/values.yaml under tenant 'foo'
  4. Add 'ci-ghcr-readonly' + 'ci-codecov' to 1Password vault
  5. Commit + push both repos; verify PaC fires on first PR.
```

### Sibling skill — `/scaffold-pac-tenant`

Skill at `.claude/skills/scaffold-pac-tenant/SKILL.md`. Frontmatter:

```yaml
---
name: scaffold-pac-tenant
description: Add a new PaC tenant entry to clusters/ocp/pac-tenants/values.yaml. Verifies the GitHub repo exists, derives a name from the URL, applies defaults, supports optional --imagePullSecret and --workspaceSecret flags. Validates the rendered chart with helm template + kubeconform before reporting completion.
argument-hint: <github-url-or-owner/repo> [--imagePullSecret name:1pwd-item] [--workspaceSecret name:1pwd-item ...]
disable-model-invocation: true
allowed-tools: Read, Edit, Bash(gh repo view *), Bash(yq *), Bash(helm template *), Bash(kubeconform *)
---
```

Edits one file (`clusters/ocp/pac-tenants/values.yaml`), runs validation, asks the user to commit.

### What both skills don't do

- **Don't auto-commit.** Skills write files and exit. User reviews diffs before committing.
- **Don't install the GitHub App on a repo.** Manual one-click in the GitHub UI per repo. Skill prints the App URL.
- **Don't push.** PaC fires on the PR opening — that's also the test of the conversion.

## Rollout sequence

1. **Manual: create GitHub App** on github.com. Permissions: `Checks: R/W`, `Contents: R`, `Issues: R/W`, `Metadata: R`, `Pull requests: R/W`. Subscribe: `Check run`, `Check suite`, `Commit comment`, `Issue comment`, `Pull request`, `Push`. Webhook URL = placeholder.
2. **Manual: store GitHub App credentials** in 1Password as item `pac-github-app`.
3. **Manual: store cosign key** in 1Password as item `tekton-chains-signing`.
4. **Manual: edit Tailscale ACL** to grant `funnel` to operator's device tag.
5. **Commit `components/openshift-pipelines/` updates.** ArgoCD reconciles in waves 10/11/12.
6. **Wait for Funnel hostname** to come up. Update GitHub App webhook URL.
7. **Commit `.helm/charts/pac-tenant/`.**
8. **Commit `clusters/ocp/pac-tenants/`** with empty `tenants:` list, plus the `pac-tenants` entry in `clusters/ocp/values.yaml`.
9. **Commit `.claude/skills/scaffold-pac-tenant/` and `.claude/skills/convert-gha-workflow/`.**
10. **First tenant onboarding (smoke test):** install GitHub App on `igou-io/igou-openshift`. Run `/scaffold-pac-tenant igou-io/igou-openshift`. Run `/convert-gha-workflow .` (against this repo). Open a PR with the resulting `.tekton/pull-request.yaml`. Watch PaC fire.
11. **Onboard remaining repos** in waves of 2–3.

## Validation

Existing `make` targets:
- `make lint` — yamllint
- `make validate-kustomize` — `kustomize build` over every `kustomization.yaml`
- `make validate-schemas` — kubeconform

Required additions to the Makefile:
- **CRD schemas for kubeconform** — `operator.tekton.dev/v1alpha1.TektonConfig`, `pipelinesascode.tekton.dev/v1alpha1.Repository`, `tekton.dev/v1.PipelineRun`. Add to schema lookup paths.
- **`make lint-helm`** — runs `helm lint` over `.helm/charts/pac-tenant`, `.helm/charts/argocd-app-of-app`, `.helm/charts/ocp-base-config`. New target; chained into `make test`.
- **`clusters/ocp/pac-tenants/` validation** — `helm template` it, pipe through kubeconform. Add to existing `validate-kustomize` (which is the umbrella render-then-validate target).

## Smoke test acceptance criteria

A single PR on `igou-io/igou-openshift` that:
1. Adds `.tekton/pull-request.yaml` with one task that runs `make lint`.
2. Touches no other file.

Expected:
- PaC controller logs show webhook received + signature verified.
- New PipelineRun appears in `ci-igou-openshift` namespace.
- GitHub PR shows a "Pipelines as Code (homelab) / lint" check that turns green.
- ArgoCD's `pac-tenants` app stays Synced/Healthy.
- TaskRun pod spec shows: `automountServiceAccountToken: false`, `runAsNonRoot: true`, `priorityClassName: tekton-ci-low`.
- Three NetworkPolicies in `ci-igou-openshift`. Egress to github.com works; egress to `192.168.x.x` fails (`oc rsh` into a paused pod, `nc -zv 192.168.1.1 22` should hang).

If all pass, hardening is real and the rest of the migration is mechanical.

## Rollback paths

- **Per-tenant disable:** delete the tenant entry from `clusters/ocp/pac-tenants/values.yaml`. Sync. Namespace stays orphaned (auto-prune is off per repo convention) but PaC stops reacting to that repo.
- **Cluster-wide disable:** flip `TektonConfig.spec.platforms.openshift.pipelinesAsCode.enable: false`. Operator scales the PaC controller to zero. Webhooks 503; GitHub will show webhook delivery failures and back off.
- **Full uninstall:** delete the `pac-tenants` ArgoCD app + the `openshift-pipelines` ArgoCD app. The operator's CSV cleans up most resources. Tenant namespaces remain (manual cleanup).

## Open questions / things to verify at implementation time

1. **OCP pod and service CIDRs** — `clusters/ocp/values.yaml` excerpts and `oc get network.config/cluster` should be checked before committing the NetworkPolicy CIDR allowlist.
2. **Tailscale operator's device tag** — verify the actual tag the operator uses on its proxy device, then write the matching ACL entry. Default is typically `tag:k8s` but is configurable.
3. **`pipelines-as-code-secret` exact key names** — operator versions have shifted these slightly. Verify against the deployed operator's PaC controller env-var bindings.
4. **PaC controller Service selector labels** — confirm `app.kubernetes.io/name: controller` + `app.kubernetes.io/part-of: pipelines-as-code` against the live cluster's Service. The Funnel Service uses the same selector to attach.
5. **First conversion target** — `igou-openshift`'s own `validate.yml` is the obvious smoke-test candidate, but it uses `imranismail/setup-kustomize` and `azure/setup-helm` which are in the mapping table. Verify these resolve cleanly before committing.
