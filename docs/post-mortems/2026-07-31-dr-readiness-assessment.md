# OCP Total-Loss DR Readiness Report

> **Addendum (2026-07-31, same day):** Gap #1 (E1, no etcd backup) is
> **remediated** — nightly `cluster-backup.sh` CronJob to
> `s3://etcd-backups/<z-stream>/<ts>/` on rustfs-cold with failure +
> staleness alerting (#598/#599, igou-inventory#238), e2e-tested incl. a
> deliberate-failure run, plus a rehearsed restore/mining runbook
> (`docs/runbooks/etcd-backup-restore.md`). The mining rehearsal also
> regenerated the PV→zvol catalog gap #2 mourns (55/55 PVs, stored at
> `s3://etcd-backups/catalogs/`) — the *scheduled* half of gap #2
> (TrueNAS snapshot tasks, Retain classes) remains open.
**Assessed:** 2026-07-31 · **Scenario:** etcd wiped, all 4 nodes need reinstall, TrueNAS storage intact · **Baseline:** 2026-07-03 post-mortem (28 days elapsed)

---

## 1. Verdict: **ROUGH**

Recovery is *possible* and materially better documented than on 2026-07-03 — the netboot loaded gun is disarmed, CNPG databases now have real daily Barman backups with a 27-day recovery window, the two hand-seeded bootstrap secrets are written down, and there is a correct fleet-wide dependency-order runbook — but nothing in the recovery path is *smooth or easy*. There is still **no etcd backup of any kind**, so total loss means a ground-up reinstall of all four nodes plus a 54-application health-gated ArgoCD convergence, and **every non-CNPG PV survives only by the same luck as last time** (reclaimPolicy is still `Delete` on all 9 StorageClasses; a dead cluster simply never issues `DeleteVolume`) — except the PVC→zvol catalog that made the July restore tractable **no longer exists on disk**, so orphan identification is now blind archaeology. Worst of all, two of the three DR documents an operator would reach for send them to playbook paths that were deleted weeks ago, one database runbook would silently restore a frozen 2026-07-02 archive, and no alert of any kind would fire during the outage or the recovery.

**Headline scorecard tally: 0 of 16 post-mortem findings fully resolved. 11 partial, 5 open.**

---

## 2. Scorecard

