# Remote Tenant Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give trusted users remote, locked-down `oc`/`kubectl` access to a single OpenShift namespace over the tailnet, with default/configurable guardrails (RBAC, NetworkPolicy, ResourceQuota, LimitRange, PSA, node-pinning, burst-node + secondary-network blocks).

**Architecture:** A new `remote-tenant` Helm chart (mirroring the existing `pac-tenant` idiom) renders, per tenant, a Namespace + ResourceQuota + LimitRange + NetworkPolicies + a `RoleBinding(group → role)`, plus once-rendered shared resources: a custom `remote-tenant-operator` ClusterRole and two ValidatingAdmissionPolicies (no-burst, no-secondary-net). The Tailscale operator's API-server proxy is enabled (`mode: "true"`) so a tailnet identity is impersonated into the bound group. Tailnet grants and node labels are one-time manual ops.

**Tech Stack:** Helm (rendered via kustomize `helmCharts` inflation), ArgoCD app-of-apps, OpenShift RBAC + NetworkPolicy + ResourceQuota/LimitRange + PSA + ValidatingAdmissionPolicy (`admissionregistration.k8s.io/v1`, GA on OCP 4.21 / k8s 1.34), Tailscale Kubernetes operator.

**Spec:** `docs/superpowers/specs/2026-06-13-remote-tenant-access-design.md`

**Working location:** the `feat/remote-tenant-access` git worktree at `/workspace/igou-openshift-remote-tenant`. All paths below are repo-root-relative.

**Commit convention:** small, frequent commits; end each commit message with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

**Validation tooling (no pytest here):**
- Chart unit checks: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml [--show-only templates/<file>]`
- `helm lint .helm/charts/remote-tenant`
- Repo gates: `make lint` (yamllint), `make validate-kustomize` (kustomize build all), `make validate-schemas` (kubeconform). Run from repo root.
- A template that doesn't exist yet makes `--show-only templates/<file>` fail with `could not find template ... in chart` — that is the "failing test" state for each template task.

---

## File Structure

**New — chart (`.helm/charts/remote-tenant/`):**
- `Chart.yaml` — chart metadata.
- `values.yaml` — `namespacePrefix`, `defaults{}`, `tenants: []`, schema docs.
- `test-values.yaml` — two example tenants exercising defaults, role override, monitoring, extraEgress.
- `templates/_helpers.tpl` — `remote-tenant.merged`, `remote-tenant.namespace`, `remote-tenant.labels`.
- `templates/namespace.yaml` — per-tenant Namespace (PSA, `openshift.io/node-selector`, `tenant-type` label).
- `templates/resourcequota.yaml` — per-tenant ResourceQuota.
- `templates/limitrange.yaml` — per-tenant LimitRange.
- `templates/networkpolicies.yaml` — per-tenant NetworkPolicies (deny/dns/intra/external/monitoring + extraEgress/extraIngress).
- `templates/clusterrole.yaml` — shared `remote-tenant-operator` ClusterRole (rendered once).
- `templates/rolebindings.yaml` — per-tenant `RoleBinding(Group → role)`.
- `templates/validatingadmissionpolicy.yaml` — two VAPs + bindings (rendered once).
- `templates/NOTES.txt` — per-tenant Tailscale grant block.
- `README.md` — onboarding runbook + one-time prereqs.

**New — cluster wiring (`clusters/ocp/remote-tenants/`):**
- `kustomization.yaml` — kustomize `helmCharts` inflator for the chart.
- `values.yaml` — cluster's `tenants:` list (starts empty + commented example).

**Modified:**
- `components/tailscale-operator/kustomization.yaml` — `apiServerProxyConfig.mode: "false"` → `"true"`.
- `clusters/ocp/values.yaml` — add the `remote-tenants` app-of-app entry (sync-wave 20).

---

## Task 1: Chart scaffold (metadata, values, helpers, test-values)

**Files:**
- Create: `.helm/charts/remote-tenant/Chart.yaml`
- Create: `.helm/charts/remote-tenant/values.yaml`
- Create: `.helm/charts/remote-tenant/test-values.yaml`
- Create: `.helm/charts/remote-tenant/templates/_helpers.tpl`

- [ ] **Step 1: Create `Chart.yaml`**

```yaml
apiVersion: v2
name: remote-tenant
version: 0.1.0
description: Per-user locked-down OpenShift namespace with guardrails (RBAC, NetworkPolicy, ResourceQuota, LimitRange, PSA, node-pinning, burst-node + secondary-network admission blocks), reachable over the tailnet via the Tailscale API-server proxy. Tenants are defined as a list in values.tenants.
type: application
kubeVersion: '>=1.30.0'
maintainers:
  - name: David Igou
```

- [ ] **Step 2: Create `values.yaml`**

```yaml
---
# remote-tenant — see README.md. Cluster tenants live in
# clusters/ocp/remote-tenants/values.yaml, not here.

# Prepended to each tenant.name to form the namespace. "" → namespace == name.
namespacePrefix: ""

