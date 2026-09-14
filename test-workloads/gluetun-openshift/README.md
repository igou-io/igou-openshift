# gluetun-openshift

Disposable live-cluster experiment proving that an ordinary container can
send all outbound traffic through a Gluetun/Mullvad WireGuard sidecar while
both containers share one OpenShift Pod network namespace.

This directory is intentionally outside `clusters/ocp/values.yaml`, ArgoCD,
and `applications/`. It is a manually deployed test workload only.

## What this proves

The `gluetun-egress-test` Deployment contains exactly two containers:

- `gluetun` starts as container root, receives only `NET_ADMIN`, and is not
  privileged. The Pod requests `/dev/net/tun` through the CRI-O
  `io.kubernetes.cri-o.Devices` annotation; there is no hostPath device mount.
  The ESO template preserves the key material and adds the one missing `=`
  padding character because this test item stores its private key as 43-char
  unpadded base64. `PUID=0` and `PGID=0` keep Gluetun's userspace WireGuard
  helper root-owned so it can create its UAPI socket; this is container-root
  execution under the narrow SCC, not privileged mode or an extra capability.
  The worker lacks kernel WireGuard support, so the test selects Gluetun's
  userspace implementation explicitly.
- `verifier` is an ordinary troubleshooting container. It has no VPN
  environment variables, no mounted Secret, no added capabilities, and drops
  all capabilities. Its traffic uses the network namespace and routes that
  Gluetun configures for the Pod.

`direct-egress-control` uses the same pinned netshoot image in the same
namespace, but has no Gluetun and uses the default ServiceAccount and normal
OpenShift SCC admission. Its egress IP is the before comparison.

The custom `gluetun-test` SCC is required only because the VPN sidecar needs
`NET_ADMIN`, container-root startup, and the CRI-O-injected TUN device. It
disallows privileged mode, host namespaces, host ports, host directory
volumes, `SYS_ADMIN`, and `SYS_MODULE`. Its RBAC grants `use` only to the
`gluetun-test` ServiceAccount in this namespace.

## Why this proves the VPN sidecar pattern

Kubernetes gives all containers in one Pod a shared network namespace. Gluetun
therefore changes the namespace's routes, policy rules, and firewall, while
the verifier continues to use ordinary sockets without knowing that a VPN is
present. This is the Kubernetes/OpenShift equivalent of Docker Compose:

```yaml
network_mode: "service:gluetun"
```

The architecture under test is deliberately reusable:

```text
Pod
├── gluetun
│   ├── establishes Mullvad WireGuard
│   ├── owns the shared Pod routing and firewall
│   └── is the only container with NET_ADMIN and VPN credentials
└── ordinary workload container
    ├── has no VPN configuration or credentials
    ├── has no NET_ADMIN or other added capabilities
    └── transparently exits through Gluetun
```

The generic `verifier` stands in for an application such as qBittorrent,
Prowlarr, or FlareSolverr. The eventual Pod shape can therefore be:

```text
Pod
├── gluetun
├── qbittorrent
├── prowlarr
└── flaresolverr
```

Only Gluetun would own the VPN settings and elevated network capability. The
verifier is ordinary from the perspective of Linux capabilities, user ID,
VPN configuration, and network privileges, but it inherits the Pod's
`spc_t` SELinux domain because the custom SCC applies that policy at Pod
admission. It is not equivalent to a fully restricted `restricted-v2`
container; that is an unresolved production security caveat documented below.

## Deploy

Prerequisites:

- `oc` is authenticated to the intended OpenShift cluster.
- External Secrets Operator is healthy and
  `onepassword-lab-external-api-keys` is Ready.
- The 1Password item `mullvad_openshift_key` in vault
  `lab_external_api_keys` contains `private_key` and
  `wireguard_addresses`.

Render and inspect the output first:

```bash
kustomize build --enable-helm test-workloads/gluetun-openshift
```

Deploy manually from the repository root using the repository-supported
rendering path:

```bash
kustomize build --enable-helm test-workloads/gluetun-openshift | oc apply -f -
```

