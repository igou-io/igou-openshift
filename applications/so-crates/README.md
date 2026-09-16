# SO-CRATES

[SO-CRATES](https://github.com/dougburks/so-crates) is a standalone analysis
application for PCAPs, log files, and binary files. It provides Suricata
network analysis, YARA scanning, Sigma detection, file metadata, and a web UI
for browsing the resulting alerts and artifacts.

The deployed URL is:

<https://so-crates.apps.ocp.igou.systems>

## Architecture

The app-template release creates two separate Deployments and Pods:

- `so-crates` runs the upstream v4.1.0 analysis image and listens on port 8000.
  PCAP processing invokes Suricata and then the bundled file, YARA, and Sigma
  analysis pipeline. The initial resource request is 500m CPU, 1Gi memory, and
  2Gi ephemeral storage; limits are 4 CPU, 8Gi memory, and 20Gi ephemeral
  storage.
- `so-crates-auth` runs the pinned OpenShift OAuth proxy on port 8443. It is the
  only externally reachable workload, and forwards authorized requests to the
  internal `so-crates` Service on port 8000. Keeping the proxy in its own Pod
  gives the auth boundary its own ServiceAccount, TLS endpoint, and selectors;
  the analysis Pod cannot receive Route traffic directly.

The Route uses OpenShift reencrypt TLS. The `so-crates-auth` Service receives
an OpenShift service-serving certificate, and its ServiceAccount is annotated
with the OAuth redirect reference for the `so-crates` Route. OAuth access is
gated by the proxy SAR requiring `get` on the `so-crates` Service in this
namespace. The proxy ServiceAccount has only the minimal
`system:auth-delegator` ClusterRoleBinding needed for token review and
subject-access checks.

Both Pods run on the normal OpenShift CRI-O runtime. Kata and
`runtimeClassName` are deliberately not used. The analysis container is
compatible with `restricted-v2`: it is non-root, disallows privilege
escalation, drops all Linux capabilities, uses `RuntimeDefault` seccomp, and
does not mount a Kubernetes ServiceAccount token. The analysis root filesystem
is read-only; `/data` and `/tmp` are the only declared writable mounts.

## Ephemeral data

`/data` is an `emptyDir`, not persistent storage. There is intentionally no
PVC, PV, StorageClass dependency, NFS/RWX volume, or backup annotation in this
phase. SO-CRATES runs as one replica with a `Recreate` strategy.

The lifecycle is intentionally disposable:

- `/data` survives a container restart while the same Pod remains alive.
- Deleting or recreating the Pod creates a fresh `emptyDir` and loses the old
  workspace.
- A Deployment rollout, rescheduling, node drain, or node failure loses the
  workspace when the Pod is replaced or moves to another node.
- User uploads, analyses, notes, SQLite databases, extracted files, logs, and
  downloaded or updated Suricata/YARA/Sigma state under `/data` are all
  disposable. Analyses do not survive a Deployment upgrade or restart that
  recreates the Pod, and are not backed up.

During the current Pod lifetime, inspect the workspace with commands such as:

```bash
oc get pods -n so-crates -o wide
oc exec -n so-crates deploy/so-crates -- sh -c 'find /data -maxdepth 2 -type f -print | sort'
oc logs -n so-crates deploy/so-crates
```

Do not place secrets or the OAuth cookie value in inspection output.

## Network isolation

The namespace has default-deny ingress and egress policies. The auth Pod
accepts only OpenShift router/host-network traffic on TCP/8443 and can reach
the analysis Pod on TCP/8000. The analysis Pod accepts only the auth Pod and
the host-network probe path on TCP/8000. DNS and the API/OAuth endpoints are
allowed explicitly.

The namespace EgressFirewall accounts for OVN-Kubernetes post-DNAT behavior:
the API Service reaches the control-plane host on `10.10.9.10:6443`, while
OAuth and DNS reach cluster Pods in `10.128.0.0/14` on their backend ports.
RFC1918, CGNAT, and link-local ranges are denied before public egress is
allowed. TCP/80 and TCP/443 to public addresses are available for explicit
rule refresh and the `Load from URL` feature; internal/private destinations
remain blocked. SO-CRATES also applies its upstream URL safety validation,
including redirect and DNS-rebinding checks.

Rule refresh is not automatic at startup. Use the Rules modal and explicitly
request the Suricata, YARA, or Sigma update when current public egress is
available.

## Image updates

The SO-CRATES image is pinned to upstream v4.1.0 with a real GHCR digest and
uses a Renovate-compatible `tag@sha256:digest` reference. GHCR currently
publishes this release under the numeric `4.1.0` tag; the manifest keeps the
requested `v4.1.0` release label alongside that digest. Upgrade by selecting
the intended upstream release, resolving its GHCR digest, and updating both
the tag and digest together. The OAuth proxy likewise remains digest-pinned
to the repository's current `origin-oauth-proxy:4.21` lineage.

## Live verification

The following are the focused checks used for this application:

```bash
oc get deploy,pod,svc,route -n so-crates -o wide
oc get pod -n so-crates -o yaml
oc get pvc -n so-crates
oc get networkpolicy -n so-crates
oc get egressfirewall default -n so-crates -o yaml
oc exec -n so-crates deploy/so-crates -- sh -c 'id; test -w /data; test -w /tmp; touch /data/marker /tmp/marker'
curl -I https://so-crates.apps.ocp.igou.systems/socrates.html
```

Verify that the external request enters OAuth, that no Route targets
`so-crates:8000`, that a harmless PCAP and a harmless log/binary sample can be
analyzed, and that public rule refresh/URL loading succeeds while representative
RFC1918, CGNAT, and link-local destinations fail. To verify the intentional
loss semantics, create a marker under `/data`, delete only the analysis Pod,
wait for its replacement, and confirm the marker is gone.
