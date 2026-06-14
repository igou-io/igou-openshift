# Hermes Agent on OpenShift Virtualization — Hardened KubeVirt VM, Ansible-Managed

**Date:** 2026-06-14
**Status:** Approved design — ready for implementation planning (phased)
**Cluster:** `ocp.igou.systems` (OpenShift 4.21.15, OpenShift Virtualization / KubeVirt 4.21.8)
**Companion reference:** `scratch/hermes-agent-deployment-security.html` (rev 3) — the generic threat model & substrate analysis this spec instantiates for the cluster.

---

## 1. Goal

Deploy, run, and secure **Nous Research "Hermes Agent"** — a self-hosted, hostile-by-default autonomous agent that runs its own LLM-generated code and ingests untrusted messaging input — inside a **hardened OpenShift Virtualization (KubeVirt) VirtualMachine** that is **bootstrapped and converged by Ansible/AWX**, on the on-prem bare-metal OpenShift cluster. A VM gives the untrusted guest its **own kernel** behind the QEMU/KVM + SELinux/sVirt boundary; the cluster network/admission policies form the **agent-immutable** containment; Ansible owns the self-mutating workload.

Per Hermes's own `SECURITY.md`, "the only security boundary against an adversarial LLM is the operating system" — so all containment is external (VM + cluster policy + credential minimization), and the agent is treated as fully compromised.

---

## 2. Cluster baseline — verified live (2026-06-14)

| Capability | State | Used as |
|---|---|---|
| OpenShift Virtualization / KubeVirt | ✓ 4.21.8, HyperConverged Deployed | the VM substrate |
| Bare-metal KVM nodes | ✓ hpg5 (16c/64G), ocp (20c/96G), p330 (16c/64G), all `devices.kubevirt.io/kvm` | run VMs |
| virt-launcher non-root/non-priv | ✓ enforced (4.21 ≥ 4.18) | inherent isolation |
| Guest boot (CentOS Stream 10) | ✓ **boots via BIOS** (validated: agent connected, multi-user) | guest OS |
| Secure Boot | nodes support it, but stock CentOS Stream 10 golden image is **BIOS-only** → **dropped** | n/a (see §17 for UEFI path) |
| CPU-Manager static policy | ✗ not enabled | → **burstable CPU**, no `dedicatedCpuPlacement` |
| OVN-Kubernetes + EgressFirewall | ✓ default network OVN-K; `EgressFirewall` CRD present | north-south egress allowlist |
| MultiNetworkPolicy | ✗ `useMultiNetworkPolicy=false`, CRD absent | → EgressFirewall on the masquerade interface (no VLAN DMZ) |
| CDI DataVolumes + VolumeSnapshots | ✓; default SC `freenas-nvmeof-ssd-csi` (RWO, snapshot-capable); `freenas-nfs-ssd-csi` RWX | root/state disks + rollback |
| Smart-clone (snapshot) | ✓ **only when target == source size** (30 GiB). Resize-on-clone deadlocks democratic-csi | clone root at golden size |
| Kyverno / Gatekeeper | ✗ neither installed | → **native VAP + ClusterImagePolicy/ImagePolicy** |
| RHACS | ✗ not installed | → host/cluster-native audit (no SIEM) |
| OpenShift Logging / Loki | ✗ operators only; **no LokiStack, no object storage** | → journald + ACL-deny + API-audit (centralized logging deferred) |
| In-cluster LLM | ✓ `llmkube-system/qwen3-35b-a3b`, OpenAI-compatible, currently Stopped | default LLM backend |
| Argo CD / Tekton / Quay / MetalLB | ✓ all installed | GitOps guardrails / build / registry / LB |
| `centos-stream10` DataSource + image-cron | ✓ in `openshift-virtualization-os-images` | root golden image |

**Validated boot path:** 30 GiB root clone from the `centos-stream10` DataSource (no resize) completes in ~56 s and boots CentOS Stream 10 to multi-user with the guest agent connected.

---

## 3. Locked decisions

