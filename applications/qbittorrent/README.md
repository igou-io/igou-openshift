# qBittorrent VPN application

This is a manually deployed Phase 2A migration-validation workload. It is not
registered in ArgoCD and is not included in `clusters/ocp/values.yaml`.

Phase 2A moves only qBittorrent and Prowlarr configuration onto static native
iSCSI PVs. It does not connect production media, change the TrueNAS source
configuration, or perform an application upgrade.

## Architecture

The `Deployment/qbittorrent` Pod contains one restartable native init-sidecar
and three application containers. All four share one network namespace:

```text
Pod
├── gluetun
│   └── /gluetun       -> EmptyDir
├── qbittorrent
│   ├── /config        -> PVC qbittorrent-config
│   └── /data          -> EmptyDir
├── prowlarr
│   └── /config        -> PVC prowlarr-config
└── flaresolverr
    └── /config        -> EmptyDir
```

`/data` is intentionally ephemeral. `/mnt/cold/media/data` is not mounted,
and no production payloads are reachable in this phase. Do not add the NFS
media export, a media PVC, or supplemental GID `3006` until the separate
Phase 2B cutover has been planned and validated.

Gluetun owns the shared Pod routing, Mullvad WireGuard connection, firewall,
and `/gluetun` runtime state. Only Gluetun receives the Mullvad Secret and
`NET_ADMIN`. The application containers run as UID/GID `1000`, drop all Linux
capabilities, and have no VPN Secret reference.

The CRI-O `io.kubernetes.cri-o.Devices: "/dev/net/tun"` Pod annotation injects
the TUN device without a `hostPath`. The tested userspace WireGuard setup
requires `spc_t` on this cluster:

> The application topology is production-shaped and networking has been
> validated, but userspace Gluetun currently requires `spc_t` on this cluster.
> This remains a production-security caveat to revisit separately.

## Image pins

The first migrated OpenShift boot used the exact live TrueNAS source image
references recorded before shutdown:

| Container | Source tag | Digest |
| --- | --- | --- |
| Gluetun | `v3.41.3` | `sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027` |
| qBittorrent | `5.2.2` | `sha256:24f2d793cb7f7a93e755e5d22e533be818e62eadc864f4a82315b901b6ffe807` |
| Prowlarr | `2.5.0` | `sha256:9c89ef21672a20f4cd4a766b5a085ae5a61de54a79e0841e136330a711b85447` |
| FlareSolverr | `v3.5.0` | `sha256:139dfee1c6f89249c8d665d1333a42e8ec74ec0a86bc6bb1c8461e10d3a66a47` |

These pins deliberately differ from newer Phase 1 image pins. Do not combine
the storage migration with an application config or database upgrade.

## External TrueNAS storage

The TrueNAS zvols, iSCSI targets, extents, and LUN mappings are manually
provisioned external dependencies. They are not declared or reconciled by
this repository, `igou-inventory`, or `igou-ansible`.

The live configuration was inspected before writing the PVs. The verified
mapping is:

| External object | OpenShift PV | Portal | Target IQN | LUN | Capacity |
| --- | --- | --- | --- | --- | --- |
| `ssd/trash/qbittorrent` | `qbittorrent-config-iscsi` | `10.10.9.213:3260` | `iqn.2005-10.org.freenas.ctl:qbittorrent-config` | `0` | `2 GiB` |
| `ssd/trash/prowlarr` | `qbittorrent-prowlarr-config-iscsi` | `10.10.9.213:3260` | `iqn.2005-10.org.freenas.ctl:prowlarr-config` | `0` | `5 GiB` |

Both zvol sizes were verified live. Both targets use authentication mode
`NONE` and the existing initiator/access group has an empty initiator list;
there are no CHAP or other authentication fields configured. Do not add
Secret or CHAP fields unless the external target configuration is deliberately
changed and re-inspected.

The PVs are static native-iSCSI filesystem volumes:

| PV | PVC | Mount | Reclaim | Access | Filesystem |
| --- | --- | --- | --- | --- | --- |
| `qbittorrent-config-iscsi` | `qbittorrent-config` | qBittorrent `/config` | `Retain` | `ReadWriteOnce` | ext4 |
| `qbittorrent-prowlarr-config-iscsi` | `prowlarr-config` | Prowlarr `/config` | `Retain` | `ReadWriteOnce` | ext4 |