Wait for the ExternalSecret and both Deployments:

```bash
oc wait --for=condition=Ready externalsecret/gluetun-mullvad \
  -n gluetun-openshift-test --timeout=180s
oc wait --for=condition=available deployment/gluetun-egress-test \
  -n gluetun-openshift-test --timeout=300s
oc wait --for=condition=available deployment/direct-egress-control \
  -n gluetun-openshift-test --timeout=180s
```

Verify only the target Secret metadata and key names; do not print its data:

```bash
oc get secret gluetun-mullvad -n gluetun-openshift-test \
  -o go-template='{{.metadata.name}}{{" keys="}}{{range $key, $_ := .data}}{{$key}} {{end}}{{"\n"}}'
```

The ExternalSecret must report `Ready=True`, and the target Secret must have
the two keys `WIREGUARD_PRIVATE_KEY` and `WIREGUARD_ADDRESSES`.

## Human verification path

Find the Pods and verify the control and VPN egress IPs:

```bash
oc get pods -n gluetun-openshift-test -o wide

# Normal OpenShift egress
oc exec -n gluetun-openshift-test \
  deploy/direct-egress-control -- \
  curl -fsS https://am.i.mullvad.net/ip

# Same request from an ordinary container sharing Gluetun's Pod
oc exec -n gluetun-openshift-test \
  deploy/gluetun-egress-test -c verifier -- \
  curl -fsS https://am.i.mullvad.net/ip

# Mullvad confirmation
oc exec -n gluetun-openshift-test \
  deploy/gluetun-egress-test -c verifier -- \
  curl -fsS https://am.i.mullvad.net/connected
```

The first and second IPs must differ. The connection endpoint must indicate
that the verifier request is using Mullvad.

Inspect the Gluetun startup and health logs:

```bash
oc logs -n gluetun-openshift-test deploy/gluetun-egress-test -c gluetun
```

Successful logs show WireGuard establishment and a Mullvad public IP. They
must not show TUN permission errors or `NET_ADMIN`/iptables permission errors.

## Sidecar-specific verification

Inspect the two containers separately. The selected BusyBox `id` does not
implement `id -Z`, so `/proc/1/attr/current` is used for the effective SELinux
context:

```bash
VPN_POD=$(oc get pod -n gluetun-openshift-test \
  -l app.kubernetes.io/name=gluetun-egress-test \
  -o jsonpath='{.items[0].metadata.name}')

# Gluetun: root, NET_ADMIN, VPN Secret references, and TUN device
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c gluetun -- \
  sh -c 'id -u; cat /proc/1/attr/current; grep "^CapEff:" /proc/1/status; \
         stat -c "%F %t:%T" /dev/net/tun'
oc get pod "$VPN_POD" -n gluetun-openshift-test -o json \
  | jq -r '.spec.containers[] | select(.name == "gluetun") | \
           .env[] | select(.valueFrom.secretKeyRef != null) | \
           (.name + "=secretKeyRef:" + .valueFrom.secretKeyRef.name + "/" + \
            .valueFrom.secretKeyRef.key)'

# Verifier: non-root, no capabilities, no VPN settings, no Secret or /gluetun
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- \
  sh -c 'id -u; cat /proc/1/attr/current; grep "^CapEff:" /proc/1/status; \
         env | grep -Eiq "VPN|WIREGUARD|MULLVAD|GLUETUN" && echo unexpected-env || \
         echo vpn-env-absent; test -e /gluetun && echo unexpected-mount || \
         echo gluetun-mount-absent; stat -c "%F %t:%T" /dev/net/tun'
```

The CRI-O device annotation is Pod-scoped: the verifier can see the same TUN
character device, but its zero capability mask means it cannot configure the
device or alter routes. It receives no VPN environment variables, no Secret
reference, and no `/gluetun` mount. The Gluetun Secret is supplied only through
the Gluetun container's `secretKeyRef` environment entries; the commands above
print names and references, never Secret data.

## TUN, routing, and DNS checks

The TUN check is made in the Gluetun container. The routing and DNS checks are
made in the ordinary verifier container:

