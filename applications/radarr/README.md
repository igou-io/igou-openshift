# Radarr migration-validation application

This is a manually deployed migration-validation workload. It is intentionally
not registered in ArgoCD or included in `clusters/ocp/values.yaml`.

Radarr configuration is on a static native-iSCSI RWO filesystem. `/data` is an
`EmptyDir` used only to make the expected container paths available during
validation. Production media at `/mnt/cold/media/data` is not mounted or
reachable in this phase.

## Topology

```text
Deployment/radarr (replicas: 0)
├── /config -> PVC/radarr-config -> PV/radarr-config-iscsi
└── /data   -> EmptyDir
```

The Service is an internal ClusterIP at `radarr.radarr.svc:7878`. No Route,
Gateway listener, LoadBalancer, NodePort, or ArgoCD registration is created.

The Pod uses the existing `nonroot-v2` SCC through a namespace-scoped Role and
runs as UID/GID `1000:1000`. It drops all capabilities, disallows privilege
escalation, and uses `RuntimeDefault` seccomp. The soft scheduling preference
away from control-plane nodes is normal repository behavior; there is no
Radarr-specific storage node affinity.

## Image and source audit

The first OpenShift boot is pinned to the exact source image reference:

`ghcr.io/home-operations/radarr:6.2.1@sha256:a566e7d364b96ce8ffb1b582266e656c69f3a12dec289d72bb0daa647ed4725e`

The live source application reported version `6.2.1.10461`, SQLite, and Docker
mode. Its source configuration path is
`/mnt/ssd/containers/radarr/config`, mounted as `/config` by the TrueNAS
container. The source `/data` is `/mnt/cold/media/data`; that production mount
is deliberately absent from this application.

Pre-migration non-secret baseline:

| Item | Observed value |
| --- | --- |
| Config files | 301 |
| Config allocated size | 83,412,992 bytes |
| Regular database files | `radarr.db` 4,599,808 bytes; `logs.db` 643,072 bytes |
| SQLite sidecars | `radarr.db-wal` 721,032 bytes; `radarr.db-shm` 32,768 bytes |
| Config ownership | all observed entries `1000:1000`; root mode `0755` |
| Movies | 38 |
| Root folders | `/data/media/movies` |
| Quality profiles | 6 |
| Custom formats | 0 |
| Download clients | qBittorrent, host `gluetun`, port `8080` |
| Indexers | 2 Prowlarr Torznab indexers |
| History | 82 records |
| SQLite integrity | `ok` before shutdown |

The source application uses the `develop` branch value reported by its system
status API. No application upgrade is combined with this migration.

## External TrueNAS storage

The destination is manually provisioned external infrastructure. It is not
declared or reconciled by this repository, `igou-inventory`, or `igou-ansible`.

| Object | Value |
| --- | --- |
| ZFS zvol | `ssd/trash/radarr` |
| Capacity | 5 GiB |
| Zvol properties | sparse; 16 KiB volblocksize; LZ4; standard sync |
| iSCSI portal | `10.10.9.213:3260` |
| Target name / alias | `radarr-config` |
| Full target IQN | `iqn.2005-10.org.freenas.ctl:radarr-config` |
| Extent | `radarr-config` -> `zvol/ssd/trash/radarr` |
| LUN | 0 |
| Filesystem | ext4 |
| Authentication | `NONE`; no CHAP |
| Access restriction | portal 1, initiator group 5, empty initiator list |
| PV / PVC | `radarr-config-iscsi` / `radarr-config` |
| Reclaim / access | `Retain` / `ReadWriteOnce` |

The 5 GiB size leaves substantial headroom over the observed 83 MiB allocated
configuration tree while keeping SQLite on SSD-backed block storage.

## Migration procedure

1. Keep this Deployment at zero replicas and apply the manifests.
2. Verify the PVC is Bound to the named PV and that a disposable helper sees
   only filesystem initialization content such as `lost+found`.
3. Gracefully stop the TrueNAS Radarr container, wait for SQLite activity to
   quiesce, and take a named snapshot of `ssd/containers/radarr`.
4. Copy only `/mnt/ssd/containers/radarr/config` into the destination PVC.
   Refuse a non-empty destination, preserve numeric ownership/modes, and emit
   only file counts, byte counts, ownership/mode summaries, and relative-file
   checksums.
5. Take a named snapshot of the populated `ssd/trash/radarr` zvol before the
   first OpenShift boot.
6. Adjust only the migrated copy. The qBittorrent download client must use
   `http://qbittorrent.qbittorrent.svc:8080`, and Prowlarr indexer callbacks
   must use `http://prowlarr.qbittorrent.svc:9696`. Retain the logical root
   folder `/data/media/movies`; do not rewrite it to a TrueNAS host path.
7. Create `/data/media/movies` and `/data/torrents` only in the ephemeral
   `/data` volume if startup or API validation requires them. Never mount
   `/mnt/cold/media/data`, add supplemental GID `3006`, import, rename, move,
   delete, rescan production media, or start a real download.
8. Scale to one replica only for validation. Keep the source stopped and never
   run two writers against the same config identity.

The imported configuration may report missing media because `/data` is
deliberately empty. That warning is expected; database, permission, and
startup errors are not.

## Rollback and persistence validation

After API and application tests, delete and recreate the Pod. The database and
configuration must remain on `radarr-config`; files written to `/data` must
disappear with the Pod. Then scale the Deployment back to zero, confirm no
destination writer or stale iSCSI session remains, leave the destination zvol
and snapshots intact, and restart the unchanged TrueNAS Radarr container.

Before the later production `/data` cutover, restore the destination from its
pre-first-boot snapshot or reseed it from the unchanged source after another
clean shutdown and named source snapshot. A missing-payload validation boot
can legitimately change application state and is not automatically the final
production seed.

## Validation record

The live validation completed on 2026-09-15 and the workload was rolled back to
the TrueNAS source afterward.

| Item | Result |
| --- | --- |
| Source shutdown snapshot | `ssd/containers/radarr@radarr-sonarr-pre-migration-20260915T094448Z` |
| Destination pre-first-boot snapshot | `ssd/trash/radarr@radarr-sonarr-pre-first-boot-20260915T095654Z` |
| Copied regular files | 301 |
| Copied regular-file bytes | 137,142,157 |
| Relative-content digest | `bbb7457e97507597b0768295e815af8352b5b827085b52b49428dc2eb4e10630` |
| Copied ownership and modes | 301 files `1000:1000`; 3 mode `0600`, 298 mode `0644`; no PID files |
| First-boot version and database | `6.2.1.10461`; SQLite integrity `ok` |
| Retained movies / history | 38 / 82 |
| Root folder and profiles | `/data/media/movies`; 6 retained profiles |
| Custom formats | 0 retained |
| qBittorrent client test | HTTP 200, empty success response |
| Prowlarr application test | HTTP 200, empty success response |
| Pod recreation | New Pod retained 38 movies; `/data` marker disappeared |
| Rollback | TrueNAS container healthy; source endpoint HTTP 200; source SQLite integrity `ok` |

The migrated qBittorrent client uses host `qbittorrent.qbittorrent.svc` and
the two Torznab base URLs use `prowlarr.qbittorrent.svc`. Prowlarr's Radarr
record uses `http://radarr.radarr.svc:7878`. These values were changed only in
the destination copy; the rollback source remained unchanged.

The Deployment is left at `replicas: 0`. The destination zvol and snapshot are
intentionally retained for the later coordinated `/data` cutover.
