# Hermes Agent POC — Phase 1: igou-openshift Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the Argo-managed cluster guardrails (namespace, state volume, network containment, admission policy) that the Ansible-managed Hermes VM (Phase 2) lands in.

**Architecture:** A new `applications/hermes-agent/` kustomize app, wired into the `clusters/ocp` app-of-apps. It provisions the `hermes` Namespace, the standalone `hermes-state` DataVolume (survives VM rebuilds), an OVN-K `EgressFirewall` (default-deny north-south), `NetworkPolicy` (deny ingress + scoped east-west egress to qwen3/DNS/Quay), and a `ValidatingAdmissionPolicy` constraining any VM in the namespace. This produces a validated, applied set of guardrails — testable on its own — before the VM exists.

**Tech Stack:** OpenShift 4.21 / OVN-Kubernetes, OpenShift Virtualization (CDI DataVolume), Kustomize, Argo CD app-of-apps, native ValidatingAdmissionPolicy (CEL). Validation: `make test` (yamllint + kustomize build + kubeconform).

**Spec:** `docs/superpowers/specs/2026-06-14-hermes-agent-kubevirt-vm-deployment-design.md`
**Conventions (from repo CLAUDE.md):** files named `<metadata.name>-<kind>.yaml`; block-style YAML (no flow JSON); apps use `project: cluster-apps`, `compare-options: IgnoreExtraneous`, `sync-wave: '20'`, `source.path: applications/<name>`.

**Deferred to later phases (do NOT add here):** `ImagePolicy`/cosign enforcement (needs the signed image from the operate-phase Tekton pipeline; enforcing it now would block the unsigned POC image), the egress proxy, OOB approvals, immutable-skills pipeline, Falco, snapshots schedule. PSA `enforce: restricted` on the namespace is deferred to Phase "harden" pending a virt-launcher compatibility check (the validated boot ran under the default PSA).

---

## File Structure

All files are **new**, under `igou-openshift/`:

- `applications/hermes-agent/hermes-namespace.yaml` — the `hermes` Namespace (acl-logging annotation; PSA audit/warn only for now).
- `applications/hermes-agent/hermes-state-datavolume.yaml` — blank 30Gi `hermes-state` DataVolume (snapshot-capable SC).
- `applications/hermes-agent/default-egressfirewall.yaml` — OVN-K `EgressFirewall` (name MUST be `default`): allow the one messaging API, deny all other external.
- `applications/hermes-agent/hermes-deny-ingress-networkpolicy.yaml` — default-deny ingress.
- `applications/hermes-agent/hermes-egress-networkpolicy.yaml` — scoped egress: DNS + qwen3 + Quay (east-west) + external (EgressFirewall governs).
- `applications/hermes-agent/hermes-vm-hardening-validatingadmissionpolicy.yaml` — VAP + binding constraining VMs in the namespace.
- `applications/hermes-agent/kustomization.yaml` — ties the above together.
- `clusters/ocp/values.yaml` — **modify**: add the `hermes-agent` app-of-apps entry.

---

### Task 1: Namespace

**Files:**
- Create: `igou-openshift/applications/hermes-agent/hermes-namespace.yaml`

- [ ] **Step 1: Write the Namespace manifest**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: hermes
  labels:
    # PSA audit/warn now; enforce:restricted deferred to "harden" pending a virt-launcher compatibility check
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
  annotations:
    # log denied (and allowed) traffic from this namespace's OVN ACLs (EgressFirewall + NetworkPolicy)
    k8s.ovn.org/acl-logging: '{"deny": "warning", "allow": "info"}'
```

- [ ] **Step 2: yamllint the file**

Run: `cd /workspace/igou-openshift && yamllint applications/hermes-agent/hermes-namespace.yaml`
Expected: no errors (exit 0).

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/hermes-namespace.yaml
git commit -m "feat(hermes-agent): add hermes namespace with ACL-deny logging"
```

---

### Task 2: State DataVolume

**Files:**
- Create: `igou-openshift/applications/hermes-agent/hermes-state-datavolume.yaml`

The agent's mutable `~/.hermes` (memory + skills) lives here — a **blank** volume (not a clone, so the resize caveat does not apply), Argo-owned so it survives VM delete/recreate.