```bash
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c gluetun -- \
  sh -c 'ls -l /dev/net/tun && ip link'

oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- ip addr
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- ip route
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- ip rule

# Kubernetes service DNS
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- \
  nslookup kubernetes.default.svc

# Public DNS and HTTPS
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- \
  nslookup am.i.mullvad.net
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- \
  curl -fsS https://am.i.mullvad.net/ip
```

`/dev/net/tun` must be a character device. The verifier's `ip route` and
`ip rule` output documents the shared namespace after Gluetun has installed
its tunnel routes and policy rules. Do not change routes from the verifier.

If Kubernetes DNS fails, inspect the verifier's `/etc/resolv.conf` and the
Gluetun firewall logs first. Only add the specific cluster DNS/service CIDR
needed through Gluetun's documented local-subnet exception; do not broadly
bypass the VPN for Internet traffic. `FIREWALL_OUTBOUND_SUBNETS` is not a
DNS-only exception: every destination in the listed OpenShift CIDR is allowed
to use the ordinary Pod network path outside the VPN routing path. This test
uses only the Service CIDR `172.30.0.0/16`, which covers the cluster DNS
resolver and Kubernetes service virtual IPs. The Pod CIDR was tested and
removed; its absence did not break cluster DNS, public DNS, or public HTTPS.
`DNS_KEEP_NAMESERVER=on` keeps the resolver injected by OpenShift. Internet
HTTP remains subject to Gluetun's VPN firewall.

The writable `emptyDir` is also used for `PUBLICIP_FILE=/gluetun/ip`. The
image's default `/tmp/gluetun` directory is not writable after unrelated
capabilities are dropped.

## Fail-closed restart test

The following probe starts a new request every 200 ms, gives each request a
400-ms connect timeout and 1-second total timeout, and positively checks each
successful response with Mullvad's `/connected` endpoint. It does not infer
Mullvad connectivity from a public-IP comparison. The direct/control IP is
not needed by this acceptance test and is not read, printed, or persisted:

```bash
VPN_POD=$(oc get pod -n gluetun-openshift-test \
  -l app.kubernetes.io/name=gluetun-egress-test \
  -o jsonpath='{.items[0].metadata.name}')

PROBE_RESULTS=$(mktemp)
trap 'rm -f "$PROBE_RESULTS"' EXIT
(
  oc exec -n gluetun-openshift-test "$VPN_POD" -c verifier -- \
    sh -c '
      attempt=0
      while [ "$attempt" -lt 150 ]; do
        (
          response="$(curl --connect-timeout 0.4 --max-time 1 -fsS \
            https://am.i.mullvad.net/connected 2>/dev/null || true)"
          if [ -z "$response" ]; then
            printf "FAIL\n"
          elif printf "%s" "$response" | grep -Fq \
              "You are connected to Mullvad"; then
            printf "MULLVAD\n"
          else
            printf "NON_MULLVAD\n"
          fi
        ) &
        attempt=$((attempt + 1))
        sleep 0.2
      done
      wait
    '
) >"$PROBE_RESULTS" 2>&1 &
PROBE_PID=$!
sleep 1
oc exec -n gluetun-openshift-test "$VPN_POD" -c gluetun -- kill 1
wait "$PROBE_PID"

grep -E '^(MULLVAD|FAIL|NON_MULLVAD)$' "$PROBE_RESULTS" | sort | uniq -c
MULLVAD_COUNT=$(grep -c '^MULLVAD$' "$PROBE_RESULTS" || true)
NON_MULLVAD_COUNT=$(grep -c '^NON_MULLVAD$' "$PROBE_RESULTS" || true)
test "$NON_MULLVAD_COUNT" -eq 0
test "$MULLVAD_COUNT" -gt 0

oc wait --for=condition=available deployment/gluetun-egress-test \
  -n gluetun-openshift-test --timeout=180s
oc exec -n gluetun-openshift-test deploy/gluetun-egress-test -c verifier -- \
  curl -fsS https://am.i.mullvad.net/connected
```

