# Remote, locked-down OpenShift namespace access via Tailscale + GitOps

- **Date:** 2026-06-13
- **Status:** Approved design — ready for implementation plan
- **Repo:** `igou-openshift` (single-master OpenShift, `ocp.igou.systems`; control-plane on the MS-01, plus an on-demand CAPI burst worker `casval` scaled 0→1). `rosa-gitops` untouched.
- **Cluster GitOps:** ArgoCD app-of-apps (admin instance, `openshift-gitops`).

## 1. Problem & goals

Give **trusted users** remote `oc`/`kubectl` access to a **single OpenShift namespace**, reachable **only over the tailnet**, with **default, manageable, configurable guardrails** — default permissions, NetworkPolicies, ResourceQuota, LimitRange, PSA — that users cannot widen and that ArgoCD self-heals.

**Goals**

- Kube API access scoped to one namespace per user, gated by RBAC.
- No public API surface; access only via the existing Tailscale tailnet.
- Per-tenant guardrails with sane defaults, overridable per tenant, all in git.
- Onboarding is GitOps-first (a values entry) plus one copy-paste tailnet grant.
- Native to `igou-openshift` conventions (mirrors the existing `pac-tenant` chart).
- A clean, additive path to expose namespace **apps** on the tailnet later (no redesign).
- Guarantee tenants cannot trigger provisioning of the on-demand `casval` burst node (see §5.5).
- Keep tenant workloads on the labeled worker pool (`hpg5`, `p330`), off the master and off `casval` (see §5.6).
- Prevent tenants from attaching to secondary networks (NAD/UDN) that would bypass NetworkPolicy isolation (see §5.7).

**Non-goals (this iteration)**

- App/service network exposure (designed-for, not built — see §7).
- Policy-as-code for the tailnet ACL (documented upgrade path — see §10).
- HA API-server proxy (single-instance is fine for this single-master cluster — see §10).
- Standing OpenShift user accounts / IdP integration (identity is the Tailscale identity).

## 2. Architecture — two cooperating control planes

```
 user laptop ──tailnet──► Tailscale API-server proxy ──Impersonate-Group──► OpenShift apiserver ──RBAC──► ns <name>
   oc/kubectl   WireGuard   (operator, mode:"true",      <name>-operator                    RoleBinding(group→role)
                            tag:k8s-operator)                                               + Quota·LimitRange·NetPol·PSA
```

- **Control plane #1 — in-cluster (`igou-openshift` git → ArgoCD):** the operator config flip (§4), and the per-tenant guardrail bundle + `RoleBinding(group → role)` (§5). This is the `remote-tenant` Helm chart.
- **Control plane #2 — tailnet policy (Tailscale admin console, manual):** the `grant` mapping a Tailscale user/group → the impersonated OpenShift group (§6). The chart **emits the exact grant block** so this is copy-paste, never hand-authored.

**Join key:** the **group name** (default `<name>-operator`). The grant impersonates it; the RoleBinding binds it. Mismatch ⇒ authenticated but zero RBAC (deny by default).

### How impersonation works (verified against Tailscale docs)

When `apiServerProxyConfig.mode: "true"`, the operator authenticates the Tailscale identity and forwards requests to the kube-apiserver with impersonation headers. For a **user device** the request is impersonated as the Tailscale user (e.g. `alice@example.com`) plus any groups defined in the grant; for a **tagged device**, as the node FQDN with its tags as groups. The chart's `tailscale-auth-proxy` ClusterRole grants the operator SA `impersonate` on `users`/`groups`, so **no extra RBAC is needed** to enable this. Impersonated identities need **no OpenShift `User`/`Identity` object** — RBAC is evaluated purely on the impersonated user + group.

## 3. Defaults at a glance