- [ ] **Step 1: Write the DataVolume manifest**

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: hermes-state
  namespace: hermes
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  source:
    blank: {}
  storage:
    accessModes:
      - ReadWriteOnce
    storageClassName: freenas-nvmeof-ssd-csi
    resources:
      requests:
        storage: 30Gi
```

- [ ] **Step 2: yamllint**

Run: `cd /workspace/igou-openshift && yamllint applications/hermes-agent/hermes-state-datavolume.yaml`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/hermes-state-datavolume.yaml
git commit -m "feat(hermes-agent): add blank hermes-state DataVolume (30Gi, snapshot-capable)"
```

---

### Task 3: EgressFirewall (north-south default-deny)

**Files:**
- Create: `igou-openshift/applications/hermes-agent/default-egressfirewall.yaml`

The EgressFirewall is the **agent-immutable** external boundary. POC channel = Telegram (`api.telegram.org`); the operator swaps the `dnsName` for whichever single channel they enable. The hosted-LLM fallback is **off** in POC (qwen3 is in-cluster/east-west), so no LLM rule here.

- [ ] **Step 1: Write the EgressFirewall manifest**

```yaml
apiVersion: k8s.ovn.org/v1
kind: EgressFirewall
metadata:
  # OVN-K requires this object to be named "default"
  name: default
  namespace: hermes
spec:
  egress:
    # the one messaging channel enabled in POC (swap dnsName for your channel)
    - type: Allow
      to:
        dnsName: api.telegram.org
    # everything else external is denied (cluster DNS + qwen3 + Quay are east-west, see NetworkPolicy)
    - type: Deny
      to:
        cidrSelector: 0.0.0.0/0
```

- [ ] **Step 2: yamllint**

Run: `cd /workspace/igou-openshift && yamllint applications/hermes-agent/default-egressfirewall.yaml`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/default-egressfirewall.yaml
git commit -m "feat(hermes-agent): default-deny EgressFirewall (allow only the messaging channel)"
```

---

### Task 4: NetworkPolicy — deny ingress

**Files:**
- Create: `igou-openshift/applications/hermes-agent/hermes-deny-ingress-networkpolicy.yaml`

The agent is outbound-only (messaging bots dial out; operator access is via Tailscale in Phase 2). Deny all ingress.

- [ ] **Step 1: Write the NetworkPolicy**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-deny-ingress
  namespace: hermes
spec:
  podSelector: {}
  policyTypes:
    - Ingress
  # no ingress rules => deny all ingress
```

- [ ] **Step 2: yamllint**

Run: `cd /workspace/igou-openshift && yamllint applications/hermes-agent/hermes-deny-ingress-networkpolicy.yaml`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/hermes-deny-ingress-networkpolicy.yaml
git commit -m "feat(hermes-agent): default-deny ingress NetworkPolicy"
```

---

### Task 5: NetworkPolicy — scoped egress

**Files:**
- Create: `igou-openshift/applications/hermes-agent/hermes-egress-networkpolicy.yaml`

Allow only the east-west destinations the agent legitimately needs (cluster DNS, the qwen3 inference Service, the in-cluster Quay registry), plus external (the EgressFirewall governs which external hosts). `0.0.0.0/0` with the cluster CIDRs excepted prevents lateral movement to other namespaces while still letting allow-listed external traffic out.

- [ ] **Step 1: Get the cluster network CIDRs to except**

Run: `oc get network.config/cluster -o jsonpath='{.spec.clusterNetwork[*].cidr} {.spec.serviceNetwork[*]}{"\n"}'`
Record the pod and service CIDRs (default OVN-K is `10.128.0.0/14` and `172.30.0.0/16`); use the actual values from your cluster in Step 2.

- [ ] **Step 2: Write the NetworkPolicy** (substitute the CIDRs from Step 1 into the two `except` entries)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-egress
  namespace: hermes
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    # cluster DNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-dns
      ports:
        - protocol: UDP
          port: 5353
        - protocol: TCP
          port: 5353
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # qwen3 inference service (east-west default LLM)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: llmkube-system
          podSelector:
            matchLabels:
              app: qwen3-35b-a3b
      ports:
        - protocol: TCP
          port: 8080
    # in-cluster Quay registry (image pull)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: quay-enterprise
    # external (EgressFirewall decides which hosts); except cluster CIDRs to block lateral movement
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.128.0.0/14
              - 172.30.0.0/16
```

