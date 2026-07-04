# Rebuild the Hermes agent VM and restore its state

## Purpose

Recreate the `hermes` KubeVirt VM (the Nous Hermes autonomous agent) on the
`ocp.igou.systems` cluster and restore its persistent `~/.hermes` state from a
TrueNAS/tar backup, after a disaster that destroyed the VM (or after the whole
cluster was reinstalled). This runbook covers the exact procedure used during the
2026-07-03 cluster-reinstall recovery: provision a fresh VM from the
`centos-stream10` golden image, work around the shared-`hostnqn` NVMe-oF attach
flakiness, load the state disk with the backed-up agent state, and hand off to the
operator for the still-deferred guest convergence and go-live.

This gets the VM **provisioned, running, and holding restored state**. It does
**not** converge Hermes (install/configure) or bring the agent online — those stay
operator-gated (see "What stays operator-deferred").

## When to use

- The `hermes` VM was deleted/lost (disaster, node loss, or full cluster reinstall)
  and needs to be rebuilt from scratch.
- The Argo `hermes-agent` app (GitOps guardrails) is already Synced/Healthy so the
  namespace, DataVolumes, NetworkPolicies, EgressFirewall, and the VAP exist, but
  no VM is running.
- You have the `hermes-state` tar backup available and want the agent's
  identity/config/memory restored (not a blank agent).

Do **not** use this to converge or start the agent — that is a separate,
operator-driven step.

## Prerequisites

- **Cluster access** — the session kubeconfig only, per standing directive:
  ```bash
  export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig
  ```
  All three nodes must be `Ready` (`ocp.igou.systems`/10.10.9.10 control-plane,
  `hpg5.igou.systems`, `truenas-w1`/10.10.9.21).

- **GitOps guardrails present** — the Argo `hermes-agent` application
  (`applications/hermes-agent/` in `github.com/igou-io/igou-openshift`) is
  Synced/Healthy, so these objects already exist in ns `hermes`:
  - blank `hermes-state` DataVolume (30Gi, `freenas-nvmeof-ssd-csi`, Block mode)
  - NetworkPolicies `hermes-deny-ingress` + `hermes-egress`
  - EgressFirewall `default`
  - ValidatingAdmissionPolicy `hermes-vm-hardening` (masquerade-only, no
    hostDevices/GPU/passthrough — the provision spec must conform or CREATE/UPDATE
    is rejected).
  Verify:
  ```bash
  oc get application hermes-agent -n openshift-gitops -o jsonpath='{.status.sync.status} {.status.health.status}{"\n"}'
  oc get dv,networkpolicy,egressfirewall,validatingadmissionpolicy -n hermes
  ```

- **centos-stream10 golden DataSource is `Ready`** — the provision playbook clones
  it. On this cluster it lives in `openshift-virtualization-os-images`:
  ```bash
  oc get datasource centos-stream10 -n openshift-virtualization-os-images \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'   # -> True
  ```
  (Golden image is **BIOS-only** — the provision spec pins `vm_firmware: bios`;
  Secure Boot is intentionally dropped.)

- **Ansible repo** — `/workspace/igou-ansible` (`github.com/igou-io/igou-ansible`),
  playbook `playbooks/hermes/provision-vm.yml` (thin wrapper over the
  `kubevirt_vm_provision` role). Collections/roles installed
  (`ansible-galaxy install -r requirements.yml`); `kubevirt.core` +
  `kubernetes.core` available. The playbook is `connection: local` and authenticates
  to the cluster via `$KUBECONFIG`.

- **Seeded SSH key** — the local keypair `~/.ssh/id_ed25519` /
  `~/.ssh/id_ed25519.pub`; the `.pub` is seeded into cloud-init as the `igou` admin
  user's authorized key (non-secret). The private key is used for the post-boot
  restore SSH session.

