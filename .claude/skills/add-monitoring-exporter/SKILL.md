---
name: add-monitoring-exporter
description: Add a Prometheus exporter (or bare ServiceMonitor/PodMonitor) to user workload monitoring. Supports four render modes — helm chart, bjw-s app-template chart, OLM operator, and servicemonitor-only. Generates the exporter directory under components/user-workload-monitoring/exporters/<name>/, wires a ServiceMonitor and optional PrometheusRule, registers it in the UWM kustomization, and chains into add-externalsecret / import-grafana-dashboard / scaffold-component-olm as needed.
argument-hint: <exporter-name> [--mode helm|app-template|olm|servicemonitor]
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(kustomize build *), Bash(helm show values *), Bash(curl *), Bash(oc get packagemanifest *), Bash(oc explain *), Bash(oc api-resources *), Bash(ls *), Bash(cat *), Bash(make lint), Bash(make validate-kustomize)
---

# Add a user workload monitoring exporter

Scaffold a Prometheus exporter (or a bare metrics scrape) so OpenShift's User
Workload Monitoring stack starts collecting metrics from a target. The skill
picks one of four render paths based on how the exporter is packaged, lays out
the files under the right directory, registers the new pieces with the UWM
component, and chains into other skills (`add-externalsecret`,
`import-grafana-dashboard`, `scaffold-component-olm`, `add-probe`) when their
output is needed.

## Where things live

```
components/user-workload-monitoring/
  kustomization.yaml                          ← register every exporter dir + every bare ServiceMonitor here
  cluster-monitoring-config-configmap.yaml    ← enables UWM (do not modify)
  user-workload-monitoring-config-configmap.yaml
  exporters/
    <exporter-name>/                          ← one directory per exporter (helm/app-template/olm)
      kustomization.yaml
      <exporter-name>-namespace.yaml
      <exporter-name>-prometheusrule.yaml     ← optional alerts
      ... (helm valuesInline / app-template values / OLM Subscription)
  servicemonitors/                            ← bare ServiceMonitor / PodMonitor against existing apps
    <target>-servicemonitor.yaml
    <target>-podmonitor.yaml
```

UWM is registered in `clusters/<cluster>/values.yaml` at sync-wave `6`
(`components/user-workload-monitoring`). New exporters inherit that wave —
do **not** add a separate cluster entry per exporter.

## Parsing arguments

`$ARGUMENTS` may contain:
- An exporter name (required unless empty — then ask)
- An optional `--mode <mode>` flag where `<mode>` is `helm`, `app-template`, `olm`, or `servicemonitor`

Examples: `postgres-exporter --mode helm`, `snmp-exporter`, `dcgm-exporter --mode olm`, `--mode servicemonitor my-app`.

Parse the name and the mode. If `$ARGUMENTS` is empty, ask for both before proceeding.

## Step 1: Pick the render mode

If the user did not supply `--mode`, ask once. The four modes:

| Mode | When to use | Files end up under |
|------|-------------|--------------------|
| `helm` | An upstream Helm chart exists (e.g. `prometheus-community/prometheus-blackbox-exporter`, `prometheus-community/prometheus-postgres-exporter`, `prometheus-community/prometheus-snmp-exporter`) | `components/user-workload-monitoring/exporters/<name>/` with a `helmCharts` stanza |
| `app-template` | The exporter is just a container image with flags/env (no upstream chart, e.g. a one-off `quay.io/.../foo-exporter:latest`) | `components/user-workload-monitoring/exporters/<name>/` rendered through `oci://ghcr.io/bjw-s-labs/helm app-template` |
| `olm` | The exporter ships as part of an OLM operator (e.g. NVIDIA DCGM via the GPU operator). The **operator** lives at `components/<operator-name>/`; this skill only adds the **ServiceMonitor / PrometheusRule** wiring under UWM | `components/user-workload-monitoring/servicemonitors/<name>-servicemonitor.yaml` (+ optional PrometheusRule under UWM). Operator scaffolding is delegated to `scaffold-component-olm`. |
| `servicemonitor` | The target workload already exposes `/metrics` and you only need to point UWM at it (e.g. cert-manager, argocd, grafana-operator) | `components/user-workload-monitoring/servicemonitors/<name>-servicemonitor.yaml` (or `-podmonitor.yaml`) |

Mode detection hints: if the user mentions a `helm` repo URL, prefer `helm`; if
they mention a container image only, prefer `app-template`; if they mention an
OLM operator name (or `Subscription`/`PackageManifest`), prefer `olm`; if they
say "the app already exposes metrics", prefer `servicemonitor`.