defaults:
  # Pod Security Admission enforce level for the tenant namespace.
  psa: restricted
  # Node pinning — tenants run only on nodes carrying this label (hpg5, p330).
  # The master and the casval burst node do NOT carry it.
  nodeSelector: "node-role.kubernetes.io/tenant="
  # ClusterRole bound to the tenant's impersonated group:
  # remote-tenant-operator (custom, default) | edit | view.
  role: remote-tenant-operator
  # Allow openshift-monitoring to scrape tenant pods.
  allowMonitoring: false
  # CIDRs carved OUT of the allow-external-egress 0.0.0.0/0 rule — blocks the
  # pod network, service network, metadata IP, and RFC1918 (incl. the LAN).
  # Matches pac-tenant so the two charts agree.
  egressBlockedCIDRs:
    - 10.128.0.0/14
    - 172.30.0.0/16
    - 169.254.169.254/32
    - 192.168.0.0/16
    - 10.0.0.0/8
  quota:
    requests.cpu: "1"
    requests.memory: 2Gi
    limits.cpu: "2"
    limits.memory: 4Gi
    pods: "20"
    persistentvolumeclaims: "5"
    requests.storage: 20Gi
    services: "10"
    secrets: "30"
    configmaps: "30"
  limitRange:
    defaultRequest:
      cpu: 50m
      memory: 128Mi
    default:
      cpu: 500m
      memory: 512Mi
    max:
      cpu: "2"
      memory: 4Gi

# tenants — onboarded users. Each entry overrides any default; unspecified
# fields inherit. Schema:
#   - name: <slug>                  # required, ^[a-z0-9-]+$ → namespace name
#     members: [<tailnet-identity>] # informational → emitted grant block (NOTES)
#     grantGroup: <group>           # optional, default "<name>-operator"
#     role: edit|view|remote-tenant-operator   # optional
#     quota: { ... }                # optional, deep-merged
#     limitRange: { ... }           # optional
#     nodeSelector: "<k=v>"         # optional, override node pinning
#     allowMonitoring: true|false   # optional
#     egressBlockedCIDRs: [ ... ]   # optional
#     extraEgress:                  # optional — additive egress NetworkPolicies
#       - name: <netpol-name>
#         cidr: <cidr>              # XOR namespaceSelector/podSelector
#         # namespaceSelector: {matchLabels: {...}}
#         # podSelector: {matchLabels: {...}}
#         ports: [{port: <int>, protocol: TCP|UDP}]   # optional
#     extraIngress:                 # optional — additive ingress NetworkPolicies (same shape)
tenants: []
```

- [ ] **Step 3: Create `test-values.yaml`**

```yaml
---
tenants:
  - name: alice-dev
    members: ["alice@example.com"]
    extraEgress:
      - name: allow-pg
        cidr: 10.10.9.20/32
        ports:
          - port: 5432
            protocol: TCP
  - name: bob-view
    members: ["bob@example.com"]
    role: view
    allowMonitoring: true
```

- [ ] **Step 4: Create `templates/_helpers.tpl`**

```yaml
{{/*
remote-tenant.merged — per-tenant config with defaults merged underneath.
Per-tenant values win. Usage:
  {{- $cfg := include "remote-tenant.merged" (dict "root" . "tenant" $tenant) | fromYaml -}}
*/}}
{{- define "remote-tenant.merged" -}}
{{- $defaults := deepCopy .root.Values.defaults -}}
{{- $merged := mergeOverwrite $defaults (deepCopy .tenant) -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
remote-tenant.namespace — namespacePrefix + tenant.name.
*/}}
{{- define "remote-tenant.namespace" -}}
{{- printf "%s%s" .root.Values.namespacePrefix .tenant.name -}}
{{- end -}}

{{/*
remote-tenant.labels — applied to every resource the chart produces.
*/}}
{{- define "remote-tenant.labels" -}}
app.kubernetes.io/managed-by: helm
app.kubernetes.io/part-of: remote-tenants
igou.systems/remote-tenant: {{ .tenant.name | quote }}
{{- end -}}
```

- [ ] **Step 5: Lint the chart**

Run: `helm lint .helm/charts/remote-tenant`
Expected: `1 chart(s) linted, 0 chart(s) failed` (an info about no templates yet is fine).

- [ ] **Step 6: Commit**

```bash
git add .helm/charts/remote-tenant/Chart.yaml .helm/charts/remote-tenant/values.yaml .helm/charts/remote-tenant/test-values.yaml .helm/charts/remote-tenant/templates/_helpers.tpl
git commit -m "feat(remote-tenant): scaffold chart (metadata, values, helpers)"
```

---

## Task 2: Namespace template

**Files:**
- Create: `.helm/charts/remote-tenant/templates/namespace.yaml`

- [ ] **Step 1: Verify the test fails (template missing)**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/namespace.yaml`
Expected: FAIL — `Error: could not find template templates/namespace.yaml in chart`.

- [ ] **Step 2: Create `templates/namespace.yaml`**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "remote-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "remote-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
apiVersion: v1
kind: Namespace
metadata:
  name: {{ $ns | quote }}
  labels:
    igou.systems/tenant-type: remote-user
    pod-security.kubernetes.io/enforce: {{ $cfg.psa | quote }}
    security.openshift.io/scc.podSecurityLabelSync: "true"
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
  annotations:
    openshift.io/description: {{ printf "Remote tenant namespace for %s" (join ", " ($tenant.members | default (list $tenant.name))) | quote }}
    openshift.io/node-selector: {{ $cfg.nodeSelector | quote }}
    argocd.argoproj.io/sync-wave: "20"
{{- end }}
```

- [ ] **Step 3: Verify the test passes**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/namespace.yaml`
Expected: PASS — two Namespaces (`alice-dev`, `bob-view`), each with `igou.systems/tenant-type: remote-user`, `pod-security.kubernetes.io/enforce: restricted`, and annotation `openshift.io/node-selector: "node-role.kubernetes.io/tenant="`.