- **State backup present** on the devcontainer:
  ```
  /workspace/backups/hermes/hermes-state-20260703.tar.zst      # ~4.9G file, 11.9G raw = ~/.hermes (auth.json/config.yaml/SOUL.md/…)
  /workspace/backups/hermes/hermes-home-root-20260703.tar.zst  # ~4.9G file, 6.8G raw = /home/hermes non-.hermes (see note)
  ```
  `zstd -t` the archive first. (Original source was TrueNAS zvol clones
  `ssd/k8s/rescue-hermes-{root,state}` snapshotted at `@rescue-20260703`; the tars
  are the extracted, verified copies.)

- `virtctl` on PATH (mise) for the port-forward SSH path.

## Step-by-step

### 1. Confirm the blank state disk exists and is Bound

The `hermes-state` PVC is an Argo-owned **blank** DataVolume (Block mode). This is
the disk that survives VM delete/rebuild and holds `~/.hermes`.

```bash
oc get pvc hermes-state -n hermes \
  -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,VOL:.spec.volumeName,MODE:.spec.volumeMode
# hermes-state  Bound  pvc-46858de9-...  Block
oc get dv hermes-state -n hermes    # PHASE Succeeded
```

If it is not Bound / not present, let Argo reconcile it (it is defined in
`applications/hermes-agent/hermes-state-datavolume.yaml`; do **not** hand-create
it — it is GitOps-managed). Note whether you will be restoring into a **fresh**
blank disk (see step 3 note on the NVMe workaround).

### 2. Provision the VM

Seed your public key and run the provision playbook. It clones `centos-stream10`
at golden size (30Gi, **no resize** — CDI smart-clone deadlocks on resize),
burstable 4c/8Gi, masquerade networking (VAP-conforming), BIOS firmware, and
attaches the existing `hermes-state` PVC as a plain data disk (`/dev/vdb` in the
guest). Cloud-init creates the `igou` admin user with your key and enables the
qemu-guest-agent; **no secrets, no convergence.**

```bash
cd /workspace/igou-ansible
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig

ansible-playbook playbooks/hermes/provision-vm.yml \
  -e host=localhost \
  -e "vm_ssh_authorized_key=$(cat ~/.ssh/id_ed25519.pub)" \
  -e kubeconfig="$KUBECONFIG"
```

- The playbook is idempotent; a re-run with no change reports `changed=0`.
- To force a destructive rebuild of an existing VM **while preserving the
  `hermes-state` data PVC**, add `-e rebuild=true` (maps to the role's
  `vm_rebuild`; deletes the VM + root DV, keeps attached `vm_extra_pvcs`).
  Never pass `vm_destroy_data` for hermes-state — it is Argo/CDI-owned and wiping
  it fights Argo.

Watch it come up (it must land on a single node; both disks attach there):

```bash
oc get vm,vmi -n hermes
# VM hermes Running True ; VMI hermes Running <podIP> <node>  (e.g. 10.129.0.36 hpg5.igou.systems)
oc get vmi hermes -n hermes -o jsonpath='{.status.guestOSInfo.prettyName}{"\n"}'   # CentOS Stream 10
```

### 3. If disk attach flakes — the shared-hostnqn NVMe-oF bug

**Symptom.** The VM's second `freenas-nvmeof-ssd` disk (the state disk) fails to
attach while the root disk is fine; VMI stays `Scheduling`/not-Ready. Node journal
shows `nvme ... Connect command failed error 6` / `failed to write to
nvme-fabrics device` / "unable to attach any nvme devices".

**Root cause (latent, cluster-wide, still unfixed).** All three RHCOS nodes were
baked with the **identical** NVMe host identity by the agent-based install:

```bash
for n in 10.10.9.10 hpg5.igou.systems 10.10.9.21; do
  echo -n "$n: "; SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new \
    core@$n 'sudo cat /etc/nvme/hostnqn'
done
# all three return: nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28
```

