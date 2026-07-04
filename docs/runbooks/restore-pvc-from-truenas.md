## Restore a PVC / persistent volume from TrueNAS

> Runbook derived strictly from the 2026-07-03 `ocp.igou.systems` cluster-reinstall incident.
> Every command, path, hostname, zvol name and PVC id below is what was actually used to
> recover the `hermes-state` PV and to identify/preserve the file-app zvols (jellyfin et al.)
> after the cluster's etcd was wiped by an unattended agent-based reinstall.

### Purpose

When an OpenShift cluster is lost/rebuilt (or a single PVC is corrupted/deleted), the underlying
persistent data usually still lives on TrueNAS as democratic-csi zvols. This runbook covers how to:

1. **Rescue** an old zvol (snapshot + clone) so nothing can destroy it while you work.
2. **Identify** which orphaned `pvc-<uuid>` zvol belongs to which app by content fingerprint.
3. **Restore** that data into a freshly-provisioned PVC, using the exact methods that worked this
   session — including the awkward case of a **block-mode PVC attached to a KubeVirt VM**
   (`hermes-state`), a **filesystem PVC for a normal pod** (jellyfin pattern), byte-exact `dd`,
   and low-copy **static import** of the zvol as a new PV.

### When to use

- A cluster rebuild left blank/fresh PVCs but the old data is intact on TrueNAS (this incident).
- A single app's PVC was deleted or corrupted and its old zvol is still present.
- You need to migrate a specific app's on-disk state onto a new cluster/namespace.