Assert: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/namespace.yaml | grep -c 'kind: Namespace'` → `2`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/remote-tenant/templates/namespace.yaml
git commit -m "feat(remote-tenant): namespace with PSA + node-selector pin"
```

---

## Task 3: ResourceQuota + LimitRange templates

**Files:**
- Create: `.helm/charts/remote-tenant/templates/resourcequota.yaml`
- Create: `.helm/charts/remote-tenant/templates/limitrange.yaml`

- [ ] **Step 1: Verify failing (templates missing)**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/resourcequota.yaml`
Expected: FAIL — `could not find template`.

- [ ] **Step 2: Create `templates/resourcequota.yaml`**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "remote-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "remote-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: tenant-quota
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  hard:
{{- range $key, $value := $cfg.quota }}
    {{ $key }}: {{ $value | quote }}
{{- end }}
{{- end }}
```

- [ ] **Step 3: Create `templates/limitrange.yaml`**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "remote-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "remote-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
apiVersion: v1
kind: LimitRange
metadata:
  name: tenant-limits
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  limits:
    - type: Container
      defaultRequest:
{{- toYaml $cfg.limitRange.defaultRequest | nindent 8 }}
      default:
{{- toYaml $cfg.limitRange.default | nindent 8 }}
      max:
{{- toYaml $cfg.limitRange.max | nindent 8 }}
{{- end }}
```

- [ ] **Step 4: Verify passing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/resourcequota.yaml`
Expected: PASS — two ResourceQuotas; `requests.cpu: "1"`, `requests.memory: "2Gi"`, `limits.cpu: "2"`, `limits.memory: "4Gi"`, `pods: "20"`.

Assert quota value: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/resourcequota.yaml | grep -E 'requests.cpu: "1"'` → matches.
Assert limitrange: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/limitrange.yaml | grep -c 'kind: LimitRange'` → `2`.

- [ ] **Step 5: Commit**

```bash
git add .helm/charts/remote-tenant/templates/resourcequota.yaml .helm/charts/remote-tenant/templates/limitrange.yaml
git commit -m "feat(remote-tenant): ResourceQuota + LimitRange from merged defaults"
```

---

## Task 4: NetworkPolicies template

**Files:**
- Create: `.helm/charts/remote-tenant/templates/networkpolicies.yaml`

- [ ] **Step 1: Verify failing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/networkpolicies.yaml`
Expected: FAIL — `could not find template`.

- [ ] **Step 2: Create `templates/networkpolicies.yaml`**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "remote-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "remote-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
# Default-deny all ingress and egress.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# Allow DNS to openshift-dns. OVN-K evaluates the egress port against the
# destination containerPort (post-NAT): dns-default exposes 53 → targetPort
# 5353, so 5353 must be allowed; 53 kept for any Service-bypass path.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-dns
      ports:
        - {port: 5353, protocol: UDP}
        - {port: 5353, protocol: TCP}
        - {port: 53, protocol: UDP}
        - {port: 53, protocol: TCP}
---
# Allow pods within the namespace to talk to each other.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-intra-namespace
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector: {}
  egress:
    - to:
        - podSelector: {}
---
# Allow external HTTPS/HTTP egress; carve out intra-cluster + LAN via except.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-egress
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            {{- with $cfg.egressBlockedCIDRs }}
            except:
              {{- range . }}
              - {{ . | quote }}
              {{- end }}
            {{- end }}
      ports:
        - {port: 443, protocol: TCP}
        - {port: 80, protocol: TCP}
{{- if $cfg.allowMonitoring }}
---
# Allow openshift-monitoring to scrape tenant pods.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-monitoring
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-monitoring
{{- end }}
{{- range $rule := ($tenant.extraEgress | default list) }}
{{- $peer := dict }}
{{- if $rule.cidr }}{{- $peer = dict "ipBlock" (dict "cidr" $rule.cidr) }}{{- else }}{{- if $rule.namespaceSelector }}{{- $peer = set $peer "namespaceSelector" $rule.namespaceSelector }}{{- end }}{{- if $rule.podSelector }}{{- $peer = set $peer "podSelector" $rule.podSelector }}{{- end }}{{- end }}
{{- if not $peer }}{{- fail (printf "extraEgress[%s] in tenant %s: set cidr OR (namespaceSelector and/or podSelector)" $rule.name $tenant.name) }}{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ $rule.name | quote }}
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - {{- toYaml $peer | nindent 10 }}
      {{- with $rule.ports }}
      ports:
        {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}
{{- range $rule := ($tenant.extraIngress | default list) }}
{{- $peer := dict }}
{{- if $rule.cidr }}{{- $peer = dict "ipBlock" (dict "cidr" $rule.cidr) }}{{- else }}{{- if $rule.namespaceSelector }}{{- $peer = set $peer "namespaceSelector" $rule.namespaceSelector }}{{- end }}{{- if $rule.podSelector }}{{- $peer = set $peer "podSelector" $rule.podSelector }}{{- end }}{{- end }}
{{- if not $peer }}{{- fail (printf "extraIngress[%s] in tenant %s: set cidr OR (namespaceSelector and/or podSelector)" $rule.name $tenant.name) }}{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ $rule.name | quote }}
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - {{- toYaml $peer | nindent 10 }}
      {{- with $rule.ports }}
      ports:
        {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}
{{- end }}
```

