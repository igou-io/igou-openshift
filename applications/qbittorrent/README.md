# qBittorrent VPN application

This is the first OpenShift application iteration for the qBittorrent stack.
It is a manually deployed, deliberately disposable topology proof. It is not
registered in ArgoCD and it is not included in `clusters/ocp/values.yaml`.

## Architecture

The `Deployment/qbittorrent` Pod contains one restartable native init-sidecar
and three ordinary application containers:

```text
Pod
├── gluetun       Mullvad WireGuard, firewall, and shared Pod routing
├── qbittorrent   Web UI on 8080
├── prowlarr      Web UI on 9696
└── flaresolverr  Internal API on 8191
```

All containers share the Pod network namespace. Gluetun is an init container
with `restartPolicy: Always`, which is the Kubernetes native restartable
sidecar pattern supported by this cluster. Its startup probe runs
`/gluetun-entrypoint healthcheck`; Kubernetes does not start the regular
application containers until that probe succeeds. The readiness and liveness
probes use the same Gluetun health mechanism, so VPN health belongs to
Gluetun rather than to the application probes.

Only Gluetun receives the Mullvad environment references and `NET_ADMIN`.
The application containers run as non-root UID/GID 1000, drop all Linux
capabilities, and have no VPN Secret reference. The CRI-O
`io.kubernetes.cri-o.Devices: "/dev/net/tun"` Pod annotation injects the TUN
device into the Pod without a `hostPath`; this is Pod-scoped on this cluster,
so ordinary containers can see the device but cannot configure it because they
do not have `NET_ADMIN`.

The dedicated `qbittorrent-vpn` SCC is narrow: it disallows privileged mode,
host namespaces, host ports, host directory volumes, privilege escalation,
`SYS_ADMIN`, and `SYS_MODULE`. It uses `spc_t` because that is required by the
tested userspace WireGuard implementation on this cluster. Every container in
the Pod inherits that SELinux domain:

> The application topology is production-shaped and networking has been
> validated, but userspace Gluetun currently requires `spc_t` on this cluster.
> This remains a production-security caveat to revisit separately.

## Image pins

The manually tested image pins are:

| Container | Tag | Digest |
| --- | --- | --- |
| Gluetun | `v3.41.3` | `sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027` |
| qBittorrent | `5.2.3` | `sha256:4fcf15b7f265c2c8d7bc2a7e13240a07e0593c326f3cf3b5b9bb69eec5b79299` |
| Prowlarr | `2.6.4` | `sha256:a5b8031268268b9d3a121c49ea7cc89248538e6379a3e29b0d419489bd95e004` |
| FlareSolverr | `v3.5.2` | `sha256:c80ae007ce2ccdcd217a12426e4f039ef763ff90738c808d38810c3e59323767` |

## Storage and secrets

Every volume is an `emptyDir`:

| Volume | Container mount | Purpose |
| --- | --- | --- |
| `gluetun-state` | Gluetun `/gluetun` | Gluetun runtime state and public-IP file |
| `qbittorrent-config` | qBittorrent `/config` | Fresh qBittorrent configuration |
| `data` | qBittorrent `/data` | `/data/torrents/movies` and `/data/media/movies` |
| `prowlarr-config` | Prowlarr `/config` | Fresh Prowlarr configuration |
| `flaresolverr-config` | FlareSolverr `/config` | Disposable runtime directory |

There are no PVCs, PVs, StorageClasses, NAS mounts, media mounts, hostPath
volumes, or imported application configuration. All configuration and
downloaded data are destroyed when the Pod is recreated.

The only secret dependency is the dedicated test item
`mullvad_openshift_key` through ClusterSecretStore
`onepassword-lab-external-api-keys`. The ExternalSecret preserves the
Gluetun test's mapping and adds `=` when the stored private key is the tested
43-character unpadded value. No qBittorrent, Prowlarr, Radarr, Sonarr,
FlareSolverr, TLS, Basic Auth, or other application secret is used.

