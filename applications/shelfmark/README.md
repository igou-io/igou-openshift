# Shelfmark

Shelfmark is a self-hosted book and audiobook search/download interface. This
initial deployment provides the base application only; external providers,
download clients, and authentication remain available for later configuration.

The deployment uses the upstream full image, which includes Chromium for its
browser-based sources:

```text
ghcr.io/calibrain/shelfmark:v1.3.15@sha256:9602290324993c801b319d3166b202b96bd9039af2416f0916dae03a5bdca815
```

## Storage

| Purpose | PVC | Source | Mount |
| --- | --- | --- | --- |
| Configuration and application state | `shelfmark-config` | `freenas-nvmeof-ssd-csi`, RWO, 5Gi | `/config` |
| Books/output | `shelfmark-books` | Static NFS PV, RWX, 1Ti, read-write | `/books` |

The static `shelfmark-books-nfs` PV uses the same TrueNAS export as
Calibre-Web: `10.10.9.213:/mnt/cold/media/data/media/books`, using NFS 4.1,
hard mounts, and a `Retain` reclaim policy. It has a unique static storage
class, claim reference, PV, and PVC because PVCs are namespace-scoped.

Shelfmark mounts the complete PVC at `/books` read-write. Its downloads and
library changes use the shared ingest directory `/books/shelfmark-incoming`.
CWA mounts that same NFS subdirectory as `/cwa-book-ingest` and imports the
downloads into the normal Calibre-managed library tree.

The effective application setting is:

```text
INGEST_DIR=/books/shelfmark-incoming
```

`/tmp` is an `emptyDir`; no temporary-data PVC is used.

## OpenShift security

The dedicated `shelfmark` ServiceAccount is bound to the purpose-specific
`shelfmark-uid1000` SCC through a namespaced RoleBinding. The built-in `anyuid`
SCC rejects an explicit `RuntimeDefault` seccomp profile, so this SCC retains
the requested seccomp, no-escalation, and dropped-capability settings without
changing the cluster-wide SCCs.

The `init-config` container runs as UID 0, mounts only Shelfmark's config PVC,
and uses the sole addable capability, `CHOWN`, to initialize that PVC for UID/GID
`1000:1000`. The pod also carries supplemental group `3006`, the shared media
group required for UID 1000 to write the NFS-backed library. The main Shelfmark
container still runs non-root as UID/GID
`1000:1000`, with `runAsNonRoot: true`, `allowPrivilegeEscalation: false`,
seccomp `RuntimeDefault`, and all Linux capabilities dropped. No Tor or
WireGuard features are enabled.

## Network and access

The app-template Deployment has one replica and a `Recreate` strategy, with a
worker-preferred affinity. The Service is `shelfmark` on port 80 targeting
Shelfmark's HTTP port 8084. The health endpoint is `/api/health` and is used
for startup, readiness, and liveness probes.

The default-deny policy allows ingress only from `openshift-ingress` and the
standard host-network namespace selector. Egress is limited to OpenShift DNS
and external Internet addresses outside the cluster pod and service CIDRs.

Shelfmark is exposed through an edge-terminated Route at:

`https://shelfmark.apps.ocp.igou.systems`

This initial deployment is intentionally unauthenticated. Do not treat the
Route as an authentication boundary; external authentication is future work.

## Backups and scope

The `shelfmark` namespace is included in the `daily-apps` OADP schedule. This
protects the config PVC through CSI snapshot data movement. The running
Shelfmark pod carries `backup.velero.io/backup-volumes: books`, so Velero also
backs up the shared static NFS books volume with kopia file-system backup. The
annotation deliberately lives here rather than on the scaled-to-zero
Calibre-Web Deployment: file-system backup requires a running pod that mounts
the volume, and only one copy of the shared export should enter each schedule.

Shelfmark provides the download side of the Calibre integration. It writes
downloads to `/books/shelfmark-incoming`; Calibre-Web Automated polls that
directory and imports completed books into the shared Calibre library. The
Shelfmark application does not write SQLite database files or run
`calibredb` itself.

## Verification and troubleshooting

```bash
oc get deployment,replicaset,pod,service,route -n shelfmark
oc get pvc -n shelfmark
oc get pv shelfmark-books-nfs
oc get networkpolicy -n shelfmark
oc get events -n shelfmark --sort-by=.lastTimestamp
oc describe pod -n shelfmark -l app.kubernetes.io/name=shelfmark
oc logs -n shelfmark -l app.kubernetes.io/name=shelfmark -c app
oc get application shelfmark -n openshift-gitops -o wide
```

To verify the application endpoint without changing the shared library:

```bash
oc -n shelfmark port-forward service/shelfmark 8084:80
curl --fail http://127.0.0.1:8084/api/health
curl --fail --location --silent --show-error https://shelfmark.apps.ocp.igou.systems/api/health
```

Any write test must use a temporary file under `/books/shelfmark-incoming` and
remove it immediately; do not create test files that remain in the shared
Calibre export.