- [ ] **Step 3: Verify passing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/networkpolicies.yaml`
Expected: PASS. For `alice-dev`: `default-deny-all`, `allow-dns`, `allow-intra-namespace`, `allow-external-egress`, `allow-pg` (extraEgress). For `bob-view`: those four + `allow-from-monitoring` (allowMonitoring: true).

Assert DNS port: `... --show-only templates/networkpolicies.yaml | grep -c 'port: 5353'` → `2` (one per tenant).
Assert extra egress: `... --show-only templates/networkpolicies.yaml | grep -A2 'name: allow-pg' | grep '10.10.9.20/32'` → matches.
Assert monitoring only for bob: `... --show-only templates/networkpolicies.yaml | grep -c 'name: allow-from-monitoring'` → `1`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/remote-tenant/templates/networkpolicies.yaml
git commit -m "feat(remote-tenant): default-deny NetworkPolicies + dns/intra/external/monitoring/extra"
```

---

## Task 5: Custom `remote-tenant-operator` ClusterRole (rendered once)

**Files:**
- Create: `.helm/charts/remote-tenant/templates/clusterrole.yaml`

This template is NOT inside a `range` — it renders exactly once regardless of tenant count. It is the "edit-minus-guardrails" allowlist: full lifecycle on workloads, read-only on guardrails, nothing for RBAC / quota writes / secondary networks / cluster-scoped resources.

- [ ] **Step 1: Verify failing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/clusterrole.yaml`
Expected: FAIL — `could not find template`.

- [ ] **Step 2: Create `templates/clusterrole.yaml`**

```yaml
# Shared, cluster-scoped role bound per-namespace by rolebindings.yaml.
# Allowlist only — RBAC has no "subtract", so this is "edit minus guardrails".
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: remote-tenant-operator
  annotations:
    argocd.argoproj.io/sync-wave: "20"
  labels:
    app.kubernetes.io/managed-by: helm
    app.kubernetes.io/part-of: remote-tenants
rules:
  # --- Workloads: full lifecycle ---
  - apiGroups: [""]
    resources: [pods, pods/log, pods/exec, pods/portforward, pods/attach,
                services, endpoints, configmaps, secrets, persistentvolumeclaims,
                serviceaccounts, replicationcontrollers]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [apps]
    resources: [deployments, deployments/scale, replicasets, statefulsets, daemonsets]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [batch]
    resources: [jobs, cronjobs]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [apps.openshift.io]
    resources: [deploymentconfigs, deploymentconfigs/scale]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [route.openshift.io]
    resources: [routes, routes/custom-host]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [autoscaling]
    resources: [horizontalpodautoscalers]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [policy]
    resources: [poddisruptionbudgets]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  - apiGroups: [networking.k8s.io]
    resources: [ingresses]
    verbs: [get, list, watch, create, update, patch, delete, deletecollection]
  # --- Guardrails: read-only (can see, cannot widen) ---
  - apiGroups: [networking.k8s.io]
    resources: [networkpolicies]
    verbs: [get, list, watch]
  - apiGroups: [""]
    resources: [resourcequotas, limitranges]
    verbs: [get, list, watch]
  # --- Visibility ---
  - apiGroups: [""]
    resources: [events]
    verbs: [get, list, watch]
  - apiGroups: [metrics.k8s.io]
    resources: [pods]
    verbs: [get, list]
```

- [ ] **Step 3: Verify passing + exclusions**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/clusterrole.yaml`
Expected: PASS — exactly one ClusterRole `remote-tenant-operator`.

Assert it renders once: `... --show-only templates/clusterrole.yaml | grep -c 'kind: ClusterRole'` → `1`.
Assert NAD/UDN are NOT granted: `... --show-only templates/clusterrole.yaml | grep -E 'k8s.cni.cncf.io|k8s.ovn.org'` → no output (exit 1).
Assert no RBAC write: `... --show-only templates/clusterrole.yaml | grep 'rbac.authorization.k8s.io'` → no output.
Assert networkpolicies are read-only: confirm the `networkpolicies` rule lists only `get, list, watch`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/remote-tenant/templates/clusterrole.yaml
git commit -m "feat(remote-tenant): remote-tenant-operator ClusterRole (edit minus guardrails)"
```

---

## Task 6: RoleBinding template

**Files:**
- Create: `.helm/charts/remote-tenant/templates/rolebindings.yaml`

Binds the impersonated **Group** (`grantGroup`, default `<name>-operator`) to the configured ClusterRole (default `remote-tenant-operator`; `edit`/`view` honored via the merged `role`).

- [ ] **Step 1: Verify failing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/rolebindings.yaml`
Expected: FAIL — `could not find template`.

- [ ] **Step 2: Create `templates/rolebindings.yaml`**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "remote-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "remote-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
{{- $group := $tenant.grantGroup | default (printf "%s-operator" $tenant.name) }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ printf "%s-operator" $tenant.name | quote }}
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "remote-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {{ $cfg.role | quote }}
subjects:
  - apiGroup: rbac.authorization.k8s.io
    kind: Group
    name: {{ $group | quote }}
{{- end }}
```

- [ ] **Step 3: Verify passing + role override**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/rolebindings.yaml`
Expected: PASS — two RoleBindings. `alice-dev` → roleRef `remote-tenant-operator`, subject Group `alice-dev-operator`; `bob-view` → roleRef `view`, subject Group `bob-view-operator`.

