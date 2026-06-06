# Runbook: CloudNativePG backup & restore (Barman Cloud Plugin)

**Applies to:** all CNPG `Cluster` databases on this cluster — `forgejo-pg` (forgejo),
`quay-pg` (quay-enterprise), `temporalio-pg` (temporalio), `rhdh-pg` (rhdh).
**Method:** the first-party **Barman Cloud Plugin** (`barman-cloud.cloudnative-pg.io`)
to an S3-compatible object store, with **scheduled (non-PITR)** backups + continuous
WAL archiving. This is the CNPG-maintained replacement for the deprecated in-tree
`.spec.backup.barmanObjectStore` (deprecated as of 1.26; still present on our 1.29.1,
removal version unsettled — do not rely on it).

Pilot: **forgejo-pg** is fully wired in-repo. The other three are rolled out by
copying the same four objects into their namespace (§4).

---

## 0. Architecture

```
cloudnative-pg ns:  cnpg-controller-manager (operator, 1.29.1)
                    barman-cloud plugin Deployment + Service (mTLS via cert-manager)
                        ▲ operator discovers the `barman-cloud` Service in its own ns
<app> ns:           ObjectStore/<cluster>-backup     S3 endpoint + creds + retentionPolicy
                    Cluster/<cluster>  .spec.plugins  isWALArchiver + barmanObjectName
                        └ instance pod + barman sidecar ──► s3://cnpg-backups/<cluster>
                    ScheduledBackup/<cluster>-daily  method: plugin
                    ExternalSecret/cnpg-s3-credentials  from 1Password
```

Repo wiring:
- Plugin install: `components/cloudnative-pg-barman-plugin/` → referenced from
  `clusters/ocp/cloudnative-pg/kustomization.yaml` (same ArgoCD app/namespace as the
  operator, sync-wave 20). The upstream manifest is namespace-retargeted from
  `cnpg-system` to `cloudnative-pg` via kustomize; the plugin's server cert uses the
  relative dnsName `barman-cloud`, so the retarget is mTLS-safe.
- Per-app objects live in the app's own kustomization (`applications/forgejo/…`).

---

## 1. Prerequisites (one-time)

1. **S3 bucket** `cnpg-backups` on the TrueNAS S3 endpoint (`truenas.igou.systems:20292`),
   with a dedicated S3 user/key that has read/write to it. Each cluster gets its own
   path prefix (`s3://cnpg-backups/<cluster>`), so one bucket serves all four.
2. **1Password item** `cnpg-s3-backup` in vault **`ocp-pull`** with fields
   `access_key_id` and `secret_access_key` (the dedicated S3 key above).
3. Plugin component synced (`oc get crd objectstores.barmancloud.cnpg.io` returns the CRD;
   `oc get deploy -n cloudnative-pg barman-cloud` is Available).

> ⚠️ **DR limitation:** the TrueNAS S3 endpoint shares a failure domain with the
> primary DB storage (both are the same TrueNAS box / `freenas-nvmeof-*` pools). A
> TrueNAS loss takes out primary **and** backups. For genuine disaster recovery,
> replicate the `cnpg-backups` bucket off-box (TrueNAS replication to a second box, or
> a second `ObjectStore` pointed at an off-site S3 such as Backblaze B2 / Wasabi /
> AWS S3). The plugin supports any S3-compatible `endpointURL`.

---

## 2. Verify backups are working

```bash
NS=forgejo; CL=forgejo-pg          # adjust per cluster

# Plugin reports healthy on the cluster + last successful backup is recent
oc get cluster "$CL" -n "$NS" -o jsonpath='{.status.lastSuccessfulBackup}{"\n"}'
oc get cluster "$CL" -n "$NS" -o jsonpath='{range .status.pluginStatus[*]}{.name}{": "}{.status}{"\n"}{end}'

# WAL archiving is progressing (continuousArchiving condition = True)
oc get cluster "$CL" -n "$NS" -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{"\n"}{end}' \
  | grep -i archiv

# Backup objects exist
oc get backups -n "$NS"
oc get scheduledbackup -n "$NS"
```

Objects should appear in the bucket under `<cluster>/base/` and `<cluster>/wals/`.

---

## 3. On-demand backup