## Step 2: Mode-specific information gathering

Ask only the fields relevant to the chosen mode, in a **single** message.

### Common fields (all modes)

| Field | Description | Default |
|-------|-------------|---------|
| `exporter-name` | Used for directory, namespace, releaseName, and ServiceMonitor name | from `$ARGUMENTS` |
| `target-job-label` | `app.kubernetes.io/part-of` label value used on the ServiceMonitor for grouping | same as `exporter-name` |
| `scrape-interval` | ServiceMonitor `interval` | `30s` |
| `scrape-timeout` | ServiceMonitor `scrapeTimeout` | `10s` |
| `metrics-port-name` | Port name on the Service the ServiceMonitor will scrape | depends on chart / image (ask) |
| `metrics-path` | HTTP path scraped | `/metrics` |
| `prometheus-rule` | Generate a PrometheusRule scaffold (`yes`/`no`) | `no` |
| `external-secret` | Exporter needs credentials from 1Password (`yes`/`no`) | `no` |
| `dashboard-id` | grafana.com dashboard ID or URL to import alongside (optional) | — |

### `helm` mode — extra fields

| Field | Description | Default |
|-------|-------------|---------|
| `chart-name` | Helm chart name (e.g. `prometheus-postgres-exporter`) | — (required) |
| `chart-version` | Pinned chart version | — (required, ask user to look up latest if unknown) |
| `chart-repo` | Helm repo URL (e.g. `https://prometheus-community.github.io/helm-charts`) | — (required) |
| `image-digest` | Container image with `@sha256:` digest for Renovate pinning | — (required) |

### `app-template` mode — extra fields

| Field | Description | Default |
|-------|-------------|---------|
| `image-repo` | Container image repository (e.g. `quay.io/prometheuscommunity/json-exporter`) | — (required) |
| `image-tag` | Tag, ideally `<tag>@sha256:<digest>` for Renovate | — (required) |
| `container-port` | Port the exporter listens on | — (required) |
| `args` | Exporter CLI args (list) | `[]` |
| `env` | Environment variables (map) | `{}` |

### `olm` mode — extra fields

| Field | Description | Default |
|-------|-------------|---------|
| `operator-component` | Existing component path that installs the operator (e.g. `components/nvidia-gpu-operator`). If missing, this skill stops and asks the user to run `scaffold-component-olm` first | — |
| `metrics-namespace` | Namespace where the operator exposes metrics | from operator component |
| `service-selector` | Label selector matching the metrics Service (`key: value` per line) | — (required) |

### `servicemonitor` mode — extra fields

| Field | Description | Default |
|-------|-------------|---------|
| `target-namespace` | Namespace of the workload that already exposes `/metrics` | — (required) |
| `target-kind` | `service` (→ ServiceMonitor) or `pod` (→ PodMonitor) | `service` |
| `service-selector` | `matchLabels` for the target Service / Pod | — (required) |

## Step 3: Validate before writing

1. **Idempotency**: if `components/user-workload-monitoring/exporters/<exporter-name>/`
   already exists (helm / app-template / olm), or if a ServiceMonitor /
   PodMonitor with the same `metadata.name + namespace` already exists under
   `components/user-workload-monitoring/servicemonitors/`, stop and report the
   existing location.
2. **OLM mode**: verify `<operator-component>/kustomization.yaml` exists and
   contains a `Subscription`. If not, tell the user to run
   `/scaffold-component-olm <operator-name>` first.
3. **Mode `helm` chart sanity**: optionally fetch
   `helm show values <chart-repo>/<chart-name> --version <chart-version>` (if
   reachable) to confirm the chart name and surface `serviceMonitor` /
   `image` keys. Air-gapped failure is non-blocking.
4. **External Secret**: if `external-secret=yes`, do **not** generate the
   ExternalSecret YAML inline — delegate to `add-externalsecret` after the
   scaffold (see Step 6).

## Step 4: File generation

### Conventions (apply to every file)

- 2-space indentation
- Files start with `---` (except `kustomization.yaml`, per kustomize convention)
- YAML 1.2 booleans only (`true`/`false`)
- File names: `<metadata.name>-<kind>.yaml` (lowercase, hyphens)
- `app.kubernetes.io/part-of: <target-job-label>` label on every ServiceMonitor / PodMonitor / PrometheusRule
- PrometheusRule has the label
  `openshift.io/prometheus-rule-evaluation-scope: leaf-prometheus` so UWM's
  Thanos Ruler evaluates it (matches `blackbox-exporter-prometheusrule.yaml`)