Assert subject kind: `... --show-only templates/rolebindings.yaml | grep -c 'kind: Group'` → `2`.
Assert override: `... --show-only templates/rolebindings.yaml | grep -A2 'bob-view' | grep 'name: "view"'` (after the roleRef) — confirm bob's roleRef.name is `view`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/remote-tenant/templates/rolebindings.yaml
git commit -m "feat(remote-tenant): per-tenant RoleBinding(Group -> role)"
```

---

## Task 7: ValidatingAdmissionPolicies (no-burst + no-secondary-net)

**Files:**
- Create: `.helm/charts/remote-tenant/templates/validatingadmissionpolicy.yaml`

Two policies + bindings, rendered once. Bound to namespaces labeled `igou.systems/tenant-type: remote-user`. The burst policy is defense-in-depth alongside the node-selector pin (which already prevents casval scale-up because the casval template lacks the `tenant` label); the policy adds an immediate, clear admission denial.

- [ ] **Step 1: Verify failing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/validatingadmissionpolicy.yaml`
Expected: FAIL — `could not find template`.

- [ ] **Step 2: Create `templates/validatingadmissionpolicy.yaml`**

```yaml
# Rendered once. Scoped to remote-tenant namespaces via the bindings'
# namespaceSelector.
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: remote-tenant-no-burst
  annotations:
    argocd.argoproj.io/sync-wave: "20"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods", "replicationcontrollers"]
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
      - apiGroups: ["batch"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["jobs", "cronjobs"]
      - apiGroups: ["apps.openshift.io"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deploymentconfigs"]
  variables:
    - name: podSpec
      expression: >
        object.kind == 'Pod' ? object.spec :
        (object.kind == 'CronJob' ? object.spec.jobTemplate.spec.template.spec : object.spec.template.spec)
    - name: tolerations
      expression: "has(variables.podSpec.tolerations) ? variables.podSpec.tolerations : []"
    - name: nodeSelector
      expression: "has(variables.podSpec.nodeSelector) ? variables.podSpec.nodeSelector : {}"
    - name: affinityTerms
      expression: >
        (has(variables.podSpec.affinity) && has(variables.podSpec.affinity.nodeAffinity)
         && has(variables.podSpec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution)
         && has(variables.podSpec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms))
        ? variables.podSpec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms : []
  validations:
    - expression: >
        !variables.tolerations.exists(t,
          (!has(t.effect) || t.effect == '' || t.effect == 'NoSchedule') &&
          (
            ((has(t.operator) && t.operator == 'Exists') && (!has(t.key) || t.key == '' || t.key == 'workload'))
            ||
            ((!has(t.operator) || t.operator == '' || t.operator == 'Equal') && has(t.key) && t.key == 'workload' && has(t.value) && t.value == 'burst')
          )
        )
      reason: Forbidden
      message: "remote tenants may not tolerate the burst taint (workload=burst:NoSchedule)"
    - expression: "!('node-role.kubernetes.io/burst' in variables.nodeSelector)"
      reason: Forbidden
      message: "remote tenants may not target the burst node via nodeSelector"
    - expression: >
        !variables.affinityTerms.exists(term,
          (has(term.matchExpressions) && term.matchExpressions.exists(e, e.key == 'node-role.kubernetes.io/burst')) ||
          (has(term.matchFields) && term.matchFields.exists(f, f.key == 'node-role.kubernetes.io/burst'))
        )
      reason: Forbidden
      message: "remote tenants may not target the burst node via nodeAffinity"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: remote-tenant-no-burst
  annotations:
    argocd.argoproj.io/sync-wave: "21"
spec:
  policyName: remote-tenant-no-burst
  validationActions: ["Deny"]
  matchResources:
    namespaceSelector:
      matchLabels:
        igou.systems/tenant-type: remote-user
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: remote-tenant-no-secondary-net
  annotations:
    argocd.argoproj.io/sync-wave: "20"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["k8s.cni.cncf.io"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["network-attachment-definitions"]
      - apiGroups: ["k8s.ovn.org"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["userdefinednetworks"]
  validations:
    - expression: "false"
      reason: Forbidden
      message: "remote tenants may not create NetworkAttachmentDefinitions or UserDefinedNetworks (secondary networks bypass NetworkPolicy isolation)"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: remote-tenant-no-secondary-net
  annotations:
    argocd.argoproj.io/sync-wave: "21"
spec:
  policyName: remote-tenant-no-secondary-net
  validationActions: ["Deny"]
  matchResources:
    namespaceSelector:
      matchLabels:
        igou.systems/tenant-type: remote-user
```

- [ ] **Step 3: Verify passing**

Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml --show-only templates/validatingadmissionpolicy.yaml`
Expected: PASS — two `ValidatingAdmissionPolicy` + two `ValidatingAdmissionPolicyBinding`.

Assert counts: `... --show-only templates/validatingadmissionpolicy.yaml | grep -c 'kind: ValidatingAdmissionPolicy$'` → `2`; `grep -c 'kind: ValidatingAdmissionPolicyBinding'` → `2`.
Assert binding selector: `... | grep -c 'igou.systems/tenant-type: remote-user'` → `2`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/remote-tenant/templates/validatingadmissionpolicy.yaml
git commit -m "feat(remote-tenant): VAPs blocking burst opt-in and secondary-net creation"
```

