## ZFS snapshot/clone rescue of cluster PVs before a destructive op

> Source of truth: the 2026-07-03 `ocp` cluster-reinstall incident. Every command,
> path, and gotcha below was taken from the ACTUAL procedure used to rescue the
> hermes agent's persistent volumes off TrueNAS before/while the cluster was rebuilt.
> Verified against live TrueNAS state on 2026-07-04 (clones + snapshots still present).

### Purpose

Take a crash-consistent, near-instant, zero-cost **ZFS snapshot** of the democratic-csi
zvols that back cluster PVCs, **clone** those snapshots into stable writable zvol devices,
loop/direct-mount them **read-only**, and **stream the contents off-box** (tar → zstd over
ssh) to durable storage — so PV data survives a destructive operation (cluster reinstall,
disk wipe, risky migration) even when the cluster's etcd/PV bindings are gone.

The live cluster is NOT required for any of this. The zvols live on TrueNAS
(`truenas.igou.systems`) and outlive the OpenShift install completely. In the incident the
cluster was already destroyed (etcd overwritten) yet all PV zvols were intact and fully
recoverable by this procedure.

### When to use

- **Before** any operation that can wipe a node/disk or orphan PVs: agent-based reinstall,
  netboot reprovision, TrueNAS pool surgery, democratic-csi driver migration, one-way app
  data migrations (SQLite/MariaDB schema upgrades — same reflex as the pre-Renovate
  `zfs snapshot -r ssd/containers@<tag>` habit).
- **After** a disaster, to extract still-valuable data from old zvols whose PVCs no longer
  exist in the new cluster (block-mode data recovery, fingerprinting orphaned zvols).
- Any time you want a portable, filesystem-agnostic backup of a PVC's contents that can be
  restored into a freshly-created (different-UUID, possibly different-size) PVC.

### Prerequisites

- **Read-only SSH to TrueNAS** with NOPASSWD sudo:
  `SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes truenas_admin@truenas.igou.systems`
  - Use `truenas_admin@truenas.igou.systems` — **NOT** `igounas.igou.systems` (that is an
    nginx vhost VIP and rejects the key). Remote shell is **zsh** (avoid bare `===` in
    unquoted echos).
  - In the devcontainer the forwarded ssh-agent often wedges — always prefix `SSH_AUTH_SOCK=`
    and pass `-o IdentitiesOnly=yes -i ~/.ssh/id_ed25519`.
- **PVC → zvol mapping.** democratic-csi zvols live at `<pool>/k8s/vols/pvc-<uuid>` on the
  `ssd`, `fast`, and `cold` pools. While the cluster is alive, get the handle from
  `oc get pv <name> -o jsonpath='{.spec.csi.volumeHandle}'`. After a disaster, fingerprint
  orphaned zvols by mounting them ro and inspecting content (the incident's `/tmp/idvol.sh`
  helper looped `blkid`/`file -s`/`ls` over `/dev/zvol/<pool>/k8s/vols/*`). A catalog of the
  survivors is at `/workspace/backups/ocp-pv-catalog-20260703.txt`
  (`<pool>/k8s/vols/pvc-… | size mtime | TYPE=/PTTYPE=`).
- **Durable landing space for the stream:** the devcontainer's `/workspace/backups/` — it is
  bind-mounted from the host and **survives container rebuilds**. Do NOT stage multi-GB
  backups in `/tmp` or anywhere on the container filesystem (ephemeral, lost on rebuild).
- `zstd` available on the devcontainer (it is), and enough free space on `/workspace`.

Known mapping from the incident (for reference):

| Role         | Live PVC zvol                              | Layout                    | Clone                          |
|--------------|--------------------------------------------|---------------------------|--------------------------------|
| hermes root  | `ssd/k8s/vols/pvc-bf4dc3cf-…` (10.8G)       | **GPT**, p2 = xfs @ 2097152 | `ssd/k8s/rescue-hermes-root`   |
| hermes state | `ssd/k8s/vols/pvc-2d19e419-…` (7.53G)       | **whole-zvol xfs** (no PT) | `ssd/k8s/rescue-hermes-state`  |