Each PV has an explicit `claimRef`; each PVC has an empty
`storageClassName`, an explicit `volumeName`, matching capacity, `ReadWriteOnce`,
and `Filesystem` volume mode. There is no CSI driver, StorageClass, or dynamic
provisioning.

The application keeps the normal repository scheduling behavior. There is no
qBittorrent-specific storage label, required node affinity, or storage
`nodeSelector`. RWO still means one writer at a time. Never intentionally
mount either LUN read/write on two nodes. After an unclean node failure, clear
or fence any stale iSCSI session/device before allowing another writer.

## SCC and security

`qbittorrent-vpn` allows `emptyDir` and `persistentVolumeClaim` volumes. It
continues to require:

- `requiredDropCapabilities: ALL`;
- `allowedCapabilities: NET_ADMIN` only;
- no privileged mode, host namespaces, host ports, `hostPath`, or privilege
  escalation; and
- no `SYS_ADMIN`, `SYS_MODULE`, or `NET_RAW`.

The Pod was admitted under `qbittorrent-vpn` with `spc_t`. The Pod security
context uses `fsGroupChangePolicy: OnRootMismatch` and the application
containers use UID/GID `1000:1000`.

## Phase 2A migration procedure

1. Inspect live TrueNAS targets and zvols. Record the portal, full IQNs, LUNs,
   capacities, authentication mode, and access restrictions without printing
   credentials.
2. Inspect the running source image references and collect a non-secret
   baseline. The source baseline used for this run was qBittorrent `5.2.2`,
   171 torrents, 170 `.torrent` files, 171 `.fastresume` files, 9 active
   torrents, and 162 already paused torrents. State counts were 5 `stalledDL`,
   4 `stalledUP`, 2 `stoppedDL`, and 160 `stoppedUP`.
3. Record qBittorrent categories and paths: `books` maps to
   `/data/media/books/shelfmark-torrents`, `movies` to `movies`, `prowlarr`
   and `radarr` to an empty category path, and `tv` to `tv`. The default save
   path is `/data/torrents`, the temp path is disabled, and the network
   interface is `tun0`.
4. Record the Prowlarr baseline: database size `8,720,384` bytes, SQLite
   integrity `ok`, 5 indexers, 1 qBittorrent download client, applications
   `Radarr` and `Sonarr`, and 21,124 history records. Do not record API keys,
   password hashes, cookies, tracker credentials, private keys, or config-file
   contents containing secrets.
5. Pause every source torrent through the qBittorrent API and wait for all
   states to settle. qBittorrent 5.2.2 uses `/api/v2/torrents/stop` for this
   pause-equivalent operation; `/api/v2/torrents/pause` is not present in its
   Web API. Gracefully stop qBittorrent, Prowlarr, FlareSolverr, and Gluetun,
   and keep the entire source stack stopped during OpenShift testing.
6. Take a named source snapshot after clean shutdown. This run created
   `ssd/containers/qbittorrent@qbittorrent-phase2a-pre-migration-20260915T033856Z`.
7. Apply the PVs/PVCs and verify exact PV/PVC binding. Mount them with a
   disposable helper, verify native login and ext4 mounting, allow the blank
   first-format path if needed, confirm only the expected `lost+found` exists,
   set roots to `1000:1000` without world-writable permissions, and remove the
   helper.
8. Take blank destination snapshots. This run created
   `ssd/trash/qbittorrent@qbittorrent-phase2a-blank-precopy-20260915T033956Z`
   and
   `ssd/trash/prowlarr@qbittorrent-phase2a-blank-precopy-20260915T033956Z`.
9. With the Deployment at zero replicas and the source cleanly stopped, use a
   one-time helper to stream only these source paths over read-only SSH:

   ```text
   /mnt/ssd/containers/qbittorrent/config
   /mnt/ssd/containers/qbittorrent/prowlarr/config
   ```

   The helper refuses a non-empty destination unless an explicit restore mode
   is deliberately selected. It preserves numeric ownership, modes,
   qBittorrent `BT_backup`, RSS/category/state data, and complete Prowlarr
   SQLite state. It never mounts the parent stack directory.