GitOps-native (declarative `Backup` CR — apply, then it's owned by the cluster):

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: forgejo-pg-manual-2026-06-06
  namespace: forgejo
spec:
  cluster:
    name: forgejo-pg
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

Imperative (needs the `cnpg` kubectl/oc plugin):

```bash
oc cnpg backup forgejo-pg -n forgejo \
  --method plugin --plugin-name barman-cloud.cloudnative-pg.io
```

---

## 4. Roll out to the other databases

For each of `quay-pg` (quay-enterprise, 40Gi), `temporalio-pg` (temporalio),
`rhdh-pg` (rhdh): copy the four Forgejo objects, swap names/namespaces, and add them to
that app's `kustomization.yaml`. Per-cluster bits that change:

| Cluster | Namespace | destinationPath | Cluster manifest to patch |
|---|---|---|---|
| `quay-pg` | `quay-enterprise` | `s3://cnpg-backups/quay-pg` | `components/quay-operator/quay-pg-cluster.yaml` |
| `temporalio-pg` | `temporalio` | `s3://cnpg-backups/temporalio-pg` | `applications/temporalio/temporalio-pg-cluster.yaml` |
| `rhdh-pg` | `rhdh` | `s3://cnpg-backups/rhdh-pg` | `components/rhdh/rhdh-pg-cluster.yaml` |

The `cnpg-s3-credentials` ExternalSecret is per-namespace, but all reference the same
cluster-scoped `ClusterSecretStore/onepassword-sdk-ocp-pull` and the same 1Password
item, so no new secret material is needed. Add to each Cluster's `.spec`:

```yaml
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: <cluster>-backup
```

> `quay-pg` has managed roles (`clair`) and the `pg_trgm` extension — these are
> unaffected by backup config; the plugin entry is purely additive. Verify a green
> backup before considering it done.

---

## 5. Restore — same cluster (data recovery)

Recovery is **never in-place**. You bootstrap a **new** Cluster that replays from the
object store, then cut the app over to it.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: forgejo-pg-restored
  namespace: forgejo
spec:
  instances: 1
  storage:
    size: 10Gi
    storageClass: freenas-nvmeof-ssd-csi
  bootstrap:
    recovery:
      source: forgejo-pg-origin       # names an externalClusters entry
  externalClusters:
    - name: forgejo-pg-origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: forgejo-pg-backup
          serverName: forgejo-pg       # the ORIGINAL cluster's serverName — finds the data
```

Then point the app at `forgejo-pg-restored-rw` (update the `*-pg-app`/host secret or the
app's DB host) and, once validated, rename/replace.

> The restored cluster does **not** re-archive WAL unless you add a `.spec.plugins`
> block to it. If you do, give it a **new** `serverName` (or a new ObjectStore path) so
> it doesn't overwrite the source's backups at `s3://cnpg-backups/forgejo-pg`.

---

## 6. Restore — disaster recovery (cluster rebuilt / new cluster)

Same as §5, run on the fresh cluster, once prerequisites exist there:

1. Plugin component synced (`objectstores.barmancloud.cnpg.io` CRD present).
2. The namespace exists with the `cnpg-s3-credentials` ExternalSecret (so the
   `externalClusters` plugin can read the bucket). The 1Password path makes this
   reproducible.
3. Apply the §5 recovery `Cluster`. It pulls base backup + WALs from
   `s3://cnpg-backups/<cluster>` and replays to the latest archived WAL.

This only works if the **bucket survived** — see the DR limitation in §1.

---

## Field traps (verified against the v0.12.0 CRD)

- **Retention** is `ObjectStore.spec.retentionPolicy` (top-level), **not**
  `.spec.configuration.retentionPolicy`. Format `^[1-9][0-9]*[dwm]$` (e.g. `30d`).
- **`ObjectStore` `serverName` must be empty.** `serverName` is set on the Cluster's
  plugin parameters (defaults to the cluster name) and on the `externalClusters` entry
  at restore. This is the single most important field for restore to find data.
- **ObjectStore must be same-namespace as the Cluster** (CNPG issues #448/#741) — one
  per DB namespace, not a shared store.
- **Plugin must live in the operator's namespace** (`cloudnative-pg`, not the upstream
  default `cnpg-system`) — handled by the kustomize namespace retarget.
- A restored cluster **does not** re-enable WAL archiving automatically (§5).
- **The S3-creds ExternalSecret must sync before the Cluster** (`sync-wave: "-2"`).
  Enabling the plugin on a Cluster triggers a rolling restart whose barman sidecar
  needs the secret to archive; if the secret is gated *behind* the (now
  archiving-blocked, unhealthy) Cluster, ArgoCD deadlocks at the cluster's wave.
- The upstream plugin Deployment hardcodes `runAsUser: 10001`; OpenShift's
  `restricted-v2` SCC rejects it (`FailedCreate`, pod never created). The plugin
  component strips it so the SCC assigns a namespace-range UID.

## References

- Plugin docs: <https://cloudnative-pg.io/plugin-barman-cloud/docs/> (intro, concepts,
  migration, usage, retention, object_stores)
- Plugin source + CRD: <https://github.com/cloudnative-pg/plugin-barman-cloud> (pinned v0.12.0)
- Recovery: <https://cloudnative-pg.io/docs/devel/recovery/>
- In-tree deprecation: <https://cloudnative-pg.io/documentation/1.26/release_notes/v1.26/>