(hermes root pvc-bf4dc3cf was itself a clone of the `centos-stream10` golden DataSource
zvol `pvc-5831f710`, which is why it carries a GPT image layout instead of a raw xfs.)

### Step-by-step (real commands, real hosts/paths)

All `zfs`/`mount`/`losetup`/`tar` commands run **on TrueNAS** (over the ssh above); the final
stream is initiated **from the devcontainer** so the bytes land on `/workspace`.

**1. Snapshot the target zvols — do this FIRST, before the destructive op.**
Snapshots are atomic, instantaneous, and cost 0B until the source diverges.

```
# per-zvol (what the incident used):
sudo zfs snapshot ssd/k8s/vols/pvc-bf4dc3cf-4cb3-4e9b-9c85-942c35e4ee89@rescue-20260703
sudo zfs snapshot ssd/k8s/vols/pvc-2d19e419-f817-4194-87b0-c5d68c6fee0a@rescue-20260703

# OR grab EVERY pvc on a pool at once (recursive), mirroring the pre-Renovate habit:
sudo zfs snapshot -r ssd/k8s/vols@rescue-20260703
```

**2. Clone each snapshot into a stable, writable zvol device.**
Cloning gives a friendly `/dev/zvol` path decoupled from the live PVC zvol, and a device you
can safely loop-mount without any risk to the source.

```
sudo zfs clone ssd/k8s/vols/pvc-bf4dc3cf-…@rescue-20260703 ssd/k8s/rescue-hermes-root
sudo zfs clone ssd/k8s/vols/pvc-2d19e419-…@rescue-20260703 ssd/k8s/rescue-hermes-state
```

The clones appear as:
```
/dev/zvol/ssd/k8s/rescue-hermes-root  -> ../../../zd576
/dev/zvol/ssd/k8s/rescue-hermes-state -> ../../../zd624
```

**3. Determine each clone's on-disk layout (decides how you mount it).**

```
sudo blkid  /dev/zvol/ssd/k8s/rescue-hermes-state   # -> TYPE="xfs"  (whole-zvol fs)
sudo sgdisk -p /dev/zvol/ssd/k8s/rescue-hermes-root  # -> GPT: part 2 (8300) starts sector 4096
```

Two cases observed:
- **Whole-zvol xfs** (block-mode PVC): `blkid` reports `TYPE=xfs` directly on the zvol.
  Mount the zvol device itself.
- **GPT image** (cloned from an OS golden image): `sgdisk -p` shows part 1 = `EF02`
  (BIOS boot, 1024 KiB) and part 2 = `8300` Linux at **start sector 4096** →
  byte offset `4096 * 512 = 2097152`. The xfs root lives inside part 2; mount via a loop
  device at that offset.

**4a. Mount the whole-zvol xfs clone directly, read-only.**

```
sudo mkdir -p /mnt/rescue-state
sudo mount -o ro,norecovery /dev/zvol/ssd/k8s/rescue-hermes-state /mnt/rescue-state
```

**4b. Loop-mount the GPT clone's partition 2 at offset 2097152, read-only.**

```
sudo mkdir -p /mnt/rescue-root
sudo losetup -f --offset 2097152 --read-only /dev/zvol/ssd/k8s/rescue-hermes-root
sudo losetup -a                                   # find it, e.g. /dev/loop1: (/dev/zd576), offset 2097152
sudo mount -o ro,norecovery /dev/loop1 /mnt/rescue-root
# (equivalent: `losetup -fP --read-only <clone>` to auto-scan, then mount /dev/loopNp2)
```

`-o norecovery` is mandatory here — see gotchas. Both mounts end up as:
```
/dev/zd624  on /mnt/rescue-state type xfs (ro,relatime,norecovery,…)
/dev/loop1  on /mnt/rescue-root  type xfs (ro,relatime,norecovery,…)
```