---

## Task 8: NOTES.txt + chart README

**Files:**
- Create: `.helm/charts/remote-tenant/templates/NOTES.txt`
- Create: `.helm/charts/remote-tenant/README.md`

- [ ] **Step 1: Create `templates/NOTES.txt`**

```
{{- if .Values.tenants }}
remote-tenant rendered {{ len .Values.tenants }} tenant namespace(s).

For EACH tenant: (1) add the grant below to the Tailscale ACL policy
(admin console -> Access controls -> "grants" array), and (2) ensure the
worker pool is labeled (one-time): see README.md.
{{ range $tenant := .Values.tenants }}
{{- $ns := include "remote-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $group := $tenant.grantGroup | default (printf "%s-operator" $tenant.name) }}
== {{ $tenant.name }}  (namespace: {{ $ns }}) ==
  {
    "src": [{{ range $i, $m := ($tenant.members | default list) }}{{ if $i }}, {{ end }}{{ $m | quote }}{{ end }}],
    "dst": ["tag:k8s-operator"],
    "app": { "tailscale.com/cap/kubernetes": [ { "impersonate": { "groups": [{{ $group | quote }}] } } ] }
  }
  user: tailscale configure kubeconfig tailscale-operator && oc -n {{ $ns }} get pods
{{ end }}
{{- end }}
```

- [ ] **Step 2: Create `README.md`**

```markdown
# remote-tenant

Per-user, locked-down OpenShift namespace reachable over the tailnet via the
Tailscale API-server proxy. Each tenant gets a Namespace + ResourceQuota +
LimitRange + default-deny NetworkPolicies + a `RoleBinding(group -> role)`,
pinned to the `hpg5`/`p330` worker pool. Two shared, once-rendered resources:
the `remote-tenant-operator` ClusterRole and the `remote-tenant-no-burst` /
`remote-tenant-no-secondary-net` ValidatingAdmissionPolicies.

See the design spec: `docs/superpowers/specs/2026-06-13-remote-tenant-access-design.md`.

## One-time cluster prerequisites

1. Enable the Tailscale API-server proxy (set in
   `components/tailscale-operator/kustomization.yaml`: `apiServerProxyConfig.mode: "true"`).
2. Label the tenant worker pool:
   ```
   oc label node hpg5.igou.systems node-role.kubernetes.io/tenant=""
   oc label node p330.igou.systems node-role.kubernetes.io/tenant=""
   ```

## Onboarding a tenant

1. Add an entry to `clusters/ocp/remote-tenants/values.yaml` under `tenants:`
   (see the schema in `values.yaml`). Open a PR; ArgoCD syncs the namespace,
   guardrails, and RoleBinding.
2. Add the grant block printed by the chart NOTES (or below) to the Tailscale
   ACL policy in the admin console:
   ```json
   { "src": ["alice@example.com"], "dst": ["tag:k8s-operator"],
     "app": { "tailscale.com/cap/kubernetes": [ { "impersonate": { "groups": ["alice-dev-operator"] } } ] } }
   ```
   The impersonated group MUST equal the tenant's `grantGroup` (default
   `<name>-operator`).
3. The user runs:
   ```
   tailscale up
   tailscale configure kubeconfig tailscale-operator
   oc -n alice-dev get pods
   ```

## Offboarding

Remove the grant (immediate API cut-off) and the `tenants:` entry (ArgoCD
prunes the namespace).

## Optional: kubectl session recording

Add `"recorder": ["tag:tsrecorder"], "enforceRecorder": true` to the grant and
deploy a `Recorder` CR to record all kubectl/exec/API sessions.
```

- [ ] **Step 3: Lint + render sanity**

Run: `helm lint .helm/charts/remote-tenant`
Expected: `0 chart(s) failed`.
Run: `helm template remote-tenants .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml >/dev/null && echo OK`
Expected: `OK` (full chart renders without error).

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/remote-tenant/templates/NOTES.txt .helm/charts/remote-tenant/README.md
git commit -m "docs(remote-tenant): NOTES grant block + chart README"
```

---

## Task 9: Cluster wiring (kustomize inflator + cluster values)

**Files:**
- Create: `clusters/ocp/remote-tenants/kustomization.yaml`
- Create: `clusters/ocp/remote-tenants/values.yaml`

- [ ] **Step 1: Create `clusters/ocp/remote-tenants/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

helmGlobals:
  chartHome: ../../../.helm/charts

helmCharts:
  - name: remote-tenant
    releaseName: remote-tenants
    valuesFile: values.yaml
    includeCRDs: false