## Manual deployment

Run these commands from the repository root. The live deployment is
intentional for this phase, but it is not ArgoCD-managed:

```bash
kustomize build --enable-helm applications/qbittorrent
kustomize build --enable-helm applications/qbittorrent | oc apply -f -

oc wait --for=condition=Ready externalsecret/qbittorrent-mullvad \
  -n qbittorrent --timeout=180s
oc wait --for=condition=available deployment/qbittorrent \
  -n qbittorrent --timeout=600s
oc get pod -n qbittorrent -o wide
```

The application Services are ClusterIP-only. For human UI testing:

```bash
oc port-forward -n qbittorrent service/qbittorrent 8080:8080
oc port-forward -n qbittorrent service/prowlarr 9696:9696
```

Prowlarr and FlareSolverr share the Pod network namespace. Configure the
disposable Prowlarr instance's FlareSolverr indexer proxy as:

```text
http://127.0.0.1:8191
```

No FlareSolverr Service is created.

## Verification

Inspect startup ordering and admitted security settings without printing
Secret data:

```bash
POD=$(oc get pod -n qbittorrent \
  -l app.kubernetes.io/name=qbittorrent \
  -o jsonpath='{.items[0].metadata.name}')

oc get pod "$POD" -n qbittorrent \
  -o jsonpath='{.metadata.annotations.openshift\\.io/scc}{"\\n"}'
oc get pod "$POD" -n qbittorrent \
  -o jsonpath='{.status.initContainerStatuses[0].name}{" started="}{.status.initContainerStatuses[0].state.running.startedAt}{" ready="}{.status.initContainerStatuses[0].ready}{"\\n"}'
oc get pod "$POD" -n qbittorrent \
  -o jsonpath='{range .status.containerStatuses[*]}{.name}{" started="}{.state.running.startedAt}{" ready="}{.ready}{"\\n"}{end}'
oc describe pod "$POD" -n qbittorrent
oc get events -n qbittorrent --sort-by=.lastTimestamp
```

The Gluetun start time must precede the regular container start times, and
the Pod must show `qbittorrent-vpn` as its SCC. The API server accepted
`initContainers[*].restartPolicy: Always` and the application containers
remain waiting until Gluetun's startup probe succeeds.

Inspect identity, SELinux context, capabilities, mounts, and Secret references
without reading Secret data:

```bash
oc exec -n qbittorrent "$POD" -c gluetun -- \
  sh -c 'id -u; cat /proc/1/attr/current; grep "^CapEff:" /proc/1/status; \
         stat -c "%F %t:%T" /dev/net/tun; ip link; ip route; ip rule'
oc exec -n qbittorrent "$POD" -c qbittorrent -- \
  sh -c 'id -u; cat /proc/1/attr/current; grep "^CapEff:" /proc/1/status'
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  sh -c 'id -u; cat /proc/1/attr/current; grep "^CapEff:" /proc/1/status'
oc exec -n qbittorrent "$POD" -c flaresolverr -- \
  sh -c 'id -u; cat /proc/1/attr/current; grep "^CapEff:" /proc/1/status'

oc get pod "$POD" -n qbittorrent -o json \
  | jq -r '.spec.initContainers[] | select(.name == "gluetun") | \
      .env[] | select(.valueFrom.secretKeyRef != null) | \
      (.name + "=secretKeyRef:" + .valueFrom.secretKeyRef.name + "/" + \
      .valueFrom.secretKeyRef.key)'
oc get pod "$POD" -n qbittorrent -o json \
  | jq -r '[.spec.initContainers[], .spec.containers[]] | \
      map({name, vpnSecret: ([.env[]? | select(.valueFrom.secretKeyRef != null) | .valueFrom.secretKeyRef.name])})'
```

Expected runtime results are UID 0 and `NET_ADMIN` only for Gluetun, UID/GID
1000 with no added capabilities for the three applications, and `spc_t` for
all four containers. Only Gluetun has `secretKeyRef` entries for the generated
Mullvad Secret.