- **Substrate:** KubeVirt VM, bare-metal OCP 4.21.
- **Guest:** CentOS Stream 10 (golden-image clone), **BIOS firmware** (Secure Boot dropped).
- **CPU/RAM:** burstable **4 vCPU / 8 GiB** (no pinning).
- **Root disk:** **30 GiB** clone at golden size (no resize); grow online later if ever needed.
- **State disk:** separate **30 GiB blank DataVolume**, snapshot-capable, mounted at `HERMES_HOME=/var/lib/hermes`.
- **LLM:** in-cluster **qwen3** (llmkube) default + hosted fallback (configurable).
- **Ownership:** **hybrid** — Argo CD (igou-openshift) owns cluster guardrails; Ansible/AWX (`kubevirt.core`) owns the VM + guest convergence.
- **Admission/policy:** native **ValidatingAdmissionPolicy + ClusterImagePolicy/ImagePolicy + SCC restricted-v2 + Pod Security Admission** (no Kyverno).
- **Runtime audit:** in-guest journald (on state DV) + OVN-K ACL-deny logging + K8s API audit + CNV serial-console log. **No RHACS/Loki**; centralized aggregation + active detection are deferred/optional.
- **Supply chain:** Tekton build → in-cluster Quay → cosign-sign → digest-pin → ImagePolicy verification at pull.
- **Management:** Tailscale one-way (AWX converges via the dynamic-inventory `network_name`).

---

## 4. Architecture & ownership (hybrid)

**Argo CD owns (GitOps, `igou-openshift` app-of-apps)** — immutable guardrails:
- `Namespace: hermes` (PSA `enforce: restricted`, `k8s.ovn.org/acl-logging` deny)
- `EgressFirewall` (default-deny + allowlist) and `NetworkPolicy` (deny ingress; egress → qwen3 + DNS)
- Standalone **`hermes-state` DataVolume** (survives VM delete/recreate; snapshot-restored independently)
- `ValidatingAdmissionPolicy` + binding (VM/pod constraints) and namespaced `ImagePolicy` (cosign verification)

**Ansible/AWX owns (`kubevirt.core`)** — the self-mutating workload:
- The hardened `VirtualMachine` (root as `dataVolumeTemplate`; references the Argo-owned `hermes-state` DV)
- `cloudInitNoCloud` SSH seed; guest convergence over Tailscale (systemd hardening, nftables, egress proxy, Hermes Quadlet, audit shipping)

```
  Tailscale (ONLY ingress, one-way) ──► AWX convergence / operator
                                            │ (in guest VM)
  ┌──────────────── ns: hermes (Argo-guarded) ────────────────────┐
  │  KubeVirt VM (Ansible-managed) · BIOS · burstable 4c/8Gi        │
  │    Hermes (Quadlet, digest-pinned) ─► in-guest egress proxy ─┐  │
  │    ~/.hermes ─► hermes-state DataVolume (Argo, snapshot)     │  │
  │    journald (audit) on state DV                             ─┤  │
  └──────────────────────────── masquerade iface ───────────────┼──┘
        EgressFirewall (N-S, default-deny)  +  NetworkPolicy (E-W) │
                                                                   ▼
        east-west (NetworkPolicy) ─► qwen3 (llmkube) + in-cluster Quay + cluster DNS   [allow]
        north-south (EgressFirewall) ─► hosted LLM + the enabled messaging API         [allow]
        everything else                                                                [DENY + ACL-log]
```

**Containment for a compromised agent:** reachable surface = `{qwen3 east-west}` + `{hosted-LLM + the enabled messaging API, north-south}` only, enforced by cluster policy the guest cannot rewrite. The in-guest proxy adds DLP/cert-pin/logging on top (best-effort).

---

## 5. The hardened VirtualMachine (Ansible-owned)

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: hermes
  namespace: hermes
  labels:
    app: hermes