- [ ] **Step 3: yamllint**

Run: `cd /workspace/igou-openshift && yamllint applications/hermes-agent/hermes-egress-networkpolicy.yaml`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/hermes-egress-networkpolicy.yaml
git commit -m "feat(hermes-agent): scoped egress NetworkPolicy (DNS + qwen3 + Quay + external-via-EgressFirewall)"
```

---

### Task 6: ValidatingAdmissionPolicy for the VM

**Files:**
- Create: `igou-openshift/applications/hermes-agent/hermes-vm-hardening-validatingadmissionpolicy.yaml`

Native (no Kyverno) admission guardrail: any `VirtualMachine` in `hermes` must use masquerade networking and must not attach host devices or GPUs.

- [ ] **Step 1: Write the VAP + binding**

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: hermes-vm-hardening
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups:
          - kubevirt.io
        apiVersions:
          - v1
        operations:
          - CREATE
          - UPDATE
        resources:
          - virtualmachines
  validations:
    - expression: "object.spec.template.spec.domain.devices.interfaces.all(i, has(i.masquerade))"
      message: "hermes VMs must use masquerade networking so EgressFirewall/NetworkPolicy apply"
    - expression: "!has(object.spec.template.spec.domain.devices.hostDevices) || size(object.spec.template.spec.domain.devices.hostDevices) == 0"
      message: "hermes VMs must not attach host devices"
    - expression: "!has(object.spec.template.spec.domain.devices.gpus) || size(object.spec.template.spec.domain.devices.gpus) == 0"
      message: "hermes VMs must not attach GPUs"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: hermes-vm-hardening
spec:
  policyName: hermes-vm-hardening
  validationActions:
    - Deny
  matchResources:
    namespaceSelector:
      matchLabels:
        kubernetes.io/metadata.name: hermes
```

- [ ] **Step 2: yamllint**

Run: `cd /workspace/igou-openshift && yamllint applications/hermes-agent/hermes-vm-hardening-validatingadmissionpolicy.yaml`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/hermes-vm-hardening-validatingadmissionpolicy.yaml
git commit -m "feat(hermes-agent): VAP requiring masquerade + no host devices on hermes VMs"
```

---

### Task 7: Kustomization

**Files:**
- Create: `igou-openshift/applications/hermes-agent/kustomization.yaml`

- [ ] **Step 1: Write the kustomization**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: hermes
resources:
  - hermes-namespace.yaml
  - hermes-state-datavolume.yaml
  - default-egressfirewall.yaml
  - hermes-deny-ingress-networkpolicy.yaml
  - hermes-egress-networkpolicy.yaml
  - hermes-vm-hardening-validatingadmissionpolicy.yaml
```

- [ ] **Step 2: Build it locally**

Run: `cd /workspace/igou-openshift && kustomize build applications/hermes-agent/`
Expected: renders all six resources with no error. (Cluster-scoped objects — Namespace, VAP, binding — render even though `namespace: hermes` is set; that is expected.)

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add applications/hermes-agent/kustomization.yaml
git commit -m "feat(hermes-agent): kustomization for the guardrail resources"
```

---

### Task 8: Wire into the app-of-apps

**Files:**
- Modify: `igou-openshift/clusters/ocp/values.yaml` (add one entry under `applications:`)

- [ ] **Step 1: Add the app entry**

Add this block under the `applications:` map (alphabetical placement near other apps is fine; match the existing 2-space indentation):

```yaml
  hermes-agent:
    project: cluster-apps
    annotations:
      argocd.argoproj.io/compare-options: IgnoreExtraneous
      argocd.argoproj.io/sync-wave: '20'
    source:
      path: applications/hermes-agent
```

- [ ] **Step 2: yamllint the values file**

Run: `cd /workspace/igou-openshift && yamllint clusters/ocp/values.yaml`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /workspace/igou-openshift
git add clusters/ocp/values.yaml
git commit -m "feat(hermes-agent): register hermes-agent app in the ocp app-of-apps"
```

---

### Task 9: Full validation

