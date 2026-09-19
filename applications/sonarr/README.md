# Sonarr migration-validation application

This workload is managed by the `sonarr` Argo CD application registered in
`clusters/ocp/values.yaml`. The migration details below are retained as a
historical validation record. The current deployment runs one replica and
mounts both the retained configuration PVC and the shared production data PVC.

During migration validation, Sonarr configuration was on a static native-iSCSI
RWO filesystem and `/data` was an
`EmptyDir` used only to make the expected container paths available during
validation. Production media at `/mnt/cold/media/data` is not mounted or
reachable in this phase.

## Topology

```text
Deployment/sonarr (replicas: 0)
├── /config -> PVC/sonarr-config -> PV/sonarr-config-iscsi
└── /data   -> EmptyDir
```

The Service is an internal ClusterIP at `sonarr.sonarr.svc:8989`. No Route,
Gateway listener, LoadBalancer, NodePort, or ArgoCD registration is created.

The Pod uses the existing `nonroot-v2` SCC through a namespace-scoped Role and
runs as UID/GID `1000:1000`. It drops all capabilities, disallows privilege
escalation, and uses `RuntimeDefault` seccomp. The soft scheduling preference
away from control-plane nodes is normal repository behavior; there is no
Sonarr-specific storage node affinity.

## Image and source audit

The current GitOps target is
`ghcr.io/home-operations/sonarr:4.0.20@sha256:1f19eb5e0f421418c1a956bbe01310a0141423afe28bd9a4b1dcb8629ff2bce2`.

The first OpenShift boot is pinned to the exact source image reference:

`ghcr.io/home-operations/sonarr:4.0.18@sha256:2cd77fb3d81909a734d61bb8f71462044cb9d2f187e626a28a05a5c4e4be8fd2`

The live source application reported version `4.0.18.2978`, SQLite, and Docker
mode. Its source configuration path is
`/mnt/ssd/containers/sonarr/config`, mounted as `/config` by the TrueNAS
container. The source `/data` is `/mnt/cold/media/data`; that production mount
is deliberately absent from this application.

Pre-migration non-secret baseline:

| Item | Observed value |
| --- | --- |
| Config files | 201 |
| Config allocated size | 32,214,528 bytes |
| Regular database files | `sonarr.db` 11,472,896 bytes; `logs.db` 765,952 bytes |
| SQLite sidecars | `sonarr.db-wal` 2,130,072 bytes; `sonarr.db-shm` 32,768 bytes |
| Config ownership | all observed entries `1000:1000`; root mode `0755` |
| Series | 13 |
| Root folders | `/data/media/tv` |
| Quality profiles | 6 |
| Custom formats | 0 |
| Download clients | qBittorrent, host `gluetun`, port `8080` |
| Indexers | 2 Prowlarr Torznab indexers |
| History | 938 records |
| SQLite integrity | `ok` before shutdown |

The source application uses the `develop` branch value reported by its system
status API. No application upgrade is combined with this migration.

## External TrueNAS storage

The destination is manually provisioned external infrastructure. It is not
declared or reconciled by this repository, `igou-inventory`, or `igou-ansible`.

| Object | Value |
| --- | --- |
| ZFS zvol | `ssd/trash/sonarr` |
| Capacity | 5 GiB |
| Zvol properties | sparse; 16 KiB volblocksize; LZ4; standard sync |
| iSCSI portal | `10.10.9.213:3260` |
| Target name / alias | `sonarr-config` |
| Full target IQN | `iqn.2005-10.org.freenas.ctl:sonarr-config` |
| Extent | `sonarr-config` -> `zvol/ssd/trash/sonarr` |
| LUN | 0 |
| Filesystem | ext4 |
| Authentication | `NONE`; no CHAP |
| Access restriction | portal 1, initiator group 5, empty initiator list |
| PV / PVC | `sonarr-config-iscsi` / `sonarr-config` |
| Reclaim / access | `Retain` / `ReadWriteOnce` |

The 5 GiB size leaves substantial headroom over the observed 32 MiB allocated
configuration tree while keeping SQLite on SSD-backed block storage.

## Migration procedure

1. Keep this Deployment at zero replicas and apply the manifests.
2. Verify the PVC is Bound to the named PV and that a disposable helper sees
   only filesystem initialization content such as `lost+found`.
3. Gracefully stop the TrueNAS Sonarr container, wait for SQLite activity to
   quiesce, and take a named snapshot of `ssd/containers/sonarr`.
4. Copy only `/mnt/ssd/containers/sonarr/config` into the destination PVC.
   Refuse a non-empty destination, preserve numeric ownership/modes, and emit
   only file counts, byte counts, ownership/mode summaries, and relative-file
   checksums.
5. Take a named snapshot of the populated `ssd/trash/sonarr` zvol before the
   first OpenShift boot.
6. Adjust only the migrated copy. The qBittorrent download client must use
   `http://qbittorrent.qbittorrent.svc:8080`, and Prowlarr indexer callbacks
   must use `http://prowlarr.qbittorrent.svc:9696`. Retain the logical root
   folder `/data/media/tv`; do not rewrite it to a TrueNAS host path.