NVMe-oF requires a **unique** `hostnqn`/`hostid` per host. When a second node
connects to the same TrueNAS target subsystem with the same `hostnqn` that another
node already holds a controller for, the connect is rejected → intermittent
attach failures (and a data-corruption risk).

**Workaround used this session (gets hermes up now):**

1. **Retry.** The attach is intermittent — deleting the failing `virt-launcher`
   pod / letting KubeVirt retry (or a `rebuild=true` re-provision) eventually wins
   as controllers free up.
2. **Recreate the blank state PVC to get a clean nvmeof subsystem.** Deleting the
   `hermes-state` DataVolume/PVC and letting Argo/CDI re-provision a fresh blank
   one allocates a **new TrueNAS zvol/target namespace** (fresh subsystem NQN),
   sidestepping the stale-controller conflict. This is exactly why the live state
   PVC is `pvc-46858de9` (recreated), not the original. Because it comes back
   **blank and unformatted**, you then restore into it (step 4).

> Recreating the state PVC discards whatever was on it — fine here, because we
> restore from the tar backup anyway. If the disk held un-backed-up data, snapshot
> or copy it first.

**Permanent fix (deferred — see below).** A MachineConfig that regenerates unique
`/etc/nvme/hostnqn` (`nvme gen-hostnqn`) + `/etc/nvme/hostid` (`uuidgen`) per node
followed by a rolling reboot. Do **not** stop/start the hermes VM casually until
this is fixed — every re-attach re-rolls this dice.

### 4. Restore `~/.hermes` state onto the (blank) state disk

The state disk presents in the guest as **`/dev/vdb`** (Block-mode PVC). A freshly
recreated PVC is unformatted; the old state was XFS.

**4a. Open an SSH path into the VM.** `hermes-deny-ingress` drops all inbound
except tcp/22 from the `ansible-automation-platform` namespace, so a direct SSH
from the devcontainer is blocked. Use the control-plane `virtctl port-forward`,
which tunnels through the API server and **bypasses the NetworkPolicy**:

```bash
virtctl port-forward vmi/hermes -n hermes 12222:22 &
ssh -p 12222 -i ~/.ssh/id_ed25519 -o IdentityAgent=none igou@localhost
```

(`IdentityAgent=none` because the forwarded agent socket flakes on signing; use the
key file directly.)

For the **bulk data transfer**, `virtctl port-forward` is unreliable for a
single >few-GB stream — the websocket drops (~1006) after ~5 min. This session
worked around it two ways, both used: (a) trimmed the payload so it fits the window
(step 4c excludes `./containers`), and (b) added a **temporary allow-ingress
NetworkPolicy** on tcp/22 for the transfer, then **deleted it** afterward so
`deny-ingress` is fully restored. If you add the temp policy, remove it the moment
the transfer completes:

```bash
# (temporary) allow ingress :22 for the transfer, e.g. temp-allow-ssh-restore
# ... run the transfer ...
oc delete networkpolicy temp-allow-ssh-restore -n hermes    # restore deny-ingress
```

**4b. Format and mount the state disk** (only if the PVC was recreated blank):

```bash
# inside the VM, as igou (sudo)
sudo mkfs.xfs /dev/vdb            # skip if already xfs
sudo mkdir -p /mnt/state && sudo mount /dev/vdb /mnt/state
```

**4c. Extract the essential state, excluding regenerable container storage.**
`./containers` inside the tar is the rootless Podman image store (~10.5G) — the
agent re-pulls it on convergence, so exclude it (this is also what keeps the
transfer inside the port-forward window). Preserve ownership (agent runs as
uid 1001):

```bash
# stream the backup from the devcontainer into the VM over the SSH path, extracting
# into the mounted state disk, dropping the container image store:
zstd -dc /workspace/backups/hermes/hermes-state-20260703.tar.zst \
  | ssh -p 12222 -i ~/.ssh/id_ed25519 -o IdentityAgent=none igou@localhost \
      'sudo tar -x --numeric-owner --exclude=./containers -C /mnt/state'
```

