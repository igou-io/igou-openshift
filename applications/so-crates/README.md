# SO-CRATES

[SO-CRATES](https://github.com/dougburks/so-crates) is a standalone analysis
application for PCAPs, log files, and binary files. It provides Suricata
network analysis, YARA scanning, Sigma detection, file metadata, and a web UI
for browsing the resulting alerts and artifacts.

The deployed URL is:

<https://so-crates.apps.ocp.igou.systems>

## Architecture

The app-template release creates one Deployment and one Service:

- `so-crates` runs the upstream v4.1.0 analysis image and listens on port 8000.
  PCAP processing invokes Suricata and then the bundled file, YARA, and Sigma
  analysis pipeline. The initial resource request is 500m CPU, 1Gi memory, and
  2Gi ephemeral storage; limits are 4 CPU, 8Gi memory, and 20Gi ephemeral
  storage.
- The `so-crates` Service exposes the analysis container's HTTP port 8000.

The OpenShift Route keeps the existing hostname and terminates TLS at the
router with edge termination. It forwards plain HTTP to `so-crates:http`,
which is port 8000. HTTP requests are redirected to HTTPS by the Route.

SO-CRATES has no application authentication. Anyone who can reach the Route
can use the application. Uploaded files and analysis results may therefore be
visible or modifiable by any user with network access to the Route. The Route
must not be treated as an authorization boundary. NetworkPolicy prevents
ordinary in-cluster Pods from bypassing the Route to reach the backend, but it
does not authenticate Route users.

The workload runs on the normal OpenShift CRI-O runtime. Kata and
`runtimeClassName` are deliberately not used. The analysis container is
compatible with `restricted-v2`: it is non-root, disallows privilege
escalation, drops all Linux capabilities, uses `RuntimeDefault` seccomp, and
does not mount a Kubernetes ServiceAccount token. The analysis root filesystem
is read-only; `/data` and `/tmp` are the only declared writable mounts.

SO-CRATES runs as one replica with a `Recreate` strategy and uses the normal
soft worker preference. This keeps the file-based analysis workspace
consistent during replacement and avoids introducing a persistent database or
shared filesystem.

## Ephemeral data

`/data` is an `emptyDir`, not persistent storage. There is intentionally no
PVC, PV, StorageClass dependency, NFS/RWX volume, or backup annotation in this
phase.

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

## Network isolation

The namespace has default-deny ingress and egress policies. The analysis Pod
accepts TCP/8000 only from the `openshift-ingress` namespace and from the
cluster's host-network source selector used for router traffic and kubelet
probes. Ordinary Pods and unrelated namespaces cannot directly reach the
backend.

The analysis workload may reach OpenShift DNS and public TCP/80 and TCP/443.
The public paths are used for explicit Suricata, YARA, or Sigma rule refreshes
and for the `Load from URL` feature. Private, cluster, carrier-grade NAT, and
link-local destinations remain excluded:

- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `100.64.0.0/10`
- `169.254.0.0/16`

The namespace EgressFirewall retains only the narrow cluster-DNS exception
required by this cluster's OVN-Kubernetes post-DNAT behavior, then denies
internal ranges, allows public TCP/80 and TCP/443, and denies everything
else. SO-CRATES also applies its upstream URL safety validation, including
redirect and DNS-rebinding checks.

Rule refresh is not automatic at startup. Use the Rules modal and explicitly
request the Suricata, YARA, or Sigma update when current public egress is
available.

## Image updates

The SO-CRATES image is pinned to the published upstream `4.1.0` GHCR tag and
the verified digest
`sha256:a6d6c63c0dd00d7de1a50658b0c71e59f9af2bf4ab4d77460d2d955b0863f2b5`.
The `tag@sha256:digest` form is retained so Renovate can identify and update
the dependency. Upgrade by selecting the intended upstream release, resolving
its GHCR digest, and updating both the published tag and digest together.

## Live verification

The following are the focused checks used for this application:

```bash
oc get deploy,pod,svc,route -n so-crates -o wide
oc get pod -n so-crates -o yaml
oc get pvc -n so-crates
oc get networkpolicy -n so-crates
oc get egressfirewall default -n so-crates -o yaml
oc exec -n so-crates deploy/so-crates -- sh -c 'id; test -w /data; test -w /tmp; touch /data/marker /tmp/marker'
curl -I http://so-crates.apps.ocp.igou.systems/socrates.html
curl -fsS https://so-crates.apps.ocp.igou.systems/socrates.html >/dev/null
```

Verify that HTTP redirects to HTTPS, the HTTPS request loads
`/socrates.html` without credentials, the Route targets `so-crates:http`, and
no second Route or separate authentication workload exists. Verify that a
harmless PCAP and a harmless log/binary sample can be analyzed, and that public
rule refresh and `Load from URL` work while representative RFC1918, CGNAT, and
link-local destinations fail. To verify the intentional loss semantics,
create a marker under `/data`, delete only the analysis Pod, wait for its
replacement, and confirm the marker is gone.