- Exporters do **not** get a sync-wave annotation on the namespace — UWM
  itself is sync-wave 6 and the exporter inherits it
- Container `securityContext` and pod `securityContext` must be
  OpenShift `restricted-v2`-friendly: `runAsNonRoot: true`,
  `allowPrivilegeEscalation: false`, drop ALL capabilities,
  seccompProfile `RuntimeDefault`. Do **not** set `runAsUser` / `runAsGroup` —
  SCC injects them from the namespace UID range. If the upstream chart hard-codes
  `runAsUser`, add a `patches:` block that removes it (see the `blackbox-exporter`
  example in `components/user-workload-monitoring/exporters/blackbox-exporter/kustomization.yaml`).

### A) `helm` mode

Create `components/user-workload-monitoring/exporters/<exporter-name>/`
with the following files. Use `components/user-workload-monitoring/exporters/blackbox-exporter/`
as the canonical reference — read that directory first.

#### `<exporter-name>-namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: <exporter-name>
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

#### `kustomization.yaml`

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <exporter-name>
resources:
  - <exporter-name>-namespace.yaml
  # - <exporter-name>-prometheusrule.yaml   (uncomment if prometheus-rule=yes)
helmCharts:
  - name: <chart-name>
    namespace: <exporter-name>
    version: <chart-version>
    releaseName: <exporter-name>
    repo: <chart-repo>
    valuesInline:
      fullnameOverride: <exporter-name>
      image:
        # split <image-digest> into registry/repository/tag@digest as the chart expects
        ...
      podSecurityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      securityContext:
        runAsNonRoot: true
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      serviceMonitor:
        enabled: true
        defaults:
          labels:
            release: <exporter-name>
          interval: <scrape-interval>
          scrapeTimeout: <scrape-timeout>
      resources:
        requests:
          cpu: 10m
          memory: 32Mi
        limits:
          memory: 128Mi
# Add a patches: block here only if the chart hard-codes runAsUser/runAsGroup;
# match the blackbox-exporter pattern.
```

If the chart does **not** expose a `serviceMonitor` toggle, generate a
standalone `<exporter-name>-servicemonitor.yaml` (see template under section D)
and add it to `resources:`.

If `external-secret=yes`, leave a commented placeholder under `resources:`
(`# - <exporter-name>-externalsecret.yaml`) — `add-externalsecret` will
uncomment it when invoked.

### B) `app-template` mode