**5. Verify you mounted the right thing.**

```
sudo ls /mnt/rescue-state      # SOUL.md  auth.json  config.yaml  bin  cache …
sudo ls /mnt/rescue-root/home  # hermes …
df -h /mnt/rescue-root /mnt/rescue-state
```

**6. Stream the contents off-box (tar → zstd over ssh) into `/workspace/backups`.**
Run from the devcontainer so bytes land on the durable bind-mount. tar the directory
**contents** (portable — restores into any freshly-created PVC), zstd on all cores locally.

```
mkdir -p /workspace/backups/hermes

# state clone -> archive
SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes truenas_admin@truenas.igou.systems \
  "sudo tar -C /mnt/rescue-state --numeric-owner -cf - ." \
  | zstd -T0 -o /workspace/backups/hermes/hermes-state-20260703.tar.zst

# root clone -> archive
SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes truenas_admin@truenas.igou.systems \
  "sudo tar -C /mnt/rescue-root --numeric-owner -cf - ." \
  | zstd -T0 -o /workspace/backups/hermes/hermes-home-root-20260703.tar.zst
```

`--numeric-owner` preserves guest uids (hermes = uid 1001) that don't exist in TrueNAS'
passwd. Result sizes from the incident: state 11.9G raw → 4.09G .zst; root 6.8G raw → 4.92G .zst.

**7. Verify archive integrity.**

```
zstd -t /workspace/backups/hermes/hermes-state-20260703.tar.zst
zstd -t /workspace/backups/hermes/hermes-home-root-20260703.tar.zst
```

### Where the rescue artifacts live

- **Clones (on TrueNAS, still present):** `ssd/k8s/rescue-hermes-root` (→ `/dev/zd576`),
  `ssd/k8s/rescue-hermes-state` (→ `/dev/zd624`).
- **Snapshots (on TrueNAS):** `…/pvc-bf4dc3cf-…@rescue-20260703`,
  `…/pvc-2d19e419-…@rescue-20260703` (created 2026-07-03 13:57).
- **Read-only mounts (on TrueNAS):** `/mnt/rescue-root` (loop1), `/mnt/rescue-state` (zd624).
- **Off-box archives (devcontainer, durable):**
  `/workspace/backups/hermes/hermes-home-root-20260703.tar.zst`,
  `/workspace/backups/hermes/hermes-state-20260703.tar.zst`.
- **Orphan-zvol catalog:** `/workspace/backups/ocp-pv-catalog-20260703.txt`.

### Verification

```
# snapshots exist
sudo zfs list -t snapshot -o name,creation | grep rescue
# clones exist and point at the right snapshot origin
sudo zfs list -o name,origin,volsize -t volume | grep rescue
# mounts are read-only
mount | grep -E 'rescue-(root|state)'
# archives pass integrity check
zstd -t /workspace/backups/hermes/*.tar.zst
# (optional) compare a known file's content between mount and the extracted tar
sudo sha256sum /mnt/rescue-state/SOUL.md
```

### Rollback / cleanup

Only after per-app restore is fully confirmed. Order matters: **unmount → detach loop →
destroy clone → destroy snapshot**. A snapshot with a live dependent clone will not
`zfs destroy` (unless `-R`, which would also nuke the clone). Never touch the live
`…/vols/pvc-*` zvol.

```
sudo umount /mnt/rescue-root /mnt/rescue-state
sudo losetup -d /dev/loop1
sudo rmdir  /mnt/rescue-root /mnt/rescue-state          # optional

sudo zfs destroy ssd/k8s/rescue-hermes-root            # clone first
sudo zfs destroy ssd/k8s/rescue-hermes-state
sudo zfs destroy ssd/k8s/vols/pvc-bf4dc3cf-…@rescue-20260703   # then snapshot
sudo zfs destroy ssd/k8s/vols/pvc-2d19e419-…@rescue-20260703
```