spec:
  runStrategy: Always
  # validated config uses the explicit settings below; the centos.stream10 preference is optional, not required
  dataVolumeTemplates:
    - metadata:
        name: hermes-root
      spec:
        # request == golden size (30Gi); a larger request triggers a resize that deadlocks the clone
        sourceRef:
          kind: DataSource
          name: centos-stream10
          namespace: openshift-virtualization-os-images
        storage:
          resources:
            requests:
              storage: 30Gi
  template:
    metadata:
      labels:
        app: hermes
        kubevirt.io/vm: hermes
    spec:
      # no firmware block => BIOS/SeaBIOS (the golden image is BIOS; validated boot)
      domain:
        cpu:
          # burstable - no dedicatedCpuPlacement (CPU-Manager static policy is off)
          cores: 4
          sockets: 1
          threads: 1
        memory:
          guest: 8Gi
        resources:
          requests:
            memory: 8Gi
          limits:
            memory: 8Gi
        devices:
          rng: {}
          # no VNC surface; serial console kept for RBAC-gated virtctl break-glass
          autoattachGraphicsDevice: false
          disks:
            - name: root
              bootOrder: 1
              disk:
                bus: virtio
            - name: state
              disk:
                bus: virtio
            - name: cloudinit
              disk:
                bus: virtio
          interfaces:
            # masquerade => EgressFirewall + NetworkPolicy govern this VM's egress
            - name: default
              masquerade: {}
      networks:
        - name: default
          pod: {}
      # RWO state DV => restart-on-drain (no live migration)
      evictionStrategy: None
      volumes:
        - name: root
          dataVolume:
            name: hermes-root
        - name: state
          # Argo-owned standalone DV (survives VM delete/recreate)
          dataVolume:
            name: hermes-state
        - name: cloudinit
          cloudInitNoCloud:
            # SSH key + mount the state disk at HERMES_HOME - nothing secret here
            userData: |
              #cloud-config
              hostname: hermes
              ssh_authorized_keys:
                - "ssh-ed25519 AAAA... ansible-bootstrap"
              # bootcmd: format/mount the state disk at /var/lib/hermes
