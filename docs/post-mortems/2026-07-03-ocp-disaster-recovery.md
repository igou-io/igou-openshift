# Post-mortem: 2026-07-03 `ocp` Cluster Disaster & Recovery

> Compiled 2026-07-04 from a multi-agent review (Claude, Opus 4.8). Each section
> below was authored by a dedicated expert reviewer or professional persona.
> Companion documents: [`2026-07-03-component-reviews.md`](./2026-07-03-component-reviews.md)
> (per-component health/functionality) and the runbooks under
> [`../runbooks/`](../runbooks/).

## Contents
- [Executive Summary](#executive-summary)
- [Incident Timeline, Root Causes & Mistakes](#incident-timeline-root-causes-mistakes)
- [GitOps Repository Review](#gitops-repository-review)
- [Ansible Repository Review](#ansible-repository-review)
- [Architecture & Environment Review](#architecture-environment-review)
- [Perspective: Kubernetes / OpenShift Administrator](#perspective-kubernetes-openshift-administrator)
- [Perspective: Site Reliability Engineer](#perspective-site-reliability-engineer)
- [Perspective: Software Engineer](#perspective-software-engineer)
- [Perspective: Virtualization Administrator](#perspective-virtualization-administrator)
- [Perspective: Database Administrator](#perspective-database-administrator)
- [Perspective: Code & Process Readability](#perspective-code-process-readability)
- [Consolidated Action Items](#consolidated-action-items)

---

## Executive Summary

On 2026-07-03 the single-control-plane OpenShift cluster `ocp` (control plane on MS-01 = `10.10.9.10`, OCP 4.21.9; workers `hpg5` + the `truenas-w1` KubeVirt VM; `p330` permanently dead) was **destroyed by a self-inflicted netboot reinstall**. MS-01 firmware boots the network before its local disk, and a per-host iPXE pin on the rb5009 router — armed since a 2026-05-11 netboot migration and left defaulting to `install-openshift` on a 30-second timeout — had sat as a latent landmine for roughly seven weeks. A routine unattended reboot was all it took: the agent-based installer wiped the 990 PRO, and its own mid-install reboot re-entered PXE and reinstalled again, turning a single wipe into a self-amplifying loop that only broke when an operator manually flipped the pin to `local` at the exact `status=installing` moment. etcd and all local control-plane state were unrecoverable; the cluster identity was gone. Detection was entirely human — the in-cluster alerting pipeline dies with the cluster it monitors, so **MTTD was effectively unbounded**.

Recovery was a manual tour de force by a single expert operator: regenerate the agent-install PXE artifacts, break the reinstall loop (pin default → `local`, `inv#120`), reinstall 4.21.9, re-seed the out-of-band bootstrap secrets (1Password Connect credentials + token), re-bootstrap OpenShift GitOps / ArgoCD app-of-apps + External Secrets, re-join both workers (hpg5 by PXE, truenas-w1 by node-image ISO), and restore persistent data — Hermes agent state from a zstd-verified tar and the quay / rhdh / forgejo CloudNativePG databases from Barman backups on RustFS. Approximate timeline: **~2.3h to a live API, ~5h to workers + core apps, 12h+ to substantially-restored data.** Two genuine DR bugs in the bootstrap playbook were found and merged mid-incident (`ansible#312`), and the netboot pin default fix (`inv#120`) makes this exact trigger non-recurring.

**Outcome: the cluster is healthy and no committed data was permanently lost** — all cluster operators `Available`, 3/3 nodes `Ready`, the Hermes VM Running with state restored, and the rhdh/forgejo/quay databases restored with real data (backstage 119 tables; forgejo 128 tables / 356 repos; quay 103 + clair 31). But recovery succeeded **despite the design, not because of it**: it leaned on luck (the democratic-csi zvols survived because only MS-01 was wiped, RustFS could be un-wedged in time, and one operator held the entire undocumented runbook in their head). A repeat of the same unattended reboot — or any loss of the single TrueNAS box that holds every zvol, every Barman backup, the boot artifacts, and truenas-w1 itself — would land very differently.

**The five most important takeaways:**

1. **A latent NVMe-oF identity collision is the single biggest correctness risk on the cluster and is still unfixed.** All three nodes were baked with the identical `/etc/nvme/hostnqn`/`hostid` (`…466937ab…`), and — deeper than the incident record captured — the democratic-csi node plugin overrides that with its *own* image-baked NQN (`941e4f03…`) that is likewise identical on every node. This violates NVMe-oF host uniqueness, already paused the Hermes VM once during recovery, and carries a genuine filesystem-corruption risk. The host-only MachineConfig fix is necessary but **not sufficient** — the CSI node plugin must also inherit the per-node identity.

2. **The settings that made the cluster recoverable live only on the running cluster, not in git.** The ArgoCD repo-server tuning (`cpu=2`, `ARGOCD_EXEC_TIMEOUT=3m`) and the PushSecret/ExternalSecret health-checks — the exact patches that un-stalled the wave gate and the repo-server timeouts during DR — are hand-applied to a playbook-created ArgoCD CR and absent from git. The next bootstrap re-run silently reverts them, reintroducing the very stalls that cost hours this time.

3. **Several stateful restores are committed as one-shot recovery mode, which is a silent data-loss trap.** All three CNPG databases still carry `bootstrap.recovery` in `origin/main` pointed at the pre-disaster archive; a Cluster recreate would silently roll them back to the 2026-07-02 snapshot (and forgejo additionally came up serving an *empty* database with its 356 repos orphaned and its git filesystem never restored). This needs to be reverted to a steady state and guarded before the next rebuild.

4. **There is no cluster-state backup and no external detection.** No etcd snapshot, no OADP/Velero (the operator is in-repo but disabled), no off-cluster heartbeat, and backups that share a failure domain with primary storage. The netboot trigger is fixed, but the *class* of "unattended reboot wipes a node" survives (firmware is still netboot-first, the install menu still defaults to install on a timeout), and if it recurs the detection would again be a human noticing.

5. **The runbooks lag the operator's knowledge — in two places they point the next engineer at the wrong thing.** The committed DR runbook names the stale, drifted bootstrap playbook (not the one recovery actually used), the destructive-pin root cause and the mid-install "flip to local" step are undocumented, and the shared-hostnqn bug lives only in a memory file. Recovery was repeatable by *one* person; making it repeatable by *any* engineer is the difference between a resilient system and a fragile one.

---

## Incident Timeline, Root Causes & Mistakes

Single-control-plane OpenShift cluster `ocp.igou.systems` (control plane on MS-01 = `10.10.9.10`; workers `hpg5` + `truenas-w1` KubeVirt VM; `p330` dead/no-BMC) was **destroyed by a stale netboot pin that auto-reinstalled the control-plane node**, wiping etcd and all local disk state. The cluster was fully rebuilt on 4.21.9 and all high-value persistent data restored from TrueNAS. At the time of writing the cluster is healthy (`ClusterVersion 4.21.9 Available`, all 3 nodes `Ready`, hermes VM `Running`, rhdh/forgejo CNPG DBs `healthy`, quay-pg still `Setting up primary`).

### Timeline (times UTC, 2026-07-03)

| Time | Event |
|---|---|
| 2026-04-23 | OpenShift PXE install artifacts staged on the boot server (latent). |
| 2026-05-11 | Netboot migration arms rb5009 pin `netboot/per-host/MAC-5847ca77098a.ipxe` **defaulting to `install-openshift` on a 30s timeout** — the landmine sits armed for ~7 weeks. |
| ~17:00 | **Unattended reboot of MS-01.** UEFI BootOrder is netboot-first (PXE I226-V → PXE I226-LM → disk LAST, 3s), the pin's 30s default fires `install-openshift`, and the agent-based installer wipes the 990 PRO. Mid-install reboot re-enters PXE → **reinstall loop** (installs forever). Old cluster is unrecoverable (etcd/state overwritten). PV zvols on TrueNAS survive. |
| (recovery) | hermes state rescued off old zvols before touching anything: `hermes-home-root-20260703.tar.zst` (6.8G) + `hermes-state-20260703.tar.zst` (11.9G), `zstd -t` verified, from snapshot clones `ssd/k8s/rescue-hermes-{root,state}`. Pull secret recovered from the live installer host. |
| (recovery) | Fresh 4.21.9 PXE artifacts regenerated via `playbooks/openshift/agent-install/deploy_pxe_assets.yml` (bypassing dead 1Password via `-e @override.yml` + `--skip-tags op-save`), uploaded to TrueNAS nginx boot dir; safe pin (default `local`) staged. |
| 18:24 | **Loop broken:** pin flipped to default-`local` at `status=installing`. |
| 18:31 | Mid-install reboot boots FROM DISK (not PXE) — loop is dead. |
| ~18:38 | Control-plane node `Ready`; CVO climbing toward 4.21.9. |
| ~19:20 | **Install complete:** `ClusterVersion 4.21.9 Available`. 21 essential Argo apps applied, 28 non-essential deferred (`igou-openshift#383` merged); `inv#120` merged (pin default `local` — durable fix). |
| (recovery) | User supplies a working "dr" 1Password service-account token (all 5 vaults); secrets re-seeded (`op-credentials`, `onepassword-connect-token`). GitOps re-bootstrapped via `playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`; 2 real bugs found + fixed + merged (`ansible#312`). ArgoCD root-applications + 21 apps Synced. |
| ~21:51 | **Both workers re-joined** (`hpg5` by PXE add-node, `truenas-w1` by `oc adm node-image` ISO). CSR-approval column bug (below) cost ~40 min here. |
| (recovery) | Waves restored in order by un-commenting `clusters/ocp/values.yaml` blocks: wave 1 stateless/CAPI/CNV/tenants (`#384`), wave 2 observability (`#385`), wave 3 hermes-agent (`#386`) + CNPG DB restores from Barman (`#387`/`#388`) + all remaining file apps + AAP (`#389`). All 49 apps re-enabled in git. |
| (recovery) | hermes VM re-provisioned fresh; state PV re-formatted xfs and 1.4G of essential `.hermes` restored from backup (excluding regenerable `./containers`). |

### Root Causes

**Technical**
- **Boot order + destructive default.** MS-01 boots network before disk (disk is LAST, 3s), and the per-host iPXE pin's *default* menu entry was the destructive `install-openshift` on a 30s timeout. Any reboot with no operator at the console self-selects a full disk-wiping reinstall.
- **Agent installer is unconditionally destructive and self-looping.** It wipes the target disk on entry, and its own mid-install reboot re-enters PXE → the installer runs again. There is no "already installed, boot local" guard — the loop only breaks by flipping the pin to `local` *while* `status=installing`.
- **Latent NVMe identity collision (separate but cluster-wide).** The agent-based install baked the **same** `/etc/nvme/hostnqn` and `/etc/nvme/hostid` (`nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28`) into **all three** RHCOS nodes — confirmed live on `10.10.9.10`, `hpg5`, and `10.10.9.21`. This violates NVMe-oF host-identity uniqueness and causes intermittent volume-attach failures (it bit the hermes state disk during restore). Still unfixed.

**Process**
- **The pin was never disarmed after the original install.** Left defaulting to `install-openshift` since the 2026-05-11 netboot migration — a ~7-week armed landmine with no expiry and no alarm.
- **No off-cluster etcd/control-plane backup.** Only PV zvols survived, and only because democratic-csi's backing store lives on TrueNAS, not on the node. Cluster identity (etcd) had no recovery point — the rebuild was a fresh install, not a restore.
- **Single control plane = single point of total loss.** Wiping the one master is game-over; there is no HA quorum to survive one node.
- **No alerting** that a production control-plane node's netboot pin pointed at a destructive install, nor that its boot order preferred network over disk.

### What Went Well

- **Data survived and was recoverable.** Democratic-csi zvols on TrueNAS were untouched by the node wipe; `p330`'s death and the MS-01 wipe cost no persistent data.
- **Backups existed and were verified.** hermes state was captured to `zstd`-verified tarballs *before* any restore action; CNPG Barman backups on RustFS enabled clean DB recovery (rhdh 111 tables, forgejo 128 tables, quay WAL-replaying) via `bootstrap.recovery` + `externalClusters` barman plugin.
- **GitOps made config reproducible.** The app-of-apps pattern meant the entire application tier (49 apps) was rebuilt by un-commenting `values.yaml` blocks and letting ArgoCD reconcile — no hand-rebuilding. The "rebuild from original" trick (`git show <defer-commit>^:...values.yaml`, re-comment only still-deferred apps) made staged restore clean.
- **The loop was broken correctly and durably.** Flipping the pin to `local` at `status=installing` (18:24) stopped the reinstall loop, and `inv#120` merged the pin default to `local` so this exact failure cannot recur.
- **Recovery hardened the runbook.** Two genuine DR bugs in `bootstrap_gitops.yaml` were found, fixed, and merged (`ansible#312`: Connect JWT lives in the item's `credential` field not `token`; `onepassword_doc` returns bytes needing `|b64encode` + `data:` not `stringData`), plus `ansible#311` (publish path). Future DR runs are less fragile.
- **Workers rejoined largely unattended** once the CSR selector was corrected (monitor auto-approves the CSRs).

### Mistakes That Cost Time

1. **CSR condition parsed by wrong column — ~40 min (largest single loss).** The monitor used `awk '$5=="Pending"'` but `oc get csr` puts CONDITION in **column 6**, so it silently matched nothing while 9 node-bootstrapper CSRs piled up and both workers hung un-joined. *Prevent:* never positionally-`awk` `oc get` output; select on the API field — `oc get csr -o go-template='{{range .items}}{{if not .status}}{{.metadata.name}}{{"\n"}}{{end}}{{end}} | xargs oc adm certificate approve`.

2. **truenas-w1 VM guest clock in local time → x509 "cert not yet valid".** VM `time` was `LOCAL`, so the guest RTC ran ~4h behind and Ignition's `GET api-int:22623/config/worker` failed x509 because the MCS cert's valid-from was the reinstall time (18:23). Cost multiple restart/debug cycles. *Prevent:* provision KubeVirt/TrueNAS VMs with `time: UTC` (`midclt call vm.update <id> '{"time":"UTC"}'`); RHCOS assumes hwclock=UTC.

3. **truenas-w1 netboot RAW `.dsk` mechanism is broken.** A raw `netboot.xyz.efi` written to a disk device is not a valid ESP, so UEFI drops to the EFI shell instead of netbooting. Dead-end before switching to the working method (`oc adm node-image create --dir` → 1.4G ISO → attach as CDROM → full QEMU restart). *Prevent:* for TrueNAS `vm.*` workers use the node-image ISO/CDROM path; document the RAW-dsk approach as non-viable.

4. **STALE local checkout rendered OLD manifests.** `/workspace/igou-openshift` was ~100 commits behind, so `oc kustomize` from it produced obsolete YAML (quay got `initdb` instead of `recovery`). *Prevent:* always `git fetch` and apply from `git show origin/main:<path>` during DR; treat the local checkout as untrusted.

5. **CNPG recovery WAL-archive collision.** Recovery failed `WAL archive check failed: Expected empty archive` because the archiving plugin's `serverName` still pointed at the non-empty source path; also the stuck full-recovery Job had to be deleted so CNPG recreated it. Cost debugging on all three DBs (`#387`/`#388`). *Prevent:* on `bootstrap.recovery`, set the archiving `serverName` to a NEW value (`<db>-r<date>`) up front and `oc delete job -l cnpg.io/jobRole=full-recovery` after changing it.

6. **1Password share link burned on first load.** The first backup SA-token share link (view-once) was consumed by a headless-browser preflight load; the re-issued SA was then deleted server-side (403). *Prevent:* extract view-once share links on the FIRST real page load with clipboard capture; never pre-load them in a bot/preview.

7. **Recurring wave-gate stalls.** The app-of-apps gates wave N+1 on wave N *health*, so any transient operator-install degrade (service-accounts, grafana, cluster-api) or a slow repo-server render stalled the whole pipeline repeatedly. Two systemic fixes were needed live: patch ArgoCD `resourceHealthChecks` for the read-only-token PushSecret 403s (so `service-accounts` reports Healthy), and bump repo-server to cpu=2 + `ARGOCD_EXEC_TIMEOUT=3m` (heavy helm render of `clusters/ocp/` exceeded the default 90s on 1 CPU). *Prevent:* fold both patches into `hub-cluster/bootstrap_gitops.yaml` (they are currently LIVE-ONLY on a playbook-managed ArgoCD CR and will be lost on re-run).

8. **Boot-file permissions (rsync 750 → nginx 403).** `rsync -a` set the boot-files dir to 750; nginx returned 403 on the PXE artifacts until `chmod 755`. Small but on the critical install path. *Prevent:* `chmod 755` the publish dir after rsync (the `ansible#311` publish-path fix addresses this class).

9. **Large-file transfer over `virtctl port-forward` is flaky.** The WebSocket drops ~1006 after ~5 min on multi-GB single streams, which is why the hermes state restore had to exclude `./containers` (10.5G) to fit. Not fatal (containers are regenerable) but forced a workaround. *Prevent:* for byte-exact multi-GB restores, `dd` the old zvol clone directly rather than tar-over-port-forward.

### Still Open (carried into follow-ups)

- **Fix the shared NVMe hostnqn/hostid cluster-wide** (MachineConfig regenerating `/etc/nvme/hostnqn`+`hostid` where `==466937ab` + rolling reboot) — a real correctness bug; **do NOT stop/start the hermes VM until fixed.**
- Fold the live-only ArgoCD CR patches (PushSecret health-check + repo-server cpu/timeout) into `bootstrap_gitops.yaml`.
- Revert CNPG `bootstrap.recovery` → `initdb` in git once DBs confirmed healthy (so a future re-sync doesn't re-trigger recovery).
- Optional per-app file-PV restores from preserved old zvols (e.g. jellyfin config `pvc-3f5e1c03`); hermes convergence + operator-deferred go-live.

---

## GitOps Repository Review

Reviewer scope: the `igou-io/igou-openshift` app-of-apps repo as it stands at `origin/main`
(`d81e454`, all 49 apps re-enabled). Focus: the failure modes the 2026-07-03 control-plane
reinstall actually stressed — sync-wave gating, the ArgoCD instance config, CNPG
backup/restore state, the 1P Connect/ESO secret bootstrap, and the netboot/agent-install
coupling. Every finding below was cross-checked against the live cluster.

Findings are ranked by blast radius. Each is written to be a single, self-contained PR.

---

### 1. [CRITICAL — data-loss landmine + permanent drift] Three CNPG clusters are frozen in `bootstrap.recovery`

`applications/forgejo/forgejo-pg-cluster.yaml`, `components/quay-operator/quay-pg-cluster.yaml`,
and `components/rhdh/rhdh-pg-cluster.yaml` all still carry the disaster-recovery bootstrap in
git, with the `initdb` block commented out:

```yaml
bootstrap:
  recovery:
    source: forgejo-pg          # restores the pre-disaster Barman base backup
externalClusters:
  - name: forgejo-pg
    plugin:
      parameters:
        barmanObjectName: forgejo-pg-backup
        serverName: forgejo-pg          # <-- PRE-DISASTER archive path
```

Meanwhile the live cluster now **archives WAL to a *different* serverName**
(`serverName: forgejo-pg-r20260704`, confirmed on-cluster). Two distinct problems fall out
of this, both verified live:

**(a) Rebuild-time silent rollback.** `bootstrap` only runs when a `Cluster` is created from
scratch. If ArgoCD ever prunes+recreates the `Cluster` (namespace re-create, a bad prune, or
the next full DR), CNPG will re-bootstrap from `serverName: forgejo-pg` — the **frozen
2026-07-02 base backup** — and every byte written since the recovery is silently gone. The
recovery source points at the *old* archive, not the live `-r20260704` one the DB is writing
to now. This is the single most dangerous line in the repo.

**(b) Permanent `OutOfSync` today.** `.spec.bootstrap` is immutable after init; CNPG's webhook
has already defaulted the live object (`recovery: {database: app, owner: app, source: …}`) so
it no longer matches git. I confirmed the `forgejo` and `rhdh` ArgoCD apps are `OutOfSync`
for exactly one resource each — `Cluster/forgejo-pg` and `Cluster/rhdh-pg` — and they will
never converge because Argo cannot patch an immutable field back to the git shape.

**PR:** For all three clusters, (i) restore `bootstrap.initdb` as the desired rebuild state
(quay/registry, backstage, and forgejo are all cheaply re-seedable; or keep `recovery` **only
if** you repoint the recovery `serverName` to the live `-r20260704` archive so a rebuild
restores *current* data), and (ii) add an `ignoreDifferences` on `/spec/bootstrap` (and the
operator-defaulted `/spec/externalClusters/.../isWALArchiver`) for these apps so the immutable
live field stops holding the app `OutOfSync`. `gitea-pg` and `temporalio-pg` are already on
`initdb` — this revert is well-scoped to the three recovered DBs. Do **not** simply flip git
to `initdb` with no `ignoreDifferences` — that trades a landmine for a permanent SyncFailed.
Also unify the inconsistent sync-waves: `rhdh-pg` uses `sync-wave: '10'` while forgejo/quay
use `'-1'`.

---

### 2. [CRITICAL — cluster-wide correctness] All 3 nodes share one NVMe `hostnqn`/`hostid`, and no MachineConfig fixes it

Confirmed live on every node (`/etc/nvme/hostnqn` **and** `/etc/nvme/hostid`):

```
master 10.10.9.10  : nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28
hpg5               : nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28
truenas-w1 10.10.9.21: nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28
```

The agent-based install baked one NVMe host identity into every RHCOS node. NVMe-oF requires
uniqueness per host; this already caused the hermes state volume to fail to attach on a second
node during recovery and risks data corruption on the `freenas-nvmeof-*` storage classes the
whole cluster depends on. There is nothing in `clusters/ocp/machineconfigs/` addressing it.

**PR:** Add `clusters/ocp/machineconfigs/99-nvme-unique-host-identity-machineconfig.yaml` — a
systemd oneshot (Ignition) that, when `/etc/nvme/hostnqn` still contains `466937ab…`, runs
`nvme gen-hostnqn > /etc/nvme/hostnqn` + `uuidgen > /etc/nvme/hostid` and reboots. Ship it for
**both** `master` **and** `worker` roles.

**Related gap in the same PR:** `99-master-load-nvme-tcp-machineconfig.yaml` loads the
`nvme-tcp` module for the **master role only**, but nvmeof volumes attach on workers too (the
hermes state disk landed on hpg5). Add a worker-role counterpart, or collapse both into a
single all-roles MC. Cross-reference `docs/runbooks/nvmeof-stuck-multiattach.md` — the
control-plane `nodeSelector` pinning on every CNPG cluster is a *workaround* for this same
storage fragility.

---

### 3. [HIGH — the recovery-critical ArgoCD tuning is not in git at all]

The ArgoCD `argocd.argoproj.io/ArgoCD` CR is **absent from this repo** (`git grep 'kind: ArgoCD'`
→ nothing). It is created out-of-band by `igou-ansible` `bootstrap_gitops.yaml`. During the
incident two fixes were applied **live-only**, and I confirmed both are present on the running
CR but nowhere in git:

- `spec.repo`: `resources.limits {cpu: 2, memory: 2Gi}` + env `ARGOCD_EXEC_TIMEOUT=3m`. This
  was the root cause of the recurring "Unknown"/`context deadline exceeded` wave stalls — the
  helm render of `clusters/ocp/` blows past the default 90s on 1 CPU.
- `spec.resourceHealthChecks`: a lenient Lua health-check for `external-secrets.io/PushSecret`
  (and `ExternalSecret`) that reports `Healthy` even when the outbound 1P publish 403s.

Both evaporate the next time the bootstrap playbook runs — i.e. the exact tuning that let the
cluster converge during DR is the tuning most likely to be missing during the *next* DR.

**PR (in this repo, preferred):** Self-manage the ArgoCD CR via GitOps — add a wave-`0`
`openshift-gitops-config` Application (or a component under `clusters/ocp/`) that owns the
`ArgoCD` CR including the repo-server resources, `ARGOCD_EXEC_TIMEOUT`, and both health-checks.
Argo managing its own instance is the idiomatic fix and makes the tuning durable and reviewable.
(Fallback, if instance management must stay in Ansible: codify all three in
`bootstrap_gitops.yaml` — that's a companion PR for the ansible-repo reviewer.) Either way the
current state — the cluster's own controller config existing only as an un-versioned live patch
— is the biggest single process gap the incident exposed.

---

### 4. [HIGH — architecture] One monolithic health-gated app-of-apps serialized the entire recovery

`root-applications` renders all 43 child `Application`s from `clusters/ocp/values.yaml` with a
single monotonic `sync-wave` ladder (0 → 50). ArgoCD will not create/sync wave N+1 until every
wave-N `Application` is `Synced` **and** `Healthy`. In steady state that's fine; in DR it means
**any** degraded low-wave app freezes everything above it. The incident hit this hard:
`service-accounts` (wave 40) was `Degraded` on 403 PushSecrets → `openshift-virt` (wave 50) and
all higher waves could not even be created, and manually creating a gated app got pruned by the
root app. Recovery became a serial "fix wave, unstick, refresh, repeat" grind.

Three PR-sized improvements, in priority order:

1. **Codify the operator-bootstrap toil as a sync option.** The recurring manual pattern
   ("apply ns+OG+Subscription, wait CSV Succeeded, then sync with
   `SkipDryRunOnMissingResource=true`") exists because CR-consuming apps fail dry-run before
   their CRD is installed (CNV/HyperConverged→CDI→StorageProfile, cluster-api providers, quay,
   loki). Add `syncOptions: [SkipDryRunOnMissingResource=true]` to those specific apps in
   `values.yaml`. This is the highest-leverage, lowest-risk DR-toil reducer.
2. **Split the monolith into a few independent roots** — e.g. `platform` (operators/storage/
   networking, waves 0–12), `services` (observability/pipelines/tenants), `apps` (user
   workloads + CNPG). A failure in the apps tier then no longer gates platform reconvergence,
   and each root converges in parallel. Keep intra-root waves only where a real CRD/operator
   dependency exists.
3. **Rationalize the wave map.** Many apps share the same wave (six at wave 6, five+ at wave
   10, ~ten at wave 20) so the ordering is already coarse; document which crossings are real
   dependencies vs incidental, and drop waves that don't encode a true prerequisite so fewer
   apps can gate each other.

---

### 5. [MEDIUM — honesty of desired state] Broken-by-design PushSecrets are masked by a live-only health-check

`components/service-accounts/values.yaml` defines 6 `pushSecrets` (into vaults `ocp-push` and
`claude`) that **cannot succeed** — the Connect token is read-only, so every push 403s forever.
Today they're only "green" because of the live-only `PushSecret` Lua health-check (finding #3),
which is not in git. That's two layers of hidden state papering over a permanent failure.

**PR:** Make git tell the truth. Either (a) set `enabled: false` on those 6 pushSecrets in
values.yaml — the chart already gates on `if $push.enabled` (`.helm/charts/service-account-access/
templates/pushsecrets.yaml`), so this cleanly stops generating doomed resources; or (b) grant
Connect a write-scoped token for those vaults and keep them. Option (a) removes the dependency
on the out-of-band health-check patch entirely and is the honest representation of the
operator's stated choice to leave publishing off.

---

### 6. [MEDIUM — bootstrap ordering is undocumented in-repo] The whole tree hinges on two hand-seeded secrets

Everything under ESO — the `ClusterSecretStore`s
(`clusters/ocp/external-secrets-operator/onepassword-sdk-*.yaml`), every `ExternalSecret`, the
CNPG S3 creds, hermes — transitively depends on two secrets that must exist **before** GitOps
can converge, and which no manifest in the repo can create:

- `op-credentials` (ns `onepassword-connect`, key `1password-credentials.json`) — consumed by
  the Connect helm chart in `components/onepassword-connect/kustomization.yaml`
  ("pre-seeded out-of-band (Task 4)").
- `onepassword-connect-token` (ns `external-secrets-operator`, key `token`) — the Connect JWT.

This is architecturally correct (a chicken-and-egg root of trust), but it was a real recovery
blocker and the only record is the incident memory file. Two live bugs bit during DR and belong
in a checked-in runbook so the next operator doesn't rediscover them: the Connect JWT lives in
the 1P item's **`credential`** field (not `token`), and `onepassword_doc` returns **bytes** so
the k8s Secret needs base64 + `data:` (not `stringData`).

**PR:** Add `docs/runbooks/dr-secrets-bootstrap.md` documenting the exact seed order, the two
secret shapes/namespaces, and those two gotchas. No manifest change — this is the missing
"step 0" of every restore.

---

### 7. [MEDIUM — the actual root cause has no in-repo guardrail or runbook] netboot pin default

The disaster trigger (rb5009 per-host netboot pin defaulting to `install-openshift` on a 30s
timeout against a netboot-first MS-01) lives in `igou-inventory`/`igou-ansible`, not here, so
the fix is out of scope for this repo — but two things about it are in-scope:

- There is **no DR runbook** in `docs/runbooks/` for "control plane was wiped → reinstall →
  re-bootstrap GitOps → restore PVs." The entire blow-by-blow exists only in the session memory
  file. That sequence (regen agent-install PXE artifacts → flip pin to `local` → re-join workers
  + CSR-approve → `bootstrap_gitops.yaml` → CNPG Barman restore) should be a checked-in runbook,
  since it's now proven and will be needed again.
- Worth a one-line note in that runbook cross-referencing `igou-inventory#120` (pin default must
  be `local`): the highest-leverage prevention for the whole incident is a one-word default in
  another repo, and this repo's DR doc is the natural place to make that dependency visible.

---

### 8. [LOW — hygiene / consistency]

- **Root-app prune semantics.** `default.app.autoSyncPrune: false` plus the root app's own
  prune behavior explains why manually-created gated apps got pruned during DR. Document the
  root-applications prune model so operators don't fight it mid-incident.
- **Dated serverName is now permanent.** `serverName: <db>-r20260704` is a one-off DR string
  baked into git; the ObjectStore `destinationPath` prefix now accumulates two server dirs per
  DB (`…/forgejo-pg` and `…/forgejo-pg-r20260704`). Fine operationally, but note it in the CNPG
  runbook so the next restore knows which prefix is live.
- **DR failure-domain caveat is real.** `docs/runbooks/cnpg-backup-restore.md` already flags
  that the TrueNAS S3 backup target shares a failure domain with primary DB storage (same
  TrueNAS box). Combined with finding #1, a TrueNAS loss + a `Cluster` recreate is a
  double-jeopardy path worth an explicit off-box backup consideration.

---

### Fastest wins

If only three PRs get merged: **#1** (stop the CNPG rollback landmine — it's an active
`OutOfSync` today and a silent data-loss on the next rebuild), **#2** (unique NVMe host
identity — a confirmed cluster-wide correctness bug), and **#3** (get the ArgoCD repo-server
tuning + health-checks into git so the next DR converges instead of stalling). #4.1
(`SkipDryRunOnMissingResource` on operator apps) is the cheapest single change that would have
saved hours of manual unsticking during this recovery.

---

## Ansible Repository Review

Reviewed against `origin/main` @ `1a341c9` (local checkout was 35 commits stale;
all findings are on fetched `origin/main`, not the working tree). Scope: the
GitOps bootstrap, the netboot pin / agent-install PXE flow and its safety
defaults, the hermes convergence playbooks, and the drift between the *live*
ArgoCD CR and the playbook that renders it.

Files reviewed:
- `playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`
- `playbooks/openshift/bootstrap_openshift_gitops.yaml` (stale duplicate)
- `playbooks/openshift/agent-install/deploy_pxe_assets.yml`
- `playbooks/openshift/add_node_iso.yml`, `vm_worker_destroy.yaml`, `vm_worker_reprovision.yaml`
- `playbooks/openshift/templates/nodes-config.yaml.j2`
- `playbooks/netboot/deploy_assets.yml` + `tasks/{preflight,render_menu,push_pins_rb5009,verify}.yml` + `templates/{menu,host-mac,entry-chainload}.ipxe.j2`
- `playbooks/hermes/{setup-os,setup-hermes,configure,provision-vm}.yml` + `templates/hermes-egress.nft.j2`
- `docs/disaster-recovery.md`, `docs/openshift-operations.md`, `molecule/openshift-bootstrap-crc/converge.yml`

---

### CRITICAL

#### C1 — The DR runbook points operators at the WRONG, stale bootstrap playbook
`docs/disaster-recovery.md` (step 4, "Rebuild from scratch", line ~255) instructs:
```
ansible-playbook playbooks/openshift/bootstrap_openshift_gitops.yaml \
  -i igou-inventory/inventory.yaml -e target_cluster=<cluster>
```
But this session's recovery actually used **`playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`** — which is where the two 1Password-Connect bugs were found and fixed (PR #312). The referenced `bootstrap_openshift_gitops.yaml` was last touched **2026-04-11** (`954320c`) and is a pre-Connect relic. Following the DR doc verbatim during the next disaster fails hard:
- It has **neither fix**: it seeds a single `onepassword-token` Secret from an **undefined** `onepassword_token` var (no `vars_prompt`, no lookup), and never seeds the Connect `op-credentials` / `onepassword-connect` namespace at all.
- It parameterizes on **`cluster_name`**, not `target_cluster`; the doc's `-e target_cluster=<cluster>` leaves `cluster_name` undefined → the cluster-config kustomize lookup errors.
- It applies from the **old repo path** `config/<cluster>/live/base-config/`, not the current `clusters/<cluster>` app-of-apps layout.
- It puts the OperatorGroup in `openshift-operators`, not `openshift-gitops-operator`.

The same stale playbook is also wired into `molecule/openshift-bootstrap-crc/converge.yml` and cited in `docs/openshift-operations.md`, so CI is validating the wrong artifact.
**Fix:** delete/redirect `bootstrap_openshift_gitops.yaml` to the hub-cluster playbook, update the DR doc + openshift-operations doc + molecule converge to `playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`, and correct the invocation.

---

### HIGH

#### H1 — Live-only ArgoCD fixes are not folded back into the playbook CR (next bootstrap silently reverts them)
The ArgoCD CR is created imperatively by `hub-cluster/bootstrap_gitops.yaml` (not GitOps-managed), so any live edit persists only until the playbook is re-run — and the next DR re-runs it. Diffing the live `openshift-gitops` ArgoCD CR against the playbook shows two meaningful live-only deltas:

| Field | Playbook (git) | Live cluster (in-use) |
|---|---|---|
| `spec.repo.env` | `KUSTOMIZE_PLUGIN_HOME=/etc/kustomize/plugin` | `ARGOCD_EXEC_TIMEOUT=3m` |
| `spec.repo.resources.limits` | cpu `1` / mem `1Gi` | cpu `2` / mem `2Gi` |
| `spec.repo.resources.requests` | cpu `250m` / mem `256Mi` | cpu `500m` / mem `512Mi` |

Both are real reliability fixes for the app-of-apps sync: `ARGOCD_EXEC_TIMEOUT=3m` raises the repo-server's default 90s exec ceiling that the `kustomize build --enable-helm | envsub` CMP pipeline blows through (manifests "context deadline exceeded"), and the bumped repo-server resources prevent OOM during those helm-heavy builds. Note the playbook's `KUSTOMIZE_PLUGIN_HOME` on `repo.env` is largely inert anyway — the CMP **sidecar** already receives it via `envFrom` the `environment-variables` ConfigMap. **Fix:** set `repo.env` to include `ARGOCD_EXEC_TIMEOUT: 3m` (keep KUSTOMIZE_PLUGIN_HOME if desired) and raise `repo.resources` to 2 CPU / 2Gi in the playbook CR. (Minor, same CR: the `resourceCustomizations: | argoproj.io/Application: health.lua: |` block is empty and superseded by `resourceHealthChecks`; live has it empty — drop it.)

#### H2 — netboot per-host pins have no safe-default guard (this is the incident's root cause)
The shared fallback menu is safe-by-design: `templates/menu.ipxe.j2` uses
`choose --timeout 30000 --default local target || goto local` and a `:local` label that `sanboot`s the disk. **Per-host pins bypass that entirely** — `templates/host-mac.ipxe.j2` emits raw `{{ pin.fragment }}` from inventory with no wrapping. `tasks/preflight.yml` validates the MAC format and forces "Form 3 (fragment) only", but performs **zero content safety checks** on the fragment. A pin whose fragment auto-selects an install target on a short timeout with no local fallback — exactly what re-imaged MS-01 (`10.10.9.10`) when an unattended reboot hit the 30s install-default — passes every assertion. The recovery's "flip the pin to default-local" is a manual, undefended-in-code convention.
**Fix (highest-value safety change):** add a preflight assertion that every pin fragment either contains a local-boot default (`sanboot`/`goto local` as the `choose --default`) **or** carries an explicit opt-in like `allow_install: true`. Bonus: for any host that is already a joined cluster node, the pin should default-local — the agent-install/PXE path has no interlock preventing an install→reboot→install loop, which is what turned a single wipe into a loop.

---

### MEDIUM

#### M1 — Pin push is size-only idempotent and verify checks only presence → a corrected same-size pin is silently not deployed
`tasks/push_pins_rb5009.yml` re-uploads a pin **only when the router file size differs** (`/file print count-only where name=... and size=...`), and `tasks/verify.yml` asserts only that the pin **file exists** and a `/ip tftp` row exists — never that the on-router **content** matches the render cache. An edit that changes a fragment while keeping byte-length identical (plausible for an install↔local swap of similar length — the precise class of change made during recovery) would neither trigger re-upload nor be caught by verify, leaving the dangerous pin live. **Fix:** compare a content hash (fetch + sha256, or push unconditionally on any render change) instead of size, and have verify compare content, not presence.

#### M2 — `hub-cluster/bootstrap_gitops.yaml`: fixed 60s sleep + no-retry ArgoCD create, and unguarded `target_cluster`
- The play does `pause: seconds: 60` then `Create ArgoCD Object` with **no `retries`**. If the GitOps operator hasn't Established the `argoproj.io/v1beta1 ArgoCD` CRD within 60s (cold catalog pull, slow InstallPlan), the create fails the run. The downstream `root-applications` Application has `retries: 50`, but the CR that everything depends on does not. **Fix:** replace the blind sleep with a `k8s_info` wait for the ArgoCD CRD (or the operator CSV `Succeeded`), and add retries to the CR create.
- `target_cluster` is defaulted only on the `hosts:` line (`{{ target_cluster | default('all') }}`) but is then referenced **unguarded** in the `environment-variables` ConfigMap (`CLUSTER_NAME: '{{ target_cluster }}'`) and the root Application path (`clusters/{{ target_cluster }}`). Invoked without `-e target_cluster`, `hosts` resolves to `all` while `target_cluster` stays undefined → templating error mid-run. **Fix:** add an early `assert target_cluster is defined`.

#### M3 — The shared NVMe `hostnqn`/`hostid` latent bug is unremediated on the Ansible side
`git grep` for `hostnqn|hostid|/etc/nvme` across `origin/main` returns nothing, and neither `deploy_pxe_assets.yml`, the `openshift_agent_install` role, nor `nodes-config.yaml.j2` sets a per-node NVMe identity. Because all three nodes PXE/ISO-boot the same RHCOS agent image, they inherit an identical `/etc/nvme/hostnqn`/`hostid` (the `...466937ab...` collision from the incident), which breaks NVMe-oF uniqueness and drives the intermittent democratic-csi nvmeof attach failures. The durable fix is likely a per-node Ignition/MachineConfig in the GitOps repo, but flagging here because the **agent-install flow is where the identity is (not) seeded** — at minimum the nodes-config/agent-install path should regenerate a unique hostnqn per host so a fresh reinstall doesn't reintroduce the collision.

---

### LOW

#### L1 — Play name vs body drift in `hub-cluster/bootstrap_gitops.yaml`
The play is named *"…add an ansible serviceaccount and save the token to 1password"*, but **no task in it creates an ansible ServiceAccount or writes any token to 1Password**. `docs/disaster-recovery.md` compounds this by claiming the `onepassword-sdk-<cluster>-push-token` item is "written by `bootstrap_openshift_gitops.yaml`" — it is not written by either playbook today. Misleading during a time-pressured recovery. **Fix:** rename the play to match reality, and correct the DR doc's provenance note (or re-add the SA/token task if AAP still depends on it).

#### L2 — `deploy_pxe_assets.yml` copies the admin kubeconfig to a world-readable /tmp path
Play 1's *"Copy auth files to /tmp/auth"* writes the cluster auth dir (including `kubeconfig` with embedded admin `client-key-data`) to `/tmp/{{ target_cluster }}-auth/` at **`mode: "0644"`**. On a shared host that is a world-readable cluster-admin credential. **Fix:** `0600` and a non-shared destination (or clean it up in an `always`).

---

### Confirmed-correct / positives (no action)
- **Both session bugs are correctly fixed in `origin/main`:** the Connect JWT is read from the item's `credential` field via the `onepassword` lookup into `stringData.token`; the credentials JSON is read via `onepassword_doc` and, because it returns bytes (ansible-core ≥2.19 won't serialize bytes as module args), correctly placed under `data:` with `| b64encode`. The inline comments capturing *why* are excellent.
- **Egress SSH keep-alive fix present:** `hermes-egress.nft.j2` includes `tcp sport 22 accept` with a precise comment explaining the mid-run default-drop wedge (matches memory `734f7c1`).
- **Worker lifecycle safety is solid:** `vm_worker_destroy.yaml` has a pre-drain guard that refuses to touch a node not mapped to a `truenas_vms` entry (prevents draining a mistyped-but-real bare-metal node); `add_node_iso.yml` computes pending-vs-joined workers, validates MAC format, and fails fast on an empty/all-joined group. Both VM-lifecycle playbooks are still marked `!! UNTESTED (2026-07-03)` — de-risk before relying on them in a DR.
- Hermes convergence phasing (setup-os/setup-hermes in the egress-open window, configure under lock), the pinned-image (`!= latest`) assertions, the `play-vars-outrank-group_vars` shadowing notes, and the tirith SHA-256-verified download are all sound.

---

## Architecture & Environment Review

**Reviewer scope:** live read-only inspection of the rebuilt cluster (2026-07-04), resilience assessment, and verification of the critical shared-NVMe-identity bug. All findings below were confirmed against the running cluster and the three nodes over SSH.

### Current state (healthy, but structurally fragile)

| Property | Observed |
|---|---|
| Version | 4.21.9, ClusterVersion `Available=True`, all 34 ClusterOperators `Available`, none `Degraded` |
| Control plane | **1 node** — `ocp.igou.systems` / MS-01 / 10.10.9.10, role `control-plane,master,worker` |
| etcd | **single member** `etcd-ocp.igou.systems` (5/5, 11 restarts from the rebuild) — no quorum, no redundancy |
| Workers | `hpg5.igou.systems` (10.10.9.240 kube-internal / 10.10.9.x mgmt), `truenas-w1` (10.10.9.21, KubeVirt VM on TrueNAS) |
| p330 | dark permanently (no BMC, cannot be power-cycled) — do not design around it |
| Machine API | **no `Machine` / `ControlPlaneMachineSet` objects** (agent-based/UPI install); one CAPI `casval-worker` MachineSet scaled to 0 |
| Default StorageClass | `freenas-nvmeof-ssd-csi` — democratic-csi, RWO, `ext4`, `reclaimPolicy: Delete`, `Immediate` binding, single TrueNAS target |
| Network | OVNKubernetes; NNCP `mapping`/`mapping-hpg5` Applied |

The cluster is *functionally* healthy. The concern is entirely about resilience: every one of the failure modes that caused the 2026-07-03 disaster (or was uncovered during recovery) is still latent.

---

### 1. CRITICAL — all three nodes share one NVMe host identity (CONFIRMED)

Verified by reading `/etc/nvme/hostnqn` and `/etc/nvme/hostid` on each node:

| Node | `/etc/nvme/hostnqn` | `/etc/nvme/hostid` |
|---|---|---|
| 10.10.9.10 (master) | `nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28` | `466937ab-67bf-4315-971b-bc110d55ce28` |
| hpg5.igou.systems | `nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28` | `466937ab-67bf-4315-971b-bc110d55ce28` |
| 10.10.9.21 (truenas-w1) | `nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28` | `466937ab-67bf-4315-971b-bc110d55ce28` |

**All three are byte-identical.** The agent-based installer baked a single NVMe host identity into the RHCOS image and every node booted with it. All three nodes then connect as the *same host* to the same TrueNAS NVMe-oF subsystem — confirmed live: each node holds `transport=tcp` controllers to `nqn.2011-06.com.truenas:uuid:116c7577-...` while presenting the identical hostnqn.

**Why this is a correctness/data-integrity bug, not cosmetics:**
- NVMe-oF requires a globally unique `hostnqn`/`hostid` per initiator. The target (TrueNAS) uses hostnqn for connection tracking, namespace masking, and reservation ownership. Two initiators sharing one hostnqn is undefined behavior.
- Observed symptom during recovery: the hermes VM's second `nvmeof-ssd` disk failed to attach on hpg5 while its root disk was attached on the master — the target saw a "host" that already held a controller, producing intermittent `Connect command failed` / `unable to attach any nvme devices` / `failed to write to nvme-fabrics device`. It "recovered" only by retry and by recreating the PVC.
- With RWO volumes and shared identity, the target cannot reliably distinguish which physical node owns a namespace → real risk of a namespace being presented to two nodes at once → **filesystem corruption**, not just attach failures.

This bug is currently masked because workloads are lightly spread and most PVCs happen to bind on the node that first connects. It will resurface on any reschedule, drain, node reboot, or KubeVirt live-migration.

#### Exact remediation — self-generating MachineConfig (day-2) + agent-install day-1

A static Ignition file cannot fix this: a MachineConfig writes *identical* content to every node in a pool, which is exactly how they became identical. The correct pattern is a **systemd oneshot that generates a unique identity at boot** and is idempotent (only rewrites when the value is missing or equals the known-duplicated UUID). MCO reboots the node to apply the unit, and on that boot the unit runs before the NVMe fabric autoconnect, so CSI reconnects with the new identity.

Script `/usr/local/bin/regen-nvme-hostid.sh` (embedded in the MachineConfig):

```bash
#!/usr/bin/env bash
set -euo pipefail
DUP_ID="466937ab-67bf-4315-971b-bc110d55ce28"
mkdir -p /etc/nvme
cur_id="$(cat /etc/nvme/hostid 2>/dev/null || true)"
if [ ! -s /etc/nvme/hostnqn ] || [ ! -s /etc/nvme/hostid ] || [ "$cur_id" = "$DUP_ID" ]; then
  newid="$(uuidgen)"
  printf 'nqn.2014-08.org.nvmexpress:uuid:%s\n' "$newid" > /etc/nvme/hostnqn
  printf '%s\n' "$newid" > /etc/nvme/hostid
fi
```

Butane source (transpile with `butane --strict`; produce **one MachineConfig per pool** — `master` and `worker` — since they are separate MachineConfigPools):

```yaml
variant: openshift
version: 4.21.0
metadata:
  name: 99-worker-unique-nvme-hostid      # + a 99-master-... copy with role: master
  labels:
    machineconfiguration.openshift.io/role: worker
storage:
  files:
    - path: /usr/local/bin/regen-nvme-hostid.sh
      mode: 0755
      contents:
        local: regen-nvme-hostid.sh       # or inline data: URL
systemd:
  units:
    - name: regen-nvme-hostid.service
      enabled: true
      contents: |
        [Unit]
        Description=Generate a unique NVMe host identity (hostnqn/hostid)
        DefaultDependencies=no
        After=local-fs.target
        Before=nvmf-autoconnect.service systemd-udev-settle.service kubelet.service
        [Service]
        Type=oneshot
        RemainAfterExit=yes
        ExecStart=/usr/local/bin/regen-nvme-hostid.sh
        [Install]
        WantedBy=multi-user.target
```

Rollout notes:
- Add these to `clusters/ocp/machineconfigs/` and its `kustomization.yaml` (alongside the existing `99-master-load-nvme-tcp`). MCO drains + reboots one node at a time; the master reboot is a brief single-node API blip (unavoidable with one control-plane node — schedule it).
- **Order matters vs. the shared target:** roll the workers first, then the master, and validate `hostnqn` differs on each node between steps, so you never briefly have two *rebooting* nodes racing new identities against live attachments.
- **Verify after:** `for n in 10.10.9.10 hpg5.igou.systems 10.10.9.21; do ssh core@$n sudo cat /etc/nvme/hostnqn; done` → three distinct UUIDs; then confirm TrueNAS shows three distinct connected hosts.

**Close the loop for future reinstalls (this is essential):** the disaster proved a full reinstall is a real event here. Bake the *same self-generating oneshot* into the agent-install day-1 manifests (`openshift/` manifests dir consumed by `deploy_pxe_assets.yml` in igou-ansible) so that **every** freshly installed node gets a unique identity from first boot. Otherwise the next DR reinstall silently reintroduces the identical-hostnqn bug.

---

### 2. HIGH — single control-plane topology has zero fault tolerance

One etcd member, one master. There is no quorum, no failover, and (below) no backup. Loss of MS-01 — hardware fault, the exact netboot-reinstall that happened, or a bad disk — is **total, immediate cluster loss**. The 2026-07-03 event only destroyed one host; a 3-node control plane would have kept quorum on the other two and survived it outright.

Recommendation, in priority order:
1. **Preferred: go to a compact 3-node control plane** (3 schedulable masters). The hardware already exists — MS-01 + hpg5 + truenas-w1 are all cluster members today. Promoting hpg5 and truenas-w1 to control-plane members would have survived this disaster and every future single-host loss. This is the single biggest resilience win available. (Caveat: truenas-w1 is a VM *on* the TrueNAS box that also serves all PV storage — co-locating an etcd member there couples control-plane and storage failure domains; MS-01 + hpg5 + a third bare-metal host is cleaner if one can be found.)
2. **If single-node is retained as a deliberate homelab tradeoff:** it must be paired with (a) automated etcd backups (section 3), (b) `Retain` reclaim on irreplaceable PVs (section 5), and (c) a rehearsed, IaC-driven rebuild. Recovery here worked but took hours of manual, undocumented-until-now steps.

---

### 3. HIGH — no etcd backup existed, and still does not

Confirmed: **no** etcd-backup CronJob in any namespace, **no** backup PV, nothing. During the disaster etcd state was unrecoverable; the cluster was rebuilt from scratch and PV data survived *only by luck* (see section 5). For a single-member etcd this is the difference between a 10-minute restore and a multi-hour ground-up rebuild.

Recommendation:
- Enable OpenShift's built-in **automated etcd backup** (`config.openshift.io/v1alpha1 Backup` / periodic backup via cluster-etcd-operator) writing to a dedicated PVC, and manage it in GitOps.
- The backup destination must be a **different failure domain** than the control-plane host — do not write etcd snapshots to a democratic-csi/TrueNAS volume that itself depends on the cluster being up, and never to MS-01's local disk. Ship snapshots off-cluster to TrueNAS/RustFS on a schedule (the same RustFS bucket pattern already used for CNPG Barman backups), so a snapshot survives even total cluster loss.
- Document and periodically rehearse `cluster-restore.sh` from a snapshot on this single-node topology.

---

### 4. HIGH — netboot-first boot order is still the loaded gun that caused the disaster

Root cause of 2026-07-03: MS-01 firmware `BootOrder` lists PXE NICs *before* the local disk with a 3s timeout, and the rb5009 served a per-host iPXE pin that defaulted to `install-openshift` on a 30s timeout. An unattended reboot netbooted straight into the agent installer, wiped the disk, and looped (mid-install reboot → PXE → reinstall).

Current mitigation (per recovery notes, inv#120 merged): the router pin now defaults to `local`. That is necessary but **not sufficient** — the firmware still boots PXE first, so cluster safety depends entirely on one router text file never regressing to an install target. This is fragile defense-in-depth-of-one.

Recommendation:
- **Set MS-01 (and all nodes') firmware to boot the local disk first**; keep PXE available only as a manual, human-selected option. Netboot should never be the default path for an installed production node.
- Make the netboot menu's default a **no-op / local-disk chainload with a long, human-gated timeout**, and move `install-openshift` behind an explicit, non-default menu entry so an unattended reboot can never trigger a reinstall.
- Physically/logically separate "install" artifacts from the routine netboot path, and treat arming an install pin as a deliberate, time-boxed action (arm → install → auto-disarm), never a persistent default.

---

### 5. MEDIUM/HIGH — democratic-csi NVMe-oF is a single point of failure with known multi-attach fragility

- **Single target, no multipath:** all nine democratic-csi StorageClasses (iscsi/nfs/nvmeof × cold/fast/ssd) point at one TrueNAS box. TrueNAS down = all persistent storage down cluster-wide. The default class is `nvmeof-ssd`.
- **RWO multi-attach wedge is a documented, recurring incident** (`docs/runbooks/nvmeof-stuck-multiattach.md`, issue #295, upstream democratic-csi #536/#559): after a transport blip the NVMe controller renumbers, `NodeUnstageVolume` loops on a missing device, the PV sticks in the old node's `volumesInUse`, and a rescheduled pod hangs on `Multi-Attach` — cascading to every app in the namespace. The shared-hostnqn bug (section 1) makes this class of failure *more* likely, not less.
- **The permanent #295 fix (`ctrl_loss_tmo=-1` via a persistent udev rule/MachineConfig) is NOT deployed.** No `/etc/udev/rules.d/*nvme*` rule exists on any node. Live TCP controllers currently read `ctrl_loss_tmo=off` (set by the driver's connect options), so the *behavior* is partly present at runtime but is **not host-enforced or persistent** — it depends on the driver reconnecting with the right args and is lost on any path that doesn't. Land the #295 MachineConfig so `ctrl_loss_tmo=-1` is guaranteed at the host level (accepting the documented tradeoff: I/O queues indefinitely during a storage outage rather than erroring).
- **`nvme-tcp` boot-load gap:** the only module-load MachineConfig is `99-master-load-nvme-tcp` — **master role only**. Workers (which do the bulk of nvmeof mounts) have `nvme_tcp` loaded today *only* because democratic-csi modprobes it at runtime. Add a `worker` (or all-role) variant so the module is guaranteed at boot and a worker reboot can't race the driver.

Recommendations: land #295; add the worker `nvme-tcp` MachineConfig; for workloads that reschedule frequently and cannot tolerate the multi-attach wedge, prefer an RWX/NFS class over RWO nvmeof; and treat TrueNAS as the SPOF it is (its own backup/HA story is out of this cluster's scope but should be acknowledged in DR planning).

---

### 6. MEDIUM — PV data survival was luck, not design (`reclaimPolicy: Delete`)

Every democratic-csi StorageClass, including the default, is `reclaimPolicy: Delete`. Deleting a PVC destroys the backing zvol. Data survived the disaster **only because the cluster died without issuing any CSI delete calls** — the old zvols were orphaned, not deleted, and were later re-mounted read-only on TrueNAS to fingerprint and restore them. A "cleaner" failure (e.g., a GitOps prune that deleted PVCs) would have permanently destroyed the data.

Recommendation:
- Set `reclaimPolicy: Retain` on the classes holding irreplaceable data (or per-PV), so an accidental PVC/namespace deletion or an errant Argo prune leaves the zvol intact.
- Keep maintaining the application-level backups that actually saved this recovery (CNPG Barman → RustFS for quay/rhdh/forgejo; hermes state tarballs), and keep the PVC→zvol catalog (`/workspace/backups/ocp-pv-catalog-20260703.txt`) current — it was the map that made restore possible.

---

### 7. MEDIUM — CSR auto-approval is not guaranteed for these nodes

`machine-approver` is running, but there are **no `Machine` objects** backing the bare-metal nodes (agent-based install). The standard approver only auto-approves CSRs it can tie to a Machine; during the worker rejoin, node bootstrap/serving CSRs had to be **approved manually** (recovery notes describe 9 `node-bootstrapper` CSRs piling up, and a column-offset gotcha that hid them). There are no pending CSRs right now, but kubelet **serving-certificate CSRs rotate on renewal**, and if they are not approved the node's metrics/logs/`oc exec`/kubelet-serving endpoints silently break, and eventually the node degrades.

Recommendation:
- Add monitoring/alerting on **pending CSRs** (`oc get csr` with unapproved conditions) so a stuck serving-cert renewal is caught before it degrades a node — remembering the condition is in the last column, not `$5`.
- Do **not** deploy a blanket auto-approver as a shortcut; auto-approving serving CSRs without Machine backing is a known privilege/impersonation risk. If automation is wanted, scope it tightly to expected node identities.

---

### Summary of recommended hardening (priority order)

1. **Unique NVMe identity** — ship the self-generating `99-*-unique-nvme-hostid` MachineConfig for both pools *and* bake it into agent-install day-1 (fixes the confirmed corruption-risk bug and prevents its reintroduction on the next reinstall).
2. **Move to a 3-node control plane** (or, if single-node is deliberate, treat it as ephemeral and back it accordingly).
3. **Enable automated etcd backups** to an off-cluster, different-failure-domain destination.
4. **Firmware boot-disk-first + human-gated netboot install** so an unattended reboot can never reinstall a node.
5. **Land the #295 `ctrl_loss_tmo` MachineConfig** and add a **worker `nvme-tcp` load** MachineConfig.
6. **`reclaimPolicy: Retain`** on irreplaceable-data StorageClasses/PVs; keep app-level backups + PVC→zvol catalog current.
7. **Alert on pending CSRs**; avoid an unscoped auto-approver.

---

## Perspective: Kubernetes / OpenShift Administrator

**Cluster:** `ocp` (OpenShift 4.21.9), single control-plane on MS-01 (`ocp.igou.systems`, 10.10.9.10) + 2 workers (`hpg5`, `truenas-w1` KubeVirt VM). `p330` permanently dark.
**Reviewed:** 2026-07-04, read-only. All 33 cluster operators `Available=True, Degraded=False`; ClusterVersion 4.21.9 stable; 3/3 nodes Ready, no node pressure. The restore landed the cluster in a genuinely healthy baseline. The findings below are about making it *easier and safer to run*, ranked by operational risk.

---

### 1. The control plane is schedulable AND unguarded — highest structural risk

- `ocp.igou.systems` carries roles `control-plane,master,worker` with **no taints**. User workloads co-schedule with etcd and kube-apiserver on the *single* control-plane node. It is already carrying real load (`oc adm top`: 35% mem / 13% cpu, 32 GiB used), while the two workers sit at 9–11% mem — the scheduler is packing the worst-possible node.
- **Zero `ResourceQuota` and zero `LimitRange` on every user namespace** checked (hermes, jellyfin, quay, rhdh, forgejo, llmkube, searxng, gotify, firecrawl — all `quota=0 limitrange=0`). CNPG DB pods (`rhdh-pg`, `forgejo-pg`) set requests but **no memory limits**.
- **Why this matters:** on a single-member etcd cluster there is no quorum to absorb a stumble. One bursty/leaky workload (llmkube model cache, quay GC, a firecrawl queue) can drive `MemoryPressure`/`DiskPressure` on the etcd node → etcd fsync stalls → API latency and evictions → cascading control-plane instability. Nothing today prevents an unbounded pod from starving the API server.
- **Recommendations:**
  - Preferred: taint the master `NoSchedule` and run user workloads only on `hpg5`/`truenas-w1`. If capacity genuinely requires scheduling on the master, then at minimum:
  - Add a per-namespace `ResourceQuota` + default `LimitRange` (default requests/limits) via a namespace template so *nothing* runs unbounded; set explicit memory limits on CNPG/quay/registry pods.
  - Confirm the `kubeletconfig` app (it exists in the app-of-apps) sets `system-reserved`/`kube-reserved` on the master so kubelet protects the control plane from workload memory.
  - Add a `PriorityClass` split (control-plane-adjacent vs. best-effort user apps) so the node-pressure evictor sacrifices user apps first.

### 2. etcd: single member, no automated backup — the disaster is a coin-flip from repeating

- One etcd member (expected for single control plane), DB 786 MB, healthy. But there is **no automated etcd backup**: no `EtcdBackup`, no `etcd.spec.backup`, no backup CronJob, nothing shipping snapshots off-node.
- The whole incident was triggered by etcd/disk state being wiped and **unrecoverable**. A single-member etcd with no scheduled snapshot means the *next* disk/node loss is again a full rebuild — the exact multi-hour path just walked.
- **Recommendation:** enable OpenShift 4.21's built-in scheduled etcd backups to a PVC backed by the TrueNAS CSI (lands off the etcd node), or a CronJob running `cluster-backup.sh` shipped to RustFS/TrueNAS. Pair with a written `quorum-restore` runbook. This is the single cheapest change that would convert a repeat of this event from a rebuild into a ~20-minute restore.

### 3. Nodes are not Machine-API managed → CSR auto-approval is a recurring landmine

- `oc get machines` returns none; workers are agent/PXE (UPI-style). The only MachineSet is `casval-worker` (scaled to 0). `machine-approver` only auto-approves CSRs for **Machine-backed** nodes.
- Consequence: kubelet-client and kubelet-**serving** CSRs for `hpg5` and `truenas-w1` never auto-approve. This is precisely what produced the 9 piled-up `node-bootstrapper` CSRs during recovery. Kubelet serving certs rotate on a schedule; when they do, `oc logs/exec/adm top` against that node silently starts failing with x509 until a human approves the serving CSR.
- **Recommendation:** deploy a scoped auto-approver for the known, static node set — a small controller/CronJob that approves only `Pending` CSRs whose CN matches `system:node:<one-of-the-3-known-hostnames>` from the expected requester. At absolute minimum, alert on `Pending` CSRs and document the *correct* approval one-liner from the postmortem (`go-template` on `not .status`; remember the CSR CONDITION is **column 6**, not 5 — the naive `awk '$5=="Pending"'` silently matches nothing and cost ~40 min during recovery).

### 4. The ArgoCD instance is un-versioned and carries load-bearing hand-patches

- The `ArgoCD` CR has **no GitOps tracking annotation** — it is created by an Ansible playbook and then hand-patched live. Confirmed load-bearing live-only patches present on the running CR:
  - `repo.resources` cpu 2 / mem 2Gi + `ARGOCD_EXEC_TIMEOUT=3m` — the fix for the `DeadlineExceeded` wave stalls caused by heavy Helm render of `clusters/ocp/` on 1 CPU.
  - `resourceHealthChecks` Lua for `PushSecret` (+ `ExternalSecret`, `Subscription`, `InstallPlan`, `ClusterSecretStore`) — the `PushSecret` check is what un-gates every wave > 40 despite the intentionally read-only push token.
- These are the exact settings that make the cluster *operable*, yet they exist only in the running cluster and a playbook (the postmortem lists "fold live-only ArgoCD CR patches into bootstrap_gitops.yaml" as an **open** TODO). If the playbook re-runs or the CR is recreated, the cluster silently reverts to the hard-to-operate state: repo-server timeouts return and the wave gate wedges on `service-accounts` being Degraded.
- **Recommendation:** make the ArgoCD CR first-class version-controlled config — bake the resources/timeout/health-checks into the idempotent bootstrap playbook, and ideally have Argo self-manage its own CR (an app-of-apps entry that owns the ArgoCD CR) so drift on these operability-critical settings is *visible* instead of tribal.

### 5. App-of-apps sync-wave model is brittle on a 3-node cluster

- The model gates wave N+1 on wave N being Synced **and Healthy**. During recovery this repeatedly stalled the whole chain when a transient operator-install Degrade (service-accounts, grafana, cluster-api) flapped at a lower wave.
- Compounded by the recurring **operator-then-CR ordering** friction: operator installs are async, so operand CRs fail dry-run until the CSV lands (CNV `StorageProfile` needs the `cdi` CRD from `HyperConverged`; quay needs its operator first). Recovery had to repeatedly hand-apply `Namespace`+`OperatorGroup`+`Subscription`, wait for CSV `Succeeded`, then sync with `SkipDryRunOnMissingResource=true`.
- **Recommendations:**
  - Structurally split "install the operator" (Subscription/OG in an earlier wave) from "apply the operand CR" (later wave) and set `SkipDryRunOnMissingResource=true` + ServerSideApply on operand apps, so a not-yet-present CRD stops *gating* the whole cluster.
  - Gate operator apps on CSV `Succeeded` (the InstallPlan/Subscription health checks already exist) rather than broad app health that flaps mid-install.
  - Decouple independent user apps from one long linear wave chain so a single flapping app doesn't block unrelated ones.
  - Keep the repo-server perf patch (item 4) — it was the root cause of many `Unknown`/`DeadlineExceeded` stalls.

### 6. Live/git drift on the CNPG databases = latent data-loss landmine

- `forgejo`, `rhdh`, `quay-operator`, `openshift-pipelines`, `pac-tenants`, and `root-applications` are **OutOfSync** (`root-applications` also Progressing). The DB apps' `syncPolicy.automated.selfHeal=true`.
- Root cause for the DBs: **git still declares `bootstrap.recovery`** (restore-from-Barman) with an in-file comment "Revert to the initdb block below once recovered and verified," while the live archiving `serverName` was patched to a new value during recovery. The child apps are stuck OutOfSync and not converging — self-heal is silently failing on the immutable `bootstrap` field, which *masks* the drift rather than resolving it.
- **Danger:** git is committed in one-shot RECOVERY mode. If any CNPG `Cluster` CR is recreated or force-synced from git, CNPG will re-run a full Barman recovery **over the now-live database**. Leaving a stateful DB's git source in recovery mode is a data-loss trap.
- **Recommendation (matches the postmortem's own open TODO):** once DBs are verified healthy, change git back to steady-state (drop the `recovery` block / represent the already-bootstrapped cluster) and reconcile the live archiving `serverName` into git so the apps go Synced. Add guards on CNPG `Cluster` CRs: `argocd.argoproj.io/sync-options: Prune=false` and treat `bootstrap` as `ignoreDifferences` so an accidental sync can never re-bootstrap a live DB.

### 7. Operator lifecycle: mixed approval strategies + entangled global namespace

- Most Subscriptions are `Automatic`. `servicemeshoperator3` is `Manual` with **two pending unapproved InstallPlans** for `v3.3.5` while `v3.2.0` runs — this is why `openshift-pipelines` shows OutOfSync/stuck.
- `servicemesh` and `pipelines` share the global `openshift-operators` OperatorGroup, and InstallPlan `install-khg9h` bundles **both** CSVs (`servicemeshoperator3.v3.3.5` + `openshift-pipelines-operator-rh.v1.22.4`). Approving/upgrading one entangles the other — the worst kind of coupling for upgrades on a cluster with no test tier.
- Several subs float on unpinned channels (`openshift-gitops-operator=latest`, `openshift-pipelines=latest`, `rhdh=fast`). Floating channel + `Automatic` approval = surprise operand migrations with no staging.
- **Recommendations:**
  - Pick one policy and hold it: pin channels to specific streams; commit to `Automatic` (accept auto-upgrades) *or* `Manual` and actually process the queue — a half-approved Manual queue is the worst of both and is currently wedging pipelines.
  - Move workload operators out of the shared `openshift-operators` global namespace into their own namespace+OperatorGroup (single-/own-namespace install mode) so their InstallPlans don't co-mingle. Pipelines and ServiceMesh must not share an InstallPlan.
  - Resolve the stuck `servicemesh` InstallPlan (approve or decline) so `openshift-pipelines` stops flapping OutOfSync.

### 8. Root-cause of the incident, from a day-2 lens

- The self-destruct latch was **netboot-first boot order + a stale per-host PXE pin defaulting to `install-openshift` on a 30 s timer**, plus an installer path that re-enters on a mid-install reboot (loop). `inv#120` (pin default=local) is merged, but the durable invariant to enforce is: *an unattended reboot must never be able to reinstall a node.* That means disk-first boot order with PXE as an explicitly, manually-armed one-shot that disarms after first boot, and a fail-safe pin (`local` default). Treat "can a reboot wipe this node?" as a design gate, not a config detail.

### 9. Housekeeping / smaller items

- **RBAC posture is actually good** and worth preserving: purpose-scoped SAs (`cluster-read-only`→`cluster-reader`, `cluster-edit`→`edit` scoped to one ns, `virtualmachine-*` custom roles, `ansible-molecule`→`node-reader`). The **only** non-system SA at `cluster-admin` is the ArgoCD application-controller (`gitops-cluster-admin`) — standard for an app-of-apps that installs operators, but it is the largest blast radius on the cluster; consider constraining via AppProject destination/namespace/resource allow-lists even if the cluster-admin binding stays.
- **PushSecrets all `Errored` by design** (read-only push token — an accepted choice). Side effect: the 6 minted SA tokens (`cluster-edit`, `cluster-read-only`, `claude-edit`, `ns-agent`, `virtualmachine-ops`, `ansible-molecule`) are **not** published to 1Password, so there is no out-of-band copy. Document that they are on-cluster-only, or fix the token.
- **Leftover installer static pods** in `openshift-kube-{apiserver,controller-manager,scheduler}` (7 in `Error`/`ContainerStatusUnknown`) — cosmetic residue of control-plane rollouts; they accumulate. Harmless but worth periodic GC/awareness.
- **PDBs on single-replica components** (`image-registry`, `nmstate-webhook` minAvailable semantics; `console` maxUnavailable=1) can block `oc adm drain` on a 3-node cluster during maintenance — verify a planned drain doesn't wedge before you need it in an emergency.
- **NVMe hostnqn/hostid collision** (from the postmortem: all 3 nodes share `nqn…466937ab…`) is a correctness bug that intermittently fails volume attach cluster-wide; it belongs on this list as an open day-2 item — resolve via a MachineConfig that regenerates unique `/etc/nvme/hostnqn`+`hostid` per node, then roll reboots. Until fixed, avoid stop/start of KubeVirt VMs on nvmeof-backed volumes.

---

### Priority summary

| # | Change | Why | Effort |
|---|--------|-----|--------|
| 1 | Taint master / add ResourceQuota+LimitRange to user namespaces | Stop workloads from starving the single control plane | Low–Med |
| 2 | Enable scheduled etcd backup off-node + restore runbook | Turn the next etcd loss into a restore, not a rebuild | Low |
| 3 | Scoped CSR auto-approver (or alert + runbook) for the 3 static nodes | Serving-cert rotation silently breaks node access | Med |
| 4 | Version-control the ArgoCD CR + its health-check/perf patches | The settings that make the cluster operable are tribal/live-only | Low |
| 5 | Revert CNPG git bootstrap out of recovery mode + `Prune=false`/ignore `bootstrap` | selfHeal + committed recovery mode risks re-nuking live DBs | Low |
| 6 | Split operator-install from operand-CR waves; de-couple global-namespace operators | Ends the recurring operator-then-CR gate stalls | Med |
| 7 | Resolve/settle the Manual servicemesh InstallPlan; pin channels | Unwedge pipelines; stop surprise upgrades | Low |
| 8 | Fix NVMe hostnqn/hostid uniqueness (MachineConfig) | Correctness — intermittent volume-attach failures | Med |

---

## Perspective: Site Reliability Engineer

**Reviewer role:** Site Reliability Engineer
**Scope:** Detection, blast radius, backup/restore coverage, observability/alerting gaps, recovery toil, runbook readiness, MTTR/MTTD, and prioritized reliability improvements.
**Verdict:** The cluster was fully recovered and no committed data was permanently lost — a credit to zvol persistence and Barman. But recovery succeeded *despite* the design, not because of it. The incident exposed a self-amplifying destroy path (netboot-first + install-default pin + reinstall loop), a total absence of cluster-state backup (no etcd snapshot, no OADP), an alerting pipeline that dies with the cluster it monitors, and a recovery that was almost entirely manual and improvised. Every one of these is fixable with low-to-moderate effort.

---

### 1. Incident reconstruction: MTTD and MTTR

| Phase | Approx. time (UTC) | Elapsed | Notes |
|---|---|---|---|
| Trigger: unattended reboot → PXE → agent installer wipes 990 PRO | ~17:00 | T+0 | Disk wiped; install then *loops* (mid-install reboot → PXE → reinstall) |
| Detection | (operator-noticed) | **unbounded** | No external alert fired — see §2 |
| Pin flipped to `local`, disk boot | 18:24–18:31 | ~T+1h30m | Loop broken manually |
| Master `Ready`, ClusterVersion `Available` 4.21.9 | 18:38–19:20 | ~T+2h20m | Control plane back |
| GitOps bootstrapped, 21 essential apps Synced | evening | ~T+3h | Secrets seeded out-of-band by human |
| Both workers re-joined (hpg5 PXE, truenas-w1 ISO) | ~21:51 | ~T+5h | CSR-approval gotcha cost ~40 min |
| DB restores (rhdh/forgejo/quay Barman) + hermes state | overnight → 2026-07-04 | **T+12h+** | Multi-step, manual, spanned into next day |

**MTTR ≈ 2.3h** to a live control plane, **~5h** to workers + core apps, **12h+** to substantially-restored data — all with a skilled operator working the problem continuously.

**MTTD is the more alarming metric: effectively unbounded.** There is no external heartbeat (see §2). Detection depended on a human noticing a service was down. Had this happened while unattended, the cluster could have sat destroyed — and *looping through reinstall attempts* — for hours or days.

---

### 2. Detection & observability gaps (the alerting pipeline dies with the cluster)

The entire alert path is **in-cluster and self-referential**:

- Alertmanager (`alertmanager-main`), UWM Prometheus + thanos-ruler, and the `alertmanager-gotify-bridge` push relay all run **on the cluster being monitored**.
- The EDA→AAP→GitHub-issue pipeline runs on **AAP, which is on the same cluster**.
- Slack is reached via `slack.com`, but the *sender* (Alertmanager) is in-cluster.
- `blackbox-exporter` exists but is **in-cluster** (`Active 3h22m`) — it probes outward; it cannot report that the cluster itself is dead.
- The standard `Watchdog` alert is `null`-routed (correct for its usual purpose) but there is **no external consumer** turning Watchdog silence into a page.

**Consequence:** the failure mode that matters most (whole-cluster loss) is precisely the one that produces **zero alerts**. This is the classic "who watches the watcher" gap, and it is the direct cause of the unbounded MTTD.

Additional observability gaps found live:

- **Platform Prometheus has no persistent storage** (`prometheus/k8s .spec.storage` empty → emptyDir). All platform metric history is lost on every reboot/reschedule — so there is no post-mortem telemetry across the very reboot that destroyed the cluster.
- UWM Prometheus/thanos-ruler retention is only **15d**, and their PVCs sit on `freenas-nvmeof-fast-csi` — the same NVMe-oF stack carrying the shared-hostnqn attach bug (§4).
- **The push receiver is currently down post-recovery:** namespace `gotify` is `NotFound`, so the Alertmanager `gotify` / `gotify-and-slack-*` webhook targets (`alertmanager-gotify-bridge.gotify.svc`) have no backend right now. The cluster is presently running with its primary push-notification path broken.

---

### 3. Single points of failure (blast radius)

**3a. Netboot-first boot + install-default pin = a single router file can wipe the cluster.**
MS-01 firmware BootOrder is PXE→PXE→disk on a 3s timeout (a *firmware* setting, not in git). The rb5009 per-host pin defaulted to `install-openshift` on a 30s timeout, armed since 2026-05-11 and sitting latent for ~2 months. A routine unattended reboot was sufficient to trigger a **full disk-wipe reinstall**. The blast radius of one stale iPXE file on the router is *the entire cluster*.

The fix applied (pin default `local`, inv#120) removes the immediate trap, but the underlying foot-guns remain:
- The netboot template **still contains an `install-openshift` menu that defaults to install on a 30s timeout** (`group_vars/all/netboot.yml`: `choose --timeout 30000 --default install-openshift target || goto local`). Any future pin pointed at that menu re-arms the bomb. The guardrail is "which menu the pin references," not "install menus can never be the unattended default."
- MS-01 firmware is still **netboot-first with disk last**, so every boot depends on the router serving a *safe* pin. Router misconfig, TFTP drift, or a re-added stale pin reproduces the disaster.

**3b. The reinstall loop is self-amplifying.** The mid-install reboot re-enters PXE and reinstalls again — a failure that *repairs itself into permanence*. Without a human flipping the pin at exactly the "installing" moment, the box never escapes.

**3c. Single control-plane node — no etcd quorum, no auto-repair.** Confirmed: `1 members are available`, no `controlplanemachineset`. Losing MS-01's disk = losing the whole cluster with no HA fallback. There is no Machine-API-managed control plane to auto-reprovision.

**3d. Single TrueNAS holds all persistent state.** Every PV zvol, every Barman bucket, the boot artifacts (nginx), and truenas-w1 itself live on one TrueNAS box. DR worked *only* because MS-01's local disk was wiped while TrueNAS survived. A TrueNAS-side failure would have been unrecoverable — there is no offsite replication of the zvols documented.

**3e. Shared NVMe host identity (latent, still unfixed).** All 3 nodes carry the identical `hostnqn`/`hostid` (`...466937ab...`) baked in by the agent installer. This violates NVMe-oF uniqueness and already caused intermittent "unable to attach nvme" failures during recovery, with a **data-corruption risk** on the shared democratic-csi NVMe-oF target. This is an active reliability + correctness landmine across all NVMe-oF volumes.

---

### 4. Backup / restore coverage

| Data class | Backup mechanism | Gap |
|---|---|---|
| **etcd / cluster state** | **NONE** | No etcd snapshot cronjob, no OADP. DR = full reinstall. `openshift-adp` ns absent; `redhat-oadp-operator` component exists in-repo but is **not enabled** in `clusters/ocp/values.yaml`. |
| Namespaces / PVs / app CRs as a set | **NONE** | No Velero/OADP → no consistent point-in-time restore of app resources + PVs together. |
| CNPG databases (quay/rhdh/forgejo) | Barman → RustFS-cold | Backup target is on **spinning rust that was recently wedged** (`rustfs-cold-disk-health-wedge`); had to be un-wedged mid-incident before restores could run. quay base backup was from **2026-06-10** (~3 weeks stale) — recovered only because WAL replay covered the gap. |
| hermes agent state | **Ad-hoc tar taken during the incident** from a zvol snapshot | No scheduled hermes backup existed. Recoverable purely because the zvol survived and an operator manually snapshotted/tar'd it. |
| PV zvols (jellyfin, app data) | Implicit — zvols persisted on TrueNAS | No snapshot *schedule* and no offsite replication documented. "It survived because only the other machine got wiped" is not a backup strategy. |

**Bottom line:** RPO for cluster state is effectively "since last GitOps commit" (config is reconstructable) but RPO for *data* ranged from good (DB WAL) to "whatever happened to still be on a zvol." There was **no designed, tested, scheduled DR backup** — recovery leaned on luck (zvols survived, RustFS could be un-wedged, an operator was available to improvise).

---

### 5. Recovery toil & manual steps

The recovery was a tour de force of manual operations. Each of these is a place where a tired or less-expert operator would have added hours or lost data:

- **Secrets bootstrap chicken-and-egg:** AAP, 1Password Connect, and ESO all ran *on* the destroyed cluster, so every `op` lookup was dead. A human had to hand-seed `op-credentials` + the Connect token out-of-band. One 1P view-once share link was **burnt by a headless-browser preload**; the replacement SA was deleted server-side — nearly blocking recovery entirely.
- **Manual pin flips at exact install phases** (per host: MS-01, hpg5, truenas-w1) with "verify pin content on the router after every deploy."
- **Manual CSR approval** with a silent gotcha (`oc get csr` condition is column 6, not 5) that cost ~40 min while bootstrapper CSRs piled up.
- **Manual per-operator subscription bootstraps** (CNV, loki) to break app-of-apps wave-gate deadlocks.
- **Live-only ArgoCD CR patches** (repo-server cpu/timeout, PushSecret health-check) that are **not in git** and will be lost on the next `bootstrap_gitops.yaml` run — the recovery hardening itself is undocumented drift.
- **Manual zvol fingerprinting** (mount-ro-and-inspect) to map old PVCs→apps.
- **Barman `serverName` juggling** (must bump to a new value or recovery fails "Expected empty archive"; must delete the stuck full-recovery Job).
- **Flaky data transfer:** hermes state moved via `virtctl port-forward` which dropped (~1006 websocket) on multi-GB streams, forcing manual exclusion of the `containers` dir to fit.
- **VM clock bug:** truenas-w1's `time: LOCAL` put the guest RTC ~4h behind → Ignition x509 "cert not yet valid" until manually set to UTC.

None of this was automated. The MTTR was low *only because* a single expert operator held the entire runbook in their head in real time.

---

### 6. Runbook readiness

There was **no pre-existing DR runbook.** The `project-ocp-cluster-reinstall.md` memory file is an excellent *post-hoc* record, but it was written *during* the fire. Nearly every gotcha (CSR column, cert rotation x509, VM UTC clock, Barman serverName, secrets bootstrap order, wave-gate deadlocks, repo-server timeout) was discovered live. There is:

- No documented, tested recovery procedure.
- No DR drill / game-day history.
- No verified RTO/RPO targets to design toward.

---

### 7. Prioritized reliability recommendations

Priorities: **P0** = do before the next reboot (prevents recurrence / detects loss); **P1** = weeks; **P2** = quarter.

#### P0 — Stop the bleeding

1. **Kill the netboot-first destroy path (defense in depth).**
   - Set MS-01 (and hpg5) firmware BootOrder to **disk-first, PXE fallback** so a reboot never depends on the router serving a safe pin. Netboot only when deliberately re-imaging.
   - In `group_vars/all/netboot.yml`, make **`local` the hard default of every menu**; require an explicit, short-lived, deliberately-armed pin to install. Never ship an install-default-on-timeout menu that a pin can point at by accident.
   - Add a CI/lint check that fails if any committed per-host pin defaults to an install target.
2. **External dead-man's-switch / heartbeat.** Stand up an off-cluster watchdog (e.g. Uptime-Kuma or a healthchecks.io push) on TrueNAS or a Pi that (a) probes the OpenShift API + a canary Route every 60s and (b) expects a periodic Watchdog-derived heartbeat *from* the cluster; page (Gotify/Slack/Telegram) on silence. This closes the unbounded-MTTD gap — the single highest-leverage fix.
3. **Fix the shared NVMe hostnqn/hostid** via MachineConfig (systemd oneshot: regen `/etc/nvme/hostnqn` + `hostid` where == `466937ab`, then rolling reboot). Removes an active data-corruption + attach-failure risk.
4. **Restore the push path:** namespace `gotify` is currently `NotFound` — the primary Alertmanager push receiver has no backend. Get gotify healthy (or repoint the bridge) so alerts are actually deliverable.

#### P1 — Backups you can trust

5. **Enable OADP/Velero** (the `redhat-oadp-operator` component is already in-repo, just unenabled) targeting RustFS/S3 — scheduled backups of namespaces, app CRs, and PV data as consistent sets. Define and **test** restore.
6. **Scheduled etcd backups.** A cluster-etcd-operator `PeriodicBackup` (or a simple cronjob running `cluster-backup.sh`) to TrueNAS/S3. Even for a single-node cluster this converts "full reinstall" into "restore state," and enables rebuild-onto-new-disk without total data reconstruction.
7. **Scheduled hermes + PV-zvol snapshots with retention**, plus **offsite/second-target replication** of the TrueNAS zvols and Barman buckets so TrueNAS is not a single DR SPOF. Move Barman off the flaky cold/spinning-rust RustFS to an ssd-backed target; add a backup-liveness/credential check (per the `rustfs-declarative-state` spec) so a stale key or wedged pool is detected *before* a DR event.
8. **Persist platform Prometheus** (add `prometheusK8s` storage) so telemetry survives reboots and post-mortems have data.
9. **Fold the live-only ArgoCD CR hardening into git** (`bootstrap_gitops.yaml`): repo-server cpu/timeout bump and the ExternalSecret + PushSecret health-checks. Recovery hardening must not live only in a running cluster.

#### P2 — Make recovery boring

10. **Write and drill a DR runbook.** Codify the reinstall→GitOps→workers→data-restore sequence with every gotcha (CSR column, cert x509 rotation, VM UTC clock, Barman serverName, secrets bootstrap order, wave-gate operator nudges). Run a **game-day** at least quarterly; set explicit RTO (target < 2h to API, < 4h to data) and RPO (< 24h, ideally < 1h for DBs) and design toward them.
11. **Automate the manual recovery steps:** an idempotent recovery playbook that regenerates PXE artifacts, seeds bootstrap secrets from a break-glass store, auto-approves scoped CSRs (using the correct `.status`-absent selector), and drives the wave-gate operator bootstraps.
12. **Break-glass secrets store off-cluster.** Because Connect/ESO/AAP all die with the cluster, keep a minimal, documented out-of-band copy of the seed secrets (`1password-credentials.json`, Connect token, pull secret) so recovery never stalls on a burnt view-once link.
13. **Consider control-plane resilience.** A single etcd member means any master-disk event is a full rebuild. If the workload warrants it, evaluate a 3-node control plane; at minimum, treat etcd backup (rec. 6) as mandatory compensation for the single-node topology.

---

### 8. Summary scorecard

| Dimension | State | Target |
|---|---|---|
| MTTD (whole-cluster loss) | **Unbounded** (no external heartbeat) | < 5 min via off-cluster watchdog |
| MTTR (to API) | ~2.3h, expert-dependent, manual | < 1h, playbook-driven |
| etcd backup | **None** | Scheduled to S3/TrueNAS |
| App/PV backup (OADP) | **None** (operator in-repo, disabled) | Enabled + restore-tested |
| DB backup (Barman) | Present but on flaky target, stale base | ssd-backed, liveness-checked |
| Guardrails vs. destroy path | 1 router file (now local) + latent install menu + netboot-first firmware | Disk-first firmware + hard-local menus + CI lint |
| Runbook | Post-hoc only | Written + quarterly drilled |
| Config drift (recovery hardening) | Live-only ArgoCD patches | In git |

The cluster is back and the data was saved, but the same unattended reboot could recur, and the *detection* of it would still be a human noticing. Prioritize the P0 items — firmware boot order, an external dead-man's-switch, the hostnqn fix, and restoring the push path — before anything else.

---

## Perspective: Software Engineer

Scope: code/config quality of the scripts, playbooks, kustomize/helm, and ad-hoc tooling
touched during the 2026-07-03 `ocp` cluster reinstall. Focus areas: correctness,
maintainability, idempotency, testing, error handling, secret handling, and the tech
debt introduced under pressure. Everything below was read from the live repos
(`/workspace/igou-openshift` @ `59a2bc7` local / `origin/main` @ `d81e454`,
`/workspace/igou-ansible` @ `78e40b1`) and the incident scratchpad.

### TL;DR verdict

The recovery got the cluster back, but it was carried by **one genuinely good playbook
(`add_node_iso.yml`) plus a pile of throwaway shell/python glue and live-only cluster
patches that are not in git.** The two highest-severity engineering problems are (1) the
NVMe `hostnqn`/`hostid` collision has **zero codified remediation** — no MachineConfig
exists in the repo — and (2) **two performance/gating fixes to the ArgoCD CR live only on
the cluster** and will be silently reverted the next time the bootstrap playbook runs,
re-introducing the exact stalls that cost time this incident. Underneath sits config
drift (three different GitOps-bootstrap artifacts, two PXE-publish playbooks one of which
targets dead infra) and a stale local checkout that already produced one wrong apply.

---

### 1. `recomment.py` — the values-toggler (disposable, but risky on the wrong file)

`/tmp/.../scratchpad/recomment.py` (33 lines) comments out deferred app blocks in
`clusters/ocp/values.yaml` so the app-of-apps skips them during the staged wave restore.

Correctness / robustness problems:

- **Silent no-match = wrong deploy.** The script builds `commented` from apps it actually
  matched, but never asserts that every name in the `defer-*.txt` input was found. A typo
  in a defer list (or an app whose key isn't lowercase-`[a-z0-9-]` at exactly 2-space
  indent, per `app_re = ^  ([a-z0-9-]+):\s*$`) means the app is **silently left enabled** —
  during a staged restore that means a workload you intended to hold offline comes up. On
  the single file that controls what the whole cluster deploys, silent partial failure is
  the worst failure mode.
- **Lossy one-way transform.** It rewrites each block line to `"  # " + line.strip()`,
  discarding original indentation ("cosmetic, ArgoCD ignores comments"). Restoration is
  therefore impossible from the output alone — it depends on keeping a pristine
  `values-original.yaml` / `git show <commit>^:...values.yaml` around. That's a manual
  round-trip contract, not a reversible tool.
- **Brittle block-consumption heuristic** (the 4-space / blank-line / peek-next-app logic,
  lines 19-28) is ad hoc and unscoped — it happens to work only because the file is flat.
- **No error handling:** positional `sys.argv[1..3]`, no `argparse`, no file-existence or
  encoding handling, no `with`; a missing arg is an unhelpful `IndexError`.

Testing: the only evidence of validation is the **no-op path** — `test-out.yaml` is
byte-identical to `values-original.yaml` (I diffed them; `dn.txt`/`defer-none.txt` were
empty). The actual commenting path was never unit-tested; verification was eyeballing the
ArgoCD app list.

Recommendation: **retire the text-mutator.** "What deploys" should be *data*, not a lossy
regex edit — a per-app `enabled: true|false` flag consumed by the app-of-apps helm/kustomize
template, or an ApplicationSet list generator gated on a boolean. If a scripted toggle must
survive, it should (a) parse YAML with a real parser (ruamel round-trip preserves comments),
(b) hard-fail if any requested name isn't present, and (c) be idempotent + reversible.

### 2. GitOps bootstrap — three artifacts, one source of truth needed

There are **three** things that bootstrap GitOps, and they disagree:

- `playbooks/openshift/hub-cluster/bootstrap_gitops.yaml` — the **good, current** one
  (creates the fully-configured ArgoCD CR: Lua health-checks, setenv CMP plugin, RBAC,
  resource tuning, ESO-scoped `resourceIgnoreDifferences`). This is what was actually used.
- `playbooks/openshift/bootstrap_openshift_gitops.yaml` — **drifted/broken**: points its
  kustomize lookup at `config/<cluster>/live/base-config/` (a path that no longer exists;
  the repo moved to `clusters/<cluster>/`) and references an undefined `onepassword_token`
  var with no prompt/default. It will fail if run. Dead and actively confusing mid-incident.
- `/tmp/.../scratchpad/bootstrap-gitops.sh` — an ad-hoc shell reimplementation written to
  work around the drifted playbook. It has real bugs:
  - `until oc get clusterversion` and the two `until oc get ...` waits are **unbounded** —
    no timeout, can hang forever.
  - The apply loop (`for i in $(seq 1 20)`) logs `retry` on failure but **falls through
    without `exit 1`** if all 20 attempts fail → the script reports success even when the
    app-of-apps never applied (silent failure under `set -euo pipefail`, which the loop
    defeats).
  - It **never creates an ArgoCD CR** — it relies on the operator's default ArgoCD, so had
    it been the path taken, the cluster would have come up missing every Lua health-check,
    the CMP plugin, and the resource tuning that the playbook carries. Heredoc-inlined
    Namespace/OG/Subscription/CRB duplicate the playbook = two sources of truth.

Recommendation: **delete `bootstrap_openshift_gitops.yaml` and `bootstrap-gitops.sh`;
keep `hub-cluster/bootstrap_gitops.yaml` as the single entry point** and add a smoke +
idempotence test (re-run must be a no-op).

### 3. Live-only ArgoCD CR patches — the biggest "fix not in code" debt

`argocd-patch.json` in the scratchpad captures two changes applied **directly to the live
ArgoCD CR** (which is playbook-created, not GitOps-managed) and **confirmed absent from git
and from the bootstrap playbook**:

1. `spec.resourceHealthChecks += external-secrets.io/PushSecret` → a Lua check that always
   returns `Healthy` (so the deliberately read-only Connect token's failing PushSecrets stop
   blocking the wave gate).
2. `spec.repo` resources bumped to cpu=2 / mem=2Gi + `ARGOCD_EXEC_TIMEOUT=3m` (heavy helm
   render of `clusters/ocp/` exceeded the default 90s on 1 CPU, causing the recurring
   `Unknown`/`DeadlineExceeded` wave stalls). I verified the playbook's ArgoCD CR still
   ships `repo.resources.limits` = cpu:"1"/mem:1Gi and has **no** PushSecret check and **no**
   `ARGOCD_EXEC_TIMEOUT`.

Because the CR is recreated by `bootstrap_gitops.yaml`, **any future DR re-run wipes both
patches and re-introduces the exact wave-gate stall and repo-server timeout that cost time
this incident.** Fold both into the playbook's ArgoCD CR. Note the patch was hand-assembled
as a *full* `resourceHealthChecks` array (re-listing every existing check plus the new one) —
brittle to keep in sync; a strategic-merge/JSON-patch that adds *only* the PushSecret entry
is safer than replacing the whole array.

### 4. `deploy_pxe_assets.yml` — wrong destination + CLI-arg secrets

`playbooks/openshift/agent-install/deploy_pxe_assets.yml` re-generated the control-plane PXE
artifacts (good), but:

- **Delivers to retired infra.** Play 2 ("Copy boot artifacts to TrueNAS netbootxyz
  directory") writes to `/mnt/ssd/containers/netbootxyz/{assets,config/menus}` — the
  netbootxyz container was retired post-2026-05-11; serving moved to public nginx at
  `/mnt/ssd/public/boot-files/`. During recovery the operator had to **manually** `chmod 755`
  + upload to the correct path (memory + open ansible#311). A publish playbook that writes to
  a dead path is worse than no playbook.
- **Secrets on the command line.** The `op item create ... kubeconfig[password]={{ ... |
  b64encode }} client_key_data[password]={{ ... }}` task passes the cluster-admin kubeconfig
  and client key as **shell argv**. `no_log: true` only hides it from Ansible output — the
  values are visible in the host process table (`ps aux`) for the command's lifetime. Also
  `op item create` is Connect-mode-incompatible, so this task was `--skip-tags op-save`'d
  during the very scenario it exists for (a task you must skip during DR is a smell). Use
  stdin/templated input or the `community.general.onepassword*` modules; never argv.
- **Auth dir copied to `/tmp/<cluster>-auth/` mode 0644** → cluster-admin kubeconfig
  world-readable in a shared tmp.
- **Item name is minute-timestamped** (`%Y%m%d%H%M`) → every re-run mints a new 1P item;
  append-only sprawl, not idempotent (acceptable for audit trails but undocumented/unpruned).

Contrast with **`add_node_iso.yml`, which is the model to converge everyone on** (see §5).

### 5. `add_node_iso.yml` — the good example, use it as the bar

`playbooks/openshift/add_node_iso.yml` is genuinely well-engineered and should be the
template the other netboot/publish plays are lifted to:

- Strong fail-fast preflight: KUBECONFIG asserted, worker group non-empty, **MAC regex-
  validated**, already-joined nodes discovered and **excluded so re-runs are idempotent**,
  at-least-one-pending assert.
- `no_log` on the pull-secret fetch + `chmod 0600` lockdown of the written `auth.json`.
- **Correct** public-nginx destination *and* the `--chmod=F0644,D0755` rsync workaround with
  an inline comment explaining the 403/boot-loop it prevents.
- Monitor task tagged `[monitor, never]` (opt-in), thorough header runbook.

The delta between this and `deploy_pxe_assets.yml` is exactly the drift that hurt during
recovery. Recommend factoring the shared "render assets → publish to public nginx with the
world-readable chmod" logic into one role/task file both plays import.

### 6. NVMe `hostnqn`/`hostid` collision — real bug, no code fix yet

The cluster-wide latent bug (all 3 nodes share
`nqn...uuid:466937ab-...` in `/etc/nvme/hostnqn` + `/etc/nvme/hostid`) has **no codified
remediation**. I confirmed the only NVMe MachineConfig in git is
`clusters/ocp/machineconfigs/99-master-load-nvme-tcp-machineconfig.yaml` (loads the module) —
nothing regenerates the identity. The only session artifacts are the throwaway
`nvme-test.sh` / `nvme-clean.sh` (hardcoded NQNs/UUIDs/target IP `10.10.9.213`;
`nvme-clean.sh` actually `nvme disconnect`s subsystems ad hoc on a node with a crude
`grep -c csi-pvc` success signal). These are diagnostics, not a fix.

Highest-priority hardening: a MachineConfig applying a systemd oneshot (guarded on
`hostid == 466937ab`) that runs `nvme gen-hostnqn > /etc/nvme/hostnqn` + `uuidgen >
/etc/nvme/hostid` then reboots, committed to `clusters/ocp/machineconfigs/`. Better still,
fix the **root cause** — the agent-based install / golden image is baking a fixed NVMe host
identity into every node — so fresh installs never collide. Add a CI/molecule assertion (or a
node-diff check) that the three nodes' `hostnqn` are distinct.

### 7. CNPG recovery bootstrap is now the committed steady state (DR footgun)

`quay-pg-recovery.yaml` in the scratchpad is well-commented and thoughtful (`enablePDB:
false` with rationale, control-plane `nodeSelector` pin to dodge the Multi-Attach bug,
"declared to avoid ArgoCD drift" defaults — good SSA hygiene). But I confirmed that #387/#388
committed **`bootstrap.recovery` (not `initdb`)** into all three CNPG cluster CRs on
`origin/main`:

- `components/quay-operator/quay-pg-cluster.yaml` (recovery, serverName `quay-pg-r20260704`)
- `components/rhdh/rhdh-pg-cluster.yaml` (recovery, `rhdh-pg-r20260704`)
- `applications/forgejo/forgejo-pg-cluster.yaml` (recovery, `forgejo-pg-r20260704`)

CNPG only runs `bootstrap` at cluster *creation*, so this is inert on the live cluster — but
the desired state now encodes a **one-time point-in-time restore as permanent config**, with
a date-stamped magic serverName. If these manifests are ever replayed to stand up a fresh
cluster (the exact DR path just exercised), they'll attempt recovery from an
ever-staler backup. Per the memory's own follow-up #5: **revert `recovery`→`initdb` now that
the DBs are verified** (keep the recovery block commented, as done), and move the restore
into the existing `docs/runbooks/cnpg-backup-restore.md` + a parameterized restore playbook
rather than leaving recovery hot in the desired state.

### 8. Cross-cutting: stale checkout, secrets on disk, un-codified steps

- **Stale local checkout caused a wrong apply.** `/workspace/igou-openshift` local `HEAD` is
  `59a2bc7`, well behind `origin/main` (`d81e454`). `kustomize build | oc apply` from it
  rendered *old* manifests (quay came up with `initdb` instead of `recovery`), per memory.
  `bootstrap-gitops.sh` also `cd`s into this local tree. Hardening: recovery tooling must
  `git fetch && git reset --hard origin/main` (or clone fresh) before any local render, or —
  better — apply **only through ArgoCD** (which pulls the remote) and never local
  `kustomize | oc apply`. Add a preflight that aborts if `HEAD != origin/main`.
- **Long-lived secrets persisted in cleartext.** The scratchpad holds
  `agent-install-override.yml` (the **full pull secret** incl. `registry.redhat.io` /
  `quay.io` tokens), `pull-secret.json`/`.yaml`, `op-sa-token`, `connect-token`,
  `agent-auth-token`, `1password-credentials.json`; plus the DR SA token was written to
  `~/.secrets/op-dr-sa-token`. The pull secret is a durable credential. Recommend: stream
  secrets from `op` at point-of-use (the `-e @override.yml` inline-literal pattern that
  bypassed op is convenient but leaves the crown jewels on disk), and `shred` the incident
  scratch at close.
- **Recovery was hand-run one-liners, not codified.** Worker re-join, CSR approval (the
  `awk '$5=="Pending"'` bug — CSR CONDITION is column 6 — silently matched nothing and cost
  ~40 min; correct form is the `go-template ... if not .status` approve), the truenas-w1 VM
  quirks (`time: UTC` to fix the Ignition x509 "cert not yet valid", CDROM device order
  1000→1010, full QEMU restart), and the NVMe cleanup were all ad hoc. Fold the CSR-approve
  idiom and the VM-clock/CDROM ordering into `add_node_iso.yml` / a truenas-vm playbook so
  they can't recur.
- **Root cause is itself a config choice.** The disaster trigger — the rb5009 per-host pin
  defaulting to `install-openshift` on a 30s timeout with MS-01 netboot-first — is a
  netboot-pin *template* default. inv#120 (pin default `local`) is merged; also ensure the
  pin generator never defaults to `install` and that MS-01 UEFI de-prioritizes PXE. This is
  the single change that most reduces blast radius.

### 9. What's already good (keep / build on)

- `add_node_iso.yml` — defensive, idempotent, documented (the standard to converge on).
- The `david-igou.openshift_agent_install` role **has molecule coverage**
  (`molecule/default/{converge,verify}.yml` + CI) — the install layer is tested even though
  the publish plays around it drifted.
- Runbooks exist: `docs/runbooks/nvmeof-stuck-multiattach.md` and
  `docs/runbooks/cnpg-backup-restore.md`.
- CNPG CRs show real SSA-drift discipline (operator-defaulted fields declared explicitly).

### Prioritized hardening backlog

1. **P0 — NVMe hostnqn/hostid:** commit a per-node identity-regen MachineConfig (or fix the
   install media) + a node-diff assertion. Real correctness/corruption risk, zero code today.
2. **P0 — fold the live ArgoCD patches into `bootstrap_gitops.yaml`** (PushSecret health-check
   + repo-server cpu=2/timeout=3m) so DR re-runs don't reintroduce the wave stalls.
3. **P1 — fix `deploy_pxe_assets.yml`** destination path (public nginx) and remove CLI-arg
   secrets; lift it to `add_node_iso.yml`'s bar; share a common publish task file.
4. **P1 — consolidate GitOps bootstrap to one playbook**; delete
   `bootstrap_openshift_gitops.yaml` and `bootstrap-gitops.sh`; add smoke + idempotence tests.
5. **P1 — revert CNPG `recovery`→`initdb`** in git now DBs are verified; keep restore as a
   parameterized runbook/playbook.
6. **P2 — replace `recomment.py`** with a declarative per-app `enabled` flag / ApplicationSet
   generator; if scripted, YAML-parse + hard-fail on unmatched names.
7. **P2 — staleness guard + secret hygiene:** recovery tooling fetches/pins `origin/main`
   (or applies only via ArgoCD); stream secrets from `op`, shred incident scratch, remove the
   persisted pull secret and SA tokens.
8. **P2 — codify worker re-join quirks** (CSR go-template approve, VM `time: UTC`, CDROM
   ordering) into playbooks.

---

## Perspective: Virtualization Administrator

Scope: the Hermes KubeVirt VM rebuild, the storage-attach failures rooted in the shared NVMe host NQN plus democratic-csi nvmeof multi-attach, VM clock/UTC correctness, boot/firmware configuration, the golden-image / DataVolume strategy, RWO PVC placement and affinity, and VM lifecycle / HA on a three-node cluster. All findings below are backed by live inspection of the recovered cluster (`ocp.igou.systems`, CNV 4.21.10, 3 nodes) and the `origin/main` GitOps + Ansible sources on 2026-07-04.

### Current state (verified)

- CNV `kubevirt-hyperconverged.v4.21.10` Succeeded; HCO Available, all virt pods Running across the 3 nodes.
- One workload VM: `hermes/hermes`, `runStrategy: Always`, Running on `hpg5.igou.systems`, VMI Ready, `AgentConnected: True` (qemu-guest-agent up).
- Disks: `hermes-root` (DataVolume clone of DataSource `centos-stream10`, 30Gi) and `hermes-state` (Argo-owned blank DataVolume, 30Gi) — **both RWO, Block, on `freenas-nvmeof-ssd-csi`** (the default StorageClass).
- Golden images: 6 auto-imported DataSources (centos-stream9/10, fedora, rhel8/9/10) all bound on `freenas-nvmeof-ssd-csi`, RWO/Block, refreshed by DataImportCrons (`33 10/12 * * *`, `garbageCollect: Outdated`).
- `hermes-vm-hardening` ValidatingAdmissionPolicy is deployed and enforcing (masquerade-exclusive networking, no hostDevices, no GPUs).

---

### Findings

#### 1. CRITICAL — NVMe-oF host NQN is shared across all nodes at *two* layers; the memory's proposed MachineConfig fix is necessary but **not sufficient**

The incident record correctly flags that all three RHCOS nodes were baked with the identical `/etc/nvme/hostnqn` + `/etc/nvme/hostid` `...466937ab...` and prescribes a MachineConfig to regenerate them. Live inspection shows the problem is deeper and the prescribed fix alone will **not** cure the nvmeof attach failures:

- Host files, all 3 nodes: `/etc/nvme/hostnqn` = `/etc/nvme/hostid` = `466937ab-67bf-4315-971b-bc110d55ce28` (still shared — unfixed).
- **But every live democratic-csi nvmeof connection on every node uses a *different* host NQN: `941e4f03-2cd6-435e-86df-731b1c573d86`** — and that value is *also identical on all three nodes* (verified on master, hpg5, and truenas-w1 via `nvme list-subsys`).
- Source confirmed: the `csi-driver` container in each `democratic-csi-nvmeof-ssd-config-node-*` pod ships its **own image-baked `/etc/nvme/hostnqn` = `941e4f03...`** (`oc exec ... cat /etc/nvme/hostnqn`). The node plugin does **not** bind-mount the host's `/etc/nvme`, so `nvme connect` runs with the container's constant NQN, identical for every pod on every node.

Consequence: NVMe-oF host uniqueness is violated for the volumes that actually matter (all VM disks + all os-image golden PVCs), and rewriting `/etc/nvme/hostnqn` on the host will change nothing for CSI traffic — the driver overrides it with `941e4f03`. This is precisely the failure window that bit the Hermes rebuild ("2nd nvmeof-ssd disk failed to attach on hpg5 while root attached"): with one shared host NQN, the TrueNAS target sees the same host identity from multiple node IPs, and during any reattach/failover window (node down → force-detach → reattach elsewhere, or an RWX multi-attach) associations collide and connects are rejected.

Recommended fix (ordered, all three parts required):
1. MachineConfig (all roles, not just master) with a systemd oneshot that writes a unique `/etc/nvme/hostnqn` (`nvme gen-hostnqn`) and `/etc/nvme/hostid` (`uuidgen`) when the current value equals the shared `466937ab`, `Before=` the kubelet/CSI node plugin starts, then reboot in a controlled rolling fashion.
2. **Make democratic-csi use the host value**: bind-mount host `/etc/nvme` (hostPath) into the `csi-driver` container so `nvme connect` inherits the now-unique per-node NQN/hostid instead of the image constant `941e4f03`. Without this step the OS fix is cosmetic. This is a change to the democratic-csi Helm values / node-plugin pod spec in the GitOps repo.
3. Drain/tear down existing controllers (the reboot in step 1 does this) so live associations re-establish under the unique NQN; verify with `nvme list-subsys` that each node now shows a distinct `hostnqn=`.

Until fixed, treat every VM as pinned: **do not** stop/start, migrate, or trigger a failover of the Hermes VM (the memory's "don't stop/start until hostnqn fixed" is correct and should be a hard gate).

#### 2. HIGH — Hermes VM is not live-migratable, so node drains / MCO updates on its host will not evict it cleanly

`oc get vmi hermes` reports `LiveMigratable: False` — "PVC hermes-root is not shared, live migration requires ReadWriteMany". There are in fact **two** independent migration blockers:
- Storage: root and state are RWO (not RWX), so no shared-disk migration; `migrationMethod` resolves to `BlockMigration` which is gated off for these disks.
- CPU: the VMI runs with `cpu.model: host-model` (KubeVirt default; the Ansible role sets no model and HCO sets no `defaultCPUModel`). host-model bakes the source host's CPU flags into the domain, which would block migration to a *different* CPU anyway — and MS-01 (control plane) and hpg5 are dissimilar hardware.

Meanwhile the cluster-wide `evictionStrategy: LiveMigrate` (HCO default) is inherited by the VMI (`spec.evictionStrategy: LiveMigrate`), and the Ansible role never overrides it. For a VMI that *cannot* migrate, this combination means an `oc adm drain` / MCO reboot of the hosting node will not gracefully evict the VM — virt-api refuses the launcher eviction and the drain stalls until the VM is manually `virtctl stop`-ed. (Confirmed there is currently no KubeVirt disruption-budget PDB in the `hermes` namespace, because KubeVirt only creates one for migratable VMIs — so the block is enforced by the eviction webhook, not a PDB, but the operational result is the same: node maintenance on hermes' host is not hands-off.)

Recommendation for this small, RWO-backed cluster: set `evictionStrategy: None` explicitly on the VM (add it to the `kubevirt_vm_provision` role's VM spec). With `runStrategy: Always`, a drain then simply shuts the VM down and it restarts on the other eligible node — deterministic maintenance instead of a hung drain. If live migration for HA is genuinely wanted later, it requires *both* RWX shared-block storage (see finding 3) *and* a common named CPU model (set HCO `defaultCPUModel` to a baseline both hosts share, or pin `cpu.model` on the VM) — not just one.

#### 3. HIGH — All VM disks and all golden images sit in a single storage failure domain on the fragile transport

Every VM disk and every os-image DataSource PVC is on `freenas-nvmeof-ssd-csi` — one TrueNAS box, over the exact NVMe-oF transport implicated in finding 1. If TrueNAS is unavailable, no VM can boot *and* no golden image is present to clone a rebuild from. Note also `truenas-w1` (a KVM guest on that same TrueNAS) is correctly excluded from VM scheduling by HCO `workloads.nodePlacement` (NotIn truenas-w1) — good — which leaves only the control-plane node and hpg5 able to host VMs; one of those two is the single control plane and thus a cluster-wide SPOF.

The `ctrl-loss-tmo=-1` / `reconnect-delay=10` tuning in the nvmeof driver config is a sound, deliberate choice for a single-target no-multipath topology (I/O queues rather than errors during a blip → the VM freezes and resumes instead of corrupting), and the `docs/runbooks/nvmeof-stuck-multiattach.md` runbook is thorough. Recommendations:
- Accept the single-target reality but make golden-image availability independent of live TrueNAS health where cheap: the DataImportCron-imported DataSources are already PVC-backed, so a TrueNAS outage does strand them — consider a second StorageClass/backend (even node-local LVMS `lvms-lvm-local-storage`, which exists) for at least the golden images or a boot-critical VM, so a rebuild isn't fully gated on TrueNAS.
- The nvme-tcp kernel module is declaratively loaded only on `master` (`99-master-load-nvme-tcp` MachineConfig targets role master). Workers currently get it only because the CSI node plugin modprobes via its host mount. Add a worker (or all-roles) `modules-load.d/nvme-tcp.conf` MachineConfig so worker nvmeof does not silently depend on CSI-pod side effects.

#### 4. MEDIUM — No protected backup/restore path for `hermes-state` (the only irreplaceable VM data)

`hermes-state` holds the agent's identity/config (`auth.json`, `SOUL.md`, `config.yaml`, memory) and during recovery it was restored **by hand** — `dd`/`tar` of an old zvol clone into a blank Block PVC. There is no scheduled backup of it in GitOps and no automated restore. The root disk is disposable (cloned from the golden DataSource), so state is the whole game.

The building blocks exist and are underused: `roles/kubevirt_vm_snapshot` + `playbooks/hermes/snapshot-vm.yml` are present, the guest agent is connected (so online, filesystem-quiesced VirtualMachineSnapshots work), and `volumeSnapshotStatuses` shows both `root` and `state` are snapshot-capable. Recommend a scheduled VirtualMachineSnapshot (or at minimum a VolumeSnapshot of `hermes-state`) plus an off-cluster export (the existing TrueNAS/RustFS pattern), and document the block-device restore procedure as a runbook so the next recovery isn't improvised.

#### 5. MEDIUM — Golden image for the security-sensitive agent is an unpinned moving target

`hermes-root` clones via `sourceRef: DataSource centos-stream10`, and that DataSource is continuously re-imported from `docker://quay.io/containerdisks/centos-stream:10` by the DataImportCron (12-hourly, `garbageCollect: Outdated`). Every VM rebuild therefore picks up whatever the latest upstream Stream 10 containerdisk happens to be — non-deterministic and an unpinned supply-chain surface for a VM that runs an autonomous agent with credentialed egress. Recommend either pinning the Hermes root clone to a specific image digest / a dedicated frozen DataSource that is updated deliberately, or at least recording the imported digest so a rebuild is reproducible and auditable. The `cloneStrategy: snapshot` smart-clone itself is correct and efficient (verified working: hermes-root DV Succeeded from the snapshot clone) — keep it.

#### 6. LOW — Clock is correct-by-default but not explicit; and BIOS boot is a hardening step backward

- **Clock/UTC**: the KubeVirt VM has no `spec.domain.clock` stanza, so libvirt defaults to `<clock offset='utc'>` — which is correct. (The `time: LOCAL` RTC bug called out in the incident was the *TrueNAS-hosted* worker VM `truenas-w1`, a KVM guest, not a KubeVirt VM — a different code path; that fix `midclt vm.update 5 {"time":"UTC"}` was right and does not apply here.) Still, for determinism I recommend setting `clock.utc: {}` with an explicit `timer` block on the VM and confirming `chronyd` is active in the guest (the centos-stream10 cloud image ships it) so agent timestamps and any TLS/token validity are anchored.
- **Firmware**: the VM boots `firmware.bootloader.bios: {}` (SeaBIOS, no UEFI, no Secure Boot). The provisioning role already supports `vm_firmware: efi`. For a security-boundary VM, UEFI (and evaluating Secure Boot re-enablement, which the memory notes was dropped) is the stronger posture; at minimum revisit why BIOS was chosen and whether EFI is now viable on the current golden image.

#### 7. LOW — VM-hardening VAP is good but leaves firmware/eviction/storage unconstrained

`hermes-vm-hardening` correctly forbids non-masquerade interfaces, hostDevices, and GPUs (so the EgressFirewall/NetworkPolicy boundary can't be bypassed). Gaps a future iteration could close, given this is a policy-guarded security VM: assert `firmware`/bootloader shape, forbid `evictionStrategy` values that reintroduce the stuck-drain behavior, and constrain the disk StorageClass, so a hand-edited or drifted VM can't quietly weaken the intended shape.

---

### Prioritized recommendations

| # | Priority | Action | Why it matters |
|---|----------|--------|----------------|
| 1 | Critical | Give each node a unique `/etc/nvme/hostnqn`+`hostid` **and** bind-mount host `/etc/nvme` into the democratic-csi `csi-driver` container so CSI stops using its image-baked shared `941e4f03` NQN | Both layers are currently shared; the memory's host-only fix does not touch CSI traffic. This is the direct cause of VM disk-attach failures and blocks safe failover/migration |
| 2 | High | Set `evictionStrategy: None` on the Hermes VM (role default) while it is RWO/non-migratable | Turns a hung `oc adm drain`/MCO reboot into a clean stop-and-reschedule; makes node maintenance hands-off |
| 3 | High | Keep the Hermes VM pinned (no stop/start/migrate) until recommendation 1 lands | Every lifecycle op currently risks the multi-attach collision |
| 4 | High | Put at least the golden images (or a boot-critical VM) on a second backend; add a worker/all-roles nvme-tcp `modules-load.d` MachineConfig | Removes total dependence of VM boot + rebuild on one TrueNAS box and on CSI-pod modprobe side effects |
| 5 | Medium | Schedule VirtualMachineSnapshots of Hermes (guest-agent quiesced) + off-cluster export of `hermes-state`; write the block-PVC restore runbook | `hermes-state` is the only irreplaceable data and was restored by hand last time |
| 6 | Medium | Pin/record the centos-stream10 golden image digest used for the Hermes root | Reproducible, auditable rebuilds of a credentialed agent VM |
| 7 | Low | Move Hermes to UEFI (`vm_firmware: efi`), add explicit `clock.utc`/timer, verify chronyd; extend the hardening VAP to cover firmware/eviction/storage | Consistency, hardening, and drift protection |
| 8 | Low | For any future live-migration HA: adopt RWX shared-block storage *and* a common `defaultCPUModel` together | host-model + RWO are two independent migration blockers; fixing one alone does nothing |

---

## Perspective: Database Administrator

**Scope:** the three CloudNativePG (CNPG) `Cluster` databases restored after the 2026-07-03
disaster — `rhdh-pg` (namespace `rhdh`, database `backstage`), `forgejo-pg` (namespace
`forgejo`, database `forgejo`), and `quay-pg` (namespace `quay-enterprise`, databases `quay`
+ `clair`). Assessed live against the cluster (read-only) and against `origin/main` of
`igou-io/igou-openshift`.

**Bottom line:** the restore worked. Two of three databases are fully recovered, healthy, and
already taking fresh backups on a new timeline; the third (quay) is mid-recovery and progressing
normally. The backup design is solid and well-documented, but it carries **one critical DR gap
(backups share a failure domain with primary storage)** and **one latent footgun (a Cluster
recreate would silently roll back to the pre-disaster snapshot)** that should be closed.

---

### 1. Restore verification (read-only table counts via `oc exec … psql`)

Non-system tables = `information_schema.tables` excluding `pg_catalog` / `information_schema`,
`table_type='BASE TABLE'`.

| Cluster | DB | Non-system tables | Extra signal | State |
|---|---|---|---|---|
| `rhdh-pg` (rhdh) | `backstage` | **119** across 18 Backstage schemas (catalog 17, adoption-insights 13, auth 12, events 10, permission 9, search 9, …) | — | **Ready**, timeline 2, read-write primary `rhdh-pg-1` |
| `forgejo-pg` (forgejo) | `forgejo` | **128** | **356 repositories, 6 users** — real data present | **Ready**, timeline 2, read-write primary `forgejo-pg-1` |
| `quay-pg` (quay-enterprise) | `quay` | **103** (+ `clair` **31**) | repository 3 / user 4 at current replay point | **In recovery** — `quay-pg-1-full-recovery` pod replaying WAL, `pg_is_in_recovery()=t`, queryable read-only |

All three counts meet or exceed the restore-time baselines recorded in the incident memory
(rhdh 111 → now 119 as RHDH ran its startup migrations post-recovery; forgejo 128 matches
exactly; quay confirmed at 103 via the in-recovery instance's local socket). **The restores are
correct** — schema and data are intact, not empty shells.

Quay was verified by connecting read-only to the still-recovering instance (it reached
"consistent recovery state" so it accepts read-only queries). Its table structure is fully
present; row counts will settle at final values once WAL replay completes and it promotes.

---

### 2. Quay recovery status — progressing, not stuck (do not intervene)

`quay-pg` has been in `Setting up primary` / `full-recovery` for ~45 min. This is expected, not a
hang:

- Base backup restored: "database system … last known up at **2026-07-02 03:33:46 UTC**"
  (the last daily base before the disaster).
- Redo starts `1B2/62000028`; consistent recovery state reached at `1B3/A6016BC0` (base
  end); now replaying continuous WAL forward toward the last archived segment (~`1B8/3A…`).
- That is roughly **37 hours / ~20 GB of WAL** being fetched **one 16 MB segment at a time**
  from the RustFS S3 endpoint and gunzipped — inherently slow but the LSN is advancing steadily
  and `restartpoint` checkpoints are pruning replayed WAL.
- PVC headroom is fine: 40 Gi PVC at **51% (20 G used / 20 G free)** mid-replay; no risk of
  filling.

`recovery_target_action = promote` with no explicit target → it will recover to the end of the
archived WAL, promote to timeline 2, and become the read-write primary. **Expected outcome:
completes on its own.** After promotion, verify `quay`/`clair` final table+row counts, that the
quay app connects, and that quay's first ScheduledBackup + WAL archiving to `quay-pg-r20260704`
succeed (see §5).

---

### 3. Backup architecture — as designed

- **CNPG operator 1.29.1** + first-party **Barman Cloud Plugin v0.12.0** (`barman-cloud` Deployment
  in `cloudnative-pg` ns, 1/1 Available). This is the supported replacement for the deprecated
  in-tree `.spec.backup.barmanObjectStore` — good forward choice.
- **Per-DB `ObjectStore`** → `s3://cnpg-backups/<db>` on the TrueNAS S3 endpoint
  `https://truenas.igou.systems:20292` (RustFS), gzip compression on both `wal` and `data`,
  `retentionPolicy: 30d` (recovery-window, correctly set at ObjectStore top-level per the runbook's
  field-trap notes).
- **Continuous WAL archiving** via the cluster's `plugins[].isWALArchiver: true`.
- **Daily base backups** via `ScheduledBackup` (method `plugin`, `immediate: true`), staggered:
  forgejo 03:00, quay 03:15, rhdh 03:45. forgejo and rhdh both show
  `lastScheduleTime 2026-07-04 01:52` and a `completed` Backup object.
- **PITR capability: yes.** Base + continuous WAL = recover to any point in the 30d window.
  The DR bootstrap used "recover to end of archive"; a point-in-time restore is available by adding
  `bootstrap.recovery.recoveryTarget` (targetTime/targetLSN) on a restore Cluster.

The runbook (`docs/runbooks/cnpg-backup-restore.md`) is genuinely good — it documents the exact
field traps (retention location, empty `serverName` on ObjectStore, same-namespace ObjectStore,
plugin-in-operator-namespace, SCC `runAsUser` strip, sync-wave ordering of the S3-creds
ExternalSecret) that make this setup fragile if mis-copied.

---

### 4. Recovery-bootstrap flow + the archive-serverName conflict fix — correct

The restore pattern used on all three:

```
bootstrap.recovery.source: <db>-pg
externalClusters[<db>-pg].plugin.parameters: { barmanObjectName: <db>-pg-backup, serverName: <db>-pg }   # ORIGINAL serverName → finds pre-disaster data
plugins[barman-cloud].parameters.serverName: <db>-pg-r20260704                                            # NEW serverName → post-recovery archiving
```

The **serverName fix is the crux and it is verified working.** If the recovered cluster archived
WAL back to the same `serverName` it recovered from, CNPG refuses with
*"WAL archive check failed: Expected empty archive."* Setting the archiver's `serverName` to a
fresh value (`<db>-r20260704`) sends the new timeline's WAL/backups to a clean path. Confirmed live:

- rhdh-pg and forgejo-pg archive to `rhdh-pg-r20260704` / `forgejo-pg-r20260704`.
- `ContinuousArchiving=True (ContinuousArchivingSuccess)` and `LastBackupSucceeded=True` on both —
  i.e. the post-recovery archive path is not just configured, it has already taken a successful
  fresh base backup. **The recovered databases are already protected on the new timeline.**
- `cnpg-s3-credentials` ExternalSecret is `SecretSynced=True` in all three namespaces.

---

### 5. Risks & concerns

**CRITICAL**

1. **Backups share a failure domain with primary storage.** The `cnpg-backups` bucket lives on the
   same TrueNAS box (RustFS + `freenas-nvmeof-ssd` pools) that hosts the primary DB PVCs. A TrueNAS
   loss destroys primary **and** every backup simultaneously — this exact recovery only worked
   because the disaster hit the *cluster*, not TrueNAS. The runbook itself flags this. This is the
   single biggest reliability gap.

2. **Latent re-bootstrap footgun — a Cluster recreate silently rolls back to the pre-disaster
   snapshot.** `origin/main` still carries `bootstrap.recovery` with `externalClusters.serverName`
   pointed at the **pre-disaster** paths (`rhdh-pg` / `forgejo-pg` / `quay-pg`). Bootstrap is a
   no-op on an already-initialized cluster, so nothing breaks today. But if the Cluster CR is ever
   deleted and recreated by ArgoCD (a prune, a PVC loss, a manual delete/resync), it will
   re-bootstrap from the **frozen 2026-07-02/03 backup**, silently discarding everything written
   since go-live. The incident memory's follow-up "revert bootstrap recovery→initdb" is **not yet
   done** — and reverting to `initdb` is the *wrong* fix (a recreate would then come up **empty**).

**HIGH / MEDIUM**

3. **Single-instance on SNO — no HA, RPO/RTO exposure.** All three are `instances: 1`,
   `enablePDB: false`, RWO NVMe-oF, pinned to the control-plane host. There is no standby to fail
   over to; any primary/PVC loss is downtime until a restore. RPO is effectively near-zero *if* the
   WAL archive survives (last archived WAL), but up to ~24 h if only a base survives. RTO is
   material — quay's replay is demonstrating a **45 min+** restore time.

4. **Daily-only base backups drive long RTO on large/high-churn DBs.** Quay must replay ~37 h of
   WAL because its only base is the prior 03:15 run. A second daily base (or a post-change on-demand
   base) for quay would cut restore time dramatically.

5. **Quay currently has no fresh backup coverage.** Until it promotes and its ScheduledBackup +
   archiving to `quay-pg-r20260704` go active, quay is unprotected on the new timeline. Watch it to
   completion and confirm the first quay backup + `ContinuousArchiving=True`.

6. **Frozen pre-disaster backup paths are now unmanaged by retention.** 30d retention
   (`barman-cloud-backup-delete`) runs against the *archiving* serverName (`<db>-r20260704`). The
   old `<db>` paths are no longer written to, so they will never be auto-pruned — they persist
   indefinitely (useful as a cold DR restore point, but unbounded in size and untracked).

7. **Monitoring gaps / inconsistency.** `rhdh-pg` sets `monitoring.enablePodMonitor: true`;
   `forgejo-pg` and `quay-pg` do not — inconsistent metrics coverage. No backup-health alerting was
   evident. Note also that `.status.lastSuccessfulBackup` is empty on the clusters (cosmetic — the
   plugin path surfaces success via the `LastBackupSucceeded` condition + the `Backup` CR, both
   green); any alerting must key off the condition, not that legacy field.

8. **Cross-cutting NVMe-oF hostnqn bug.** The cluster-wide duplicate `hostnqn`/`hostid` across all
   three nodes (documented in the incident memory) degrades volume-attach reliability for exactly
   these RWO NVMe-oF DB PVCs. Pinning CNPG pods to the control-plane host mitigates reschedule
   churn, but the underlying identity collision should be fixed so a DB pod reschedule can't hit
   "unable to attach" storms.

---

### 6. Recommendations (prioritized)

1. **Break the backup failure domain (DR-critical).** Add a second `ObjectStore` per DB pointed at
   an **off-box / off-site** S3 (Backblaze B2, Wasabi, or a second TrueNAS with replication) so a
   TrueNAS loss no longer takes primary and backups together. The plugin supports multiple stores.

2. **Close the re-bootstrap footgun.** Do **not** revert to `initdb`. Instead, on each recovered
   cluster repoint `externalClusters[].parameters.serverName` from the pre-disaster path
   (`<db>-pg`) to the **live** archive (`<db>-pg-r20260704`), so that a Cluster recreate recovers
   the *current* data, not the frozen snapshot. Add a code-comment/runbook warning that these
   Clusters are recovery-bootstrapped and must never be blindly pruned/recreated.

3. **Finish + validate quay.** Let recovery complete; then verify final `quay`/`clair` counts, quay
   app connectivity, and that quay's first ScheduledBackup and WAL archiving to `quay-pg-r20260704`
   succeed.

4. **Add backup-health alerting.** Prometheus alerts on `ContinuousArchiving=False`,
   `LastBackupSucceeded=False`, and last-backup-age > ~26 h. Add `enablePodMonitor: true` to
   `forgejo-pg` and `quay-pg` for parity with rhdh.

5. **Shorten RTO on quay.** Add a second daily base backup (or twice-daily) for the 40 Gi
   high-churn quay cluster so WAL-replay windows stay small.

6. **Manage the orphaned pre-disaster backup paths.** Once confident the new timeline is the source
   of truth, plan a retention/cleanup (or explicit archival) of the old `s3://cnpg-backups/<db>`
   base+WAL sets so they don't grow unbounded.

7. **Longer term (HA).** Single-instance is the right call on SNO with RWO NVMe-oF today. Once there
   is a second durable, non-ephemeral node with appropriate storage, consider `instances: 2` (and
   re-enabling PDB) for the highest-value DBs (quay, forgejo) to remove the single-primary downtime
   window. Also fix the NVMe-oF `hostnqn` collision so DB-volume attach is reliable under reschedule.

---

### 7. Verdict

- **Restores correct:** yes — backstage (119 tables), forgejo (128 tables, 356 repos), quay
  (103 tables + clair 31) all verified with real data. quay finishing WAL replay.
- **Backup strategy:** sound and well-documented (plugin-based, per-DB stores, daily base +
  continuous WAL, 30d retention, PITR-capable). The serverName-conflict fix is correct and already
  producing fresh backups on the new timeline.
- **Must-fix before calling DR "done":** (1) off-box backup replica to escape the shared TrueNAS
  failure domain, and (2) neutralize the recovery-bootstrap footgun so a future recreate can't roll
  the databases back to the pre-disaster snapshot.

---

## Perspective: Code & Process Readability

Scope: readability and process-clarity of the recovery itself — how discoverable, unambiguous, and repeatable the runbooks, playbooks, naming, and decision-log are for *a second engineer who was not in the room*. Assessed the operational runbooks in `igou-ansible/docs/`, the recovery playbooks, the two OpenShift runbooks in `igou-openshift/docs/runbooks/`, and the incident record `project-ocp-cluster-reinstall.md` plus the `MEMORY.md` index as documentation artifacts. Repos were fetched from `origin/main` because the local `igou-openshift` checkout is 100+ commits stale (a hazard in its own right — see F5).

### Verdict

The homelab is *better documented than most*. There is a real disaster-recovery runbook (`docs/disaster-recovery.md`), a netboot runbook, an OpenShift-operations runbook, and symptom-keyed component runbooks — and the best of them (`nvmeof-stuck-multiattach.md`, `hermes-vm-lifecycle.md`) are genuinely excellent: symptom → confirm → remediate → verify structure, explicit blockquote danger callouts, and stated trade-offs. That baseline is the reason recovery was possible at all.

But this incident exposed a consistent failure mode: **the knowledge that actually saved the cluster lived in the operator's head (and now in a dense memory file), not in the runbooks — and in two places the runbooks actively point a follower at the wrong thing.** A second engineer executing the committed DR runbook literally, without the memory file, would have run a stale playbook and would not have known the one timing-sensitive step that breaks the reinstall loop. The single most important lesson of the whole incident — that a netboot pin can silently wipe a production cluster — is not written down anywhere an operator would look.

---

### Critical findings

#### F1 — The DR runbook sends you to the *wrong, drifted* GitOps-bootstrap playbook (CONFIRMED)

The recovery used `playbooks/openshift/hub-cluster/bootstrap_gitops.yaml` and the memory file is emphatic about it: *"GitOps FULLY bootstrapped via `hub-cluster/bootstrap_gitops.yaml` (the CURRENT one, NOT the drifted `bootstrap_openshift_gitops.yaml`)"* — and two real bugs had to be fixed in it mid-incident (ansible#312).

But both committed runbooks tell an operator to run the *other* file:
- `docs/disaster-recovery.md` → "OCP cluster / Rebuild from scratch" step 4 runs `bootstrap_openshift_gitops.yaml`.
- `docs/openshift-operations.md` → "GitOps bootstrap / Run" runs `bootstrap_openshift_gitops.yaml`, and frames `hub-cluster/bootstrap_gitops.yaml` as a "near-identical playbook for a hub cluster pattern… use it instead when bringing up the hub" — i.e. explicitly *not* for `ocp`.

Evidence of the drift:

| Playbook | Lines | Last touched |
|---|---|---|
| `bootstrap_openshift_gitops.yaml` (what the docs say to run) | 96 | 2026-04-11 (lint pass) |
| `hub-cluster/bootstrap_gitops.yaml` (what recovery actually used) | 623 | 2026-07-03 (#312, during this incident) |

The doc-endorsed playbook is a 3-month-stale 96-line stub; the working one is a 623-line actively-maintained playbook. A follower doing exactly what the runbook says gets a broken bootstrap and no signal as to why. The operator only avoided this from prior memory.

**Recommendation:** Pick one bootstrap playbook as canonical for `ocp`, delete or clearly deprecate the other (a header comment `# DEPRECATED — superseded by hub-cluster/bootstrap_gitops.yaml, do not run`), and update both runbooks to name the real one. This is the highest-value single fix in this review.

#### F2 — The root cause (a netboot pin that silently reinstalls) is undocumented; there is no danger callout and no mid-install pin-flip step

The entire incident was: MS-01 is netboot-first, a per-host pin defaulted to `install-openshift` on a 30s timeout, an unattended reboot wiped the disk, and the mid-install reboot re-entered the installer in a loop that only breaks if you flip the pin to `local` *during* the install.

None of that is in the runbooks:
- No doc warns that a per-host pin defaulting to an installer is destructive on an unattended reboot. `docs/netboot-operations.md` line 51 *reassures* the reader that the fallback menu "offers localboot (default after 30s)" — the destructive install-defaulting host pin is never flagged as dangerous. The only PXE-wipe warning in the whole repo is buried in a 2026-05-06 *superpowers plan* about hpg5's k3s teardown, about a different host.
- The mid-install "flip the pin to `local` or it loops forever" step appears nowhere. The `docs/openshift-operations.md` install flow is just "PXE-boot the rendezvous host" → "watch progress." Grepping the three runbooks for `flip`/`mid-install`/`default local` returns only an unrelated HTTPS↔HTTP note.

The repo already has the right pattern for this — `docs/hermes-vm-lifecycle.md` uses blockquote **"Fully destructive"** callouts. It just was never applied to the netboot install pin, which is the most destructive lever in the whole system.

**Recommendation:** Add a prominent danger callout to `netboot-operations.md` and `disaster-recovery.md`: which hosts are netboot-first, that an install-defaulting pin wipes disk on any reboot, that pins must default to `local` at rest, and the exact "flip to local at status=installing to break the reinstall loop" procedure with the `scp -O …/per-host/MAC-*.ipxe` command. This is a safety writeup, not a nicety.

#### F3 — The shared nvme hostnqn/hostid bug is a latent cluster-wide correctness defect recorded only in the memory file

The recovery found all three nodes baked with the *identical* `/etc/nvme/hostnqn`+`hostid` (`…466937ab…`), which violates NVMe-oF uniqueness and causes intermittent volume-attach failures cluster-wide. This will recur on every future agent-based reinstall.

There is an nvmeof runbook — `docs/runbooks/nvmeof-stuck-multiattach.md` — and it is well-written, but it covers a *different* failure mode (Multi-Attach after a transport drop / `ctrl_loss_tmo`). It contains no mention of `hostnqn`, `hostid`, or `466937ab` (grep: no match). An engineer who hits the shared-hostnqn attach failure and lands on this runbook will follow a remediation that does not fix their problem.

**Recommendation:** File the fix (a MachineConfig regenerating unique hostnqn/hostid per node) and, until then, add a short runbook or a "known latent issue" section to the DR runbook and the nvmeof runbook cross-linking it, with the symptom string ("unable to attach any nvme devices", "Connect command failed error 6") so it's discoverable by search.

#### F4 — Live-only cluster state diverges from git and is recorded only in the memory file

Several load-bearing changes exist *only* on the running cluster, not in git, and are tracked solely as memory-file TODOs:
- ArgoCD CR `spec.resourceHealthChecks` PushSecret Lua health-check (opens the wave gate).
- ArgoCD repo-server `cpu=2 / mem=2Gi` + `ARGOCD_EXEC_TIMEOUT=3m` (the fix for recurring wave stalls).
- `kustomizeBuildOptions --enable-helm` sourced from a playbook-created CR.

The memory file itself flags these as "⚠ live-only (CR playbook-managed) — fold into bootstrap_gitops.yaml." Until that happens, anyone who re-runs the bootstrap playbook silently reverts them, and anyone comparing git to the cluster cannot tell intentional drift from accident.

**Recommendation:** Track these as explicit issues (not memory bullets) and fold them into the bootstrap playbook / GitOps so the cluster is reconcilable from source. This is both a readability (single source of truth) and a durability problem.

#### F5 — The stale-local-checkout hazard is a process footgun with no documented convention

The memory file repeatedly warns that the local `igou-openshift` checkout is stale, so `oc kustomize` renders *old* manifests (it nearly redeployed the pre-recovery quay `initdb` instead of the recovery config). The mitigation the operator adopted — "fetch origin and `git show origin/main:<path>`" — is nowhere in a runbook or the repo's `CLAUDE.md`. This is exactly the kind of trap a second engineer would fall into.

**Recommendation:** Add a one-line convention to the DR runbook and `CLAUDE.md`: "During recovery the control-node checkout may be stale; always `git fetch` and apply from `origin/main`, never from the working tree."

#### F6 — CSR-approval guidance is fragile; the robust method found under fire wasn't captured

A ~40-minute stall during worker re-join came from CSR filtering on the wrong column (`CONDITION` is column 6, not 5), so `awk '$5=="Pending"'` silently matched nothing while bootstrapper CSRs piled up. `docs/openshift-operations.md` offers `oc get csr | awk '/Pending/{print $1}' | …`, which is column-fragile in the same family. The robust approach the operator settled on — approve any CSR with no `.status` via `-o go-template='{{range .items}}{{if not .status}}…'` — is not in the docs.

**Recommendation:** Replace the awk one-liner in the runbook with the status-based go-template form and a one-line note on why (unacted CSRs have empty `.status`, and node re-join issues two rounds per node).

---

### The incident memory file as a documentation artifact

`project-ocp-cluster-reinstall.md` is the de-facto decision log for the whole recovery, so it deserves assessment on its own terms.

**As a personal recall tool it is excellent.** It captures exact commands, file paths, PR numbers, PVC UUIDs, and — importantly — the *why* behind decisions and the operator directives that shaped them ("user CHOSE to leave publishing broken," "GO-LIVE DEFERRED per operator," "p330 stays dark per user"). That decision-provenance is genuinely good practice and better than most human runbooks.

**As a shared artifact for a second engineer it has real readability problems:**

- **Structure is a flat append-only timeline.** ~40 bullets, some 300+ words each, no sub-headings. There is no separation between "current state / what's left" and "narrative of what happened." To answer "is hermes restored?" you must read the whole thing and reconcile three bullets (state PV restored, VM provisioned, convergence still TODO).
- **Durable lessons are buried mid-timeline.** The three highest-value, reusable facts — the destructive-pin root cause, the shared-hostnqn bug, and the three gotchas that each cost 40+ minutes — are scattered in the middle, marked with the same status emoji as ephemera. A reader cannot skim to "what must I never repeat."
- **High cognitive load from unexpanded shorthand.** `zvol`, `CSS`, `HCO`, `CDI`, `MCS`, `OG`, `CVO`, `MCO`, `SSA`, `WAL`, `barman` appear without expansion, mixed with nested parentheticals and stacked status emoji (✅ ⏳ ⚠ 🚨🚨🚨). Fine for the author; a wall for a newcomer.
- **The `MEMORY.md` index has the same trait at the top level** — each entry is a single run-on line packed with abbreviations and PR numbers. It optimizes for the author's grep-and-recall, not for a newcomer's orientation.

**Recommendation:** When this incident closes, promote it from a chronological memory into a short structured post-incident record with four fixed sections: **Root cause** (2–3 sentences), **Timeline** (the existing bullets, unchanged), **Durable lessons / never-again** (the pin hazard, the hostnqn bug, the gotchas — the reusable core, surfaced), and **Follow-ups** (the open TODOs, ideally as tracked issues). The memory file is where reusable operational knowledge is *born*; the gap is that little of it graduates into the runbooks where the next operator will actually look.

---

### Naming and cognitive-load nits

- **Two near-identical playbook names invite exactly the F1 mistake:** `bootstrap_openshift_gitops.yaml` vs `hub-cluster/bootstrap_gitops.yaml`. Whatever the outcome of F1, these two names are too close to sit side by side.
- **`.yml` vs `.yaml` is inconsistent** across sibling playbooks (`add_node_iso.yml`, `deploy_pxe_assets.yml` vs `bootstrap_openshift_gitops.yaml`, `hub-cluster/bootstrap_gitops.yaml`). Trivial, but it costs a second of "which one" every time and breaks tab-completion muscle memory.
- **`sync_1pasword_secrets.yml` has a typo in the filename** — and the runbook *documents the typo* ("fix in a future cleanup pass") rather than fixing it. Documenting a broken name normalizes it.
- **The VM-name-must-be-alphanumeric footgun** (`truenasw1` the VM vs `truenas-w1` the hostname) is a genuine trap; it lives in memory but not in `hermes-vm-lifecycle.md` / the scaffold docs where someone would hit it.

---

### Prioritized recommendations

| # | Action | Type | Priority |
|---|---|---|---|
| 1 | Fix both runbooks to name the correct GitOps-bootstrap playbook; deprecate/delete the drifted 96-line stub (F1) | Correctness of docs | **P0** |
| 2 | Add a netboot-pin danger callout + the mid-install "flip to local" step to netboot/DR runbooks (F2) | Safety writeup | **P0** |
| 3 | Document + track the shared nvme hostnqn/hostid bug and its fix; cross-link from the nvmeof runbook (F3) | Latent correctness | **P0** |
| 4 | Fold the live-only ArgoCD CR patches into git/playbook; track as issues, not memory bullets (F4) | Single source of truth | P1 |
| 5 | Add the "recovery uses origin/main, not the stale working tree" convention to DR runbook + CLAUDE.md (F5) | Process convention | P1 |
| 6 | Replace the fragile awk CSR filter with the status-based go-template form (F6) | Runbook accuracy | P1 |
| 7 | Convert the incident memory into a 4-section post-incident record (root cause / timeline / never-again / follow-ups) | Doc structure | P1 |
| 8 | Normalize playbook extensions, fix the `1pasword` typo, disambiguate the two bootstrap names | Naming hygiene | P2 |

**One-line takeaway:** the runbooks are good but *lagging* — recovery succeeded on operator memory that the committed docs contradict in two places (F1) and omit entirely for the two most important lessons (F2, F3); closing that gap is the difference between "one person can do this" and "any engineer can safely repeat it."

---

## Consolidated Action Items

De-duplicated and prioritized merge of every recommendation across the six persona sections, the four repo/architecture reviews, and the 46 component reviews. **P0** = do before the next reboot (prevents recurrence, active correctness/data-loss, or closes the detection gap); **P1** = weeks (backups, drift, restore-completion, missing capability); **P2** = quarter (hardening, hygiene, cost). Where reviewers disagreed the row notes it.

### P0 — stop the bleeding

| Priority | Item | Rationale | Rough effort | Source reviewer(s) |
|---|---|---|---|---|
| P0 | **Fix the shared NVMe hostnqn/hostid at both layers.** Ship a MachineConfig for *both* master and worker pools with a self-generating oneshot (regenerate `/etc/nvme/hostnqn` + `hostid` only when `==466937ab`, ordered before nvmf-autoconnect/kubelet), roll workers-then-master, **and** bind-mount host `/etc/nvme` into the democratic-csi `csi-driver` container so CSI stops using its image-baked shared `941e4f03` NQN. Bake the same oneshot into agent-install day-1 manifests. | NVMe-oF host-uniqueness violation across all 3 nodes → intermittent volume-attach failures and filesystem-corruption risk on the default StorageClass; already paused the Hermes VM once. Host-only fix is insufficient — CSI overrides it. Reintroduced on every reinstall unless day-1. | Med | Virtualization Admin, Architecture, GitOps Repo, Ansible Repo, K8s Admin, SRE, machineconfigs, democratic-csi (+ echoed by ~15 component reviews) |
| P0 | **Fold the live-only ArgoCD CR patches into git.** Self-manage the ArgoCD CR via a wave-0 GitOps app (preferred) or codify in `bootstrap_gitops.yaml`: repo-server `cpu=2`/`mem=2Gi` + `ARGOCD_EXEC_TIMEOUT=3m`, and the `PushSecret`/`ExternalSecret` Lua health-checks. Add only the PushSecret entry via merge/JSON-patch, not a full-array replace. | These are the exact patches that un-stalled the wave gate and repo-server timeouts during DR; they exist only on the running cluster and are wiped the next time bootstrap runs — reintroducing the stalls during the *next* DR. | Low | K8s Admin, SRE, SWE, Readability, GitOps Repo, Ansible Repo, Incident |
| P0 | **Neutralize the CNPG recovery-bootstrap footgun on all 3 DBs** (quay / rhdh / forgejo). Revert `bootstrap.recovery` to a steady-state (`initdb` for the cheaply-reseedable DBs, per K8s-admin/SWE/GitOps) **or** repoint the recovery `serverName` to the live `-r20260704` archive (DBA's preference, so a recreate restores *current* data rather than empty), and add `ignoreDifferences` on `/spec/bootstrap`. | Git currently encodes a one-shot point-in-time restore as permanent desired state pinned to the pre-disaster archive; a Cluster recreate silently rolls back to the 2026-07-02 snapshot, and the immutable field holds all three apps permanently OutOfSync today. | Low | K8s Admin, SWE, DBA, GitOps Repo, Incident, cloudnative-pg, quay/rhdh/forgejo |
| P0 | **Kill the netboot-first destroy path (defense in depth).** Set MS-01 (and all nodes) firmware to disk-first with PXE as a manual-only option; make `local` the hard default of every netboot menu and move `install-openshift` behind an explicitly-armed, auto-disarming pin; add a CI/lint check that fails on any committed per-host pin defaulting to an install target; make pin push/verify content-hash based (not size-only). | Root cause. `inv#120` (pin default `local`) removed the immediate trap, but firmware is still netboot-first and the install menu still defaults to install on a 30s timeout, so any re-added stale pin re-arms the wipe. | Low–Med | SRE, Architecture, Ansible Repo, Incident, K8s Admin, Readability |
| P0 | **Enable scheduled etcd backups** to an off-cluster / different-failure-domain target (TrueNAS/RustFS S3), managed in GitOps, plus a written+rehearsed single-node quorum-restore runbook. | Single etcd member with zero backup means the next disk/node loss is again a multi-hour ground-up rebuild instead of a ~20-min restore; the cheapest change that converts a repeat event from rebuild → restore. | Low | K8s Admin, SRE, Architecture |
| P0 | **Stand up an external dead-man's-switch / heartbeat** (off-cluster watchdog on TrueNAS or a Pi that probes the API + a canary Route and expects a periodic Watchdog-derived heartbeat; page Gotify/Slack/Telegram on silence). | Whole-cluster loss produces zero alerts because the entire alert pipeline is in-cluster; this is the direct cause of the unbounded MTTD — the single highest-leverage detection fix. | Low–Med | SRE |

### P1 — backups you can trust, and finish the restore

| Priority | Item | Rationale | Rough effort | Source reviewer(s) |
|---|---|---|---|---|
| P1 | **Fix the 1Password Connect write grant** on vaults `claude` + `ocp-push`, then drain the 6 `service-accounts` PushSecrets. | Reinstall minted new SA tokens; 6 automation consumers (claude, molecule, ns-agent, vm-ops, cluster-read-only/edit) still read stale/invalid tokens from 1Password because write-back 403s; ArgoCD "Healthy" masks it. | Low | service-accounts, onepassword-connect, external-secrets-operator, molecule, K8s Admin |
| P1 | **Recover Forgejo correctly.** Re-run recovery with `database: forgejo, owner: forgejo` so the `-app` secret points at the restored DB (currently serving an empty `app` DB); locate + restore the 100Gi `forgejo-shared-storage` git repo filesystem (orphaned zvol / gitea-mirror / GitHub mirrors); add a filesystem backup for it. | forgejo is Running but functionally empty — 356 repos orphaned in the wrong DB and the git objects were never restored and have no backup; also breaks PaC tenants. Active data-loss exposure. | Med | forgejo, DBA |
| P1 | **Restore the alert-delivery path:** deploy the `gotify` bridge and the AAP/EDA event-stream endpoint. | Default Alertmanager receiver NXDOMAINs (gotify ns absent) so push/Watchdog delivery fails and fans out retry-storms to Slack; `eda-github-issue` 503s so no auto-issues are filed. | Low | SRE, alertmanager-config, gotify, ansible-automation-platform |
| P1 | **Unblock the OpenShift Pipelines operator** (delete the stuck shared InstallPlan `install-khg9h` so OLM regenerates a pipelines-only auto plan, preserving ServiceMesh's Manual gate), and move workload operators out of the shared `openshift-operators` OperatorGroup. | Pipelines never installed post-rebuild — its Automatic install is co-bundled with a Manual servicemesh CSV; cascades to `pac-tenants` (all tenant CI down). | Low–Med | openshift-pipelines, pac-tenants, K8s Admin |
| P1 | **Enable OADP/Velero** (operator already in-repo, unenabled) targeting RustFS/S3 for scheduled, restore-tested backups of namespaces + app CRs + PV data as consistent sets; add scheduled Hermes-state + PV-zvol snapshots with retention and an off-box replica. | No consistent point-in-time backup of app resources + PVs exists; Hermes state and forgejo git were recovered by hand/luck. | Med | SRE, Virtualization Admin, Architecture |
| P1 | **Break the backup failure domain.** Add a second off-box/off-site S3 target (Backblaze/Wasabi or a replicated TrueNAS) for the CNPG Barman stores and etcd/PV snapshots; move Barman off the flaky cold RustFS to SSD; add a backup-liveness/credential check. | Every zvol, every Barman bucket, the boot artifacts, and truenas-w1 all live on one TrueNAS — a TrueNAS loss destroys primary + all backups together; the RustFS target was wedged mid-incident and the quay base was ~3 weeks stale. | Med | DBA, SRE, Architecture, GitOps Repo, cloudnative-pg |
| P1 | **Fix the DR runbook to name the correct bootstrap playbook** (`hub-cluster/bootstrap_gitops.yaml`); delete/deprecate the stale 96-line `bootstrap_openshift_gitops.yaml` and the ad-hoc `bootstrap-gitops.sh`; update the molecule converge that validates the wrong artifact. | Both committed runbooks and CI point at a 3-month-stale drifted stub that fails hard on a real DR; recovery only avoided it from memory. Highest-value single doc fix. | Low | Readability, Ansible Repo, SWE |
| P1 | **Write and check in the DR runbook gaps:** netboot-pin danger callout + the mid-install "flip to local" step; the shared-hostnqn known issue cross-linked from the nvmeof runbook; the out-of-band secrets seed order (Connect JWT is the `credential` field; `onepassword_doc` returns bytes → base64/`data:`); the stale-checkout "apply from origin/main" convention; the status-based go-template CSR approve (condition is column 6, not 5). | Nearly every gotcha was rediscovered live; the two most important lessons (destructive pin, hostnqn) are in no runbook an operator would search. | Med | Readability, SRE, GitOps Repo, external-secrets-operator, onepassword-connect, Incident |
| P1 | **Codify the CAPI burst-worker restore.** Reconcile `clusterName` `ocp-hb42r → ocp-m97rd` (in `cluster-config-configmap.yaml` *and* the autoscaler's discovery arg atomically); re-copy `worker-user-data-managed`; recreate the `ocp-m97rd-kubeconfig` secret and patch `ControlPlaneInitialized=True`; fold these one-time steps into GitOps/DR automation. | Reinstall regenerated the infra name; the burst-scale path is broken (latent only because MachineSet is at 0) and the manual bootstrap steps were silently skipped during recovery. | Med | cluster-api, cluster-api-operator, cluster-api-autoscaler |
| P1 | **Fix the llmkube p330 node-pin.** Repoint or `replicas: 0` the `qwen35-2b` InferenceService currently pinned to the dead `p330.igou.systems`. | It will be permanently `Pending` the moment llmkube deploys — stale-hardware config that survived the rebuild. | Low | llmkube |
| P1 | **Correct the openshift-virt placement guard.** Change the virt-handler `NotIn` value from `truenas-w1.igou.systems` to `truenas-w1` (the real hostname label). | The guard meant to keep VMs off the nested-KVM/storage-colocated worker is a silent no-op; virt-handler runs on truenas-w1 today. | Low | openshift-virt |
| P1 | **Guard the single control plane against workload starvation.** Taint the master `NoSchedule` (run user workloads on hpg5/truenas-w1) or, if it must stay schedulable, add per-namespace `ResourceQuota` + default `LimitRange` and explicit memory limits on CNPG/quay/registry pods; confirm system/kube-reserved via kubeletconfig. | No quota/limits on any user namespace; one leaky pod can drive MemoryPressure on the single etcd node → fsync stalls → cascading control-plane instability. | Low–Med | K8s Admin |
| P1 | **Finish app-of-apps convergence and de-couple it.** Split the monolithic health-gated root into a few independent roots (platform/services/apps); add `SkipDryRunOnMissingResource=true` on operator/operand apps; gate operator apps on CSV `Succeeded` rather than broad health. | One monolithic wave ladder serialized the whole recovery — a single degraded low-wave app (quay/service-accounts) froze 7 unrelated apps (firecrawl, searxng, jellyfin, llmkube, gotify, gitea-mirror, AAP). | Med | K8s Admin, GitOps Repo, firecrawl/searxng/jellyfin/llmkube/gotify/gitea-mirror/AAP |
| P1 | **Set `reclaimPolicy: Retain`** on the democratic-csi StorageClasses holding irreplaceable data (or per-PV), and keep the PVC→zvol catalog current. | Every class is `Delete` today; data survived only because the cluster died without issuing CSI deletes — a clean prune would have destroyed the zvols permanently. | Low | Architecture |
| P1 | **Break-glass off-cluster secrets store.** Keep a minimal, documented out-of-band copy of the seed secrets (`1password-credentials.json`, Connect token, pull secret) and codify the seed as a checklisted DR step. | Connect/ESO/AAP all die with the cluster, so every `op` lookup was dead during recovery; a burnt view-once share link nearly blocked the whole restore. | Low | SRE, external-secrets-operator, onepassword-connect |
| P1 | **Add CSR-pending alerting + a tightly-scoped auto-approver** for the 3 known static nodes (select on absent `.status`, not `awk $5`). | Nodes are not Machine-backed, so kubelet serving-cert CSRs never auto-approve; rotation silently breaks `oc logs/exec/adm top`. The column bug cost ~40 min during recovery. | Med | K8s Admin, Architecture, SRE |
| P1 | **Land the nvme-tcp worker/all-roles module-load MachineConfig and the `ctrl_loss_tmo=-1` (#295) udev MachineConfig.** | nvme-tcp is boot-loaded only on master; workers depend on a CSI modprobe side-effect (first-attach-after-reboot race). The #295 multi-attach fix is not host-persistent. | Low | Architecture, machineconfigs, Virtualization Admin |
| P1 | **Add backup-health alerting** (`ContinuousArchiving=False`, `LastBackupSucceeded=False`, last-backup-age > ~26h) and `enablePodMonitor` parity across all 3 CNPG DBs; alert on `PushSecret Ready=False`. | No backup-liveness alerting exists; ArgoCD Healthy masks Errored PushSecrets and stale backups. | Low | DBA, service-accounts |
| P1 | **Persist platform Prometheus** (add `prometheusK8s` storage; the chart already parameterizes `freenas-nvmeof-fast-csi`). | Platform metrics are emptyDir → all history lost on reboot, so there was no telemetry across the very reboot that destroyed the cluster. | Low | SRE, ocp-base-config |

### P2 — make recovery boring / hardening / hygiene

| Priority | Item | Rationale | Rough effort | Source reviewer(s) |
|---|---|---|---|---|
| P2 | **Write and quarterly-drill a full DR runbook / game-day**; set explicit RTO (<2h API, <4h data) and RPO (<24h, <1h DBs); automate the manual recovery steps (idempotent recovery playbook: regen PXE, seed break-glass secrets, scoped CSR approve, drive wave-gate operator bootstraps). | There was no pre-existing tested runbook; MTTR was low only because one expert improvised the whole thing. | Med–High | SRE, Readability, Incident |
| P2 | **Fix `deploy_pxe_assets.yml`:** correct the dead netbootxyz destination → public nginx (with the `chmod 755`/`--chmod=F0644,D0755` fix), remove CLI-argv secrets, `0600` + non-shared the /tmp auth copy; factor a shared publish task with the model `add_node_iso.yml`. | The publish playbook writes to retired infra and leaks the cluster-admin kubeconfig via argv/world-readable tmp; recovery had to hand-upload. | Med | Ansible Repo, SWE |
| P2 | **Consolidate GitOps bootstrap to one playbook** (delete the stale duplicate + the shell reimplementation) and add smoke + idempotence tests; add early `assert target_cluster is defined` and replace the blind 60s sleep with a CRD/CSV wait + retries on the ArgoCD CR create. | Three disagreeing bootstrap artifacts (one drifted, one buggy shell) invited the wrong path mid-incident; the good one has a no-retry create and unguarded vars. | Med | SWE, Ansible Repo, Readability |
| P2 | **Move to a compact 3-node control plane** (or explicitly accept single-node as ephemeral and back it accordingly). | One etcd member / one master = total, immediate cluster loss on any MS-01 event; a 3-node plane would have survived this disaster outright. | High | Architecture, SRE |
| P2 | **Harden the Hermes VM:** set `evictionStrategy: None` while RWO/non-migratable; pin/record the centos-stream10 golden-image digest; schedule guest-agent-quiesced VirtualMachineSnapshots + off-cluster export of `hermes-state` with a block-PVC restore runbook; move to UEFI + explicit `clock.utc`; extend the hardening VAP to firmware/eviction/storage. | Non-migratable VM hangs node drains; the only irreplaceable VM data was restored by hand; the agent's root image is an unpinned moving target. | Med | Virtualization Admin, hermes-agent |
| P2 | **Put golden images (or a boot-critical VM) on a second backend** (node-local LVMS exists) so VM boot + rebuild is not fully gated on live TrueNAS. | Every VM disk and every os-image DataSource is on one TrueNAS over the fragile nvmeof transport. | Med | Virtualization Admin |
| P2 | **Replace `recomment.py` with a declarative per-app `enabled` flag / ApplicationSet generator**; if a scripted toggle survives, YAML-parse + hard-fail on unmatched names + make it reversible. | The lossy regex text-mutator on the single file that controls the whole cluster can silently leave a workload enabled during a staged restore. | Med | SWE |
| P2 | **Staleness guard + secret hygiene:** recovery tooling must `git fetch`/pin `origin/main` (or apply only via ArgoCD) with a preflight that aborts if `HEAD != origin/main`; stream secrets from `op` at point-of-use and `shred` the incident scratch (persisted pull secret + SA tokens). | A stale local checkout already produced one wrong apply (quay `initdb` vs `recovery`); crown-jewel credentials were left in cleartext on disk. | Low | SWE, Readability, Incident |
| P2 | **Codify worker re-join quirks** into playbooks: status-based CSR approve, truenas-w1 VM `time: UTC` (Ignition x509), CDROM device ordering + node-image ISO path (RAW `.dsk` is non-viable), and de-risk the `!! UNTESTED` VM-lifecycle playbooks. | These ad-hoc one-liners each cost debug cycles and will recur on the next worker rebuild. | Med | SWE, Ansible Repo, Incident |
| P2 | **Resolve operator-lifecycle drift:** settle the Manual servicemesh InstallPlan queue, pin floating channels (`gitops`/`pipelines`=latest, `rhdh`=fast), and decide one approval policy per operator. | Half-approved Manual queue + floating Automatic channels = surprise operand migrations with no test tier on a cluster that just proved it has no staging. | Low | K8s Admin, openshift-pipelines, several operator components |
| P2 | **Make the service-accounts PushSecrets honest** (set `enabled: false` on the 6 doomed read-only pushes, or grant a write-scoped token) so git isn't papering over a permanent 403 with a live-only health-check; split read-only vs write Connect tokens per store class. | Two layers of hidden state (live-only Lua check + broken-by-design pushes) mask a permanent failure; single shared token spans read+write across all vaults. | Low | GitOps Repo, external-secrets-operator, service-accounts |
| P2 | **Decide durability posture for ephemeral components:** back the internal image-registry (emptyDir today) with S3/PVC or document it as a deliberate cache; flip lvms `forceWipeDevicesAndDestroyAllData` back to `false`; decide jellyfin `/config` and gitea-mirror SQLite restore (or accept fresh) and add both to a backup routine; guard gitea-mirror's auto-cleanup (`CLEANUP_DRY_RUN`) against the freshly-restored Forgejo. | Assorted per-component durability gaps that will surface on the next restart/rebuild. | Low–Med | image-registry, lvms-operator, jellyfin, gitea-mirror |
| P2 | **Config-quality / drift cleanup:** add a `letsencrypt-staging` ClusterIssuer (rebuild-loop rate-limit safety); prune the stale `automation.apps` blackbox probe; add the `firecrawl` namespace to the searxng NetworkPolicy; add a LokiStack+ClusterLogForwarder or document logging as intentionally idle; wire or delete the orphaned nvidia time-slicing ConfigMap; bump nfd operand to v4.21; label `node-role.kubernetes.io/tenant` durably for remote-tenants; remove the dead `certManager` block from `ocp-base-config`; normalize `.yml`/`.yaml` + fix the `sync_1pasword` typo. | Long tail of misleading/dead config and cosmetic drift that raises cognitive load and invites wrong "fixes" during the next incident. | Low (each) | cert-manager-config, user-workload-monitoring, searxng, loki/openshift-logging, nvidia-gpu-operator, openshift-nfd, remote-tenants, ocp-base-config, Readability |
| P2 | **Optional posture decisions:** etcd encryption-at-rest (`identity → aescbc`); quay `FEATURE_USER_CREATION` on its public route; MetalLB BGP MD5/BFD; audit the Tailscale API-server-proxy ACL grants and version them alongside the repo. | Deliberate security/resilience choices worth an explicit decision now that the cluster is stable. | Low (each) | apiserver, quay-operator, metallb, tailscale-operator |
| P2 | **Promote the incident memory into a structured post-incident record** (Root cause / Timeline / Never-again / Follow-ups) and graduate the durable lessons into the runbooks. | The knowledge that saved the cluster lives in a dense append-only memory file, not where the next operator will look. | Low | Readability |