10. Change only the migrated Prowlarr copy. The two application `baseUrl`
    values became `https://radarr.biscuit.igou.systems` and
    `https://sonarr.biscuit.igou.systems`. qBittorrent remained
    `localhost:8080`; FlareSolverr was set to `http://127.0.0.1:8191`.
    qBittorrent credentials, categories, `/data/...` paths, and `tun0` were
    not changed. Old TrueNAS certificate bind mounts were not copied.
11. Take populated destination snapshots before first application boot. This
    run created snapshots with suffix
    `qbittorrent-phase2a-pre-first-boot-20260915T034942Z` for both zvols.
12. Boot the pinned Deployment, validate it, and keep every imported torrent
    stopped. Never resume, force-recheck, relocate, delete, or download an
    imported torrent while `/data` is empty.

The source and destination configuration trees matched immediately after the
copy and before the destination-only Prowlarr endpoint edits. The Prowlarr
digest below is the pre-edit copy digest; changing the migrated Radarr and
Sonarr URLs intentionally changes the destination database afterward. Source
and destination verification used relative-content digests, so mount prefixes
did not affect the comparison:

| Tree | Files | Regular-file bytes | Ownership | Modes | Relative-content digest |
| --- | ---: | ---: | --- | --- | --- |
| qBittorrent | 352 | 16,506,563 | 352 × `1000:1000` | 351 × `644`, 1 × `600` | `a5e2117d07400ee01a2967756d6f7f1e8dd941d78fa147c172153013c59ceca6` |
| Prowlarr | 714 | 90,528,905 | 714 × `1000:1000` | 711 × `644`, 3 × `600` | `126e8c6baa3e4f2aa8b1c850b3d6d2b5ef526594f8840687166ed8834cbd2938` |

The source `du` allocation readings were 16,506,649 bytes for qBittorrent
and 90,599,608 bytes for Prowlarr. These readings include filesystem/directory
allocation differences and are distinct from the regular-file byte totals.

## Validation rules and results

The workload was applied manually from this branch and then scaled back to
zero for rollback. The live migration test results were:

- PV/PVC status: both PVs and PVCs were `Bound` to their explicitly named
  counterparts; both PVs reported `Retain`.
- Runtime: the Pod reached `4/4 Ready` under `qbittorrent-vpn`; the first boot
  used the four image digests in this README. No storage-specific hard
  scheduling constraint was introduced.
- qBittorrent: Web API login returned HTTP 204 from inside the cluster; the
  migrated version was `v5.2.2`; 171 torrents, 170 `.torrent` files, and 171
  `.fastresume` files remained. After the missing-payload boot, qBittorrent
  represented 166 entries as `missingFiles` and 5 as `stoppedDL`; all transfer
  rates were zero and the stop operation returned HTTP 200. No payload file
  existed in `/data`.
- qBittorrent configuration: categories, category save paths, default save
  path, and `tun0` remained intact. WebUI authentication was validated using
  the imported qBittorrent configuration credential without printing it.
- Prowlarr: API status was HTTP 200, package version `2.5.0.5422`, SQLite
  database type, 5 indexers, qBittorrent download client, Radarr and Sonarr
  applications, FlareSolverr proxy, and 21,134 retained history records were
  observed. SQLite integrity was `ok` before boot and again after Pod
  recreation. The database/config identity and safe config-key set remained
  present.
- Prowlarr tests: qBittorrent and FlareSolverr test actions returned HTTP 200.
  Direct HTTPS probes from the Prowlarr container reached both TrueNAS
  application endpoints at `10.10.45.240` with HTTP 200. The Prowlarr
  application test actions returned HTTP 400 only at the reverse callback
  check because `prowlarrUrl` still names the old Docker-only
  `http://gluetun:9696`, and TrueNAS cannot reach the OpenShift ClusterIP or
  Pod CIDR. Adding a Route, Gateway, HTTPRoute, router DNS, or a TrueNAS
  reverse-proxy change is outside Phase 2A. This callback must be solved
  before final production application synchronization.
- Mullvad: qBittorrent, Prowlarr, and FlareSolverr each positively reported
  `You are connected to Mullvad` from their own container context.
- Fail closed: the controlled Gluetun restart produced 60 classified probes:
  `MULLVAD=40`, `FAIL=20`, `NON_MULLVAD=0`. Gluetun restarted once and the Pod
  returned Ready. No probe was classified from an observed IP alone.
