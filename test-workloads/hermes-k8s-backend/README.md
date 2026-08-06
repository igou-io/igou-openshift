# hermes-k8s-backend

Hermes running with the **`kubernetes` terminal backend**: instead of executing
agent shell commands inside its own container, the agent creates a **session
pod** per session and execs into it. The backend is a port of the closed
upstream PR [#37591](https://github.com/NousResearch/hermes-agent/pull/37591),
re-scoped so every setting lives in `config.yaml`
([david-igou/hermes-agent#1](https://github.com/david-igou/hermes-agent/pull/1)).

Proven end to end 2026-08-06: `terminal_tool` returns exit 0 executing in a
session pod running `igou-devenv`, with no LLM provider configured.

Sibling workload: [`hermes-nested-podman`](../hermes-nested-podman) solves the
same problem the other way — nested rootless podman *inside* the agent pod.
The contrast is the point:

| | nested-podman | this |
|---|---|---|
| Sandbox is | a container inside the agent pod | its own pod |
| Agent pod needs | `SYS_ADMIN`, userns, `procMount: Unmasked`, unconfined seccomp | root start only (s6 requirement) |
| Sandbox pod SCC | n/a | **`restricted-v2`** — the strictest one |
| Kata/gVisor | impossible (no nested virt in a pod) | `pod_template.spec.runtimeClassName: kata` |

## Layout

| File | Purpose |
|---|---|
| `kustomization.yaml` | inflates the hermes-operator OCI chart via `helmCharts` |
| `namespace.yaml` | `hermes-k8s-test` + the `hermes-agent` ServiceAccount |
| `operator-namespace.yaml` | `hermes-operator` (chart inflation has no `--create-namespace`) |
| `scc.yaml` | `hermes-agent-root` SCC — restricted-v2 + `RunAsAny` + 5 caps |
| `scc-rbac.yaml` | binds that SCC to the agent SA |
| `rbac.yaml` | session SA (no perms) + the agent's pod/exec Role |
| `session-networkpolicy.yaml` | session-pod default-deny + optional internet |
| `agent-egress-networkpolicy.yaml` | **the one that makes it work** — see below |
| `quay-pull-externalsecret.yaml` | Quay robot pull secret from 1Password |
| `hermesinstance.yaml` | the `HermesInstance` CR |

## Apply

`helmCharts` needs `--enable-helm`, which `oc apply -k` does not pass, and the
`hermesinstances` CRD is **600 KiB** — far past the 256 KiB cap on the
`last-applied-configuration` annotation that client-side apply writes. So build
and pipe through **server-side** apply:

```bash
kustomize build --enable-helm test-workloads/hermes-k8s-backend \
  | oc apply --server-side --force-conflicts -f -
```

`--force-conflicts` is needed because the operator's webhook and CRD objects
are also managed by Helm's field manager.

Kustomize does not order resources, so on a **first** apply the `HermesInstance`
is rejected until the operator's CRD is established. Re-run the same command
once the operator is up; it is idempotent.

Cleanup: `kustomize build --enable-helm … | oc delete -f -`.

## Verify (no LLM provider needed)

```bash
POD=hermes-k8s-0
oc -n hermes-k8s-test exec $POD -- runuser -u hermes -- bash -c '
  export HERMES_HOME=/opt/data HOME=/opt/data
  cd /opt/hermes && .venv/bin/python -c "
import sys, json; sys.path.insert(0, \"/opt/hermes\")
from hermes_cli.config import apply_terminal_config_to_env; apply_terminal_config_to_env()
from tools.terminal_tool import terminal_tool
print(terminal_tool(command=\"grep PRETTY /etc/os-release && id\"))"'
```

Expect exit 0 and `CentOS Stream 10` — the devenv sandbox, not the agent pod.
Session pods are ephemeral; watch them with
`oc -n hermes-k8s-test get pods -w` during a call, or look for
`hermes-ws-*` in the namespace events after one.

## Status

Proven end to end 2026-08-06 on this cluster, on the image built from the
project's own Dockerfile:

* `provisioner: pod` — `terminal_tool` exit 0 in a session pod.
* `provisioner: sandbox` + `pod_template.spec.runtimeClassName: kata` — exit 0
  with the session container reporting `product_name=KVM`, i.e. a per-session
  Kata VM. The `Sandbox` CR carried `managed-by=hermes-agent`, an
  ownerReference to the agent pod, and the `hermes-session-noperms` SA.

Config follows the collapsed schema from upstream issue #79869: one
`pod_template` dict rather than ~42 enumerated keys, `provisioner: pod|sandbox`,
strict server-side field validation, and a reserved core Hermes rejects
overrides of. The old enumerated keys are **rejected**, so a config written
against the earlier revision of this workload will now fail loudly.

## Findings this workload encodes

Each of these cost real debugging; none are cosmetic.

1. **`agent-egress-networkpolicy.yaml` — OVN-Kubernetes applies load-balancer
   DNAT *before* egress ACLs.** The operator's own NetworkPolicy allows egress
   on 53 and 443, which is right on vanilla Kubernetes and blocks everything
   here: the apiserver's `172.30.0.1:443` DNATs to `:6443` and OpenShift
   CoreDNS's `172.30.0.10:53` to `:5353`, so neither rule matches post-DNAT.
   Symptom: in-cluster auth fails, DNS times out, `terminal_tool` hangs and no
   session pod is ever created. NetworkPolicies are additive, so this
   supplements rather than replaces the operator's.
2. **The upstream s6 image refuses an arbitrary UID** (verified at 1234:
   `stage2 ERROR: container started with --user`). It must start as
   container-root and remaps to `HERMES_UID` itself. `restricted-v2` rejects
   UID 0 and legacy `anyuid` rejects the operator's `seccompProfile`, hence
   `hermes-agent-root`. `runAsUser: 0` is set **explicitly** — leaving it unset
   let `restricted-v2` win admission and rewrite the UID.
3. **`fsGroup: 1000`** — the agent drops to the hermes user, but the projected
   ServiceAccount token is root-only, so in-cluster auth failed until the
   volume was group-owned.
4. **RBAC under `spec.security.rbac`**, not `spec.rbac` — the latter is
   silently ignored and the operator creates its own SA lacking pod/exec rights.
5. **`get pods/exec`, not `create`** — the python client opens exec with
   `connect_get_namespaced_pod_exec`, a websocket-upgrading GET.
6. **The operator rejects a floating `:latest`** tag; the image is pinned by
   digest.

SCC changes need the pod **deleted** to re-run admission — restarts do not.

## Caveats

- The image is hosted on the cluster's own Quay and is not anonymously
  pullable, hence the ExternalSecret. It requires 1Password item
  `igou-local-quay-modify` in vault `lab_container_registries`.
- `pod_template.spec.runtimeClassName` is empty until OpenShift sandboxed containers is
  installed (see `components/sandboxed-containers-operator`). With `kata`,
  raise `ready_timeout_seconds` — cold starts exceed the 120 s default.
- This is a **test workload**: it is not wired into `clusters/ocp/values.yaml`
  and ArgoCD does not manage it.
