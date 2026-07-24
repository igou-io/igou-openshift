# Runbook: Database recovery after total cluster loss

**Applies to:** every database on `ocp.igou.systems`, after the cluster itself is
gone (disk wipe, reinstall, unrecoverable control plane). Exercised for real in
the 2026-07-03 reinstall — post-mortem:
[`../post-mortems/2026-07-03-ocp-disaster-recovery.md`](../post-mortems/2026-07-03-ocp-disaster-recovery.md)
(PRs #387/#388). Backup inventory re-verified against the live bucket on
**2026-07-24**.

This is the *orchestrator*: it sequences the existing runbooks and holds the
one piece of state that changes after every recovery — the Barman
**serverName** map. Per-database mechanics live in
[`cnpg-barman-recovery.md`](cnpg-barman-recovery.md); day-to-day backup wiring
in [`cnpg-backup-restore.md`](cnpg-backup-restore.md); the GitOps/secrets
bootstrap in [`gitops-bootstrap-from-scratch.md`](gitops-bootstrap-from-scratch.md).

---

## 1. Database inventory and what you will get back

| Database | Namespace | Kind | Backup | Restore path |
|---|---|---|---|---|
| `forgejo-pg` (db `forgejo`) | `forgejo` | CNPG Cluster | daily base + WAL → `s3://cnpg-backups/forgejo-pg` | §3 (CNPG recovery) |
| `quay-pg` (dbs `quay`, `clair`) | `quay-enterprise` | CNPG Cluster | daily base + WAL → `s3://cnpg-backups/quay-pg` | §3 — expect **~1.5 days** of WAL replay |
| `rhdh-pg` (db `backstage`) | `rhdh` | CNPG Cluster | daily base + WAL → `s3://cnpg-backups/rhdh-pg` | §3 |
| `aap-postgres-15` | `ansible-automation-platform` | AAP-operator StatefulSet | **none automated** (deliberate) | rebuild from config-as-code; job history is lost unless a manual `pg_dump` exists — see the igou-docs page *AAP Backup, Restore, and Rebuild-from-Loss* |
| `tekton-results-postgres` | `openshift-pipelines` | operator StatefulSet | none | **accepted loss** — pipeline-run history; operator recreates it empty |
| `firecrawl-nuq-postgres` | `firecrawl` | Deployment | none | **accepted loss** — crawl queue state; comes back empty |

Dormant manifests (`applications/gitea/`, `applications/temporalio/`) are not
referenced by `clusters/ocp/values.yaml` and deploy nothing — ignore them.

> ⚠️ **Failure-domain caveat:** all CNPG backups live on the same TrueNAS box
> as the primary DB storage (RustFS-cold, `https://truenas.igou.systems:20292`,
> data at `/mnt/cold/apps/rustfs-cold/cnpg-backups/`). This runbook covers
> *cluster* loss. A total **TrueNAS** loss takes the backups with it — off-box
> replication of `cnpg-backups` is a known open gap.

## 2. Order of operations

1. **Reinstall the cluster** — `ocp-agent-reinstall-netboot-safety.md`.
2. **Verify the backup store is serving** *before* anything depends on it.
   RustFS-cold wedges its disk-health monitor and then masks every bucket as
   `InvalidAccessKeyId` / empty. If S3 auth fails but
   `/mnt/cold/apps/rustfs-cold/cnpg-backups/` has data:
   `ssh truenas_admin@truenas 'sudo docker restart ix-rustfs-cold-rustfs-1'`.
3. **Flip the CNPG cluster manifests to recovery bootstrap in git FIRST** (§3),
   merge to `main`, *then* run the ArgoCD handover in
   `gitops-bootstrap-from-scratch.md`. Ordering matters: if the app-of-apps
   syncs the steady-state manifests, every CNPG Cluster is created **empty**
   via `initdb` and the apps happily start writing into blank databases. In
   2026-07 the flip happened after handover, which cost an extra
   delete-Cluster-and-PVC round per database.
4. **Wait for each recovery to complete** (§4), then let / make the consuming
   apps (forgejo, quay, rhdh) roll.
5. **AAP**: rebuild from config-as-code per the AAP runbook (igou-docs). It is
   its own chicken-and-egg (Connect credential seed) and does not block the
   CNPG work.
6. **Post-recovery reverts** (§5) — do not skip; the next disaster depends on it.

## 3. CNPG: the serverName rule (the only part that changes each time)

Each recovery reads from one object-store prefix and archives forward to a
**new, empty** one. Getting these two names right is the entire game:

- **READ side** (`externalClusters[].plugin.parameters.serverName`): the
  serverName the cluster was archiving to *at the time of loss* — i.e. whatever
  `spec.plugins[0].parameters.serverName` says in the committed cluster
  manifest. **As of 2026-07-24 that is `<cluster>-r20260704`** for all three
  (the post-2026-07-03-recovery timelines). It is *not* the cluster name — the
  bare `<cluster>` prefixes hold the pre-2026-07-03 archive, frozen at
  2026-07-02, and restoring from them silently resurrects month-old data.
- **WRITE side** (`spec.plugins[].parameters.serverName`): a fresh
  `<cluster>-r<YYYYMMDD>` (today's date). CNPG refuses to archive into a
  populated prefix (`WAL archive check failed: Expected empty archive`).

If git is unavailable or you doubt it, list the bucket and trust the prefixes:
the READ side is the per-cluster server prefix with the **newest** WAL objects
(`s3://cnpg-backups/<cluster>/<serverName>/wals/`).

Edit each of `applications/forgejo/forgejo-pg-cluster.yaml`,
`components/quay-operator/quay-pg-cluster.yaml`,
`components/rhdh/rhdh-pg-cluster.yaml`: swap `bootstrap.initdb` →
`bootstrap.recovery` + `externalClusters` and bump the archiving serverName,
exactly as shown step-by-step in `cnpg-barman-recovery.md`. The
`ObjectStore`/`ScheduledBackup`/`ExternalSecret` objects are unchanged — they
sync from git as-is.

If a Cluster was already created before the flip landed: delete the Cluster,
its PVC, and any failed `cnpg.io/jobRole=full-recovery` Job, then let ArgoCD
re-create it — bootstrap only runs at creation.

## 4. Verify

Per `cnpg-barman-recovery.md` — cluster `Ready`, new timeline, and sane table
counts. Reference counts from the 2026-07-03 recovery: `forgejo` 128 tables
(public), `quay` 103 (public), `backstage` 119 (**across all non-system
schemas** — a public-only count on rhdh returns 0 even on success). Then
exercise each app: log into Forgejo, push/pull against Quay, load the
Backstage catalog. `quay-pg` replaying WAL for many hours is normal — tail the
full-recovery pod logs, don't kill it.

Routine (pre-disaster) verification is `cnpg-backup-restore.md` §2; the
one-line fleet check:

```bash
oc get scheduledbackups.postgresql.cnpg.io -A          # LAST BACKUP < 24h
oc get objectstores.barmancloud.cnpg.io -A -o yaml | grep -A3 serverRecoveryWindow
```

## 5. Post-recovery reverts (two, and they differ)

1. **Revert `bootstrap` to `initdb` in git** once verified. No-op for the live
   cluster (bootstrap is immutable after creation; ignoreDifferences on
   `/spec/bootstrap` + `/spec/externalClusters` in `clusters/ocp/values.yaml`
   suppresses the drift) but prevents a future re-create from silently
   restoring stale data.
2. **Keep the new archiving serverName forever.** It is now the live timeline
   and the READ side of the *next* disaster. Rolling it back re-collides with
   the old archive. Update the "as of" line in §3 of this runbook instead.