- Persistence: deleting and recreating the Pod preserved qBittorrent config,
  torrent metadata, Prowlarr config, and the Prowlarr database. Deliberate
  markers in `/data`, `/gluetun`, and FlareSolverr `/config` disappeared.
  `/data` remained an XFS EmptyDir with zero regular files, and
  `/mnt/cold/media/data` was absent.
- Rollback: OpenShift was scaled to zero, no node retained a session to either
  destination IQN, and the unchanged TrueNAS stack was restarted healthy.
  The source qBittorrent state was restored to the baseline membership of 9
  active and 162 paused torrents. Existing TrueNAS endpoints responded, and
  source Prowlarr SQLite integrity was `ok`.

## Phase 2B warning

The tested destination PVC state is not automatically final production state.
Booting qBittorrent while all payloads are missing can alter resume and
application state. Before connecting `/data` to production media in Phase 2B,
either restore both destination zvols from the pre-first-boot snapshots or
wipe and reseed them from the unchanged TrueNAS source after another graceful
shutdown and fresh source snapshot. The final cutover must start from config
state synchronized with the actual payload tree.

Do not delete the source dataset, source snapshots, destination zvols, iSCSI
targets, extents, LUNs, PVs, or PVCs as part of Phase 2A rollback. The PV
reclaim policy is `Retain`; external storage remains manually managed.

## Manual deployment and inspection

Run from the repository root with the OpenShift context selected:

```bash
kustomize build --enable-helm applications/qbittorrent
kustomize build --enable-helm applications/qbittorrent | oc apply -f -

oc wait --for=condition=Ready externalsecret/qbittorrent-mullvad \
  -n qbittorrent --timeout=180s
oc wait --for=condition=available deployment/qbittorrent \
  -n qbittorrent --timeout=600s
oc get pv qbittorrent-config-iscsi qbittorrent-prowlarr-config-iscsi
oc get pvc -n qbittorrent qbittorrent-config prowlarr-config
oc get pod -n qbittorrent -o wide
```

For disposable UI checks, use ClusterIP port-forwards. Do not expose the
application publicly in Phase 2A:

```bash
oc port-forward -n qbittorrent service/qbittorrent 8080:8080
oc port-forward -n qbittorrent service/prowlarr 9696:9696
```

Inspect admission and mounts without reading Secret data:

```bash
POD=$(oc get pod -n qbittorrent \
  -l app.kubernetes.io/name=qbittorrent \
  -o jsonpath='{.items[0].metadata.name}')

oc get pod "$POD" -n qbittorrent \
  -o jsonpath='{.metadata.annotations.openshift\\.io/scc}{"\\n"}'
oc get scc qbittorrent-vpn -o json \
  | jq '{allowedCapabilities,requiredDropCapabilities,volumes}'
oc get pod "$POD" -n qbittorrent -o json \
  | jq '[.spec.volumes[] | {name,emptyDir,persistentVolumeClaim}]'
```

Only the Gluetun container should have the Mullvad Secret references and
`NET_ADMIN`. qBittorrent, Prowlarr, and FlareSolverr must remain non-root with
all capabilities dropped. No FlareSolverr Service is created.

## Rollback

After validation, scale the OpenShift Deployment to zero and confirm no Pod is
mounting either config PVC and no destination iSCSI session remains. Leave the
manually provisioned TrueNAS storage intact. Restart the original unchanged
TrueNAS qBittorrent, Prowlarr, FlareSolverr, Gluetun, and health-monitor
containers. Restore the intended source active/paused torrent states and check
the existing `*.biscuit.igou.systems` endpoints and integrations.

The source snapshot and the pre-first-boot destination snapshots are the
rollback points. Do not use the Phase 2A destination after missing-payload
testing as the Phase 2B production seed without restoring or reseeding it.

## Out of scope

Phase 2A does not implement production `/data`, NFS media storage,
supplemental GID `3006`, Gateway API, HTTPRoute, router DNS, NetworkPolicy,
Shelfmark or Homepage cutover, ArgoCD registration, OADP, application
upgrades, TrueNAS declarative storage backfill, or TrueNAS storage
deletion/recreation.