7. Create `/data/media/tv` and `/data/torrents` only in the ephemeral `/data`
   volume if startup or API validation requires them. Never mount
   `/mnt/cold/media/data`, add supplemental GID `3006`, import, rename, move,
   delete, rescan production media, or start a real download.
8. Scale to one replica only for validation. Keep the source stopped and never
   run two writers against the same config identity.

The imported configuration may report missing media because `/data` is
deliberately empty. That warning is expected; database, permission, and
startup errors are not.

## Rollback and persistence validation

After API and application tests, delete and recreate the Pod. The database and
configuration must remain on `sonarr-config`; files written to `/data` must
disappear with the Pod. Then scale the Deployment back to zero, confirm no
destination writer or stale iSCSI session remains, leave the destination zvol
and snapshots intact, and restart the unchanged TrueNAS Sonarr container.

## Phase 2B restore and reseed warning

The existing `radarr-sonarr-pre-first-boot-20260915T095654Z` destination
snapshot is a clean migration checkpoint, not production-ready final state.
It predates some OpenShift-specific endpoint rewrites. Restoring it can
reintroduce Docker/TrueNAS-era values.

Phase 2B must use this order:

```text
restore or reseed clean source-derived config state
        ↓
apply all required OpenShift/Kubernetes endpoint rewrites
        ↓
verify those rewritten values
        ↓
take a NEW final pre-production-boot snapshot
        ↓
mount production /data
        ↓
perform first production boot
```

After any restore or reseed, verify or reapply these fields without logging
secret-bearing resource bodies:

| Application API resource | Field | Required value |
| --- | --- | --- |
| Radarr `/api/v3/downloadclient/{id}` for qBittorrent | `host` | `qbittorrent.qbittorrent.svc` |
| Radarr `/api/v3/downloadclient/{id}` for qBittorrent | `port` | `8080` |
| Sonarr `/api/v3/downloadclient/{id}` for qBittorrent | `host` | `qbittorrent.qbittorrent.svc` |
| Sonarr `/api/v3/downloadclient/{id}` for qBittorrent | `port` | `8080` |
| Radarr and Sonarr `/api/v3/indexer/{id}` Torznab resources | `baseUrl` host and port | `prowlarr.qbittorrent.svc:9696` |
| Prowlarr `/api/v1/applications/{id}` for Radarr | `baseUrl` | `http://radarr.radarr.svc:7878` |
| Prowlarr `/api/v1/applications/{id}` for Sonarr | `baseUrl` | `http://sonarr.sonarr.svc:8989` |
| Both Prowlarr application resources | `prowlarrUrl` | `http://prowlarr.qbittorrent.svc:9696` |

For Torznab resources, preserve each existing path and API-key field; replace
only the Docker-era host and port in `baseUrl`. Use each application's normal
GET/PUT resource semantics and verify the stored fields through the API before
snapshotting. Do not print or reconstruct API keys, passwords, or complete
secret-bearing resources in migration logs.

Prowlarr's migrated database was also modified during this phase to point its
Radarr and Sonarr application records at the new Services. Restoring Prowlarr
from an older checkpoint can therefore require both application records and
their `prowlarrUrl` fields to be reapplied. Connect production `/data` only
after all three applications report the required values and a new final
pre-production-boot snapshot has been taken.

## Validation record

The live validation completed on 2026-09-15 and the workload was rolled back to
the TrueNAS source afterward.

| Item | Result |
| --- | --- |
| Source shutdown snapshot | `ssd/containers/sonarr@radarr-sonarr-pre-migration-20260915T094448Z` |
| Destination pre-first-boot snapshot | `ssd/trash/sonarr@radarr-sonarr-pre-first-boot-20260915T095654Z` |
| Copied regular files | 200 |
| Copied regular-file bytes | 99,071,862 |
| Relative-content digest | `5fc629909a1bb1107587a49e53cdd2ee2edeba93f47380e28558c85a040b765d` |
| Copied ownership and modes | 200 files `1000:1000`; 3 mode `0600`, 197 mode `0644`; no PID files |
| First-boot version and database | `4.0.18.2978`; SQLite integrity `ok` |
| Retained series / history | 13 / 938 |
| Root folder and profiles | `/data/media/tv`; 6 retained profiles |
| Custom formats | 0 retained |
| qBittorrent client test | HTTP 200, empty success response |
| Prowlarr application test | HTTP 200, empty success response |
| Pod recreation | New Pod retained 13 series; `/data` marker disappeared |
| Rollback | TrueNAS container healthy; source endpoint HTTP 200; source SQLite integrity `ok` |

The migrated qBittorrent client uses host `qbittorrent.qbittorrent.svc` and
the two Torznab base URLs use `prowlarr.qbittorrent.svc`. Prowlarr's Sonarr
record uses `http://sonarr.sonarr.svc:8989`. These values were changed only in
the destination copy; the rollback source remained unchanged.

The Deployment is left at `replicas: 0`. The destination zvol and snapshot are
intentionally retained for the later coordinated `/data` cutover.