| ID | Finding | Then | Now | One-line evidence |
|---|---|---|---|---|
| **A1** | CNPG clusters frozen in `bootstrap.recovery` in git | CRITICAL | **partial** | Reverted to `initdb` + `ignoreDifferences` live (deada78, 2026-07-04); but prescribed `Prune=false` guard absent on all 3 Cluster CRs while forgejo app runs `prune: true` against a `Delete` SC, and rhdh-pg sync-wave still `10` vs `-1` |
| **A2** | No designed/tested/scheduled DB backup | HIGH | **partial** | 4/4 ScheduledBackups green, 88 Backups since 2026-07-04, 28–29 base backups verified on TrueNAS under `*-r20260704`; but **zero backup-failure alerting** (74 PrometheusRules, no `cnpg_` metric — the 2026-07-30 forgejo failure was silent) and no restore rehearsal |
| **B1** | All nodes share one NVMe hostnqn/hostid | CRITICAL | **open** | TrueNAS `/sys/kernel/debug/nvmet` census: **29 controllers, 1 hostnqn** (`…941e4f03…`) across 3 distinct `host_traddr`; no MachineConfig in git or live, zero hits for `hostnqn` in igou-ansible → **a rebuild reintroduces it** |
| **B2** | democratic-csi multi-attach fragility (#295) | MED/HIGH | **partial** | `ctrl-loss-tmo=-1` works (proven 2026-07-29 recovery) but predates the incident; #295 open & untouched 8 wks, no udev/MachineConfig, worker `nvme-tcp` module load still master-only; 2026-07-30 half-up-target/NSID-renumber failure mode has no issue, runbook, or doc anywhere |
| **C1** | Recovery-critical ArgoCD tuning live-only | HIGH | **partial** | Tuning codified in `bootstrap_gitops.yaml:479-499` (a5acf67/#377) and matches live exactly; but ArgoCD CR still absent from GitOps (`grep -rn 'kind: ArgoCD'` = 0), live CR has no tracking-id → no drift detection; controller **OOMKilled 23× since 2026-07-06**, last 2026-07-31T13:13 |
| **C2** | Monolithic health-gated app-of-apps serialized recovery | HIGH | **open** | Still one root (`root-applications` → `clusters/ocp`), tree **grew 43 → 54 apps** on the same 0→50 monotonic wave ladder; zero per-app `SkipDryRunOnMissingResource`; chart defaults untouched since 2026-04-23 |
| **C3** | Bootstrap order + 2 hand-seeded secrets undocumented; DR doc pointed at wrong playbook | CRITICAL | **partial** | `gitops-bootstrap-from-scratch.md` now exists and both gotchas are codified in the playbook — **but it cites the deleted `hub-cluster/` path 4× and a `vars_prompt` that was deliberately removed**; `igou-ansible/docs/disaster-recovery.md:241,255` still names the deleted `bootstrap_openshift_gitops.yaml`; blind 60s pause, no-retry CR create and unguarded `target_cluster` all unfixed |
| **C4** | Broken-by-design PushSecrets masked by live-only health check | MEDIUM | **partial** | 7/7 PushSecrets genuinely Synced with real `syncedPushSecrets` writes, mask gone from git *and* live; but the prescribed read/write token split never happened — **all 13 ClusterSecretStores share one `onepassword-connect-token`**, now holding write on 3 vaults + read on 10, and PR #411's "removed in a later phase" dual-targeting is still in place 25 days on |
| **D1** | netboot pin default = loaded gun | HIGH / root cause | **partial** | All 5 pins default `local` in git and the live MS-01 pin on rb5009 reads `--default local` + `sanboot … \|\| exit 1` — **but** preflight asserts nothing about content (an unconditional install pin sits in-inventory and deployed), push is size-only idempotent, verify is presence-only, **git-deleted pins are NOT pruned from the router** (2 orphans still live), no reconcile schedule, firmware still PXE→PXE→disk by design |
| **E1** | No automated etcd backup | HIGH | **open** | 5 CronJobs cluster-wide, none etcd; `etcd/cluster` has no `backup` stanza; `backups.config.openshift.io` CRD absent (default featureset); no etcd dataset/bucket on TrueNAS; **not even filed as an issue** |
| **E2** | Single schedulable unguarded control plane | HIGH | **open** | `controlPlaneTopology: SingleReplica`, 1 etcd pod, `mastersSchedulable: true`, **zero taints on all 4 nodes**, master runs 244 pods incl. forgejo/quay/jellyfin/keycloak at **61% memory (was 35%)**; 0 ResourceQuota / 0 LimitRange across 10 user namespaces |
| **E3** | CSR auto-approval not guaranteed for non-Machine-API nodes | MEDIUM | **partial** | Routine serving-cert rotation *does* auto-approve (verified 4/4 nodes Jul 29-30 — post-mortem overstated this); **fresh joins and IP changes still need a human** (2026-07-18 IP move left ~30 CSRs pending 3h15m); scoped auto-approver exists for the TrueNAS VM worker only; **pending-CSR alert not implemented** (built-in threshold = machines+100 = 100) |
| **F1** | PV survival = luck; `Delete` everywhere, no Retain, no snapshot schedule | MED/HIGH | **partial** | New `-detached` snapshot classes are real, live and e2e-tested (cold-pool parent `cold/k8sbak/*`) — **but the datasets are empty (591K)**, `oc get volumesnapshot -A` = none, TrueNAS `pool.snapshottask.query` = **0**, `replication.query` = **0**, inv#125 open; **54 of 55 PVs still reclaimPolicy Delete** (the 1 Retain is a hand-written read-only NFS media PV) |
| **F2** | Runbooks for rebuilding stateful app PVCs | HIGH | **partial** | 9 real runbooks exist and the methods are sound — but **`/workspace/backups/` (the PVC→zvol catalog + hermes tarballs) does not exist**, cited as a prerequisite by 5 documents; hermes off-box tarball is **2026-07-10 (21-day RPO)** with `hermes_backup_weekly: enabled: false`; forgejo git 100Gi, stackrox central-db, comfyui 300Gi, gitea-mirror, sands-of-time have **no restore path at all**; no detached-snapshot-without-cluster procedure |
| **G1** | Alerting single-homed on the cluster it monitors | P0 | **open** | Alertmanager + gotify bridge both on ocp; Watchdog still `receiver: 'null'` with no external consumer; **no watchdog/deadman/synthetic probe anywhere in the fleet**; rk8s Alertmanager is stock-default (`receiver: "null"` only) and its `components/alertmanager-config` is in git but **not wired into `clusters/internal/values.yaml`**; platform Prometheus still emptyDir |
| **G2** | Runbook readiness / drills / RTO-RPO | P2 | **partial** | Three-layer corpus now exists and 5 of 7 spot-checks passed against live reality; but 2 of 3 DR docs route to nonexistent playbooks, **zero RTO/RPO targets fleet-wide** (`grep RTO\|RPO` = 0 hits), no drill or game-day has ever been run, and the PXE smoke test has no AAP job template or schedule |

---

## 3. The recovery path TODAY

### Phase-by-phase

| # | Step | Instrument | Manual? | Est. |
|---|---|---|---|---|
| 0 | **Notice the cluster is gone** | none — no watchdog exists | **100% human** | unbounded (hours) |
| 1 | Pre-flight: TrueNAS/ZFS healthy, `public.igou.systems` boot-files reachable, 1P Connect standby answering (`connect.infra.igou.systems/heartbeat` → 200 ✅) | igou-docs *Fleet-Wide Disaster Recovery* (the **only** correct doc) | partly | 15–30 m |
| 2 | Regenerate agent-install artifacts + PXE assets | `playbooks/openshift/agent-install/deploy_pxe_assets.yml` | scripted | 30–60 m |
| 3 | **Flip MS-01 rb5009 pin `local` → `install`** | `playbooks/netboot/deploy_assets.yml` / JT `netboot_deploy_assets` | ⚠️ **verify by reading the file back off the router** — push is size-only idempotent and verify is presence-only | 10 m |
| 4 | Boot MS-01, agent-install SNO control plane; **flip the pin back to `local` before the installer's mid-flight reboots** | manual + playbook | ⚠️ **this is the exact 2026-07-03 loop** | 60–120 m |
| 5 | Bootstrap GitOps | `playbooks/openshift/bootstrap_gitops.yaml -e target_cluster=ocp` — requires `OP_SERVICE_ACCOUNT_TOKEN` **in env, not a prompt** | ⚠️ two published runbooks name deleted paths; blind 60 s pause; no retry on ArgoCD CR create | 20–40 m |
| 6 | **ArgoCD convergence — the long pole.** 54 apps, one root, monotonic waves 0→50, gate = every wave-N app Synced **AND** Healthy | ArgoCD | ⚠️ expect to hand-unblock stuck waves; controller OOMKills at its 2Gi limit under this tree size | **3–8 h** |
| 7 | Re-add hpg5 + p330 (bare-metal) and truenas-w1 (VM) | `add_node_iso.yml`; `vm_worker_reprovision.yaml` (has a scoped CSR approver) | ⚠️ **manual `oc adm certificate approve` for bare-metal joins**; no alert if you miss them; CONDITION is column 6 | 60–120 m |
| 8 | **Data reattachment — per app, see below** | `database-total-loss-recovery.md`, `restore-pvc-from-truenas.md`, `zfs-snapshot-rescue.md`, `rebuild-hermes-vm.md` | ⚠️ heavily manual | **4 h – multiple days** |
| 9 | Verify; re-fix latent items the rebuild reintroduces (shared NVMe hostnqn, master untainted) | — | manual | 1 h |

**Realistic total to a functioning cluster with core services: 10–20 hours of expert-operator time.** Full restoration of every stateful workload: **days**, and some of it is unrecoverable-to-a-point-in-time.

### What survives — and what does not

**✅ Survives cleanly**
- **CNPG databases** — forgejo, quay, rhdh, keycloak. Barman on rustfs-cold, continuous archiving, 28–29 base backups, recovery window 2026-07-04 → today, 30-day retention. **RPO ≈ WAL-continuous / worst-case 24 h.** This is the single genuinely-solid piece of the recovery.
- **Secrets** — 1Password is off-cluster; the Connect standby on TrueNAS is up. ESO rehydrates everything after the two documented seed Secrets are hand-created (`op-credentials` in `onepassword-connect`, `onepassword-connect-token` in `external-secrets-operator`). Both gotchas (`credential` field; `data:` + `b64encode` for bytes) are codified in the playbook, not just prose.
- **GitOps desired state** — all in git; the ArgoCD CR tuning is now in Ansible so a bootstrap re-run no longer silently reverts it.
- **Netboot/router config** — rb5009 config and pins persist; off-homelab RouterOS backups run daily/weekly/monthly.

**⚠️ Survives only as orphaned zvols — manual archaeology, no catalog**
All 54 dynamically-provisioned PVs (`reclaimPolicy: Delete`). They live because a dead cluster issues no `DeleteVolume` — **the identical luck as 2026-07-03, and this time the map is gone.** `/workspace/backups/ocp-pv-catalog*` does not exist; the surviving zvol names are `pvc-<uuid>` with no app name. Affected, with **no other backup**: `forgejo-shared-storage` 100Gi (git repos), `stackrox/central-db` 40Gi, `gitea-mirror-config` 40Gi, `comfyui-data` 300Gi, `sands-of-time-data`, `grafana-pvc`, `windows-images/codex-desktop-boot` 50Gi, jellyfin config. Recovery = fingerprint-by-content per `restore-pvc-from-truenas.md` §Method 3D static import.

**⚠️ Degraded RPO**
- **hermes VM state** — last off-box tarball **2026-07-10 (21 days stale)**; `hermes_backup_weekly` is `enabled: false` and the nightly VM snapshot schedule is commented out. `rebuild-hermes-vm.md` is built on `/workspace/backups` tarballs that don't exist.

**❌ Does not survive**
- **etcd / all cluster objects** — no backup exists. Every VolumeSnapshot, VolumeSnapshotContent, Alertmanager silence, and any live-only config is gone. This is what forces the full rebuild rather than a restore.
- **Platform Prometheus metrics** — `prometheus/k8s` storage is still emptyDir.
- **AAP Fernet `SECRET_KEY`** — flagged unrecoverable in the DR doc; anything encrypted with it is lost.
- **Alerting, throughout** — Alertmanager and the gotify bridge both run on ocp. **From the moment the cluster dies until ArgoCD reaches the monitoring waves, there is zero alerting on anything in the fleet**, including TrueNAS, and no external system would have told you the cluster died in the first place.

### Two live traps to brief the operator on before starting

1. **`docs/runbooks/cnpg-barman-recovery.md:125` still specifies `serverName: forgejo-pg` as the READ side** ("the ORIGINAL pre-disaster serverName"). Following it verbatim restores the **frozen 2026-07-02 archive** over a rebuild. The correct READ serverName is `<cluster>-r20260704` — stated correctly only in `database-total-loss-recovery.md:66-79` and the igou-docs storage page. The orchestrator delegates mechanics to the wrong file and there is no cross-link.
2. **Deleting a pin from git does not remove it from rb5009.** Two pins deleted on 2026-07-16 still have live flash files and `/ip tftp` rows, one of them a netboot.xyz menu with a `centosautoinstall` entry and a bare `exit 1` local branch. The DR runbook presents "flip/delete the pin" as *the* safety lever; it is only half-working.

---

## 4. Top remaining gaps, ranked by impact × likelihood

| Rank | Gap | Why it hurts | Concrete next action |
|---|---|---|---|
| **1** | **No etcd backup (E1)** — not implemented, not filed | Converts every incident into a 10–20 h ground-up rebuild. Certain to bite: it is the definition of this scenario. | Ship a `cluster-backup.sh` CronJob (hostPath on the master → tar → rustfs-cold `etcd-backups` bucket, 14-day retention) **plus** a tested SNO quorum-restore runbook. Do **not** enable the TechPreview featuregate on this cluster — it is irreversible. File the issue today. |
| **2** | **PVC→zvol catalog is gone; no snapshot schedule; `Delete` everywhere (F1/F2)** | The one artifact the post-mortem credits with making the July restore possible does not exist, and 54 PVs still depend on luck. High likelihood, high blast radius. | (a) Add an AAP job that dumps `PV → zvol → namespace/PVC → app` nightly to rustfs-cold and repoint all 5 runbooks at that location; (b) enable TrueNAS periodic snapshot tasks on `ssd/k8s/vols` + `fast/k8s/vols` (inv#125 — currently **0** tasks); (c) recreate the SCs holding irreplaceable data (`forgejo`, `stackrox`, hermes/VM disks) with `reclaimPolicy: Retain` via the delete-SC + resync dance #592 documented. |
| **3** | **DR docs route to deleted playbooks (C3/G2)** | A recovering operator is blocked at step 1 with "file not found" — at 3 a.m., under pressure. Cheap to fix, certain to be hit. | Fix `igou-ansible/docs/disaster-recovery.md:241,255` and `docs/openshift-operations.md:23,144,169,177` → `playbooks/openshift/bootstrap_gitops.yaml -e target_cluster=`; fix `gitops-bootstrap-from-scratch.md:95,102,212,323` (dead `hub-cluster/` path), delete its `vars_prompt` steps (:80-90, :105) and its now-obsolete ArgoCD hand-patch Step 5 (:207-240). |
| **4** | **`cnpg-barman-recovery.md` wrong READ serverName** | Silently restores 4-week-old data during the one operation that must be exact. | One-line fix at `:125` → `<cluster>-r20260704`, plus a banner cross-linking `database-total-loss-recovery.md`; add `keycloak-pg` and drop `temporalio-pg` from both runbook inventories. |
| **5** | **Zero detection (G1)** | MTTD is unbounded; you cannot recover what you don't know is dead, and you fly blind for the whole recovery. | Wire the already-written `components/alertmanager-config` into `igou-kubernetes/clusters/internal/values.yaml`, give it a delivery path that is **not** the ocp-hosted gotify, and add one blackbox `Probe` of `api.ocp.igou.systems:6443` from rk8s. Near-zero new infrastructure; converts unbounded MTTD into minutes. |
| **6** | **Monolithic wave-gated app-of-apps + OOMKilling controller (C2/C1)** | This is the mechanism that made the July recovery drag; the tree has since grown 43 → 54 apps and the controller has OOMKilled 23× at its declared 2Gi. Guaranteed to bite during mass sync. | Raise `application-controller` memory to 4Gi in `bootstrap_gitops.yaml:550-556` **now**; then split into `platform` / `services` / `apps` roots, or at minimum add per-app `syncOptions: SkipDryRunOnMissingResource` (the chart already supports it; `values.yaml` never uses it). |
| **7** | **Backup/PushSecret/CSR failures are all silent (A2, C4, E3)** | Three independent silent-failure classes; one already fired unnoticed (forgejo backup, 2026-07-30). | Add PrometheusRules: CNPG `LastBackupSucceeded=False`, ESO `PushSecret Ready=False`, and pending-CSR-age > 30 m (the built-in machine-approver alert needs 100 pending CSRs and will never fire here). |
| **8** | **hermes VM 21-day RPO (F2)** | Agent state is the operator's own tooling; losing 3 weeks of it degrades the recovery itself. | Flip `hermes_backup_weekly` to `enabled: true` in `igou-inventory/group_vars/aap/schedules.yml:89-93` and un-comment the nightly VM snapshot schedule (inv#155). |
| **9** | **netboot: no pin content guard, broken prune, size-only push (D1)** | Defense-in-depth-of-one, and the depth is thinner than assumed — the router can hold install-defaulting pins that git no longer knows about. | Add a preflight assertion that every pin fragment contains `--default local` **and** a `sanboot … \|\| exit 1`, gated by an explicit `allow_install: true`; make push content-hash-based; make verify read back and compare content; fix the prune so router state converges on git. |
| **10** | **Latent issues the rebuild reintroduces (B1, E2, C4)** | Not rebuild blockers, but you rebuild straight back into them: one shared NVMe hostnqn across all nodes (29 controllers, 1 identity — **and the identity that matters is the CSI node-plugin's image-baked NQN, not `/etc/nvme`, so a MachineConfig alone is a false fix**); untainted single control plane with no quotas at 61% memory; one Connect token with write on 3 vaults. | Set `hostnqn` per-node in the democratic-csi driver config (or mount a per-node `/etc/nvme` into the node plugin) and verify **target-side** via `/sys/kernel/debug/nvmet/*/ctrl*/hostnqn` — issue #404, open 25 days with zero activity. Taint the master `NoSchedule` or add per-namespace quotas. Split the Connect token read/write per store class (post-mortem P2, :1589). |

---

### Bottom line for the operator

You would get the cluster back — the person who did it on 2026-07-03 could do it again, and would find real runbooks this time instead of nothing. But you would do it **without a recovery point**, **without a map of your own volumes**, **without any alert telling you it happened or how it's going**, and with **three published documents actively pointing you at files that no longer exist or data that is a month stale**. Items 1–4 above are the difference between "rough" and "mostly smooth", and none of them requires new hardware or more than a day of work.