Each probe has exactly one of these states:

```text
MULLVAD      acceptable: Mullvad explicitly confirms the connection
FAIL         acceptable while the tunnel is unavailable or restarting
NON_MULLVAD  failure: a successful response was not a Mullvad confirmation
```

The acceptance criteria are `NON_MULLVAD` count equal to zero and at least one
`MULLVAD` response after recovery. This positive check is stronger than
comparing against one control IP: Mullvad may reconnect through a different
exit IP, and a direct leak could use a different NAT address. After restart,
the separate final verifier request must again report `You are connected to
Mullvad`. The temporary results file contains classifications only and is
removed on shell exit.

## Effective security inspection

Check the admitted SCC and security settings without reading Secret data:

```bash
VPN_POD=$(oc get pod -n gluetun-openshift-test \
  -l app.kubernetes.io/name=gluetun-egress-test \
  -o jsonpath='{.items[0].metadata.name}')
CONTROL_POD=$(oc get pod -n gluetun-openshift-test \
  -l app.kubernetes.io/name=direct-egress-control \
  -o jsonpath='{.items[0].metadata.name}')

oc get pod "$VPN_POD" -n gluetun-openshift-test \
  -o jsonpath='{.metadata.annotations.openshift\.io/scc}{"\n"}'
oc get pod "$CONTROL_POD" -n gluetun-openshift-test \
  -o jsonpath='{.metadata.annotations.openshift\.io/scc}{"\n"}'

oc exec -n gluetun-openshift-test "$VPN_POD" -c gluetun -- \
  sh -c 'cat /proc/1/attr/current; id -u; grep "^CapEff:" /proc/1/status'
oc exec -n gluetun-openshift-test "$VPN_POD" -c verifier -- \
  sh -c 'cat /proc/1/attr/current; id -u; grep "^CapEff:" /proc/1/status'
oc exec -n gluetun-openshift-test "$CONTROL_POD" -c verifier -- \
  sh -c 'cat /proc/1/attr/current; id -u; grep "^CapEff:" /proc/1/status'

oc get pod "$VPN_POD" -n gluetun-openshift-test -o yaml \
  | grep -E 'privileged:|host(Network|PID|IPC):|hostPath:|NET_ADMIN|SYS_ADMIN|SYS_MODULE|io.kubernetes.cri-o.Devices'
```

The VPN Pod must report SCC `gluetun-test`; the control Pod must report a
default restricted SCC such as `restricted-v2`, not `gluetun-test`. Gluetun's
effective capability mask should include `NET_ADMIN`; verifier's mask must
not. The Pod must show no privileged container, host namespace, hostPath,
`SYS_ADMIN`, or `SYS_MODULE` use.

On this cluster, the VPN Pod's SELinux context is enforcing but is
`spc_t`. This was the smallest working SELinux setting for the selected
userspace WireGuard implementation: both the normal `container_t` context and
the less restrictive `container_engine_t` context generated an AVC denial for
Gluetun's `inotify_add_watch` on `/run/wireguard/tun0.sock`. `spc_t` is a
security caveat because it is broader than ordinary container confinement;
the SCC still independently disallows privileged mode, host access, hostPath
volumes, and all capabilities except `NET_ADMIN`.

The relevant audit denial was `avc: denied { watch }` for the WireGuard socket
with `syscall=inotify_add_watch` and `exit=-13`; no host policy, CRI-O, OVN,
or node firewall changes were made.

`runAsUser: RunAsAny` is retained only because the Gluetun entrypoint requires
container-root startup for this userspace setup. The Gluetun container runs as
UID 0; the verifier explicitly runs as non-root UID 1000; the control Pod is
assigned its normal restricted UID by `restricted-v2`.

No narrower alternative worked in this environment. Gluetun v3.41.3 exposes
no setting for relocating its userspace WireGuard UAPI socket from
`/run/wireguard/tun0.sock`; mounting an `emptyDir` at that path under
`container_t` still produced the same enforcing AVC because the socket kept
the `container_file_t` label. The cluster has no Security Profiles Operator
resources installed, and no custom SELinux policy or node-level change was
made. Gluetun works in the OpenShift Pod-sidecar architecture on this cluster,
but userspace WireGuard currently requires `spc_t`. That is acceptable for
proving runtime feasibility and remains an unresolved production security
concern.