```

- [ ] **Step 2: Create `clusters/ocp/remote-tenants/values.yaml`**

Start with no tenants — the first sync establishes the shared ClusterRole + VAPs; tenants are added later via PR.

```yaml
---
# Remote-access tenants for the OCP cluster.
# Schema and defaults: see .helm/charts/remote-tenant/values.yaml
#
# Each tenant also needs a one-time Tailscale ACL grant (impersonate group
# "<name>-operator") — see the chart NOTES / README.
#
# Example:
# tenants:
#   - name: alice-dev
#     members: ["alice@example.com"]
#     # role: view
#     # extraEgress:
#     #   - { name: allow-pg, cidr: 10.10.9.20/32, ports: [{ port: 5432, protocol: TCP }] }
tenants: []
```

- [ ] **Step 3: Verify the kustomization inflates the chart**

Run: `kustomize build clusters/ocp/remote-tenants --enable-helm`
Expected: PASS — renders the `remote-tenant-operator` ClusterRole + the two VAPs + two bindings (no per-tenant resources, since `tenants: []`).

Assert: `kustomize build clusters/ocp/remote-tenants --enable-helm | grep -c 'kind: ValidatingAdmissionPolicy$'` → `2`.

- [ ] **Step 4: Temporarily validate per-tenant rendering through kustomize**

Run: `kustomize build clusters/ocp/remote-tenants --enable-helm --load-restrictor LoadRestrictionsNone >/dev/null && echo OK` (sanity).
Then verify the repo schema gate passes:
Run: `make validate-kustomize`
Expected: builds all kustomizations (including the new one) with no error.
Run: `make validate-schemas`
Expected: kubeconform passes (use the repo's existing missing-schema handling for CRD-only kinds; built-in kinds here — Namespace/Quota/LimitRange/NetworkPolicy/ClusterRole/RoleBinding/VAP — validate against the bundled schemas).

- [ ] **Step 5: Lint YAML**

Run: `make lint`
Expected: yamllint passes for the new files.

- [ ] **Step 6: Commit**

```bash
git add clusters/ocp/remote-tenants/kustomization.yaml clusters/ocp/remote-tenants/values.yaml
git commit -m "feat(remote-tenant): wire chart into clusters/ocp via kustomize helmCharts"
```

---

## Task 10: Enable the API-server proxy + app-of-app entry

**Files:**
- Modify: `components/tailscale-operator/kustomization.yaml` (the `apiServerProxyConfig.mode` line)
- Modify: `clusters/ocp/values.yaml` (add the `remote-tenants` app entry)

- [ ] **Step 1: Verify the auth-proxy is currently absent**

Run: `kustomize build components/tailscale-operator --enable-helm | grep -c 'name: tailscale-auth-proxy'`
Expected: `0` (proxy disabled — `mode: "false"`).

- [ ] **Step 2: Flip the proxy mode**

In `components/tailscale-operator/kustomization.yaml`, under `helmCharts[0].valuesInline.apiServerProxyConfig`, change:

```yaml
    apiServerProxyConfig:
      mode: "false" # "true", "false", "noauth"
```

to:

```yaml
    apiServerProxyConfig:
      mode: "true" # "true" = operator authenticates the tailnet identity and impersonates it (grants -> k8s groups)
```

- [ ] **Step 3: Verify the auth-proxy now renders**

Run: `kustomize build components/tailscale-operator --enable-helm | grep -c 'name: tailscale-auth-proxy'`
Expected: `>= 1` — the `tailscale-auth-proxy` ClusterRole (impersonate users/groups) + its ClusterRoleBinding now render.

- [ ] **Step 4: Add the app-of-app entry**

In `clusters/ocp/values.yaml`, add a `remote-tenants` entry alongside the other apps (mirror the existing `pac-tenants` entry; sync-wave 20):

```yaml
  remote-tenants:
    annotations:
      argocd.argoproj.io/compare-options: IgnoreExtraneous
      argocd.argoproj.io/sync-wave: '20'
    source:
      path: clusters/ocp/remote-tenants
```

- [ ] **Step 5: Validate**

Run: `make validate-kustomize`
Expected: PASS (the app-of-app for `clusters/ocp` builds with the new entry).
Run: `make lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add components/tailscale-operator/kustomization.yaml clusters/ocp/values.yaml
git commit -m "feat(remote-tenant): enable Tailscale API-server proxy + add remote-tenants app"
```

---

## Task 11: Manual bootstrap & functional verification (live cluster)

No code — operational steps to run once the branch is merged/synced. Record results.

- [ ] **Step 1: Label the tenant worker pool**

```bash
oc label node hpg5.igou.systems node-role.kubernetes.io/tenant=""
oc label node p330.igou.systems node-role.kubernetes.io/tenant=""
oc get nodes -L node-role.kubernetes.io/tenant
```
Expected: `hpg5` and `p330` show the `tenant` role; `ocp` (master) and `casval` do not.

- [ ] **Step 2: Onboard a test tenant**

Add to `clusters/ocp/remote-tenants/values.yaml` and sync:
```yaml
tenants:
  - name: rt-smoke
    members: ["<your-tailnet-identity>"]
```
Sync the `remote-tenants` Application (e.g. `argocd app sync remote-tenants` or via UI). Confirm the namespace + guardrails exist:
```bash
oc get ns rt-smoke -o jsonpath='{.metadata.annotations.openshift\.io/node-selector}{"\n"}'   # node-role.kubernetes.io/tenant=
oc -n rt-smoke get resourcequota,limitrange,networkpolicy,rolebinding
```

- [ ] **Step 3: Add the Tailscale grant**

Paste into the admin console ACL `grants` array (from the chart NOTES):
```json
{ "src": ["<your-tailnet-identity>"], "dst": ["tag:k8s-operator"],
  "app": { "tailscale.com/cap/kubernetes": [ { "impersonate": { "groups": ["rt-smoke-operator"] } } ] } }