Restored (~1.4G): `auth.json`, `config.yaml`, `SOUL.md`, agent-config, dashboard,
cron, memory — owner uid 1001 preserved.

**4d. Unmount cleanly** so the data is durably on the PVC. The convergence's
`setup-os.yml` later remounts `/dev/vdb` at `/home/hermes/.hermes` and, because the
filesystem is already XFS, its `community.general.filesystem` task runs with
`force: false` and **skips mkfs** — the pre-formatted, pre-populated disk survives.

```bash
sudo umount /mnt/state
```

Then tear down the temporary access: kill the `virtctl port-forward`, and delete
any temp allow-ingress NetworkPolicy you created (4a).

> `/home/hermes` non-`.hermes` content (agent-repos/workspace) lived on the
> **non-persistent root disk** pre-disaster and is not restored here — it is
> agent-regenerable. `hermes-home-root-20260703.tar.zst` holds it if any of it is
> wanted later.

## Verification

```bash
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig

# VM running, guest agent connected, both disks attached, VAP-admitted:
oc get vm,vmi -n hermes
oc get vmi hermes -n hermes -o jsonpath='{.status.phase}  {.status.nodeName}  {.status.guestOSInfo.prettyName}{"\n"}'

# State PVC bound (the recreated one), 30Gi, Block:
oc get pvc hermes-state -n hermes -o custom-columns=STATUS:.status.phase,VOL:.spec.volumeName,MODE:.spec.volumeMode

# Guardrails intact:
oc get networkpolicy hermes-deny-ingress hermes-egress -n hermes
oc get egressfirewall default -n hermes -o jsonpath='{.status.status}{"\n"}'

# Inside the VM (via port-forward SSH): state disk XFS, populated, uid 1001:
#   sudo blkid /dev/vdb                 -> TYPE="xfs"
#   sudo mount /dev/vdb /mnt/state && ls -la /mnt/state    # auth.json config.yaml SOUL.md ...
#   stat -c '%u' /mnt/state/auth.json   -> 1001
```

Success = VM `Running`/Ready on a single node, guest agent up, `hermes-state`
Bound and holding the restored XFS state, and `deny-ingress` back in force with no
lingering temp NetworkPolicy or port-forward.

## Rollback

This runbook creates only the VM (and, if needed, a fresh blank state PVC); it does
not converge or start the agent, so "rollback" is limited and safe.

- **Undo the VM** without touching state data:
  ```bash
  # via the playbook, preserving hermes-state:
  ansible-playbook playbooks/hermes/provision-vm.yml -e host=localhost -e rebuild=true \
    -e "vm_ssh_authorized_key=$(cat ~/.ssh/id_ed25519.pub)" -e kubeconfig="$KUBECONFIG"
  # or just delete the VM (root DV goes, hermes-state stays — it is a plain PVC):
  oc delete vm hermes -n hermes
  ```
- **Bad restore / want a clean disk again:** delete the `hermes-state`
  DataVolume/PVC, let Argo re-provision a fresh blank one (also re-rolls the NVMe
  subsystem), then redo step 4. The tar backup is untouched and re-usable.
- **Always remove temporary access artifacts** on abort: kill any
  `virtctl port-forward`, `oc delete networkpolicy temp-allow-ssh-restore -n hermes`.
- **Never** delete or hand-edit the Argo-owned guardrail objects to "fix" a
  problem — let GitOps own them.

## Gotchas & pitfalls (from this incident)

- **All 3 nodes share one NVMe `hostnqn`/`hostid`** (`...466937ab...`) — the #1
  cause of state-disk attach flakiness and a latent data-corruption risk. Verified
  still true post-recovery on all of 10.10.9.10 / hpg5 / 10.10.9.21. Workaround:
  retry + recreate the blank state PVC (fresh nvmeof subsystem). Real fix
  (deferred): per-node MachineConfig regenerating unique hostnqn/hostid + rolling
  reboot. **Avoid gratuitous stop/start of the hermes VM until fixed.**
