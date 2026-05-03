---
name: scaffold-app-template
description: Scaffold a new user-facing application in applications/ that uses the bjw-s app-template Helm chart. Generates a Namespace, kustomization.yaml with a fully-populated helmCharts stanza (controllers, service, ingress as OpenShift Route, optional persistence/serviceMonitor/serviceAccount), and optional ExternalSecret, NFS PV+PVC, and Probe placeholder. Use when adding a self-hosted app that does not have its own Helm chart.
argument-hint: <app-name>
disable-model-invocation: true
allowed-tools: Read, Write, Bash(kustomize build *), Bash(helm show values *), Bash(curl *), Bash(ls *), Bash(cat *), Bash(make lint), Bash(make validate-kustomize)
---

# Scaffold a new application using the bjw-s app-template chart

Scaffold a new application under `applications/` that runs an arbitrary container
image via the [bjw-s app-template](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
Helm chart. The chart is rendered inline by Kustomize via a `helmCharts` stanza,
matching the convention used by every other app in this repo.

If the user wants to scaffold an app whose vendor publishes its own Helm chart,
use the existing `scaffold-app` skill instead.

## Chart reference — where to find the values schema

The `app-template` chart (`charts/other/app-template/`) is a thin wrapper with an
**empty** `values.yaml`. All configuration keys are defined in the bundled
`common` library chart. To look up available options, fetch the annotated
`values.yaml` from the common library:

```bash
curl -sL https://raw.githubusercontent.com/bjw-s-labs/helm-charts/main/charts/library/common/values.yaml
```

(`helm` is not available in this environment; use `curl` instead.)

### Repository layout

```
https://github.com/bjw-s-labs/helm-charts
  charts/
    other/app-template/          ← the chart referenced by kustomization.yaml
      values.yaml                  (empty — no defaults)
      values.schema.json           (JSON Schema for validation)
      Chart.yaml                   (declares dependency on common@4.x)
    library/common/              ← the real implementation
      values.yaml                  (full annotated schema — fetch this for reference)
      values.schema.json
```

### Top-level keys (common library)

| Key | Purpose |
|-----|---------|
| `global` | Name overrides, global labels/annotations, propagate metadata to pods |
| `defaultPodOptionsStrategy` | `overwrite` (default) or `merge` — how per-controller pod options interact with defaults |
| `defaultPodOptions` | Shared pod-level defaults: affinity, tolerations, nodeSelector, securityContext, imagePullSecrets, dnsPolicy, etc. |
| `controllers` | Map of controllers (deployment/daemonset/statefulset/cronjob/job). Each has `containers`, `initContainers`, `pod`, `strategy`, `replicas`, etc. |
| `serviceAccount` | Map of ServiceAccount objects |
| `secrets` | Map of Secret objects (plain-text values, use ExternalSecret for real secrets) |
| `configMaps` | Map of ConfigMap objects |
| `configMapsFromFolder` | Auto-generate ConfigMaps from a folder in the chart filesystem |
| `service` | Map of Service objects. Each references a `controller` and defines `ports` |
| `ingress` | Map of Ingress objects. Each has `hosts`, `tls`, `className`, `annotations` |
| `route` | Map of Gateway API route objects (HTTPRoute, TCPRoute, etc.) |
| `serviceMonitor` | Map of Prometheus ServiceMonitor objects |
| `persistence` | Map of volume mounts: `persistentVolumeClaim`, `emptyDir`, `nfs`, `hostPath`, `secret`, `configMap`, or `custom`. Supports `globalMounts` and `advancedMounts` |
| `networkpolicies` | Map of NetworkPolicy objects |
| `rbac` | Map of Role/ClusterRole and RoleBinding/ClusterRoleBinding objects |
| `rawResources` | Escape hatch for arbitrary Kubernetes resources not covered above |

### Container options (under `controllers.<name>.containers.<name>`)

| Key | Notes |
|-----|-------|
| `image.repository` / `image.tag` / `image.digest` / `image.pullPolicy` | Image config |
| `command` / `args` / `workingDir` | Override entrypoint |
| `env` | Environment variables — plain value, `valueFrom`, or list syntax |
| `envFrom` | Load from ConfigMap or Secret by identifier or name |
| `probes.liveness` / `probes.readiness` / `probes.startup` | `enabled`, `custom`, `type` (TCP/HTTP/GRPC/exec), `spec` |
| `resources` | Standard `requests`/`limits` |
| `securityContext` | Container-level security context |
| `lifecycle` | `postStart` / `preStop` hooks |

### Persistence — `advancedMounts` vs `globalMounts`

- `globalMounts`: mount the volume at the same path in **every** container of every controller.
- `advancedMounts`: fine-grained — specify per-controller, per-container mounts with optional `subPath`, `readOnly`, `mountPropagation`.

```yaml
persistence:
  config:
    type: persistentVolumeClaim
    existingClaim: my-app-config
    advancedMounts:
      my-app:        # controller name
        app:         # container name
          - path: /config
```

### `ingress` vs `route`

This repo uses **`ingress`** with the `openshift-default` class and the
`route.openshift.io/termination: edge` annotation to create an OpenShift Route
via the Ingress operator. Do **not** use the `route` key (Gateway API) unless
explicitly requested.

### `serviceAccount` identifier vs controller assignment

Each serviceAccount entry must have a unique identifier key. To assign it to a
controller, set `controllers.<name>.serviceAccount.identifier: <sa-key>`.
The default scaffold creates a serviceAccount with the same identifier as the
app name and does not assign it explicitly (the controller inherits the default
SA unless overridden).

## App name

The application to scaffold is: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask the user for the app name before proceeding.

## Information to gather

Before generating any files, collect the following. If the user provided all of
it inline, proceed directly. Otherwise ask in a **single** message — do not ask
one question at a time.

### Required

| Field | Description | Default |
|-------|-------------|---------|
| `app-name` | Directory name under `applications/`, namespace, controller/service name, Helm release name | from `$ARGUMENTS` |
| `image-repo` | Container image repository (e.g. `ghcr.io/foo/bar`) | — (required) |
| `image-tag` | Image tag, ideally `<tag>@sha256:<digest>` for Renovate pinning | — (required) |
| `container-port` | Port the container listens on | `8080` |
| `hostname` | Public hostname for the OpenShift Route | `<app-name>.apps.ocp.igou.systems` |

### Optional (default `no` unless noted)

| Field | Description |
|-------|-------------|
| `persistence` | `none` / `pvc` (config PVC) / `pvc+nfs` (config PVC plus an NFS PV+PVC for read-only data) |
| `pvc-size` | Size of the config PVC, only if `persistence` includes `pvc` (default `5Gi`) |
| `pvc-storage-class` | StorageClass name (default empty — cluster default) |
| `pvc-mount-path` | Where to mount the config PVC inside the container (default `/config`) |
| `nfs-server` / `nfs-path` / `nfs-mount-path` | Only if `persistence=pvc+nfs` |
| `external-secret` | `yes` / `no` — if `yes`, this skill does NOT write the ExternalSecret itself; it points the user at `/add-externalsecret applications/<app-name>` after scaffolding |
| `service-monitor` | `yes` / `no` — adds a Prometheus ServiceMonitor stanza scraping `/metrics` on the http port |
| `probe` | `yes` / `no` — generates an empty `<app-name>-probe.yaml` placeholder. Note: the existing `add-probe` skill is the better tool for actually filling this in. |

## File generation

Create directory `applications/<app-name>/` and generate the files below.

### Conventions (apply to every file)

- 2-space indentation
- Files start with `---` (except `kustomization.yaml`, per kustomize convention)
- YAML 1.2 booleans: `true`/`false` only
- File names: `<metadata.name>-<kind>.yaml` (all lowercase, hyphens)
- Namespace has no sync-wave annotation (applications deploy at wave 20+ and the
  Namespace is bundled with the app)
- Container-level `securityContext` and pod-level `pod.securityContext` are set
  for OpenShift `restricted-v2` SCC compatibility (`runAsNonRoot: true`,
  `allowPrivilegeEscalation: false`, drop ALL capabilities,
  seccompProfile `RuntimeDefault`)
- **Always** generate a `values-dummy.yaml` alongside `kustomization.yaml` and
  reference it via `valuesFile: values-dummy.yaml` in the `helmCharts` stanza.
  This is a required workaround for
  [bjw-s-labs/helm-charts#397](https://github.com/bjw-s-labs/helm-charts/issues/397):
  Kustomize 5.4.2+ fails with `could not parse values file into rnode: EOF` when
  `valuesInline` is used with a chart whose upstream `values.yaml` is empty
  (which is the case for `app-template`). The dummy file satisfies Kustomize's
  parser without affecting chart behaviour.

### 1. `<app-name>-namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: <app-name>
```

### 2. `kustomization.yaml`

The chart name is **`app-template`**, repo
**`oci://ghcr.io/bjw-s-labs/helm`**, current pinned version **`4.6.2`**.
Bump the version only if explicitly requested.

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <app-name>
resources:
  - <app-name>-namespace.yaml
  # Uncomment the lines below as the corresponding files are generated:
  # - <app-name>-config-pvc.yaml
  # - <app-name>-data-nfs-pv.yaml
  # - <app-name>-data-nfs-pvc.yaml
  # - <app-name>-probe.yaml
  # (the ExternalSecret entry is added by /add-externalsecret if you run it)
helmCharts:
- name: app-template
  namespace: <app-name>
  version: 4.6.2
  releaseName: <app-name>
  repo: oci://ghcr.io/bjw-s-labs/helm
  valuesFile: values-dummy.yaml
  valuesInline:
    controllers:
      <app-name>:
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
            env: {}
            probes:
              liveness:
                enabled: true
                type: TCP
              readiness:
                enabled: true
                type: TCP
              startup:
                enabled: true
                type: TCP
            resources: {}
            securityContext:
              allowPrivilegeEscalation: false
              runAsNonRoot: true
              capabilities:
                drop:
                  - ALL
    service:
      app:
        controller: <app-name>
        ports:
          http:
            port: <container-port>
            targetPort: <container-port>
    ingress:
      app:
        className: openshift-default
        annotations:
          route.openshift.io/termination: edge
        hosts:
          - host: <hostname>
            paths:
              - path: /
                pathType: Prefix
                service:
                  identifier: app
                  port: http
    serviceAccount:
      <app-name>:
        enabled: true
```

#### Optional valuesInline blocks

Append the following blocks under `valuesInline` only when the corresponding
option was selected. Keep keys alphabetised at the top level when adding more
than one (e.g. `persistence` before `service`, `serviceMonitor` after
`serviceAccount`).

##### Persistence (config PVC + optional NFS data volume)

When `persistence` includes `pvc`:

```yaml
    persistence:
      config:
        type: persistentVolumeClaim
        existingClaim: <app-name>-config
        advancedMounts:
          <app-name>:
            app:
              - path: <pvc-mount-path>
```

When `persistence=pvc+nfs`, also add a `data` mount that references the NFS PVC:

```yaml
      data:
        type: persistentVolumeClaim
        existingClaim: <app-name>-data
        advancedMounts:
          <app-name>:
            app:
              - path: <nfs-mount-path>
                readOnly: true
```

##### ServiceMonitor

```yaml
    serviceMonitor:
      app:
        serviceName: <app-name>-app
        endpoints:
          - port: http
            scheme: http
            path: /metrics
            interval: 60s
            scrapeTimeout: 10s
```

### 3. `values-dummy.yaml` (always)

Required workaround for [bjw-s-labs/helm-charts#397](https://github.com/bjw-s-labs/helm-charts/issues/397).
Create this file unconditionally — it is referenced by `valuesFile` in the
`helmCharts` stanza and prevents Kustomize 5.4.2+ from failing with
`could not parse values file into rnode: EOF`.

```yaml
foo: bar
```

Note: this file does **not** start with `---` and is **not** added to
`resources:` — it is only referenced by `valuesFile:` and is invisible to
Kubernetes.

### 4. `<app-name>-config-pvc.yaml` (if `persistence` includes `pvc`)


```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <app-name>-config
  namespace: <app-name>
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: <pvc-size>
  # storageClassName: <pvc-storage-class>   # uncomment to override the default
```

### 5. `<app-name>-data-nfs-pv.yaml` and `<app-name>-data-nfs-pvc.yaml` (if `persistence=pvc+nfs`)

Model on `applications/jellyfin/jellyfin-media-nfs-pv.yaml` and
`applications/jellyfin/jellyfin-media-nfs-pvc.yaml` — read those files with the
Read tool first to copy the exact PV/PVC binding pattern (matching `volumeName`
+ unique `storageClassName` to keep the binding 1:1).

### 6. ExternalSecret (if `external-secret=yes`)

Do **not** generate the ExternalSecret YAML inline in this skill. Instead,
delegate to the existing `add-externalsecret` skill, which validates the
1Password reference against the live `op` CLI and patches `kustomization.yaml`
correctly. Tell the user to run:

```
/add-externalsecret applications/<app-name>
```

after the scaffold completes (or invoke it directly if the user authorised
this skill to chain). The user is then responsible for wiring the resulting
Secret into `valuesInline` (typically via
`controllers.<app-name>.containers.app.envFrom` with a `secretRef` to
`<app-name>-secrets`). Mention this in the completion report.

### 7. `<app-name>-probe.yaml` (if `probe=yes`)

Generate a minimal placeholder and immediately tell the user to run the
`add-probe` skill (`/add-probe https://<hostname>`) to fill it in correctly:

```yaml
---
# Placeholder — populate via `/add-probe https://<hostname>` (skill: add-probe).
# Until then, this file intentionally contains no Probe resources.
```

If you generate this file, do **not** add it to `kustomization.yaml` until it
contains an actual Probe — kustomize will fail on an empty/comment-only resource.
Mention this trade-off in the completion report.

## After generating files

1. Run `kustomize build applications/<app-name>/` to validate the scaffold builds.

2. If kustomize build fails because it can't fetch the chart (network or auth
   error against `ghcr.io/bjw-s-labs`), that's expected in an air-gapped
   environment — note it clearly but do not treat it as a blocker.

3. If kustomize build fails for a YAML/structure reason, diagnose and fix it
   before reporting.

4. Optionally run `make lint` to catch yamllint issues. Do **not** run
   `make test` — that pulls every chart and is slow; the per-app
   `kustomize build` is sufficient.

## Completion report

After generating files, report:

1. Files created (list with full paths).
2. Kustomize build result (pass / expected network failure / structural error).
3. Three explicit next steps for the user:
   - **Tune `valuesInline`**: customise env vars, resources, probes (replace
     the default TCP probes with HTTP if the app exposes a health endpoint),
     and any image-specific knobs.
   - **Register with the cluster**: run the `add-to-cluster` skill
     (`/add-to-cluster <cluster> <app-name>`) to add the app under
     `applications:` in the target cluster's `values.yaml` with sync-wave 20+.
   - **(If probe=yes)**: run `/add-probe https://<hostname>` to populate the
     placeholder, then add `<app-name>-probe.yaml` to `kustomization.yaml`
     under `resources:`.
4. **(If external-secret=yes)**: remind the user to reference the generated
   Secret from the container env (e.g. `envFrom: [{ secretRef: { name:
   <app-name>-secrets } }]` under `controllers.<app-name>.containers.app`).