```

Rationale: BIOS (validated), burstable CPU (no static policy), root cloned at golden size (the only clone size that works on this storage), graphics off, serial console retained for RBAC-gated `virtctl console` break-glass.

---

## 6. Storage

- **Root:** 30 GiB clone of the `centos-stream10` golden image. **Do not request a larger size at clone time** — the 30→40 GiB resize deadlocks the democratic-csi volume-populator. If root space is ever needed, expand the PVC online (`ALLOWVOLUMEEXPANSION=true`) after the clone binds.
- **State (`hermes-state`):** a separate **blank** 30 GiB DataVolume on `freenas-nvmeof-ssd-csi` (snapshot-capable), Argo-owned so it survives VM rebuilds. Mounted at `HERMES_HOME=/var/lib/hermes`. Blank volumes are not cloned, so the resize caveat does not apply.
- **Snapshots:** schedule `VolumeSnapshot`s of `hermes-state` for memory/skills rollback (restore from a pre-compromise snapshot). The default SC has a working snapshot class.
- **Live migration:** RWO state ⇒ `evictionStrategy: None` (restart-on-drain; the network-backed DV re-attaches on the new node). Switch the state DV to `freenas-nfs-ssd-csi` (RWX) if live-migration is later required.

---

## 7. Networking & egress

The cluster policies are the **hard, agent-immutable boundary** (enforced outside the guest). The VM's masquerade interface NATs behind the pod IP, so pod-level policy applies.

- **`EgressFirewall`** (Argo-owned, default-deny + allowlist): allow the **hosted LLM** (only if the fallback is enabled) and the **one messaging API** actually enabled; otherwise **Deny `0.0.0.0/0`** (including external DNS — cluster DNS is east-west). In-cluster Quay and qwen3 are east-west, handled by NetworkPolicy.
- **`NetworkPolicy`** (Argo-owned): default-deny **ingress** (agent is outbound-only); egress allow to **cluster DNS**, the **qwen3 Service** in `llmkube-system` (default LLM), and **in-cluster Quay** (image pull) — all east-west, *not* governed by EgressFirewall. Deny all other in-cluster traffic (no lateral movement).
- **Egress-deny audit:** annotate the namespace `k8s.ovn.org/acl-logging` so blocked egress is logged (OVN-K node logs).
- **Management ingress:** a `tailscaled` in the guest joins the tailnet with a **one-way grant** (operator/AWX → guest allowed; guest → tailnet denied), key kept out of the agent user's reach. AWX converges over this interface; no inbound LoadBalancer/NodePort exposure.

---

## 8. Secrets

- **Guest secrets** (hosted-LLM key for the fallback, scoped messaging bot token) are injected **at convergence time** by AWX/AAP credentials / **`op inject`** from 1Password into a tmpfs `EnvironmentFile` (0600) referenced by the Hermes Quadlet. Never baked into the image, cloud-init, or Git.
- **Cluster secrets** (if any are needed by guardrails) use the existing External Secrets Operator → 1Password pattern.
- LLM key is **spend-capped** and per-provider; the messaging token is least-privilege and chat-ID-scoped where the platform allows.

---

## 9. Admission & policy (native — no Kyverno)

- **`ValidatingAdmissionPolicy` + binding** scoped to the `hermes` namespace: forbid privileged pods / host namespaces / extra capabilities; constrain the `VirtualMachine` (e.g., require `masquerade` networking, forbid host devices). Example CEL:
  ```
  matchConstraints:
    resourceRules:
      - apiGroups:
          - kubevirt.io
        resources:
          - virtualmachines
  validations:
    - expression: "object.spec.template.spec.domain.devices.interfaces.all(i, has(i.masquerade))"
  ```
- **`ImagePolicy`** (namespaced, `config.openshift.io/v1`) requiring the Hermes image to be cosign/sigstore-signed (operator key or a Fulcio identity) before pull.
- **SCC `restricted-v2`** + **Pod Security Admission `enforce: restricted`** for any auxiliary pods (the virt-launcher already runs restricted/non-root).

---

## 10. Supply chain

Build Hermes from its Dockerfile via **OpenShift Pipelines (Tekton)** → push to in-cluster **Quay** → **cosign-sign** → **pin by digest** → the namespaced `ImagePolicy` enforces the signature at pull. Build **hermetically** (vendored / hash-locked deps; the upstream installer's `uv`/PyPI resolution must be pinned at build time, not just relocated). Renovate bumps the pinned digest. This replaces the upstream `curl|bash` install entirely.

---

## 11. Hermes configuration & containment controls (§5.5, adapted)

- **`cli-config.yaml`** (immutable, in Git): `backend: local` (the VM is the sandbox — no nested Docker), `approvals.mode: manual`, SSRF protection on, model → qwen3 default + hosted fallback, **one** low-trust channel to start, minimal tool allowlist.
- **Out-of-band approvals:** approvals delivered on a separate channel/bot the agent cannot post to; the prompt shows a wrapper-rendered (agent-immutable) description; approval-rate tripwire.
- **Immutable / Git-gated skills:** skills directory read-only at runtime; new/changed skills flow through a Git/PR + signed pipeline; memory treated as untrusted on read-back; restore the state DV from a pre-compromise snapshot on suspected compromise.
- **Egress proxy (in-guest):** DLP/full-body logging + LLM cert-pin + per-session token/iteration budget (denial-of-wallet). Best-effort layer on top of the cluster EgressFirewall (the real boundary).
- **nftables** in-guest default-deny egress (defense-in-depth behind EgressFirewall).
- **systemd sandboxing** for the Hermes service: `ProtectSystem=strict`, `NoNewPrivileges`, `SystemCallFilter`, `RestrictAddressFamilies`, etc.

---

## 12. Runtime audit & detection (no RHACS / no Loki)

- **In-guest `journald`** — Hermes, the egress proxy (DLP), and nftables log to journald, persisted on the state DataVolume (survives reboots; queryable via SSH/`journalctl`). Primary audit trail.
- **OVN-K ACL-deny logging** (namespace annotation) — blocked egress/ingress logged → catches a compromised agent probing the allowlist.
- **Kubernetes API audit log** (already running) — VAP / ImagePolicy admission denials and API access.
- **CNV serial-console log** per-VM (`oc logs <virt-launcher> -c guest-console-log`).
- **Honest gap:** without RHACS/Falco/Loki there is **no real-time behavioral detection** — these are evidentiary trails for forensics; prevention is the EgressFirewall/policies/admission. **Optional, deferred:** add **Falco** (alerts to a webhook, no object storage) for active detection, or stand up object storage + a LokiStack + ClusterLogForwarder for centralized aggregation/alerting.

---

## 13. Sizing

| Resource | Value | Notes |
|---|---|---|
| vCPU | 4 (burstable) | no pinning (static policy off); bursts as scheduled |
| RAM | 8 GiB (requests==limits) | driver = on-demand headless Chromium (Hermes needs Node.js 22 + browser automation) + Python agent + proxy |
| Root disk | 30 GiB clone | == golden (no resize); CentOS uses ~2–10 GiB |
| State disk | 30 GiB blank DV | `~/.hermes` memory/skills; snapshot-able; grows over time |

Estimate (Hermes publishes no official minimums) — **load-test before committing**; account for KubeVirt virt-launcher overhead (~200–300 MiB + per-vCPU) in node capacity. Open question: confirm whether Hermes code-exec runs as in-guest subprocesses (assumed) vs expecting nested Podman.

---

## 14. Ansible bootstrap & convergence

1. **Install:** `ansible-galaxy collection install kubevirt.core` (pulls `kubernetes.core`) in the AWX execution environment.
2. **Create VM:** `kubevirt.core.kubevirt_vm` (idempotent, patch-on-diff; **never `force: yes`**) applies the §5 VM; `cloudInitNoCloud` seeds the SSH key + state-disk mount.
3. **Discover:** `kubevirt.core.kubevirt` dynamic inventory (`inventory.kubevirt.yml`, `label_selector: app=hermes`, `network_name: tailscale`) → the guest appears as an Ansible host over its tailnet IP; auth via the cluster bearer-token credential in AAP.
4. **Converge (roles over SSH):** `systemd_sandbox`, `nftables_egress`, `egress_proxy`, `hermes_quadlet` (digest-pinned Quay image; `HERMES_HOME` on the state DV), `tailscale` (one-way), `audit` (journald persistence + forwarding hooks). Secrets injected at converge time via AAP creds / `op inject`.

---

## 15. Repos & GitOps placement

- **`igou-openshift`** (Argo CD app-of-apps): the `hermes` Namespace, EgressFirewall, NetworkPolicies, `hermes-state` DataVolume, ValidatingAdmissionPolicy + binding, ImagePolicy, SCC binding, Tekton build pipeline. This spec lives here (`docs/superpowers/specs/`).
- **`igou-ansible`**: the `kubevirt.core` playbooks + the guest convergence roles + the dynamic inventory; surfaced as AWX/AAP job templates.

---

## 16. Phased implementation plan

1. **POC** — Argo guardrails (ns, EgressFirewall, NetworkPolicy, `hermes-state` DV, VAP, ImagePolicy) → Ansible creates the VM (30 GiB BIOS clone) + cloud-init → converge minimal (Hermes Quadlet → qwen3, one channel, manual approvals, `op` secrets). Validate end-to-end + red-team the blast radius (confirm the agent cannot reach the LAN, read cluster creds, or exfiltrate past the allowlist — incl. over an allowed channel).
2. **Harden** — egress proxy + DLP, out-of-band approvals, immutable/Git-gated skills, nftables, ACL-deny logging, scheduled state-DV snapshots, systemd sandboxing.
3. **Operate** — Tekton build + cosign + ImagePolicy enforcement, Renovate digest bumps, snapshot/restore drills, runbooks, cautiously expand channels/tools. Optionally add Falco and/or centralized logging.

---

## 17. Open items, risks & future options

- **No active runtime detection** (no RHACS/Falco/Loki) — accepted for now; Falco is the lightweight add-on if desired.
- **Secure Boot** is off (stock CentOS Stream 10 golden image is BIOS). To regain it later: build/import a **UEFI** CentOS Stream 10 image (ESP + signed shim) or switch the golden to a UEFI image; then re-enable `firmware.bootloader.efi.secureBoot` + `features.smm.enabled` (nodes support it) and optionally vTPM/measured boot.
- **Clone strategy** — root must clone at golden size; document the online-expand procedure for growth. If snapshot-clone proves fragile, switch the VM-root StorageProfile to `clone=copy`.
- **First cluster VM** — Hermes will be the first VM booted on this cluster; expect to shake out CNV/storage edge cases during POC.
- **Messaging channel** selection (and its egress allowlist entry) is an operator config decision at POC time — start with one low-trust channel.
- **Hermes code-exec model** (in-guest subprocess vs nested container) to confirm against the repo; affects sizing and the in-guest sandbox.
- **Live migration** disabled (RWO state); revisit with RWX state if node-maintenance downtime is unacceptable.

---

## 18. References

- Generic threat model & substrate analysis: `scratch/hermes-agent-deployment-security.html` (rev 3).
- Hermes `SECURITY.md`: github.com/NousResearch/hermes-agent.
- Cluster verification performed live on `ocp.igou.systems`, 2026-06-14 (this spec's §2).