- **Recreated state PVC comes back blank + unformatted** — you must `mkfs.xfs
  /dev/vdb` and re-extract; convergence's `setup-os.yml` only formats when the
  device is unformatted (`force: false`), so it will preserve an already-XFS,
  populated disk — that is by design, don't re-mkfs it.
- **`deny-ingress` blocks devcontainer SSH** — it only allows tcp/22 from the AAP
  namespace. Use `virtctl port-forward vmi/hermes` (API-server path, bypasses
  NetworkPolicy). For bulk transfer, port-forward's websocket drops on a large
  single stream (~1006 after ~5 min) → exclude `./containers` (~10.5G, regenerable)
  and/or add a *temporary* allow-ingress NetworkPolicy and delete it right after.
- **VM guest clock must be UTC.** A skewed/local-time guest clock breaks TLS
  validation (against the OpenShift router / api.telegram.org / the in-cluster LLM)
  and desyncs journald; `setup-os.yml` installs+enables `chrony` for this
  (pre-rebuild the hermes VM was observed ~24h behind). This is the same class of
  bug that bit the sibling `truenas-w1` RHCOS worker VM during this reinstall: its
  hypervisor `time` was set to **local**, the guest RTC ran ~4h behind, and
  Ignition's `GET api-int:22623/config/worker` failed x509 "certificate not yet
  valid" because the MCS serving cert's valid-from was the (later) reinstall time —
  fixed by setting the VM `time: UTC` and restarting. **Guest VMs in this cluster
  must run their clock as UTC.**
- **`vm_ssh_authorized_key` must be supplied** — provision-vm.yml defaults it to
  empty and cloud-init only writes `ssh_authorized_keys` when it is non-empty; a
  blank value yields a VM you cannot SSH into. The key must land on the **`igou`**
  user (the cloud-init `user:` is `igou`), matching the convergence machine
  credential — not the image default `cloud-user`.
- **Clone at golden size, no resize** — CDI smart-clone deadlocks on resize with
  the democratic-csi nvmeof volume-populator; `vm_root_size: 30Gi` matches the
  golden image. Grow online later if ever needed.
- **BIOS, not UEFI/Secure Boot** — the stock `centos-stream10` golden image is
  BIOS-only; the spec pins `vm_firmware: bios`. Requesting SB/UEFI (or
  hostDevices/GPU/non-masquerade) trips the `hermes-vm-hardening` VAP on
  CREATE **and** UPDATE.
- **Local repo checkouts are STALE** — for `igou-openshift` read from
  `git show origin/main:<path>` rather than the working tree.

## What stays operator-deferred

Everything past "VM running with restored state" is intentionally **not** done by
this runbook:

- **Guest convergence** — `playbooks/hermes/{setup-os,setup-hermes,configure}.yml`
  (install Hermes, mount `/dev/vdb`→`~/.hermes`, render `config.yaml`/`.env`,
  nftables egress backstop, hardened `hermes-gateway.service` +
  `hermes-dashboard.service`). These run **in-cluster via the AAP
  `hermes-converge-e2e` workflow** (the devcontainer can't reach the masquerade pod
  IP), and are gated on the operator's manual EgressFirewall OPEN→LOCKED git commits
  in igou-openshift. `configure.yml` needs the in-cluster LLM (llmkube) up and the
  1Password-sourced env (`.env`, dashboard basic-auth) supplied as extra-vars.
- **Go-live** — enabling/starting `hermes-gateway.service`, Telegram, re-locking
  egress, tearing down any temp LB/Route, and 1Password-sourcing the dashboard auth
  are all held for the operator. Do **not** auto-enable the agent service.