| Knob | Default | Override |
|---|---|---|
| PSA enforce | `restricted` | per-tenant `psa:` |
| ResourceQuota | req cpu `1` / mem `2Gi`, lim cpu `2` / mem `4Gi`, pods `20`, pvc `5`, `requests.storage 20Gi`, services `10`, secrets/configmaps `30` | per-tenant `quota:` (deep-merge) |
| LimitRange (Container) | defaultRequest `50m`/`128Mi`, default `500m`/`512Mi`, max `2`/`4Gi` | per-tenant `limitRange:` |
| Default role | `remote-tenant-operator` (custom, §5) | per-tenant `role: edit\|view\|remote-tenant-operator` |
| Egress | `default-deny` + DNS + intra-ns + external `443/80` minus `egressBlockedCIDRs` | `extraEgress`, `extraIngress`, `egressBlockedCIDRs` |
| Monitoring scrape | off | per-tenant `allowMonitoring: true` |
| Session recording | off | grant-level (§6) |
| Burst-node containment | VAP `remote-tenant-no-burst` forbids the burst toleration / nodeSelector / affinity | stricter: forbid all user tolerations |
| Node placement | namespace pinned via `openshift.io/node-selector` to `node-role.kubernetes.io/tenant=` (hpg5, p330); never master/casval | per-tenant `nodeSelector:` |
| Secondary networks | forbidden — no NAD/UDN creation (role allowlist + VAP `remote-tenant-no-secondary-net`) | n/a |

## 4. Layer 1 — enable the API-server proxy

**Change:** `components/tailscale-operator/kustomization.yaml`, in the operator chart's `valuesInline`:

```yaml
apiServerProxyConfig:
  mode: "true"   # was "false"
```

This makes the chart render `ServiceAccount/kube-apiserver-auth-proxy`, `ClusterRole/tailscale-auth-proxy` (`impersonate` on `users`,`groups`), and the `ClusterRoleBinding` to the operator SA. The proxy is advertised at the operator hostname (`tailscale-operator`).

**Safety:** enabling the proxy grants **nobody** anything — access requires both a tailnet grant **and** a matching in-cluster RoleBinding. No public endpoint is created.

**HA upgrade path (documented, not built):** deploy a `ProxyGroup` of `spec.type: kube-apiserver` and set `apiServerProxyConfig.allowImpersonation: "true"` to move the proxy off the operator pod.

## 5. Layer 2 — the `remote-tenant` Helm chart

New chart `.helm/charts/remote-tenant/`, following `pac-tenant` conventions: `range` over `.Values.tenants`, a `remote-tenant.merged` defaults helper, a `remote-tenant.labels` helper, `argocd.argoproj.io/sync-wave` annotations, and `<name>-<kind>.yaml` file naming.

### 5.1 Per-tenant resources

**Namespace** (`<name>`, wave 20):

```yaml
metadata:
  name: <name>
  labels:
    igou.systems/tenant-type: remote-user
    pod-security.kubernetes.io/enforce: restricted
    security.openshift.io/scc.podSecurityLabelSync: "true"
  annotations:
    openshift.io/description: "Remote tenant namespace for <members>"
    openshift.io/node-selector: "node-role.kubernetes.io/tenant="   # pin to labeled worker pool (hpg5, p330); never master/casval
    argocd.argoproj.io/sync-wave: "20"
```

**ResourceQuota** `tenant-quota` (wave 21) and **LimitRange** `tenant-limits` (wave 21): rendered from the merged defaults exactly like `pac-tenant`'s `resourcequota.yaml`/`limitrange.yaml`.

**NetworkPolicies** (wave 21):

