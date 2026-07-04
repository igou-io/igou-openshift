## Recover a CloudNativePG database from Barman on RustFS

> Operational runbook. Derived verbatim from the 2026-07-03 `ocp.igou.systems` reinstall,
> in which the `quay-pg`, `rhdh-pg`, and `forgejo-pg` CloudNativePG (CNPG) databases were
> restored from Barman Cloud backups on the RustFS S3 endpoint after the cluster's disks
> were wiped. All three came back healthy: `forgejo` (128 tables), `backstage` (119 tables
> across its per-plugin schemas), `quay` (103 tables). Corresponds to merged PRs
> [igou-openshift#387](https://github.com/igou-io/igou-openshift/pull/387) (recovery bootstrap)
> and [#388](https://github.com/igou-io/igou-openshift/pull/388) (the serverName fix).

### Purpose

Rebuild a CNPG `Cluster`'s data from its Barman Cloud backup (base backup + WAL replay)
when the underlying Postgres storage is gone — e.g. after a full cluster reinstall, a
destroyed PVC, or an unrecoverable corruption. This switches the cluster's `bootstrap`
stanza from `initdb` (create empty DB) to `recovery` (restore from object store), then
puts the recovered cluster back onto a fresh WAL-archiving timeline so it keeps making
its own backups.

### When to use

Use this when **all** of the following hold:

- A CNPG `Cluster` on `ocp` needs its data recreated and there is no live Postgres
  instance to `pg_dump` from (the volume is blank or gone).
- A Barman Cloud backup for that cluster exists on RustFS. Confirm before starting:
  the base backups used in this incident lived under
  `s3://cnpg-backups/<cluster>` on `https://truenas.igou.systems:20292`, with the
  latest base backups dated **2026-07-02** (the day before the disaster). On TrueNAS the
  same data is browsable at `/mnt/cold/apps/rustfs-cold/cnpg-backups/{quay-pg,rhdh-pg,forgejo-pg}`.
- The RustFS-cold instance is **up and serving** (see Gotchas — it wedges and masks all
  buckets as `InvalidAccessKeyId`). If restores can't reach the bucket, unwedge RustFS first.

Do **not** use this for a routine point-in-time rollback of a *running* database — that is
a different (and destructive) operation. This runbook is for rebuild-from-nothing DR.

### Prerequisites

1. **Cluster + GitOps healthy.** `KUBECONFIG` points at the reinstalled cluster:
   ```bash
   export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig
   ```
   OpenShift GitOps (ArgoCD), 1Password Connect, and External Secrets are all up so the
   `cnpg-s3-credentials` ExternalSecret can resolve.

2. **CNPG operator + Barman Cloud plugin installed** in the `cloudnative-pg` namespace
   (CNPG 1.29.1 in this incident). Verify:
   ```bash
   oc get crd objectstores.barmancloud.cnpg.io
   oc get deploy -n cloudnative-pg barman-cloud        # Available
   ```
   For an app whose operator/CRDs are not yet present (quay, CNV), apply the namespace +
   OperatorGroup + Subscription + ObjectStore + ExternalSecret + Cluster **directly first**,
   let the operator install, then let ArgoCD sync the rest.

3. **S3 credentials reachable.** The `cnpg-s3-credentials` Secret is produced by an
   ExternalSecret (`applications/<app>/cnpg-s3-credentials-externalsecret.yaml`) from the
   1Password item **`cnpg-s3-backup`** in vault **`ocp-pull`** (fields `access_key_id` /
   `secret_access_key` → keys `ACCESS_KEY_ID` / `ACCESS_SECRET_KEY`). Confirm it exists in
   the app namespace:
   ```bash
   oc get externalsecret,secret cnpg-s3-credentials -n <app-namespace>
   ```

4. **The ObjectStore CR exists** in the app namespace and points at the pre-disaster
   backup path. It is intentionally left with `serverName` **omitted** (defaults to the
   cluster name), e.g. `applications/forgejo/forgejo-pg-objectstore.yaml`:
   ```yaml
   apiVersion: barmancloud.cnpg.io/v1
   kind: ObjectStore
   metadata:
     name: forgejo-pg-backup
     namespace: forgejo
   spec:
     configuration:
       destinationPath: s3://cnpg-backups/forgejo-pg
       endpointURL: https://truenas.igou.systems:20292
       s3Credentials:
         accessKeyId:    { name: cnpg-s3-credentials, key: ACCESS_KEY_ID }
         secretAccessKey: { name: cnpg-s3-credentials, key: ACCESS_SECRET_KEY }
   ```

5. **Fresh repo checkout.** Work from `origin/main`, not the local tree — see the
   stale-checkout gotcha below.
   ```bash
   cd /workspace/igou-openshift
   SSH_AUTH_SOCK= git fetch origin main
   ```

Namespace / cluster / database map for this cluster (for reference):

| ArgoCD source path                          | Namespace         | Cluster      | Database    |
| ------------------------------------------- | ----------------- | ------------ | ----------- |
| `applications/forgejo/forgejo-pg-cluster.yaml` | `forgejo`         | `forgejo-pg` | `forgejo`   |
| `components/rhdh/rhdh-pg-cluster.yaml`          | `rhdh`            | `rhdh-pg`    | `backstage` |
| `components/quay-operator/quay-pg-cluster.yaml` | `quay-enterprise` | `quay-pg`    | `quay`      |

### Step-by-step

Below uses `forgejo-pg` as the worked example. Repeat per cluster, substituting from the
table above. `<db>` is the CNPG cluster name (`forgejo-pg`), `<ns>` its namespace.

#### 1. Switch `bootstrap.initdb` → `bootstrap.recovery` + add `externalClusters`

Edit the cluster manifest (e.g. `applications/forgejo/forgejo-pg-cluster.yaml`). **Comment
out** the existing `initdb` block (keep it in the file for the later revert) and replace it
with a `recovery` bootstrap plus an `externalClusters` entry that names the Barman source:

```yaml
  # 2026-07-03 disaster recovery: restore from the Barman Cloud backup on RustFS
  # instead of initdb. Revert to the initdb block below once recovered and verified.
  #   bootstrap:
  #     initdb:
  #       database: forgejo
  #       owner: forgejo
  bootstrap:
    recovery:
      source: forgejo-pg          # must match an externalClusters[].name below
  externalClusters:
    - name: forgejo-pg
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: forgejo-pg-backup   # the ObjectStore CR name
          serverName: forgejo-pg                # READ side: the ORIGINAL (pre-disaster) serverName
```

`serverName: forgejo-pg` here is the **read/recover** side — it tells CNPG which historical
server's base+WAL to replay (the pre-disaster archive, which defaults to the cluster name).

#### 2. CRITICAL — archive the recovered cluster to a NEW serverName

In the **same** manifest, the live WAL-archiving plugin (`spec.plugins[]`,
`isWALArchiver: true`) **must** use a *different, empty* `serverName`. If you leave it at
the default (cluster name = the same server you just recovered from), CNPG refuses to start
archiving and the recovery never completes:

```
WAL archive check failed: Expected empty archive
```

CNPG will not archive a new timeline into an object-store prefix that already holds another
server's WAL (that would corrupt the source you recovered from). Point archiving at a fresh
name — the convention used here is `<db>-r<YYYYMMDD>`:

```yaml
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      enabled: true
      isWALArchiver: true
      parameters:
        barmanObjectName: forgejo-pg-backup
        serverName: forgejo-pg-r20260704       # WRITE side: NEW, empty prefix for the post-recovery timeline
```

Net effect: recover **from** `s3://cnpg-backups/forgejo-pg/forgejo-pg/…` (old, populated),
archive **to** `s3://cnpg-backups/forgejo-pg/forgejo-pg-r20260704/…` (new, empty). The
ObjectStore `destinationPath` is unchanged.

#### 3. Apply the change

Commit + push and let ArgoCD sync (the normal path — this is how #387/#388 landed), **or**
for a direct DR apply pull the manifest straight from `origin/main` so a stale local
checkout can't render the wrong thing (see gotcha):

```bash
SSH_AUTH_SOCK= git show origin/main:applications/forgejo/forgejo-pg-cluster.yaml | oc apply -f -
```

Deleting the old `Cluster`/PVC first (if a half-created one exists) forces CNPG to run the
recovery bootstrap from scratch. Bootstrap only runs at cluster **creation**, so recovery
must be in place *before* the cluster object is first created.

#### 4. If the recovery Job is already stuck, delete it to force a retry

If the cluster was already created and its full-recovery Job failed the archive check
**before** you fixed the serverName (very common — this is the exact #387→#388 sequence),
CNPG will not re-run it on its own after you edit the manifest. Delete the failed Job so
CNPG recreates it with the corrected config:

```bash
oc delete job -n forgejo -l cnpg.io/jobRole=full-recovery
```

CNPG immediately spawns a fresh `<db>-full-recovery-*` Job. Watch it:

```bash
oc get pods -n forgejo -l cnpg.io/jobRole=full-recovery -w
oc logs -n forgejo -l cnpg.io/jobRole=full-recovery -f
```

#### 5. Wait for recovery to finish

Recovery = restore base backup, then replay WAL forward. Small DBs finish in minutes;
**quay took ~1.5 days of WAL replay** because of its WAL volume, so do not assume a hang —
tail the logs. When done, the recovery Job completes and the primary pod goes `Running` /
`Ready 2/2`:

```bash
oc get cluster forgejo-pg -n forgejo
# NAME         INSTANCES  READY  STATUS                     PRIMARY
# forgejo-pg   1          1      Cluster in healthy state   forgejo-pg-1
```

### Verification

For each restored cluster, confirm it is healthy, on a new timeline, archiving to the new
serverName, and — most importantly — that the **data is actually there**.

```bash
# 1. Cluster healthy, no leftover recovery jobs
oc get cluster -A
oc get jobs -A -l cnpg.io/jobRole=full-recovery      # expect: No resources found

# 2. New timeline opened (recovery bumps timeline_id past 1)
oc exec -n forgejo forgejo-pg-1 -c postgres -- \
  psql -U postgres -tAc "SELECT timeline_id FROM pg_control_checkpoint();"     # e.g. 2

# 3. Table counts match the pre-disaster database
oc exec -n forgejo forgejo-pg-1 -c postgres -- \
  psql -U postgres -d forgejo -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"   # 128

oc exec -n quay-enterprise quay-pg-1 -c postgres -- \
  psql -U postgres -d quay -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"    # 103
```

**Backstage / rhdh is a trap:** `backstage` stores each plugin in its own schema
(`catalog`, `scaffolder`, `auth`, `search`, …), so counting only `public` returns **0**
even on a perfectly good restore. Count across all non-system schemas instead:

```bash
oc exec -n rhdh rhdh-pg-1 -c postgres -- \
  psql -U postgres -d backstage -tAc \
  "SELECT count(*) FROM information_schema.tables
   WHERE table_type='BASE TABLE'
     AND table_schema NOT IN ('pg_catalog','information_schema');"                 # 119
```

Also confirm the live archive is writing to the **new** serverName (not the source):

```bash
oc get cluster forgejo-pg -n forgejo \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}' | grep -i archiv
# ContinuousArchiving=True
```

Finally, exercise the app itself (log in to Forgejo, push/pull an image to Quay, load the
Backstage catalog) to confirm the app is happy with its restored schema.

### Rollback / post-recovery cleanup

Two distinct "reverts" apply here — do not confuse them:

1. **Revert `bootstrap` recovery → initdb in git (required follow-up).** Once the DBs are
   verified healthy, change the `bootstrap` stanza back to the original `initdb` block
   (uncomment it; remove `recovery` + `externalClusters`) and merge. `bootstrap` is only
   honored at *initial* cluster creation, so this is a no-op on the running cluster — but it
   is essential hygiene: it stops a future ArgoCD re-sync or a fresh cluster recreation from
   silently re-triggering a recovery from a now-stale backup. This was tracked as an explicit
   remaining item after #389.

2. **Keep the archiving `serverName` at `<db>-r20260704` — do NOT roll it back.** That new
   prefix is now the cluster's live WAL timeline. Reverting it to the base cluster name would
   re-collide with the old archive and re-trigger `Expected empty archive`. Leave the
   `spec.plugins[].parameters.serverName` at the recovery value permanently. (When you next
   need to restore, the recover-from `externalClusters` serverName is what changes, not this.)

If a recovery goes wrong mid-flight (wrong source, corrupt base, wrong serverName), the safe
reset is: delete the `Cluster` and its PVC, correct the manifest, and re-apply so bootstrap
runs cleanly from scratch — recovery cannot be "resumed" on a half-built cluster, only
restarted (via the Job delete in step 4, or a full cluster recreate).

### Gotchas & pitfalls (from this incident)

- **`WAL archive check failed: Expected empty archive` is the #1 failure.** It is *not* an
  S3/credential problem — it means your archiving `serverName` still points at a populated
  prefix. Fix = new serverName (step 2). This was the entire content of PR #388.

- **Editing the manifest is not enough to un-stick a failed recovery.** CNPG will not
  re-run a failed full-recovery Job automatically. You must
  `oc delete job -l cnpg.io/jobRole=full-recovery -n <ns>` to force a retry (step 4).

- **Stale local checkout renders the wrong manifest.** The local `/workspace/igou-openshift`
  tree was ~100 commits behind (`59a2bc7`). Running `oc kustomize` from it rendered the
  **old `initdb`** for `quay-pg` instead of the recovery bootstrap, silently undoing the fix.
  Always `git fetch origin main` and apply via `git show origin/main:<path> | oc apply -f -`
  (or let ArgoCD sync from `main`) — never `oc kustomize .` from an unfetched tree.

- **Backstage table count in `public` is 0 by design.** Its data is in per-plugin schemas;
  count across all non-system schemas (see Verification) or you will wrongly conclude the
  restore failed.

- **Quay's WAL replay took ~1.5 days.** A long-running recovery Job is normal for a
  WAL-heavy DB. Tail the logs; don't kill it as "hung."

- **RustFS-cold wedges and hides every bucket.** The alpha RustFS instance
  (`ix-rustfs-cold-rustfs-1` on TrueNAS) can flip its in-memory disk-health monitor to
  "faulty," after which *all* S3 auth returns `InvalidAccessKeyId` / `InsufficientReadQuorum`
  and buckets appear empty even though the data is intact on disk. If restores can't see the
  backup, unwedge it first (`sudo docker restart ix-rustfs-cold-rustfs-1` on
  `truenas.igou.systems`) before assuming the backup is missing.

- **DR failure-domain caveat.** The RustFS S3 endpoint and the primary DB storage are the
  *same* TrueNAS box / `freenas-nvmeof-*` pools. This restore works for a cluster wipe (disks
  intact on TrueNAS) but a TrueNAS loss takes out primary **and** backups. Off-box replication
  of `cnpg-backups` is the real DR gap.

- **Operator/CRD ordering for quay & CNV apps.** If the target app's operator isn't installed
  yet, `oc apply` the Namespace + OperatorGroup + Subscription + ObjectStore + ExternalSecret
  + Cluster directly first, wait for the CSV to reach `Succeeded`, then let ArgoCD sync the
  rest. A `Cluster` applied before its CRDs/operator will fail dry-run.

- **RWO NVMe-oF pin.** These clusters pin to the control-plane node
  (`nodeSelector: node-role.kubernetes.io/control-plane: ""`) so a rolling restart never
  migrates the RWO NVMe-oF PVC to an ephemeral worker and trips the democratic-csi
  Multi-Attach bug. Keep that affinity on the recovered cluster. (Separately, all three nodes
  currently share one NVMe `hostnqn`/`hostid` — an unrelated latent bug that can cause
  intermittent volume-attach failures; noted here only so an attach failure isn't mistaken
  for a backup problem.)
