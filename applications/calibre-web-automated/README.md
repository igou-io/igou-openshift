# Calibre-Web Automated

This is the parallel migration-phase deployment of Calibre-Web Automated (CWA)
v4.0.6. It is deliberately separate from the existing `calibre-web`
application. **CWA is currently NOT production.**

## Parallel migration phase

The existing Calibre-Web deployment remains in the `calibre-web` namespace at
`https://calibre-web.apps.ocp.igou.systems`. This application runs separately
in the `calibre-web-automated` namespace at
`https://calibre-web-automated.apps.ocp.igou.systems`.

The applications do not share SQLite databases:

| Purpose | Existing Calibre-Web | CWA parallel deployment |
| --- | --- | --- |
| Namespace | `calibre-web` | `calibre-web-automated` |
| Route | `calibre-web.apps.ocp.igou.systems` | `calibre-web-automated.apps.ocp.igou.systems` |
| Config | Existing `calibre-web-config` PVC | Independent `calibre-web-automated-config` PVC |
| Settings database | `/config/app.db` | Cloned `/config/app.db` |
| Calibre metadata database | `/config/calibre-db/metadata.db` | Cloned `/calibre-library/metadata.db`, physically `/config/calibre-db/metadata.db` |
| Book files | Existing NFS library, read-write | Same NFS library, mounted read-only at `/books` |
| Ingest | Shelfmark-managed path | Isolated `emptyDir` at `/cwa-book-ingest` |
| Temporary files | `emptyDir` at `/tmp` | `emptyDir` at `/tmp` |

The CWA config PVC is mounted read-write at `/config` and mounted a second time
with `subPath: calibre-db` at `/calibre-library`. CWA's library auto-detection
therefore finds `/calibre-library/metadata.db` and updates its cloned
`app.db` to use `/calibre-library` while the book-files path remains `/books`.
The production `app.db` and production `metadata.db` are never mounted by CWA.

The NFS export is `10.10.9.213:/mnt/cold/media/data/media/books`. CWA uses
`NETWORK_SHARE_MODE=true` because the exposed book filesystem is NFS. It also
uses `CWA_WATCH_MODE=poll`; this is intentional for the eventual NFS-backed
ingest design. The ingest watcher is currently isolated in an emptyDir and is
not connected to Shelfmark or the production library.

## Security and resources

CWA runs as the official `crocodilestick/calibre-web-automated:v4.0.6` image,
pinned to its immutable registry digest. The base environment is:

```yaml
PUID: "1000"
PGID: "3006"
TZ: America/New_York
NETWORK_SHARE_MODE: "true"
CWA_WATCH_MODE: poll
```

UID `1000` and GID `3006` match the existing media permission model. The
dedicated `calibre-web-automated` ServiceAccount has
The CWA pod sets `automountServiceAccountToken: false` while using the
dedicated `calibre-web-automated` ServiceAccount, which is the only subject of
the `calibre-web-automated-anyuid` ClusterRoleBinding. That binding grants only the
built-in `system:openshift:scc:anyuid` SCC so the upstream LinuxServer/s6
startup process can initialize as root and launch the application as `abc`.
The deployment is not privileged and does not use a privileged SCC.

The deployment has one replica and uses the `Recreate` strategy. It requests
250m CPU and 512Mi memory, with limits of 2 CPU and 2Gi memory. Its startup
probe allows approximately five minutes for initialization; readiness checks
run every ten seconds and liveness checks every thirty seconds.

NetworkPolicy is retained with a namespace default-deny policy and an allow
policy matching the existing Calibre-Web pattern: ingress on TCP 8083 from
`openshift-ingress` and host-network traffic, DNS egress to `openshift-dns`,
and Internet egress outside the cluster pod and service CIDRs.

## Safe config-copy procedure

The config PVC must be populated before CWA is started. The committed
Deployment has one replica, but the preparation procedure temporarily scales
it to zero. Do not stop or scale the existing Calibre-Web Deployment.

1. Render and apply only this application, with the CWA Deployment temporarily
   scaled to zero. Create the namespace, independent config PVC, namespace-local
   static NFS PV/PVC, ServiceAccount, SCC binding, Service, Route, and
   NetworkPolicies.
