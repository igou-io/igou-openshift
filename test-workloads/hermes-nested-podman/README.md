# hermes-nested-podman

Proof that the [ultraworkers hermes-agent Helm chart](https://github.com/ultraworkers/hermes-agent-helm-chart)
can run on this cluster with a **nested rootless podman terminal backend** —
the one capability that previously justified the hermes KubeVirt VM — using
OpenShift 4.21's GA user-namespace support. No privileged pods, no
MachineConfig, no feature-gate changes.

First executed end-to-end 2026-08-05: hermes v0.20.0's `terminal_tool`
executed commands inside a nested podman container running
`ghcr.io/igou-io/igou-devenv:2026.07.27`, inside an unprivileged
user-namespaced pod. Verified with no LLM provider configured (the terminal
backend is driven directly, see Verify below). The `--userns=keep-id`
variant used by the production VM's terminal config also works.

This is a **test workload**, not a hermes replacement: the namespace has
none of the production egress layers, secrets handling, or systemd unit
model. See "Caveats" and the memory/docs trail before promoting any of it.

## What's in here

The agent container *is* the devenv image (upstream's
`nousresearch/hermes-agent` image is not anonymously pullable, and the
devenv image already carries podman + fuse-overlayfs + setuid newuidmap).
The entrypoint installs Hermes onto the PVC with the same installer flags
as `igou-ansible/playbooks/hermes/setup-hermes.yml`, writes a
fuse-overlayfs `storage.conf`, and idles; the terminal backend is
configured for nested podman via the chart-rendered `config.yaml`.

Manifests are the chart's rendered output (split per resource) plus the
cluster-scoped pieces the chart cannot express:

| File | Why |
|------|-----|
| `scc.yaml` | `hermes-nested-podman` SCC: caps `SETUID,SETGID,DAC_OVERRIDE,SETFCAP,SYS_ADMIN`, `container_engine_t`, `userNamespaceLevel: RequirePodLevel`, seccomp `unconfined` allowed |
| `scc-rbac.yaml` | binds the SCC to the workload ServiceAccount |
| `subuid-configmap.yaml` | pod-userns-sized `/etc/subuid`+`/etc/subgid` (`igou:2000:63536`) mounted over the image's host-sized ranges |
| `bootstrap-configmap.yaml` | chart-rendered `config.yaml` (terminal backend: docker→podman, devenv image) + `SOUL.md` |
| `deployment.yaml` | `hostUsers: false`, `procMount: Unmasked`, `io.kubernetes.cri-o.Devices: /dev/fuse,/dev/net/tun`, seccomp `Unconfined` |
| `helm-values.yaml` + `postrender.py` | source of the render — see Regenerating |

## Procedure

1. **Deploy**: `oc apply -k test-workloads/hermes-nested-podman` and wait
   for the rollout (first start pulls the devenv image and installs Hermes
   onto the PVC; a few minutes).
2. **Patch the installed backend** (once per fresh PVC): hermes hardcodes
   `--tmpfs` flags whose copy-up tries to preserve SELinux xattrs — always
   denied inside a userns. Append `,notmpcopyup` to the four tmpfs sites:

   ```bash
   POD=$(oc -n hermes-nested-test get pod -l app.kubernetes.io/name=hermes-agent -o name | head -1)
   oc -n hermes-nested-test exec $POD -- sed -i \
     's|size=512m|size=512m,notmpcopyup|; s|size=256m|size=256m,notmpcopyup|; s|size=64m|size=64m,notmpcopyup|g' \
     /opt/data/hermes-agent/tools/environments/docker.py
   ```

   (Upstream-worthy one-liner against nousresearch/hermes-agent.)
3. **Verify** — no LLM provider needed:

   ```bash
   oc -n hermes-nested-test exec $POD -- bash -c '
     export XDG_RUNTIME_DIR=/tmp/xdg-runtime HERMES_HOME=/opt/data
     cd /opt/data/hermes-agent
     ./venv/bin/python -c "
   from tools.terminal_tool import terminal_tool
   print(terminal_tool(command=\"grep PRETTY /etc/os-release && id\"))"'
   ```

   Expect exit_code 0 and `CentOS Stream 10` — the devenv payload, not the
   pod. Session containers persist (`container_persistent: true`), so a
   second call reuses the sandbox.
4. **Cleanup**: `oc delete -k test-workloads/hermes-nested-podman`
   (removes the namespace, SCC, and ClusterRole).

## The five blockers (why each knob exists)

Debugged sequentially on 2026-08-05; every one was load-bearing:

1. **seccomp `RuntimeDefault`** returns ENOSYS for `unshare` →
   `Unconfined`. The pod user namespace is the isolation boundary (same
   posture as Dev Spaces workspaces).
2. **`DAC_OVERRIDE`**: the nested child's `/proc/*/uid_map` is owned by
   uid 1000; setuid-root `newuidmap` can't open it without DAC override.
3. **Pod-sized subuid ranges**: sub-delegated UIDs must exist in the pod's
   65536-UID namespace; the image's `igou:524288:65536` cannot. The
   ConfigMap maps `0→1000` plus `1..63536→2000..65535` — exactly full.
4. **Namespaced `CAP_SYS_ADMIN`**: the actual missing capability for
   another-process uid_map writes (`SETFCAP` alone is not it —
   `verify_root_map` only fires when mapping *parent* uid 0). Probe used:
   the image has passwordless sudo, so `sudo grep Cap /proc/self/status`
   shows exactly what a setuid-root process receives under the bounding
   set.
5. **tmpfs copy-up SELinux xattrs** → the `notmpcopyup` patch in step 2.

Also: hermes `terminal.cwd` must be the container-side `/workspace` (a
host path makes crun exit 126), and the entrypoint's PID-1 `sleep` ignores
SIGTERM, hence `terminationGracePeriodSeconds: 5`.

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
- PSA `restricted` would warn on the added caps; the namespace carries no
  enforce label.
- No EgressFirewall/NetworkPolicy/nftables layers here, unlike the
  production hermes namespace — full egress.
- Sandbox containers default to root-in-namespace; production parity would
  add the VM's `--userns=keep-id:uid=1000,gid=1000 --user 1000:1000`
  `docker_extra_args` to `config.yaml`.
