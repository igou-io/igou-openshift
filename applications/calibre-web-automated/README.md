# Calibre-Web Automated

Calibre-Web Automated (CWA) v4.0.6 is the authoritative Calibre library
manager. It uses the database state synchronized from the stopped stock
Calibre-Web deployment and is now the only active Calibre database writer.

The existing stock deployment remains in the `calibre-web` namespace at
`https://calibre-web.apps.ocp.igou.systems`, scaled to zero for rollback. CWA
is served at `https://calibre-web-automated.apps.ocp.igou.systems`. The
canonical stock hostname is deliberately not moved by this change.

## Storage and ingest flow

The application state and SQLite databases use the CSI-backed
`calibre-web-automated-config` PVC. Book files use the existing TrueNAS NFS
export; no second export or storage system is used.

| Purpose | PVC or source | Mount | Access |
| --- | --- | --- | --- |
| Application state and settings database | `calibre-web-automated-config` | `/config` | read-write |
| Calibre metadata database | same config PVC, `subPath: calibre-db` | `/calibre-library` | read-write |
| Calibre-managed book files | `calibre-web-automated-books`, TrueNAS NFS | `/books` | read-write |
| Shelfmark ingest queue | same books PVC, `subPath: shelfmark-incoming` | `/cwa-book-ingest` | read-write |
| Temporary files | `emptyDir` | `/tmp` | read-write |

The TrueNAS source is:

```text
10.10.9.213:/mnt/cold/media/data/media/books
```

The shared book tree has this shape:

```text
/books
├── shelfmark-incoming/
└── normal Calibre-managed author/book directories
```

The end-to-end flow is:

```text
Shelfmark downloads
    ↓
/books/shelfmark-incoming
    ↓
CWA /cwa-book-ingest polling watcher
    ↓
CWA imports the book
    ↓
Calibre metadata.db on the CSI PVC is updated
    ↓
The imported book appears in the CWA UI
```

Shelfmark must use `INGEST_DIR=/books/shelfmark-incoming`. CWA uses
`NETWORK_SHARE_MODE=true` and `CWA_WATCH_MODE=poll` because the book files and
ingest queue are on NFS.

SQLite remains on CSI and must not be placed on NFS. The effective CWA split
library settings are:

- Calibre database: `/calibre-library`
- Separate Book Files from Library: enabled
- Book files: `/books`

The metadata file is physically `/config/calibre-db/metadata.db`, reached by
CWA through the `/calibre-library` mount. Do not configure Calibre to use
`/books/metadata.db`.

## Security and availability

CWA runs with UID `1000` and GID `3006`, matching the shared media permission
model. Its dedicated ServiceAccount has an `anyuid` SCC exception because the
upstream LinuxServer/s6 startup process must initialize the mounted volumes as
root before launching the application as the configured user. The workload is
not privileged and does not share this ServiceAccount with other applications.
The pod also carries supplemental group `3006` so root-squashed helper
processes in the image can write the group-writable NFS mounts.

CWA is intentionally a single-replica Deployment with the `Recreate`
strategy. SQLite must have one application writer, and the NFS ingest watcher
must not run concurrently in multiple replicas. Do not increase the replica
count.

The stock Calibre-Web Deployment must remain stopped after the final database
synchronization. Starting it against its old database would create a second
writer and cause its metadata and settings to diverge immediately after the
first CWA import. Keep its namespace, PVCs, Route, manifests, and migration
backup for rollback. A rollback requires an explicit procedure that stops CWA,
restores or resynchronizes the intended database state, and only then starts
stock Calibre-Web; do not start stock Calibre-Web directly against its old
database.

## Verification

Check the workload and GitOps application:

```bash
oc -n calibre-web-automated get pods,deploy,pvc,svc,route
oc -n shelfmark get pods,deploy,pvc,svc,route
oc -n openshift-gitops get application calibre-web-automated shelfmark -o wide
```

Check the effective split-library settings from CWA's settings database:

```bash
cwa_pod=$(oc -n calibre-web-automated get pod \
  -l app.kubernetes.io/name=calibre-web-automated \
  -o jsonpath='{.items[0].metadata.name}')
oc -n calibre-web-automated exec "$cwa_pod" -c app -- sqlite3 /config/app.db \
  'SELECT config_calibre_dir, config_calibre_split, config_calibre_split_dir FROM settings;'
```

The result must be `/calibre-library`, enabled, and `/books` (the enabled
value may be represented as `1` by SQLite). If the schema changes, inspect the
settings table and retrieve the equivalent fields.

Verify writes only inside the ingest mount; never create arbitrary files in
the root of `/books`:

```bash
oc -n calibre-web-automated exec "$cwa_pod" -c app -- \
  sh -c 'touch /cwa-book-ingest/.write-test && rm /cwa-book-ingest/.write-test'
```

Observe the import while running a legal or public-domain EPUB test:

```bash
oc -n calibre-web-automated logs deploy/calibre-web-automated -c app -f
oc -n shelfmark logs deploy/shelfmark -c app
```

Confirm the incoming file is removed after successful processing, a normal
Calibre-managed author/book path exists under `/books`, the book is visible in
the CWA UI, and the ebook can be downloaded. Do not leave test files in the
shared NFS tree.