> NOTE: as of 2026-07-04 these clones/snapshots/mounts are STILL PRESENT — the incident note
> reads "Clean these up after full restore." Do not destroy them until every intended per-app
> PV restore is verified against the new cluster.

**Restoring the data back into a PVC.** The tar-of-contents restores filesystem-agnostically:
- **Block-mode (xfs) PVC:** create the PVC, run a temp pod with it as a raw
  `volumeDevices`/`volumeDevice` (block), `mkfs.xfs` the device, `mount`, extract the tar,
  unmount. (This is exactly how hermes-state was rehydrated — vdb formatted xfs, essential
  `.hermes` extracted, `./containers` excluded as regenerable.)
- **Byte-exact alternative:** `dd if=/dev/zd624 of=…` (or into the new zvol) for an exact
  image — larger, and only works if the target zvol matches size/layout.

### Gotchas & pitfalls (from this incident)

1. **Snapshot FIRST, decide later.** It is atomic, instant, and 0B. Reach for
   `zfs snapshot -r <pool>/k8s/vols@<tag>` to capture every PVC on a pool before any
   destructive op — same reflex as the pre-Renovate `zfs snapshot -r ssd/containers@<tag>`.
2. **Whole-zvol xfs vs GPT image — always check before mounting.** Block-mode PVCs are raw
   xfs on the whole zvol (mount directly). A zvol cloned from an OS golden image
   (e.g. hermes root ← `centos-stream10` golden `pvc-5831f710`) is **GPT-partitioned**; you
   must loop-mount part 2 at **offset 2097152**. Run `blkid` / `sgdisk -p` first — guessing
   wrong wastes time.
3. **xfs read-only mount of an unclean filesystem REQUIRES `-o norecovery`.** The clone's log
   is dirty (the cluster died uncleanly). Without `norecovery`, a `ro` mount errors out
   because xfs wants to replay the log (which it can't do read-only). `norecovery` skips
   replay so the ro mount succeeds — and ro (plus operating on a clone, never the live zvol)
   guarantees the source of truth is untouched.
4. **Shared xfs UUID across clones of the same golden image** can cause a mount collision
   (duplicate-UUID). Mount them one at a time, or add `-o nouuid`.
5. **Wrong TrueNAS hostname fails silently-ish.** Use `truenas_admin@truenas.igou.systems`,
   not `igounas.igou.systems` (nginx VIP rejects the key). Remote shell is zsh.
6. **Devcontainer ssh-agent wedges** — always `SSH_AUTH_SOCK= … -o IdentitiesOnly=yes
   -i ~/.ssh/id_ed25519`.
7. **Stage backups on `/workspace/backups` only** — it is a durable host bind-mount. `/tmp`
   and the container FS are ephemeral (lost on rebuild); a multi-GB archive there would
   vanish exactly when you need it.
8. **`--numeric-owner` on tar** — guest uids (hermes 1001) aren't in TrueNAS' passwd; without
   it you lose ownership on restore.
9. **Prefer tar-of-contents over `dd` of the block device** for the general case — it is
   smaller and restores into a re-created PVC that may have a new fs UUID or different size.
   Reserve `dd` for when you need a byte-exact image into an identically-sized target.
10. **`virtctl port-forward` is unreliable for multi-GB single streams** (websocket 1006
    drops around the ~5-minute mark). The ssh + tar + zstd path straight off the TrueNAS host
    is the dependable large-transfer route; when forced through a port-forward, exclude bulky
    regenerable data (e.g. `./containers` podman image storage) to keep the stream short.
11. **Operate ONLY on the clone device** (`/dev/zvol/ssd/k8s/rescue-*` → `zdNNN`), never on
    the live PVC zvol (`/dev/zvol/ssd/k8s/vols/pvc-*`). The clone is the safety layer; the
    whole point is to keep the live zvol pristine.
