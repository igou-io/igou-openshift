# hermes-nested-podman

Proof that the [ultraworkers hermes-agent Helm chart](https://github.com/ultraworkers/hermes-agent-helm-chart)
runs on this cluster with a **nested rootless podman terminal backend** —
the one capability that previously justified the hermes KubeVirt VM — using
OpenShift 4.21's GA user-namespace support. No privileged pods, no
MachineConfig, no feature-gate changes.

First executed end-to-end 2026-08-05 (installer-into-PVC pattern), then
re-verified the same day on the purpose-built image
**`ghcr.io/igou-io/hermes-agent-podman`** (`igou-containers`): the official
`nousresearch/hermes-agent` image with the podman stack, pod-sized
subuid/subgid, storage/containers config, the `notmpcopyup` patch, and an
`XDG_RUNTIME_DIR` cont-init baked in. In the final state the pod runs the
official s6 entrypoint (supervised `gateway run`), and hermes v0.20.0's
`terminal_tool` executes commands inside a nested podman container running
`ghcr.io/igou-io/igou-devenv` — verified with no LLM provider configured.

This is a **test workload**, not a hermes replacement: the namespace has
none of the production egress layers, secrets handling, or converge model.
See "Caveats" before promoting any of it.

## What's in here

Manifests are the chart's rendered output (split per resource) plus the
cluster-scoped pieces the chart cannot express:

| File | Why |
|------|-----|
| `scc.yaml` | `hermes-nested-podman` SCC: caps `CHOWN,DAC_OVERRIDE,FOWNER,SETUID,SETGID,SETFCAP,SYS_ADMIN` (all namespaced), `RunAsAny` (upstream's s6 bootstrap must start as container-root and drops privileges itself), `container_engine_t`, `userNamespaceLevel: RequirePodLevel`, seccomp `unconfined` allowed |
| `scc-rbac.yaml` | binds the SCC to the workload ServiceAccount |
| `bootstrap-configmap.yaml` | chart-rendered `config.yaml` (terminal backend: docker→podman, devenv image) + `SOUL.md` |
| `deployment.yaml` | `hostUsers: false`, `procMount: Unmasked`, `io.kubernetes.cri-o.Devices: /dev/fuse,/dev/net/tun`, seccomp `Unconfined`, `runAsUser: 0` + `HERMES_UID=1000`/`HERMES_GID=1000` (the supported remap contract — a pinned `runAsUser` is rejected by upstream stage2) |
| `helm-values.yaml` + `postrender.py` | source of the render — see Regenerating |

subuid/subgid ranges, `storage.conf`, `containers.conf`, the `notmpcopyup`
patch, and the `XDG_RUNTIME_DIR` cont-init all live in the image now.

## Procedure

1. **Deploy**: `oc apply -k test-workloads/hermes-nested-podman` and wait
   for the rollout. Watch the logs for the stage2 remap
   (`Changing hermes UID to 1000`) and s6 starting `main-hermes`.
2. **Verify** — no LLM provider needed:

   ```bash
   POD=$(oc -n hermes-nested-test get pod -l app.kubernetes.io/name=hermes-agent -o name | head -1)
   oc -n hermes-nested-test exec $POD -- runuser -u hermes -- bash -c '
     export HOME=/opt/data HERMES_HOME=/opt/data XDG_RUNTIME_DIR=/tmp/xdg-runtime
     export TERMINAL_ENV=docker TERMINAL_DOCKER_IMAGE=ghcr.io/igou-io/igou-devenv:2026.07.27 TERMINAL_CWD=/workspace
     cd /opt/hermes && .venv/bin/python -c "
   from tools.terminal_tool import terminal_tool
   print(terminal_tool(command=\"grep PRETTY /etc/os-release && id\"))"'
   ```

   Expect exit_code 0 and `CentOS Stream 10` — the devenv payload, not the
   pod. First sandbox start on a fresh PVC pulls the devenv image; hermes's
   60s cgroup probe may time out once and disable resource limits for that
   session (subsequent runs are warm).
3. **Cleanup**: `oc delete -k test-workloads/hermes-nested-podman`
   (removes the namespace, SCC, and ClusterRole).

## Why each knob exists

Debugged sequentially on 2026-08-05; every one was load-bearing:

1. **seccomp `RuntimeDefault`** returns ENOSYS for `unshare` →
   `Unconfined`. The pod user namespace is the isolation boundary (same
   posture as Dev Spaces workspaces).
2. **`DAC_OVERRIDE`**: the nested child's `/proc/*/uid_map` is owned by
   the launching uid; setuid-root `newuidmap` can't open it without DAC
   override.
3. **Pod-sized subuid ranges** (now baked in the image): sub-delegated
   UIDs must exist in the pod's 65536-UID namespace; ranges are split
   around uid 10000 so they're valid for both the stock hermes uid and
   the `HERMES_UID=1000` remap (the kernel rejects overlapping uid_map
   extents).
4. **Namespaced `CAP_SYS_ADMIN`**: the actual missing capability for
   another-process uid_map writes (`SETFCAP` alone is not it —
   `verify_root_map` only fires when mapping *parent* uid 0).
5. **tmpfs copy-up SELinux xattrs** → the `notmpcopyup` image patch
   (upstream-worthy fix to `tools/environments/docker.py`).
6. **Gateway mode** (official s6 entrypoint): `CHOWN` + `FOWNER` for s6
   preinit fixing `/run` ownership, `RunAsAny` + `HERMES_UID` because
   upstream stage2 refuses `--user` and remaps/drops privileges itself,
   and the cont-init must chown `XDG_RUNTIME_DIR` to hermes.

Also: hermes `terminal.cwd` must be the container-side `/workspace` (a
host path makes crun exit 126).

## Regenerating from the chart

```bash
helm template hermes-agent-test <chart-checkout> -n hermes-nested-test \
  -f helm-values.yaml | ./postrender.py
```

`postrender.py` injects `spec.template.spec.hostUsers: false` — the chart
has no passthrough for it (Helm 4's `--post-renderer` expects a plugin,
hence template→patch→apply rather than a helm release).

## Caveats

- `SYS_ADMIN` is namespaced (root-in-userns, not host root) but is still
  the cap to scrutinize first; the set may be minimizable (untested
  whether `DAC_OVERRIDE`/`SETFCAP` are redundant once `SYS_ADMIN` is
  present).
- Container-root start is upstream's requirement, not a preference; the
  userns (`hostUsers: false`, enforced by the SCC's `RequirePodLevel`)
  is what makes it acceptable.
- PSA `restricted` would warn on the added caps and root user; the
  namespace carries no enforce label.
- No EgressFirewall/NetworkPolicy/nftables layers here, unlike the
  production hermes namespace — full egress.
- Sandbox containers default to root-in-namespace; production parity would
  add the VM's `--userns=keep-id` `docker_extra_args` to `config.yaml`.
- The chart's default image tag (`0.8.0`) does not exist upstream — tags
  are date-based; `helm-values.yaml` points at
  `ghcr.io/igou-io/hermes-agent-podman` instead.