Verify the TUN device, DNS, HTTPS, and positive Mullvad classification from
each workload context. These commands do not print Secret values:

```bash
oc exec -n qbittorrent "$POD" -c gluetun -- \
  sh -c 'ls -l /dev/net/tun && ip link'
oc exec -n qbittorrent "$POD" -c qbittorrent -- \
  curl -fsS https://am.i.mullvad.net/connected
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  curl -fsS https://am.i.mullvad.net/connected
oc exec -n qbittorrent "$POD" -c flaresolverr -- \
  python -c 'import urllib.request; print(urllib.request.urlopen("https://am.i.mullvad.net/connected", timeout=15).read().decode())'
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  getent hosts kubernetes.default.svc
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  getent hosts am.i.mullvad.net
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  curl -fsS https://am.i.mullvad.net/ip
```

If an application image lacks a troubleshooting binary, use the FlareSolverr
Python request or a temporary debug Pod; do not add tools, capabilities,
mounts, or credentials to the application containers.

The fail-closed test classifies successful responses only when Mullvad says
the connection is Mullvad. A failed request is acceptable while Gluetun
reconnects; `NON_MULLVAD` must remain zero:

```bash
RESULTS=$(mktemp)
trap 'rm -f "$RESULTS"' EXIT
(
  oc exec -n qbittorrent "$POD" -c prowlarr -- sh -c '
    attempt=0
    while [ "$attempt" -lt 150 ]; do
      (
        response="$(curl --connect-timeout 0.4 --max-time 1 -fsS \
          https://am.i.mullvad.net/connected 2>/dev/null || true)"
        if [ -z "$response" ]; then
          printf "FAIL\\n"
        elif printf "%s" "$response" | grep -Fq \
            "You are connected to Mullvad"; then
          printf "MULLVAD\\n"
        else
          printf "NON_MULLVAD\\n"
        fi
      ) &
      attempt=$((attempt + 1))
      sleep 0.2
    done
    wait
  '
) >"$RESULTS" 2>&1 &
PROBE_PID=$!
sleep 1
oc exec -n qbittorrent "$POD" -c gluetun -- kill 1
wait "$PROBE_PID"
grep -E '^(MULLVAD|FAIL|NON_MULLVAD)$' "$RESULTS" | sort | uniq -c
test "$(grep -c '^NON_MULLVAD$' "$RESULTS" || true)" -eq 0
test "$(grep -c '^MULLVAD$' "$RESULTS" || true)" -gt 0
oc wait --for=condition=available deployment/qbittorrent \
  -n qbittorrent --timeout=300s
```

Check both Services from a temporary debug Pod if needed:

```bash
oc run -n qbittorrent service-check --rm -i --restart=Never \
  --image=docker.io/nicolaka/netshoot:latest@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70 -- \
  curl -fsS http://qbittorrent:8080/
oc run -n qbittorrent service-check --rm -i --restart=Never \
  --image=docker.io/nicolaka/netshoot:latest@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70 -- \
  curl -fsS http://prowlarr:9696/ping
```

Configure the disposable Prowlarr UI with `http://127.0.0.1:8191` as its
FlareSolverr proxy, then use the Prowlarr test action. A direct local check
from the Prowlarr network namespace is also useful:

```bash
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  curl -fsS http://127.0.0.1:8191/health
```

The qBittorrent and Prowlarr probes check their own HTTP listeners, while
Gluetun owns VPN health. FlareSolverr is intentionally not exposed by a
Service, Route, Ingress, or Gateway resource.

## Ephemeral-storage test

Create markers in all disposable paths, recreate the Pod, and verify they are
gone:

```bash
oc exec -n qbittorrent "$POD" -c qbittorrent -- \
  sh -c 'printf marker >/config/phase1-marker && printf marker >/data/phase1-marker'
oc exec -n qbittorrent "$POD" -c prowlarr -- \
  sh -c 'printf marker >/config/phase1-marker'
oc delete pod "$POD" -n qbittorrent
oc wait --for=condition=available deployment/qbittorrent \
  -n qbittorrent --timeout=600s
NEW_POD=$(oc get pod -n qbittorrent -l app.kubernetes.io/name=qbittorrent \
  -o jsonpath='{.items[0].metadata.name}')
oc exec -n qbittorrent "$NEW_POD" -c qbittorrent -- \
  sh -c '! test -e /config/phase1-marker && ! test -e /data/phase1-marker'
oc exec -n qbittorrent "$NEW_POD" -c prowlarr -- \
  sh -c '! test -e /config/phase1-marker'
```

## Cleanup

This removes only the new disposable application namespace resources. It does
not touch existing workloads, existing secrets, TrueNAS, or ArgoCD:

```bash
kustomize build --enable-helm applications/qbittorrent | \
  oc delete -f - --ignore-not-found
oc delete namespace qbittorrent --ignore-not-found
```

## Future path: phase 2

Phase 2 can replace the disposable paths without changing the network shape:

- replace configuration `emptyDir` volumes with PVCs;
- replace `/data` with real shared media storage;
- preserve `/data/torrents` and `/data/media` for hardlinks;
- publish qBittorrent and Prowlarr through the trusted-lan Gateway;
- add router DNS; and
- register the application in `clusters/ocp/values.yaml`.

None of those phase-2 items is implemented here.

## Live test results

The results below are recorded after a manual deployment from this branch.
Public IP values are intentionally not recorded in Git.

- API support: OpenShift 4.22.10 / Kubernetes 1.34 accepted the native
  restartable init-sidecar fields.
- Deployment status: `4/4 Running`, with all four containers ready after the
  replacement Pod was recreated.
- Startup ordering: Gluetun started at `2026-09-14T22:09:39Z`; qBittorrent,
  Prowlarr, and FlareSolverr started at `2026-09-14T22:09:50Z`. The native
  sidecar startup probe held the regular containers until Gluetun was healthy.
- SCC and isolation: the admitted SCC was `qbittorrent-vpn`; all four
  containers reported `spc_t`. Gluetun ran as UID/GID 0 with effective
  capability mask `0000000000001000` (`NET_ADMIN`); each application ran as
  UID/GID 1000 with effective capability mask `0000000000000000` and no VPN
  environment references. Only Gluetun had the two `qbittorrent-mullvad`
  Secret references.
- Storage: all five volumes were verified as `emptyDir`; the generated Secret
  contained only `WIREGUARD_PRIVATE_KEY` and `WIREGUARD_ADDRESSES`.
- Mullvad routing: qBittorrent, Prowlarr, and FlareSolverr each positively
  reported a Mullvad connection from their own container context. Public IP
  values are intentionally not recorded here.
- Fail-closed restart: `MULLVAD=105`, `FAIL=45`, `NON_MULLVAD=0`; the
  Deployment became available again after Gluetun recovered.
- qBittorrent Service: ClusterIP `172.30.216.38:8080`, temporary debug Pod
  HTTP 200, and `oc port-forward` HTTP 200.
- Prowlarr Service: ClusterIP `172.30.201.254:9696`, temporary debug Pod
  returned `{"status":"OK"}`, and `oc port-forward` HTTP 200.
- Prowlarr to FlareSolverr: from the Prowlarr container,
  `http://127.0.0.1:8191/health` returned `{"status":"ok"}`.
- DNS and HTTPS: OpenShift service DNS, public DNS, and public HTTPS all
  succeeded from the shared workload namespace.
- EmptyDir recreation: markers in qBittorrent `/config`, qBittorrent
  `/data`, and Prowlarr `/config` disappeared after Pod deletion; the
  required `/data/torrents/movies` and `/data/media/movies` directories were
  recreated.