**Why the old data survives at all (important):** all democratic-csi StorageClasses here are
`reclaimPolicy: Delete`. The old zvols only survived because **etcd was wiped** — with no PV
objects left, the CSI controller never issued a `DeleteVolume`, so the zvols were simply orphaned
on TrueNAS (nothing GC'd them). On a *healthy* cluster, deleting the PVC/PV **will** destroy the
zvol. That is exactly why Step 1 (snapshot + clone) comes first.

### Prerequisites

- **Cluster access:** `export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig`
  (this session's kubeconfig; never use `~/.kube/*` — all stale).
- **TrueNAS shell (read + zfs):**
  `SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 truenas_admin@truenas.igou.systems`
  (host is `truenas.igou.systems`, **not** `igounas.igou.systems` which is an nginx VIP and rejects
  the key). Remote shell is **zsh**, sudo is NOPASSWD. Long-running ZFS jobs: `midclt call --job ...`
  (double-dash `--job`; `-job` errors).
- **Backups / catalog on the devcontainer:**
  - `/workspace/backups/ocp-pv-catalog-20260703.txt` — full `pool/k8s/vols/pvc-<uuid> | size | mtime | fs-type` list.
  - `/workspace/backups/hermes/hermes-state-20260703.tar.zst` (11.9G raw = `~/.hermes` contents, xfs-level tar).
  - `/workspace/backups/hermes/hermes-home-root-20260703.tar.zst` (hermes `/home` non-`.hermes`).
- **`virtctl`** on PATH (for the KubeVirt-VM case).
- **democratic-csi layout:** managed volumes live at `<pool>/k8s/vols/pvc-<uuid>` where pool ∈
  `ssd` / `fast` / `cold`. Default StorageClass is `freenas-nvmeof-ssd-csi`. democratic-csi tags each
  managed zvol with `democratic-csi:*` ZFS user properties — inspect with
  `zfs get all <dataset> | grep democratic-csi` (this is also how the old PVC→zvol map is recoverable).

---

### Step 1 — Rescue the old zvol (snapshot + clone) BEFORE touching anything

Pin the data with a recursive snapshot, then clone it to a **stable, human-named** dataset you can
mount read-only. Cloning (vs. mounting the live zvol) means the app can never write through it and a
stray `DeleteVolume` on the original can't take your rescue copy with it.

```bash
# on truenas.igou.systems (sudo, NOPASSWD)
# example: old hermes-state = pvc-2d19e419 (xfs, 7.53G), old hermes-root = pvc-bf4dc3cf (gpt)

sudo zfs snapshot ssd/k8s/vols/pvc-2d19e419-f817-4194-87b0-c5d68c6fee0a@rescue-20260703
sudo zfs snapshot ssd/k8s/vols/pvc-bf4dc3cf-4cb3-4e9b-9c85-942c35e4ee89@rescue-20260703

# clone to a friendly, mountable name (these are what were used this session)
sudo zfs clone ssd/k8s/vols/pvc-2d19e419-...@rescue-20260703 ssd/k8s/rescue-hermes-state
sudo zfs clone ssd/k8s/vols/pvc-bf4dc3cf-...@rescue-20260703 ssd/k8s/rescue-hermes-root
```

Mount the clones **read-only**. A clone of a zvol shows up as a block device under
`/dev/zvol/<clone-path>` (and a `/dev/zdNNN` node — e.g. `ssd/k8s/rescue-hermes-state` = `/dev/zd624`):

```bash
sudo mkdir -p /mnt/rescue-state /mnt/rescue-root

# bare filesystem zvol (hermes-state is raw xfs, no partition table) → mount directly, ro:
sudo mount -o ro /dev/zvol/ssd/k8s/rescue-hermes-state /mnt/rescue-state

# PARTITIONED zvol (hermes-root is GPT — the data was on partition 2) → expose partitions first:
sudo losetup -Pf /dev/zvol/ssd/k8s/rescue-hermes-root   # creates e.g. /dev/loop1 with loop1p2
sudo mount -o ro /dev/loop1p2 /mnt/rescue-root          # this session: "loop1 = root p2"
```

> Clean these up only **after** the full restore is verified: `umount`, `zfs destroy` the clones, then
> `zfs destroy` the `@rescue-20260703` snapshots. Leave the original `pvc-*` zvols in place.

---

### Step 2 — Identify which old zvol belongs to which app (content fingerprint)

After a rebuild you have dozens of anonymous `pvc-<uuid>` zvols and no PVC→zvol map (etcd is gone).
Fingerprint them by mounting each read-only and listing the top level. This session used a helper
(`/tmp/idvol.sh` on truenas) that, for every `*/k8s/vols/pvc-*`:

1. Reads the fs type: `sudo blkid /dev/zvol/<ds>` / `sudo file -s /dev/zvol/<ds>`
   (the catalog's `TYPE=xfs|ext4` / `PTTYPE=gpt|dos` column comes from this).
2. If it's a **bare fs** → `mount -o ro` and `ls`.
3. If it's **partitioned** (`PTTYPE=gpt|dos`) → `losetup -Pf` (or `kpartx -a`), mount the data
   partition ro, `ls`.
4. Records size + mtime + top-level directory names as the fingerprint, then unmounts.

Confirmed mappings from this incident (full list: `/workspace/backups/ocp-pv-catalog-20260703.txt`):

| App / data | Old zvol | FS | Fingerprint (top-level) |
|---|---|---|---|
| **jellyfin** config | `pvc-3f5e1c03-b542-4103-b911-a700f680d3c2` | ext4 | `config/ data/ log/ metadata/ plugins/` |
| **hermes-state** | `pvc-2d19e419-f817-4194-87b0-c5d68c6fee0a` | xfs | `SOUL.md auth.json config.yaml` (candidate `pvc-2a75b3ea` also xfs) |
| **hermes-root** | `pvc-bf4dc3cf-4cb3-4e9b-9c85-942c35e4ee89` | gpt | clone of centos-stream10 golden `pvc-5831f710` |

> Old `pgdata`/DB zvols were **not** needed — those databases (quay/rhdh/forgejo) were restored from
> Barman/RustFS backups instead of from their zvols. Only clearly-valuable file-app zvols (jellyfin)
> justify a per-app restore; most file-app data is regenerable (model caches, queues, git-mirror).

---

### Step 3 — Restore the data (pick the method that matches the PVC)

#### 3A. Block-mode PVC attached to a KubeVirt VM — the `hermes-state` case (the method actually used)

`hermes-state` is a **block-mode** 30Gi PVC (`freenas-nvmeof-ssd-csi`) attached to the `hermes`
KubeVirt VM as disk **`vdb`**. It comes up **blank/unformatted** from a fresh provision. Restore is
done **inside the guest**, not with a temp pod.

1. Provision the VM (creates + attaches the blank `hermes-state` PVC as `vdb`):

   ```bash
   ansible-playbook playbooks/hermes/provision-vm.yml \
     -e host=localhost \
     -e vm_ssh_authorized_key="$(cat ~/.ssh/id_ed25519.pub)" \
     -e kubeconfig="$KUBECONFIG"
   ```

2. Reach the VM. Ingress is blocked by the `hermes-deny-ingress` (deny-all) NetworkPolicy, so use
   `virtctl port-forward` — it rides the **control-plane path and bypasses the NetworkPolicy**:

   ```bash
   virtctl port-forward vmi/hermes -n hermes 12222:22 &
   ssh -p 12222 -i ~/.ssh/id_ed25519 igou@localhost
   ```

3. Inside the guest, format and mount the blank block device:

   ```bash
   sudo mkfs.xfs /dev/vdb                 # blank PVC; this session got UUID 431c7ecf
   sudo mkdir -p /mnt/restore
   sudo mount /dev/vdb /mnt/restore
   ```

4. **Stream + extract the backup, EXCLUDING the regenerable `./containers` podman storage.**
   The tar is xfs *contents* (not a raw image), so extract into the mounted fs. `./containers` is
   ~10.5G of podman image storage the agent re-pulls on convergence — excluding it is what let the
   transfer fit past the port-forward's size limit (see next note). ~1.4G of essential state was
   restored (`auth.json config.yaml SOUL.md agent-config dashboard cron memory`), owner **uid 1001**
   preserved:

   ```bash
   # from the devcontainer, piping the backup into the guest over ssh
   zstd -dc /workspace/backups/hermes/hermes-state-20260703.tar.zst \
     | ssh -p 12222 -i ~/.ssh/id_ed25519 igou@localhost \
         'sudo tar -x --exclude=./containers --numeric-owner -C /mnt/restore'
   ```

   **Port-forward is flaky for large single streams** (websocket drops with code 1006 after ~5 min).
   Two levers were used: (a) shrink the payload via `--exclude=./containers`; (b) for bulk transfer,
   temporarily allow direct SSH to the VM's pod IP with a short-lived **allow-ingress** NetworkPolicy,
   then delete it. Representative temp policy (match the virt-launcher pod's labels; delete when done):

   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: temp-allow-ssh-restore
     namespace: hermes
   spec:
     podSelector:
       matchLabels:
         kubevirt.io/vm: hermes      # verify against the live virt-launcher pod labels
     policyTypes: [Ingress]
     ingress:
       - ports:
           - port: 22
             protocol: TCP
   ```

   ```bash
   # transfer straight to the VM pod IP while the temp policy is up, then REMOVE it:
   POD_IP=$(oc get vmi hermes -n hermes -o jsonpath='{.status.interfaces[0].ipAddress}')
   zstd -dc /workspace/backups/hermes/hermes-state-20260703.tar.zst \
     | ssh -i ~/.ssh/id_ed25519 igou@${POD_IP} \
         'sudo tar -x --exclude=./containers --numeric-owner -C /mnt/restore'
   oc delete networkpolicy temp-allow-ssh-restore -n hermes   # restores deny-all ingress
   ```

5. Unmount cleanly so the data lands on the zvol, then let convergence take over:

   ```bash
   sudo umount /mnt/restore
   ```

   Convergence's `setup-os.yml` remounts this device at `/home/hermes/.hermes` and **skips mkfs**
   (`force=false`) because it is already xfs — so the pre-populated state survives.

> **Do NOT stop/start the hermes VM until the NVMe hostnqn bug (Gotchas) is fixed** — a stop/start
> re-triggers the duplicate-hostnqn attach failure.

#### 3B. Filesystem PVC for a normal pod — the jellyfin pattern (scale-to-0 + helper pod, tar-over-`oc exec`)

For `jellyfin-config` (`pvc-3f5e1c03`, ext4) restore into a fresh filesystem PVC without the VM machinery:

1. **Freeze Argo automated sync on BOTH `root-applications` (owns the child app spec) and the app
   itself** — otherwise selfHeal rescales the deployment mid-copy.
2. Scale the workload to 0: `oc scale deploy/jellyfin -n jellyfin --replicas=0`.
3. Launch a helper pod mounting the target PVC. **Pin `runAsUser`/`fsGroup` to the namespace's
   uid-range** (e.g. `1000950000`) — cluster-admin helper pods land in the `anyuid` SCC with no UID
   injection, so a `runAsNonRoot` image otherwise fails.
4. Copy the old data in via a tar stream (mirrors the biscuit→OCP migration: `ssh tar | oc exec`):

   ```bash
   # from truenas rescue clone → helper pod, over oc exec stdin (avoids flaky port-forward)
   ssh -i ~/.ssh/id_ed25519 truenas_admin@truenas.igou.systems \
       'sudo tar -C /mnt/rescue-<app> -cf - .' \
     | oc exec -i -n jellyfin <helper-pod> -- tar -xf - -C /config
   ```

5. Restore Argo automated on both apps; selfHeal rescales the deployment back to 1.

> Prefer `oc exec` stdin streaming or the temp-netpol SSH path over `virtctl port-forward` for
> anything more than a few GB.

#### 3C. Byte-exact raw copy (`dd` the clone into the block device)

When you want a byte-for-byte restore (same fs/UUID, block PVC), attach the fresh block PVC to a
pod/VM and `dd` the rescue clone straight in. Sizes must match.

```bash
# stream the rescue clone device from truenas into the VM's blank block disk
ssh -i ~/.ssh/id_ed25519 truenas_admin@truenas.igou.systems \
    'sudo dd if=/dev/zvol/ssd/k8s/rescue-hermes-state bs=4M' \
  | ssh -p 12222 -i ~/.ssh/id_ed25519 igou@localhost 'sudo dd of=/dev/vdb bs=4M'
```

This was the documented byte-exact alternative to 3A's tar method; 3A was preferred because it lets
you exclude the regenerable `./containers` and doesn't require size parity.

#### 3D. Static-import the old zvol as a PV (lowest-copy, most fiddly)

Instead of copying, present the existing zvol to the new cluster as a statically-provisioned PV and
bind a PVC to it. Steps: `zfs get all <dataset> | grep democratic-csi` to read the driver metadata,
then hand-author a `PersistentVolume` with the democratic-csi `csi:` block (`driver`,
`volumeHandle` = the existing dataset, matching `volumeAttributes`, `volumeMode`) and
**`persistentVolumeReclaimPolicy: Retain`** so a later delete can't destroy it, plus a matching PVC.
The session preferred copy-based restores (3A/3B) over this because the nvmeof/iscsi `volumeHandle`
and attributes must be reconstructed exactly.

---

### Verification

- **Zvol / clone health (truenas):** `zfs list -t all | grep -E 'rescue|pvc-<uuid>'`;
  `blkid /dev/zvol/<clone>` shows the expected fs (`xfs`/`ext4`).
- **hermes-state (3A):** after mount, `ls -la /mnt/restore` shows `auth.json config.yaml SOUL.md
  agent-config dashboard cron memory` (NOT `containers`), owned by uid **1001**;
  `xfs_admin -u /dev/vdb` (or `blkid`) reports the expected UUID; clean `umount` returns 0.
- **PVC bound & attached:**
  `oc get pvc -n hermes hermes-state` → `Bound` to a `pvc-<uuid>` on `freenas-nvmeof-ssd-csi`;
  `oc get vmi hermes -n hermes` running with `vdb` attached.
- **App-level (jellyfin 3B):** after rescale, the app reports its restored identity/library and file
  counts match the fingerprint (this session verified 3318 files / 323M for the biscuit migration).
- **Ingress locked back down:** `oc get networkpolicy -n hermes` shows `hermes-deny-ingress` present
  and `temp-allow-ssh-restore` **absent**.

### Rollback

- The original `pvc-<uuid>` zvols are **never modified** (all writes go to the *clone* or to the *new*
  PVC), so rollback is: destroy the new/failed target and re-clone from the `@rescue-20260703`
  snapshot. `zfs rollback` is available on the original because the snapshot exists.
- If a restore into a PVC goes wrong: unmount, `oc delete pvc` (fresh data only — the source zvol is
  untouched), re-provision, retry.
- Always keep the rescue clones and snapshots until the app is verified healthy; tear them down only
  at the end (`umount /mnt/rescue-*`; `losetup -d /dev/loop1`; `zfs destroy ssd/k8s/rescue-hermes-*`;
  `zfs destroy <orig>@rescue-20260703`).

### Gotchas & pitfalls (from this incident)

- **`reclaimPolicy: Delete` is a data-loss trap.** All democratic-csi SCs here are `Delete`. Old
  zvols survived *only* because etcd was wiped (no PV → no `DeleteVolume`). Deleting a live PVC/PV
  **destroys** the zvol. Always snapshot + clone first; set static-imported PVs to `Retain`.
- **`virtctl port-forward` drops on big transfers.** Websocket dies with code 1006 after ~5 min on a
  multi-GB single stream. Mitigations: exclude regenerable data (`--exclude=./containers`), or add a
  temporary allow-ingress NetworkPolicy and SSH straight to the VM pod IP, then delete the policy.
- **Restore the deny-all NetworkPolicy afterward.** `temp-allow-ssh-restore` must be deleted so
  `hermes-deny-ingress` is back in force.
- **Block PVC comes up blank.** A fresh block-mode PVC is unformatted — `mkfs.xfs /dev/vdb` yourself;
  convergence's `setup-os.yml` will then *skip* mkfs (`force=false`) and keep your data.
- **Exclude podman/container storage.** `./containers` in the hermes tar is ~10.5G of regenerable
  image cache; excluding it is both faster and what made the transfer fit. The agent re-pulls on
  convergence.
- **Preserve ownership.** Extract with `--numeric-owner`; hermes state is uid **1001**. For pod
  helper restores, pin `runAsUser`/`fsGroup` to the namespace uid-range (`anyuid` SCC does no UID
  injection).
- **Partitioned vs. bare zvols mount differently.** Raw-fs zvols (hermes-state = xfs) mount directly;
  GPT/DOS zvols (hermes-root) need `losetup -Pf` (or `kpartx`) and you mount the data partition
  (`loop1p2` this session).
- **🚨 Duplicate NVMe hostnqn/hostid across all 3 nodes.** All nodes share
  `nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28` (baked by the agent
  install). This causes intermittent nvme-of attach failures ("unable to attach any nvme devices" /
  "Connect command failed error 6") when a second node connects to the same subsystem, and risks
  corruption. It directly hit the hermes VM's second nvmeof disk during restore. Workaround that
  worked: retry, and recreate the PVC if it stays stuck (`hermes-state` was recreated fresh →
  `pvc-46858de9`). Real fix pending: per-node MachineConfig regenerating `/etc/nvme/hostnqn`
  (`nvme gen-hostnqn`) + `/etc/nvme/hostid` (`uuidgen`) + rolling reboot. **Until fixed, do not
  stop/start the hermes VM.**
- **DBs restore from Barman, not zvols.** Don't waste time on old `pgdata` zvols — quay/rhdh/forgejo
  were recovered from RustFS/Barman object-store backups; their zvols are stale.
- **TrueNAS host name & shell quirks.** SSH to `truenas.igou.systems` (not `igounas.igou.systems`);
  remote shell is zsh; ZFS job methods need `--job` (double dash).
- **Stale local repo checkout.** `/workspace/igou-openshift` is far behind origin — use
  `git fetch origin` + `git show origin/main:<path>` when authoring/applying manifests; `oc kustomize`
  from the stale tree renders old specs.