```

- [ ] **Step 4: Connect and verify scoped access**

```bash
tailscale configure kubeconfig tailscale-operator
oc -n rt-smoke get pods          # works
oc get nodes                     # Forbidden
oc -n openshift-config get cm    # Forbidden (other namespace)
oc -n rt-smoke edit networkpolicy default-deny-all   # Forbidden (guardrail read-only)
```

- [ ] **Step 5: Verify guardrail admission denials**

Test manifests are PSA-`restricted`-compliant (non-root, drop ALL caps, seccomp RuntimeDefault) so the VAP/quota — not Pod Security — is what denies. Run (a) and (c) as the **tenant** (the tailnet kubeconfig); for (b) note the two layers.

```bash
# (a) burst toleration -> denied by remote-tenant-no-burst (RBAC allows the
#     Deployment; the VAP rejects the toleration), as the TENANT:
cat <<'EOF' | oc -n rt-smoke apply --dry-run=server -f - 2>&1 | grep -i "burst taint"
apiVersion: apps/v1
kind: Deployment
metadata: { name: burst-test }
spec:
  replicas: 1
  selector: { matchLabels: { app: burst-test } }
  template:
    metadata: { labels: { app: burst-test } }
    spec:
      tolerations: [{ key: workload, value: burst, effect: NoSchedule }]
      containers:
        - name: c
          image: registry.access.redhat.com/ubi9/ubi-minimal
          command: ["sleep", "infinity"]
          securityContext:
            allowPrivilegeEscalation: false
            runAsNonRoot: true
            capabilities: { drop: ["ALL"] }
            seccompProfile: { type: RuntimeDefault }
EOF

# (b) NetworkAttachmentDefinition is blocked at BOTH layers:
#   as the TENANT -> RBAC denies first (role omits k8s.cni.cncf.io):
cat <<'EOF' | oc -n rt-smoke apply --dry-run=server -f - 2>&1 | grep -iE "forbidden|cannot create"
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata: { name: rt-smoke-nad }
spec: { config: '{"cniVersion":"0.3.1","type":"macvlan"}' }
EOF
#   as a CLUSTER-ADMIN (override-proof VAP layer; use your admin kubeconfig):
cat <<'EOF' | KUBECONFIG=<admin-kubeconfig> oc -n rt-smoke apply --dry-run=server -f - 2>&1 | grep -i "may not create NetworkAttachmentDefinitions"
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata: { name: rt-smoke-nad }
spec: { config: '{"cniVersion":"0.3.1","type":"macvlan"}' }
EOF

# (c) over-quota pod -> rejected by ResourceQuota (requests > 1 cpu / 2Gi), as the TENANT:
oc -n rt-smoke run toobig --restart=Never --image=registry.access.redhat.com/ubi9/ubi-minimal \
  --overrides='{"spec":{"containers":[{"name":"toobig","image":"registry.access.redhat.com/ubi9/ubi-minimal","command":["sleep","infinity"],"resources":{"requests":{"cpu":"4","memory":"16Gi"}},"securityContext":{"allowPrivilegeEscalation":false,"runAsNonRoot":true,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}' \
  2>&1 | grep -i "exceeded quota"
```
Expected: (a) prints the burst-taint denial; (b) tenant → `forbidden`/`cannot create` (RBAC), admin → the secondary-net VAP message; (c) prints `exceeded quota`.

- [ ] **Step 6: Confirm casval stayed down**

```bash
oc -n openshift-cluster-api get machineset casval-worker -o jsonpath='{.spec.replicas}{"\n"}'   # 0
```
Expected: `0` — no tenant action triggered a burst node.

- [ ] **Step 7: Tear down the smoke tenant**

Remove the `rt-smoke` entry from `clusters/ocp/remote-tenants/values.yaml`, sync (ArgoCD prunes the namespace), and remove the grant from the Tailscale ACL.

- [ ] **Step 8: Commit any values changes (if a real first tenant is being added)**

```bash
git add clusters/ocp/remote-tenants/values.yaml
git commit -m "feat(remote-tenant): onboard <tenant>"   # only if keeping a real tenant
```

---

## Self-Review

- **Spec coverage:** §4 proxy enable → Task 10; §5.1 namespace/quota/limit/netpol → Tasks 2-4; §5.2 custom role → Task 5; §5.3 values schema → Task 1; §5.4 NOTES → Task 8; §5.5 burst VAP → Task 7 + verified Task 11; §5.6 node-selector pin → Task 2 (annotation) + Task 11 (labels); §5.7 secondary-net VAP → Task 7 + verified Task 11; §6 grant → Task 8/11; §8 layout → all; §9 onboarding → README; §11 testing → per-task asserts + Task 11.
- **Placeholders:** none — every template is complete; `<your-tailnet-identity>` / `<tenant>` in Task 11 are operator inputs, not code placeholders.
- **Type/name consistency:** helper names (`remote-tenant.merged/.namespace/.labels`), the `igou.systems/tenant-type: remote-user` label (namespace + VAP bindings), the `node-role.kubernetes.io/tenant=` selector (values default + namespace annotation + node labels), `grantGroup` default `<name>-operator` (rolebinding subject + NOTES grant), and ClusterRole name `remote-tenant-operator` (clusterrole + rolebinding default role) all match across tasks.