2. Identify the production Calibre-Web pod and confirm that both
   `/config/app.db` and `/config/calibre-db/metadata.db` exist.
3. In that production pod, create consistent SQLite backups:

   ```bash
   sqlite3 /config/app.db \
     ".backup '/config/.cwa-parallel-copy/app.db'"
   sqlite3 /config/calibre-db/metadata.db \
     ".backup '/config/.cwa-parallel-copy/metadata.db'"
   ```

4. Create the temporary `cwa-config-restore` pod in
   `calibre-web-automated`, using the dedicated ServiceAccount and mounting
   the destination PVC at `/target`.
5. Stream the production config directly into the destination PVC; do not use
   a local workstation copy as the authoritative source:

   ```bash
   oc -n calibre-web exec <production-pod> -- \
     tar -C /config -cf - . \
   | oc -n calibre-web-automated exec -i cwa-config-restore -- \
     tar -C /target -xf -
   ```

6. Replace the copied live database files with the consistent backups, remove
   `/target/.cwa-parallel-copy`, and set ownership:

   ```bash
   cp /target/.cwa-parallel-copy/app.db /target/app.db
   cp /target/.cwa-parallel-copy/metadata.db /target/calibre-db/metadata.db
   rm -rf /target/.cwa-parallel-copy
   chown -R 1000:3006 /target
   ```

7. Validate both destination databases before starting CWA:

   ```bash
   sqlite3 /target/app.db 'PRAGMA integrity_check;'
   sqlite3 /target/calibre-db/metadata.db 'PRAGMA integrity_check;'
   ```

   Each command must return `ok`.
8. Remove `/config/.cwa-parallel-copy` from the production pod and delete the
   temporary `cwa-config-restore` pod.
9. Start the committed CWA Deployment with one replica.

The production source databases are:

```text
/config/app.db
/config/calibre-db/metadata.db
```

The CWA destination database paths are:

```text
/config/app.db
/config/calibre-db/metadata.db
/calibre-library/metadata.db
```

The first two destination paths are on the independent
`calibre-web-automated-config` PVC. `/calibre-library/metadata.db` is the same
destination file reached through the second PVC mount's `calibre-db` subPath;
it is not the production database.

## Validation and safety boundaries

Before considering the Route usable, verify that the cloned `app.db` contains
the existing users and that the existing administrator credentials work. Query
the CWA database for the effective split-library settings:

```sql
SELECT
    config_calibre_dir,
    config_calibre_split,
    config_calibre_split_dir
FROM settings;
```

The expected values are `/calibre-library`, split-library enabled, and
`/books`. If the schema differs, inspect it and retrieve the equivalent values.

From the running CWA pod, verify the mounts and explicitly prove that a write
to `/books` fails. If a write succeeds, stop CWA and correct the mount; never
leave a test file behind.

```bash
oc -n calibre-web-automated exec deploy/calibre-web-automated -- \
  sh -c 'touch /books/cwa-write-test'
```

Also verify that existing books, metadata, covers, downloads, and the CWA UI
are readable; that CWA logs show successful s6 startup, database detection,
`/calibre-library` detection, network-share mode, and polling; and that the
stock Calibre-Web pod and Route remain healthy. Do not test ingest, uploads,
metadata edits, cover replacement, conversion, renaming, moving, or deletion
in this phase. Shelfmark remains unchanged and its ingest directory is not
connected to CWA.

## Later cutover phase

This PR does not implement cutover. A later migration phase will:

1. Stop writes to stock Calibre-Web.
2. Refresh CWA's database copies from production.
3. Change CWA `/books` to read-write.
4. Map `/cwa-book-ingest` to `/books/shelfmark-incoming`.
5. Point Shelfmark at `shelfmark-incoming`.
6. Perform end-to-end ingest validation.
7. Switch the canonical Route if desired.
8. Only then decommission stock Calibre-Web.

Until those steps are separately approved and implemented, CWA is a parallel
test deployment and is **NOT production**.