Create `components/user-workload-monitoring/exporters/<exporter-name>/` and
follow the conventions from the `scaffold-app-template` skill (read its SKILL.md
first to copy the exact `valuesInline` shape and the `values-dummy.yaml`
workaround for [bjw-s-labs/helm-charts#397](https://github.com/bjw-s-labs/helm-charts/issues/397)).

The deltas vs. `scaffold-app-template` are:
- Path is `components/user-workload-monitoring/exporters/<name>/`, **not** `applications/<name>/`
- No `ingress` block — exporters are scraped in-cluster, not exposed externally
- `serviceMonitor` block is **always** populated (it's the whole point)
- Default `replicas: 1`, `strategy: RollingUpdate`, `restricted-v2` SCC settings

Required files:
- `<exporter-name>-namespace.yaml` (with the same `pod-security.kubernetes.io/*: restricted` labels as the helm mode)
- `kustomization.yaml` with `helmCharts.[0]` referencing
  `app-template` from `oci://ghcr.io/bjw-s-labs/helm` at the version pinned by
  `scaffold-app-template` (currently `4.6.2` — re-read that skill if older)
- `values-dummy.yaml` (`foo: bar`) — required workaround
- Optional `<exporter-name>-prometheusrule.yaml`

Example `valuesInline` skeleton (omit unused keys):

```yaml
    controllers:
      <exporter-name>:
        type: deployment
        replicas: 1
        strategy: RollingUpdate
        pod:
          securityContext:
            seccompProfile:
              type: RuntimeDefault
        containers:
          app:
            image:
              repository: <image-repo>
              tag: <image-tag>
              pullPolicy: IfNotPresent
            args: <args>
            env: <env>
            probes:
              liveness:  { enabled: true, type: TCP }
              readiness: { enabled: true, type: TCP }
              startup:   { enabled: true, type: TCP }
            resources:
              requests: { cpu: 10m, memory: 32Mi }
              limits:   { memory: 128Mi }
            securityContext:
              allowPrivilegeEscalation: false
              runAsNonRoot: true
              capabilities:
                drop: [ALL]
    service:
      app:
        controller: <exporter-name>
        ports:
          metrics:
            port: <container-port>
            targetPort: <container-port>
    serviceMonitor:
      app:
        serviceName: <exporter-name>-app
        labels:
          app.kubernetes.io/part-of: <target-job-label>
        endpoints:
          - port: metrics
            scheme: http
            path: <metrics-path>
            interval: <scrape-interval>
            scrapeTimeout: <scrape-timeout>
    serviceAccount:
      <exporter-name>:
        enabled: true
```

### C) `olm` mode

Do **not** scaffold the operator itself here. If the operator component does
not yet exist, stop and tell the user to run
`/scaffold-component-olm <operator-name>` first, then re-invoke this skill.

When the operator component exists:

1. Generate `components/user-workload-monitoring/servicemonitors/<exporter-name>-servicemonitor.yaml`
   targeting the operator's metrics Service (use the `service-selector` and
   `metrics-namespace` answers from Step 2). Use the same template as section D.
2. If `prometheus-rule=yes`, generate
   `components/user-workload-monitoring/exporters/<exporter-name>-prometheusrule.yaml`
   (note: PrometheusRule lives one level up from `servicemonitors/` because the
   existing layout has no `prometheusrules/` dir; place it directly under
   `components/user-workload-monitoring/` and register it in the UWM kustomization).

### D) `servicemonitor` mode (and the standalone monitor templates used by other modes)

Pick the resource shape based on `target-kind`:

#### ServiceMonitor (`target-kind: service`)

`components/user-workload-monitoring/servicemonitors/<exporter-name>-servicemonitor.yaml`:

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: <exporter-name>
  namespace: <target-namespace>
  labels:
    app.kubernetes.io/part-of: <target-job-label>
spec:
  selector:
    matchLabels:
      <service-selector keys/values, one per line>
  endpoints:
    - port: <metrics-port-name>
      interval: <scrape-interval>
      scrapeTimeout: <scrape-timeout>
      path: <metrics-path>
```

#### PodMonitor (`target-kind: pod`)

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: <exporter-name>
  namespace: <target-namespace>
  labels:
    app.kubernetes.io/part-of: <target-job-label>
spec:
  selector:
    matchLabels:
      <service-selector keys/values, one per line>
  podMetricsEndpoints:
    - port: <metrics-port-name>
      interval: <scrape-interval>
      scrapeTimeout: <scrape-timeout>
      path: <metrics-path>
```

### E) Optional `<exporter-name>-prometheusrule.yaml` (any mode)

For helm / app-template, place under
`components/user-workload-monitoring/exporters/<exporter-name>/`. For
servicemonitor / olm, place under `components/user-workload-monitoring/`.

Skeleton (model on `blackbox-exporter-prometheusrule.yaml`):

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: <exporter-name>
  namespace: <namespace>
  labels:
    app.kubernetes.io/name: <exporter-name>
    openshift.io/prometheus-rule-evaluation-scope: leaf-prometheus
spec:
  groups:
    - name: <exporter-name>.alerts
      rules:
        - alert: <ExporterDown>
          expr: up{job="<exporter-name>"} == 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: <human summary>
            description: <human description>
```

Leave the alert rules as a TODO comment unless the user provides them — pure
boilerplate alerts often do more harm than good.

## Step 5: Wire the new resources into the UWM kustomization

Edit `components/user-workload-monitoring/kustomization.yaml` to register the
new resource(s). Use `Edit` to insert; do not rewrite the whole file.

- `helm` / `app-template` mode → add `- exporters/<exporter-name>` to `resources:`,
  alphabetically among siblings (e.g. after `exporters/blackbox-exporter`).
- `servicemonitor` / `olm` mode → add `- servicemonitors/<exporter-name>-servicemonitor.yaml`
  (or `-podmonitor.yaml`) to `resources:`, sorted alphabetically among the
  existing `servicemonitors/*` entries.
- If a top-level PrometheusRule was generated for `olm` / `servicemonitor` mode,
  also add `- <exporter-name>-prometheusrule.yaml`.

## Step 6: Chain into other skills

After files are written and the UWM kustomization is updated, decide whether
to invoke another skill. Prefer telling the user to run them explicitly (so
they can review the inputs) unless the user has clearly authorised chaining.

| Condition | Skill to run | Command to suggest |
|-----------|-------------|--------------------|
| `external-secret=yes` | `add-externalsecret` | `/add-externalsecret components/user-workload-monitoring/exporters/<exporter-name>` (helm/app-template only — for OLM the secret belongs in the operator component) |
| `dashboard-id` provided | `import-grafana-dashboard` | `/import-grafana-dashboard <dashboard-id> components/grafana` |
| OLM operator missing in mode `olm` | `scaffold-component-olm` | `/scaffold-component-olm <operator-name>` (run first, then re-invoke this skill) |
| Exporter is blackbox-style (probes external URLs) | `add-probe` | `/add-probe <url>` for each target |

After scaffolding the secret, remind the user to wire it into `valuesInline`:
- For helm mode: typically `extraEnv` / `envFrom` keys differ per chart — point
  the user at the chart's values reference.
- For app-template mode:
  `controllers.<exporter-name>.containers.app.envFrom: [{ secretRef: { name: <exporter-name>-secret } }]`.

## Step 7: Validation

Run, in order:

```bash
kustomize build components/user-workload-monitoring/exporters/<exporter-name>/   # only for helm / app-template
kustomize build components/user-workload-monitoring/
make lint
make validate-kustomize
```

- A network failure pulling the chart from the upstream registry is **expected**
  in air-gapped environments — note it but do not treat it as a blocker.
- Any structural / yamllint / kubeconform error must be fixed before reporting
  completion. Do not paper over with `# noqa`-style escapes.
- Do **not** run `make test` (full schema scan) unless the user explicitly asks
  — the per-component build plus `make lint` + `make validate-kustomize` is
  sufficient for an exporter scaffold.

## Step 8: Completion report

Report:

1. **Mode chosen** and a one-line justification (e.g. "helm — chart pinned at
   prometheus-postgres-exporter 6.1.0").
2. **Files created** (full paths).
3. **`components/user-workload-monitoring/kustomization.yaml`** — show the
   one- or two-line diff of what was added.
4. **Validation result** (kustomize build / make lint / make validate-kustomize:
   pass / expected-network-failure / structural-error).
5. **Next steps** for the user (only the ones that apply):
   - Tune `valuesInline` (or the ServiceMonitor selector) — point at the exact
     keys to fill in.
   - Run `/add-externalsecret …` if `external-secret=yes`.
   - Run `/import-grafana-dashboard <id> components/grafana` if a dashboard ID
     was supplied.
   - Run `/scaffold-component-olm <name>` first if mode `olm` and the operator
     component was missing.
   - Reminder: UWM is registered at sync-wave 6; Argo will pick the new
     exporter up automatically on the next sync. No `clusters/<name>/values.yaml`
     change is required.
6. **Verification** once Argo syncs:
   - OCP console → Observe → Targets → confirm the new ServiceMonitor / PodMonitor
     shows `up`.
   - OCP console → Observe → Metrics → query a metric the exporter exposes
     (e.g. `up{job="<exporter-name>"}`) to confirm scrape success.
   - If `prometheus-rule=yes`, check Observe → Alerting → Alerting rules for
     the new rule group.

## Notes & gotchas

- **OLM-shipped exporters often expose metrics on a Service the operator
  reconciles itself.** Confirm the Service name and label selector by inspecting
  the running cluster (`mcp__kubernetes__resources_list` or `oc get svc -n <ns>`)
  rather than guessing — operator-managed Services rarely follow
  `app.kubernetes.io/instance` conventions.
- **`fullnameOverride: <exporter-name>`** in helm mode keeps generated resource
  names short and predictable so the ServiceMonitor selector works without
  templating gymnastics.
- **`release: <exporter-name>` label on the chart-rendered ServiceMonitor** is
  what UWM's Prometheus uses to claim ServiceMonitors across namespaces. Some
  charts default this to `prometheus`; override it.
- **`runAsUser` / `runAsGroup`**: many community charts hard-code these. Always
  add a `patches:` block that removes them so OpenShift SCC can inject valid
  values from the namespace UID range — without this, the pod will fail to
  admit. Reference the `blackbox-exporter` patches block.
- **PodMonitor vs ServiceMonitor**: PodMonitor scrapes pods directly and skips
  the Service abstraction. Use it when the workload doesn't expose a Service
  for metrics (e.g. `external-secrets-operator`'s metrics-only port).
- **No `Probe` resources here** — those belong to the `blackbox-exporter`
  exporter and are managed via `/add-probe`. Do not generate `Probe` CRs from
  this skill.
- **Renovate**: pin the Helm chart `version:` and image `tag@sha256:<digest>`
  so Renovate can bump them. Untagged or `latest` images are silently rejected
  by Renovate config in this repo.