- `default-deny-all` — `podSelector: {}`, `policyTypes: [Ingress, Egress]`.
- `allow-dns` — egress to `openshift-dns`, ports `5353` and `53` (UDP+TCP). Reuses the existing OVN-K post-NAT targetPort note from `pac-tenant`.
- `allow-intra-namespace` — `ingress: [{from: [{podSelector: {}}]}]` and `egress: [{to: [{podSelector: {}}]}]` so pods in the namespace can talk to each other.
- `allow-external-egress` — egress to `0.0.0.0/0` (with `except: egressBlockedCIDRs`), ports `443`/`80`.
- `allow-from-monitoring` *(only if `allowMonitoring: true`)* — ingress from `openshift-monitoring`.
- `extraEgress` / `extraIngress` — per-tenant additive rules (reuse `pac-tenant`'s `extraEgress` peer-builder: `cidr` XOR `namespaceSelector`/`podSelector`, optional `ports`).

**RoleBinding** `<name>-operator` (wave 21):

```yaml
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: <role> }   # default remote-tenant-operator
subjects:
  - apiGroup: rbac.authorization.k8s.io
    kind: Group
    name: <grantGroup>   # default "<name>-operator" — the impersonated group
```

### 5.2 Shared custom ClusterRole `remote-tenant-operator`

Rendered **once** (cluster-scoped, wave 20), reused by all tenants via per-namespace RoleBindings. RBAC cannot "subtract" from a built-in role, so this is an explicit allow-list = "`edit` minus the guardrails."

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: remote-tenant-operator
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

**Deliberately excluded:** writing `networkpolicies`/`resourcequotas`/`limitranges`, secondary-network resources (`k8s.cni.cncf.io` NetworkAttachmentDefinitions, `k8s.ovn.org` UserDefinedNetworks), all of `rbac.authorization.k8s.io` (roles/rolebindings), `namespaces`, and every cluster-scoped resource. A tenant can run and operate workloads but cannot widen guardrails, grant themselves access, or see other namespaces. (Optional stricter variant: drop `pods/exec`+`pods/portforward` — left in by default to match `edit` ergonomics.)

> Note: `build.openshift.io`/`image.openshift.io` are intentionally omitted by default (this cluster's image builds run via the PaC tenants, not remote users). Add per need.

### 5.3 `values.yaml` schema

```yaml
defaults:
  psa: restricted
  nodeSelector: "node-role.kubernetes.io/tenant="   # pin tenants to the labeled worker pool (hpg5, p330)
  role: remote-tenant-operator
  allowMonitoring: false
  egressBlockedCIDRs: ["10.10.0.0/16"]   # block LAN by default; external 443/80 still allowed
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
    defaultRequest: { cpu: 50m, memory: 128Mi }
    default: { cpu: 500m, memory: 512Mi }
    max: { cpu: "2", memory: 4Gi }

tenants:
  - name: alice-dev
    members: ["alice@example.com"]      # informational → feeds the emitted grant block
    grantGroup: alice-dev-operator      # defaults to "<name>-operator" if omitted
    # role: view                        # optional: built-in view/edit instead of custom
    # quota: { pods: "40" }             # optional deep-merge override
    # extraEgress:
    #   - { name: allow-pg, cidr: 10.10.9.20/32, ports: [{ port: 5432, protocol: TCP }] }
```

### 5.4 `NOTES.txt`

Prints, per tenant, the exact grant block to paste (see §6), so the manual tailnet step is copy-paste.

### 5.5 Burst-node containment — tenants cannot provision `casval`

**Context.** `MachineSet/casval-worker` (Metal3, `openshift-cluster-api`) sits at `replicas: 0`. A dedicated CAPI cluster-autoscaler (`--cloud-provider=clusterapi`, node-group min `0` / max `1`) provisions the bare-metal `casval` host (≈192 vCPU / 428 GiB / 2× NVIDIA GPU, powered on via Metal3 BMC) **only when a Pending pod would fit its synthetic node template** — and that template carries taint `workload=burst:NoSchedule` and labels `node-role.kubernetes.io/burst=`,`node-role.kubernetes.io/worker=`. Therefore the autoscaler scales 0→1 **only for a pod that tolerates `workload=burst`**; a pod without that toleration neither fits the template nor passes the live taint. Real burst workloads (llmkube, ollama) opt in with `nodeSelector: node-role.kubernetes.io/burst: ""` + the matching toleration.

**Threat.** A tenant with workload-create rights could add `tolerations: [{key: workload, value: burst}]` (or a blanket `operator: Exists`), plus a large request / anti-affinity making the pod unschedulable on the master, and trigger a 0→1 power-on of `casval`.

**Control (defense in depth):**

1. **ValidatingAdmissionPolicy `remote-tenant-no-burst`** — built-in (OCP 4.21 / k8s 1.34 → GA, no operator needed), rendered **once** by the chart and bound via `namespaceSelector: igou.systems/tenant-type: remote-user`, so every tenant namespace is covered automatically. It **denies** create/update of Pods and pod-templated workloads (`apps` Deployment/ReplicaSet/StatefulSet/DaemonSet, `batch` Job/CronJob, core ReplicationController/Pod, `apps.openshift.io` DeploymentConfig) whose effective pod spec:
   - carries a toleration that would tolerate `workload=burst:NoSchedule` — `key == "workload"` with `value == "burst"` or `operator == "Exists"`, **or** a blanket toleration (empty/unset `key` with `operator == "Exists"`); **or**
   - targets the burst node via `nodeSelector["node-role.kubernetes.io/burst"]`, or a `nodeAffinity` `requiredDuringSchedulingIgnoredDuringExecution` term referencing that key.

   A CEL `variable` normalizes the pod-spec path across kinds (`spec`, `spec.template.spec`, `spec.jobTemplate.spec.template.spec`). Binding to the controllers gives immediate rejection at `oc apply`; binding to bare Pods is defense-in-depth. *(Configurable stricter variant: forbid all user-supplied tolerations in tenant namespaces — the standard `not-ready`/`unreachable` tolerations are injected by the system **after** admission, so normal scheduling is unaffected.)*
2. **Live taint (already in place):** `workload=burst:NoSchedule` on `casval` repels any pod lacking the toleration, so the no-toleration case is safe even without the policy; the VAP closes the deliberate-opt-in path.
3. **ResourceQuota backstop (§5.1):** default per-tenant limits (cpu `2` / mem `4Gi`) are far below what would require `casval`, so a tenant cannot even create a pod large enough to be unschedulable on the master and thus "need" a burst node.

**Net:** a remote tenant cannot tolerate, select, or size their way onto `casval`, so they cannot cause a burst-node power-on.

### 5.6 Node placement — tenants run on the labeled worker pool (`hpg5`, `p330`), never master or `casval`

The chart sets `openshift.io/node-selector: "<nodeSelector>"` (default `node-role.kubernetes.io/tenant=`) on each tenant Namespace. OpenShift's built-in **NodeSelector admission** merges this selector into every pod in the namespace and rejects pods that try to override it with a conflicting value, so all tenant workloads are confined to nodes carrying that label — they **cannot** run on the master (`ocp`, unlabeled) or on `casval` (burst, unlabeled). If no labeled node has room, tenant pods stay `Pending` rather than spilling onto the control plane (the safer posture for locked-down tenants, per the "off master" requirement).

**One-time cluster prerequisite** (documented in the chart README, like the tailnet grant): label the always-on worker(s) —

```
oc label node hpg5.igou.systems node-role.kubernetes.io/tenant=""
oc label node p330.igou.systems node-role.kubernetes.io/tenant=""
```

Add the same label to any future tenant-eligible worker; remove it to drain tenants off a node. The label is intentionally **absent** from `casval`, so node placement and burst containment (§5.5) reinforce each other — a tenant pod can never be scheduled onto, and therefore never trigger, the burst node. Per-tenant override: set `nodeSelector:` in a tenant entry to target a different pool.

### 5.7 Forbid secondary-network attachment (NADs / UDNs)

Secondary networks attach pods to interfaces **outside** the primary OVN-Kubernetes network — and the default-deny NetworkPolicy (§5.1) only governs the primary network. A tenant who could create a `NetworkAttachmentDefinition` (Multus macvlan/ipvlan/VLAN-trunk, as used across `test-workloads/`) or a `UserDefinedNetwork` could bridge onto the LAN/VLANs and sidestep that isolation. Tenants are therefore blocked from creating them, two ways:

1. **RBAC (default):** the custom `remote-tenant-operator` allowlist omits `k8s.cni.cncf.io` and `k8s.ovn.org`, and built-in `edit`/`view` don't grant them either — so no tenant can create a NAD/UDN out of the box.
2. **Admission guard (override-proof):** a second policy in the chart's VAP template — `remote-tenant-no-secondary-net`, bound by the same `igou.systems/tenant-type: remote-user` namespaceSelector — **denies** create/update of `NetworkAttachmentDefinition` (`k8s.cni.cncf.io`) and namespaced `UserDefinedNetwork` (`k8s.ovn.org`) in tenant namespaces. This holds even if a tenant is later granted `admin`/`edit` or those verbs get aggregated into a built-in role.

(Cluster-scoped `ClusterUserDefinedNetwork` is already unreachable — the custom role grants nothing cluster-scoped.)

## 6. Layer 3 — tailnet grant (manual)

Paste into the Tailscale admin console ACL editor per tenant:

```json
{
  "src": ["alice@example.com"],
  "dst": ["tag:k8s-operator"],
  "app": {
    "tailscale.com/cap/kubernetes": [
      { "impersonate": { "groups": ["alice-dev-operator"] } }
    ]
  }
}
```

`src` may be a user or a `group:` from the tailnet policy. `dst` is the operator tag (`tag:k8s-operator`, already this operator's `defaultTags`). Optional audit hardening (documented toggle, off by default): add `"recorder": ["tag:tsrecorder"], "enforceRecorder": true` and deploy a `Recorder` CR — records all kubectl/exec/API sessions and fails closed if the recorder is unreachable.

## 7. Extensibility — app access path (additive, not built now)

- Add an optional `expose:` list per tenant → render a Tailscale `Ingress` (`ingressClassName: tailscale`) or a `tailscale.com/expose` annotation on the named Service, advertising it on the tailnet, **plus** an `allow-from-tailscale` ingress NetworkPolicy (ingress from the `tailscale` proxy namespace) so `default-deny` doesn't block it.
- App reachability is governed by standard tailnet ACLs (not the kubernetes capability) — documented when enabled.
- No change to §4–§6; this is purely new chart templates keyed off `expose`.

## 8. File layout

```
components/tailscale-operator/kustomization.yaml          # mode "false" → "true"
.helm/charts/remote-tenant/
  Chart.yaml
  values.yaml            # defaults: {…}  + tenants: []  (commented example)
  test-values.yaml       # one example tenant for `helm template` assertions
  README.md              # onboarding runbook (two control planes, the manual grant step)
  templates/
    _helpers.tpl         # remote-tenant.namespace / .merged / .labels  (mirrors pac-tenant)
    namespace.yaml
    resourcequota.yaml
    limitrange.yaml
    networkpolicies.yaml
    clusterrole.yaml     # remote-tenant-operator (rendered once)
    validatingadmissionpolicy.yaml  # remote-tenant-no-burst + no-secondary-net VAPs + bindings (rendered once)
    rolebindings.yaml    # per-tenant Group → role
    NOTES.txt            # emits the per-tenant grant block
clusters/ocp/remote-tenants/
  kustomization.yaml     # helmGlobals.chartHome ../../../.helm/charts ; helmCharts: [remote-tenant]
  values.yaml            # defaults + tenants list for the OCP cluster
clusters/ocp/values.yaml # add app-of-app "remote-tenants" entry (sync-wave 20), via the add-to-cluster pattern
```

Wiring mirrors `pac-tenants` exactly: a Kustomization that renders the local chart, plus a sync-wave-20 app-of-app entry with `argocd.argoproj.io/compare-options: IgnoreExtraneous`. (Optional later: a `/scaffold-remote-tenant` skill paralleling `/scaffold-pac-tenant`.)

## 9. Onboarding runbook (end-to-end)

1. **GitOps** — add a `tenants:` entry to `clusters/ocp/remote-tenants/values.yaml`; open PR; on merge ArgoCD creates the namespace, guardrails, and RoleBinding.
2. **Tailnet** — paste the grant block from `helm template … --show-only templates/NOTES.txt` (or the rendered Application notes) into the Tailscale ACL editor.
3. **User** — `tailscale up` → `tailscale configure kubeconfig tailscale-operator` → `oc -n alice-dev get pods`. They reach only their namespace; cluster-scoped reads and other namespaces are denied.

**Offboarding** — remove the grant (immediate API cut-off) and the values entry (ArgoCD prunes the namespace).

## 10. Security posture, caveats, out of scope

- **No public surface:** kube API reachable only over WireGuard/tailnet; no Route/LB for the API.
- **Deny-by-default everywhere:** no grant ⇒ no impersonation; `default-deny` NetworkPolicy; custom role can't touch guardrails or RBAC; ArgoCD `selfHeal` reverts tampering.
- **Blast radius = one namespace:** group bound only in its namespace; nothing cluster-scoped is readable.
- **PSA `restricted`:** workloads needing root require an admin-granted SCC exception (out of scope; document per-case).
- **Manual grants:** managed in the admin console this iteration; policy-as-code (Tailscale Terraform provider or `gitops-acl` GitHub Action, e.g. under `igou-infrastructure`) is a documented upgrade path.
- **Single-instance proxy:** acceptable on this single-master cluster; `ProxyGroup` is the HA path (§4).
- **One-time node labeling:** tenant-eligible workers must be labeled `node-role.kubernetes.io/tenant=` (e.g. `hpg5`, `p330`) — a documented bootstrap step alongside the tailnet grant (§5.6).
- **`rosa-gitops` untouched.**

## 11. Testing & validation

- `helm template .helm/charts/remote-tenant -f .helm/charts/remote-tenant/test-values.yaml` → assert: namespace PSA=`restricted`; ResourceQuota + LimitRange present; the 4–5 NetworkPolicies; `RoleBinding.subjects[0].kind == Group`; `remote-tenant-operator` ClusterRole rendered once; the `remote-tenant-no-burst` and `remote-tenant-no-secondary-net` ValidatingAdmissionPolicies + Bindings rendered once; the Namespace carries `openshift.io/node-selector`.
- `kustomize build components/tailscale-operator` (with `mode:"true"`) → assert `ClusterRole/tailscale-auth-proxy` + its binding present.
- `yamllint` (repo `.yamllint`); ArgoCD diff / `--dry-run=server`.
- **Functional (granted identity):** `oc -n <ns> get pods` works; `oc get nodes` denied; another namespace denied; `oc edit networkpolicy default-deny-all` denied; exceeding quota denied.
- **Functional (burst containment):** as a tenant, `oc apply` a Deployment with a `workload=burst` toleration → denied; with `nodeSelector node-role.kubernetes.io/burst: ""` → denied; with a blanket `operator: Exists` toleration → denied; a normal Deployment → admitted. Confirm `MachineSet/casval-worker` stays at `replicas: 0`.
- **Functional (placement):** a tenant Deployment's pods schedule on `hpg5`/`p330`, never on `ocp` (master) or `casval`; a pod adding a conflicting `nodeSelector` is rejected by NodeSelector admission.
- **Functional (secondary nets):** as a tenant, `oc apply` a `NetworkAttachmentDefinition` (or namespaced `UserDefinedNetwork`) → denied (RBAC and/or VAP).
- **Negative:** an un-granted tailnet identity gets no API access.