## Cleanup

The namespace is disposable. Delete the complete rendered workload so the
namespaced resources and cluster-scoped test RBAC/SCC are removed:

```bash
kustomize build --enable-helm test-workloads/gluetun-openshift \
  | oc delete -f - --ignore-not-found
oc delete namespace gluetun-openshift-test --ignore-not-found
oc delete clusterrole system:openshift:scc:gluetun-test --ignore-not-found
oc delete scc gluetun-test --ignore-not-found
```

The explicit namespace deletion handles any retained Secret and other
namespaced leftovers. Confirm cleanup:

```bash
oc get namespace gluetun-openshift-test
oc get scc gluetun-test
oc get clusterrole system:openshift:scc:gluetun-test
```

The three commands should report NotFound. Never delete a pre-existing SCC or
ClusterRole with another name as part of this experiment.

## Results

Live run completed 2026-09-14. No Secret values are included in this report.

- SCC admitted for `gluetun-egress-test`: `gluetun-test`.
- SCC admitted for `direct-egress-control`: `restricted-v2`.
- Effective SELinux types: Gluetun `spc_t`, verifier `spc_t`, and control
  `container_t`; all were enforcing. The verifier therefore inherits the
  Pod-level `spc_t` policy despite remaining capability- and credential-free.
- `/dev/net/tun` injection: passed; it was a character device with major/minor
  `10:200`, and `tun0` became `UP` in the shared Pod namespace.
- Gluetun WireGuard health: passed after selecting an IPv4 Sweden endpoint;
  logs reported WireGuard setup complete and a Mullvad public IP. The initial
  IPv6 endpoint attempts failed because this worker has no usable IPv6 route,
  but there were no TUN, `NET_ADMIN`, or iptables permission failures.
- Normal control egress IP: observed during the test and confirmed different
  from the Mullvad egress; the value is intentionally not persisted in Git.
- Mullvad verifier egress: differed from the control egress and was confirmed
  by Mullvad; the value is intentionally not persisted in Git.
- Sidecar routing demonstration: passed; the ordinary verifier's public
  request exited through Mullvad without VPN configuration in that container.
- Verifier security isolation: passed; effective capabilities were zero, the
  verifier ran non-root, VPN-specific environment variables were absent, and
  it had no Secret or `/gluetun` mount.
- Mullvad `/connected` result: `You are connected to Mullvad`.
- Kubernetes DNS: passed; `kubernetes.default.svc` resolved through
  the OpenShift cluster resolver to the Kubernetes service IP.
- Public DNS and HTTPS: passed; `example.com` resolved and verifier HTTPS
  returned the Mullvad IP.
- Fail-closed restart test: passed with 150 probes launched 200 ms apart;
  `MULLVAD: 4`, `FAIL: 146`, and `NON_MULLVAD: 0`. Failed requests occurred
  while Gluetun recovered; no successful response was classified as
  non-Mullvad. Gluetun restarted once and the verifier again reported
  connected to Mullvad afterward.
- Additional permissions/runtime adjustments: no Linux capability beyond
  `NET_ADMIN`, no privileged mode, and no host access were needed. The
  working runtime required Gluetun `userspace` WireGuard because the worker
  lacks kernel WireGuard support, root PUID/PGID for the helper, the writable
  public-IP path documented above, the OpenShift Service CIDR exception for
  DNS and Kubernetes services (the Pod CIDR was tested and was unnecessary),
  and enforcing `spc_t` for the userspace UAPI socket. The ESO template also
  normalizes the item's
  unpadded private-key encoding without exposing its value.
- Cleanup completed: after the live run, the namespace, Deployments,
  ExternalSecret and generated Secret, ServiceAccount, RoleBinding,
  ClusterRole, and SCC were all deleted and verified NotFound.
