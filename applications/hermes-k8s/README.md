# hermes-k8s — production Hermes on the kubernetes terminal backend

Container/operator-based replacement for the hermes VM
(`applications/hermes-agent`). The agent runs as a `HermesInstance`
(paperclipinc hermes-operator, inflated in `kustomization.yaml`) using the
fork build of the pending upstream PR
([david-igou/hermes-agent `feat/kubernetes-terminal-backend`](https://github.com/david-igou/hermes-agent),
commit `c80e5bd17`): every terminal session is a **per-session Kata VM** on
the kata-oc pool instead of a rootless-podman container inside the VM.

Graduated from `test-workloads/hermes-k8s-backend`, which holds the full
finding log (OVN post-DNAT NetworkPolicy ports, the `hermes-agent-root` SCC,
`fsGroup` for the SA token, `spec.security.rbac` vs `spec.rbac`, pods/exec
needing both `get` and `create`). This directory only documents what is
*different* from that workload.

## What maps to what

| VM (applications/hermes-agent) | here |
|---|---|
| VM guest + Ansible `configure.yml` | `HermesInstance.spec.config.raw` (live config.yaml reduced to its non-default delta; **this CR now owns config.yaml** — it is re-rendered at every pod start, so durable changes belong here, not in the dashboard UI) |
| `.env` from 1Password via AAP | `hermes-env` ExternalSecret (`op://lab_agents/hermes`, `op://lab_agents/opencode-go-api-key`) via `spec.envFrom` |
| `hermes-state` DataVolume (30Gi) | operator PVC via `spec.storage.persistence` (30Gi ssd) — sessions, memory, skills, **cron store**, auth.json, SOUL.md |
| `/home/hermes/agent-repos` bind mount | `hermes-workspace` RWX NFS PVC, `repos/` subPath: agent sees `/opt/data/agent-repos`, sessions see `/workspace` |
| `cache/documents` → `/output` bind | same PVC, `output/` subPath: agent `/opt/data/cache/documents`, sessions `/output` |
| `~/.config/gcp-sa` (storescrape sheets SA) | `gcp-sa-storescrape` ExternalSecret mounted read-only in session pods |
| terminal containers (podman, keep-id 1000) | Kata session pods, `runAsUser: 1000` (devenv `igou` user) |
| nftables egress backstop | NetworkPolicies + the ported `default` EgressFirewall |
| dashboard :9119 + edge Route | operator Service + `hermes-k8s-dashboard` Route (parallel hostname until cutover) |
| sshd + `hermes-ssh` VIP 10.10.150.1 | none — access is the dashboard, Slack, or `oc exec` |

## Known gaps (deliberate, tracked for cutover)

* **ghapp broker** (`/run/ghbroker/ghbroker.sock`) has no container port yet —
  sessions have no GitHub App token source. Needs a sidecar or in-session
  fallback before the VM retires.
* **State migration is manual**: rsync `~/.hermes` (minus the regenerable
  dirs), `agent-repos` → PVC `repos/`, `agent-skills` → `/opt/data`, and the
  root-disk identity files (`~/.claude*`, `~/.codex`, `~/.config/opencode`…)
  the terminal bind mounts used to project.
* Host-side extras not ported: tirith trust reseed, agent-runtime overlay
  nightly timer, journald→Alloy shipping (container logs flow via the
  cluster logging path instead), storescrape `quick_commands` (VM-host
  wrappers).
* AAP `hermes_*` job templates / schedules become obsolete at cutover.

## Updating the image

Until the upstream PR merges, updates follow the fork loop — rebase
`feat/kubernetes-terminal-backend` onto upstream main (regenerate `uv.lock`),
run the backend test suite, rebuild with the podman Dockerfile variant, push to
Quay, then bump the tag + digest **in both places** in `hermesinstance.yaml`
(`spec.image` and the dashboard `spec.sidecars[0].image`). Full runbook with
the exact commands and failure modes: igou-docs →
`openshift/Hermes Agent Container Update - Fork Rebase, Image Rebuild, and Rollout`.

Two rollout behaviors to remember: an image change rolls the StatefulSet by
itself; a `spec.config.raw`-only change does not — the pod copies config at
boot, so delete `hermes-k8s-0` after the sync.

## Verify

`hermes doctor` in the agent pod must be fully green, and:

```bash
POD=hermes-k8s-0
oc -n hermes-k8s exec $POD -- runuser -u hermes -- bash -c '
  export HERMES_HOME=/opt/data HOME=/opt/data
  cd /opt/hermes && .venv/bin/python -c "
import sys; sys.path.insert(0, \"/opt/hermes\")
from hermes_cli.config import apply_terminal_config_to_env; apply_terminal_config_to_env()
from tools.terminal_tool import terminal_tool
print(terminal_tool(command=\"grep PRETTY /etc/os-release && id && ls /workspace /output\"))"'
```

Expect exit 0, CentOS Stream 10, uid 1000, and the shared workspace visible.
Session pods (`hermes-ws-*`) must report `product_name=KVM`
(`/sys/class/dmi/id/product_name`) — real Kata isolation.