**Files:** none (validation only)

- [ ] **Step 1: Run the repo's full validation suite**

Run: `cd /workspace/igou-openshift && make test`
Expected: PASS — yamllint clean, all kustomizations build, kubeconform schema-validates (KubeVirt/CDI/OVN CRD schemas resolve). If kubeconform lacks a CRD schema (EgressFirewall, ValidatingAdmissionPolicy, DataVolume), confirm it is skipped/ignored per the repo's existing kubeconform config — do not add `--strict` failures for known CRDs.

- [ ] **Step 2: Server-side dry-run against the live cluster** (catches admission/CRD issues before Argo syncs)

Run: `cd /workspace/igou-openshift && kustomize build applications/hermes-agent/ | oc apply --dry-run=server -f -`
Expected: each resource reports `... (server dry run)` with no validation error.

- [ ] **Step 3: Commit any fixes, then push for PR**

```bash
cd /workspace/igou-openshift
git status   # confirm clean or commit fixes
# push the branch and open a PR per repo workflow (recent merges are #309/#310)
```

---

### Task 10: Sync &amp; verify on-cluster

**Files:** none (post-merge verification — run after Argo syncs the merged change)

- [ ] **Step 1: Confirm the Argo Application is healthy/synced**

Run: `oc -n openshift-gitops get applications.argoproj.io hermes-agent -o jsonpath='{.status.sync.status} / {.status.health.status}{"\n"}'`
Expected: `Synced / Healthy`.

- [ ] **Step 2: Confirm the guardrail resources exist**

Run:
```bash
oc get ns hermes
oc -n hermes get datavolume hermes-state
oc -n hermes get egressfirewall default
oc -n hermes get networkpolicy
oc get validatingadmissionpolicy hermes-vm-hardening
oc get validatingadmissionpolicybinding hermes-vm-hardening
```
Expected: all present; `hermes-state` DataVolume reaches `Succeeded` (blank volume provisions quickly).

- [ ] **Step 3: Verify the VAP actually rejects a non-compliant VM** (negative test, persists nothing)

Run:
```bash
cat <<'YAML' | oc apply --dry-run=server -f -
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: vap-negtest
  namespace: hermes
spec:
  runStrategy: Halted
  template:
    spec:
      domain:
        devices:
          interfaces:
            - name: default
              bridge: {}
      networks:
        - name: default
          pod: {}
YAML
```
Expected: **DENIED** with `hermes VMs must use masquerade networking ...` (bridge, not masquerade). This proves the admission guardrail works. (A masquerade interface would pass.)

---

## Self-Review

**Spec coverage (Phase-1 scope):**
- Namespace + ACL-deny logging → Task 1 ✓ (spec §4, §12)
- `hermes-state` DataVolume, Argo-owned, snapshot-capable → Task 2 ✓ (spec §4, §6)
- EgressFirewall default-deny + one channel → Task 3 ✓ (spec §7)
- NetworkPolicy deny-ingress + scoped east-west egress (DNS/qwen3/Quay) → Tasks 4–5 ✓ (spec §7)
- Native VAP (no Kyverno) → Task 6 ✓ (spec §9)
- App-of-apps wiring → Task 8 ✓ (spec §15)
- ImagePolicy/cosign, egress proxy, OOB approvals, snapshots, Falco → **intentionally deferred** to harden/operate (spec §16); PSA `enforce:restricted` deferred pending virt-launcher compat. Listed in the header so they are not silently dropped.

**Placeholder scan:** the one substitution is the cluster CIDRs in Task 5 (Step 1 fetches the real values; defaults given) and the Telegram `dnsName` in Task 3 (a concrete POC channel the operator may swap) — both are explicit decisions with the exact value shown, not "TODO".

**Type/name consistency:** namespace `hermes` and the file naming `<name>-<kind>.yaml` are consistent across all tasks; the qwen3 selector (`app=qwen3-35b-a3b`, port 8080, ns `llmkube-system`) matches the live Service; the VAP `policyName`/binding names match.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-hermes-agent-poc-phase1-guardrails.md`. **Phase 2 (the `igou-ansible` VM bring-up + convergence) will be a separate plan** once this one is applied and the guardrails are verified.

Two execution options for this plan:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
