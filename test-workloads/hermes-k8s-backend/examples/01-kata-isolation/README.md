# Per-session VM isolation with Kata

Runs every session's commands inside a lightweight VM instead of a container,
by asking for the `kata` RuntimeClass that OpenShift sandboxed containers
installs. `provisioner: sandbox` also hands pod creation to the Red Hat build of
Agent Sandbox, so the cluster's own controller owns pod shape and lifecycle.

Neither needed a change to Hermes. `runtimeClassName` is an ordinary PodSpec
field, and it composes precisely because the sandbox is a pod.

**Merge behaviour: maps merge recursively.** `spec.runtimeClassName` and
`spec.nodeSelector` are added; everything the default base puts under `spec`
survives — `restartPolicy`, `securityContext`, the workspace container, and both
volumes.

## Prerequisites

* OpenShift sandboxed containers installed and a `KataConfig` applied
  (`components/sandboxed-containers-operator`), with the target nodes labelled
  `kata-runtime=enabled`.
* The agent-sandbox operator (`components/agent-sandbox-operator`) and the
  `hermes-session-sandbox` Role from `../rbac-sandbox.yaml`, which grants
  `sandboxes` create/delete instead of bare pod creation.

Raise `ready_timeout_seconds`: Kata cold starts are considerably slower than a
container, and the default 120s is not always enough on a cold image pull.

## Verify

```bash
oc -n hermes-k8s-test exec hermes-k8s-0 -- runuser -u hermes -- bash -c '
  export HERMES_HOME=/opt/data HOME=/opt/data
  cd /opt/hermes && .venv/bin/python -c "
from hermes_cli.config import apply_terminal_config_to_env; apply_terminal_config_to_env()
from tools.terminal_tool import terminal_tool
print(terminal_tool(command=\"cat /sys/class/dmi/id/product_name; cat /sys/class/dmi/id/sys_vendor\"))"'
```

Observed 2026-08-07:

```
EXIT: 0
KVM
Red Hat
```

`product_name=KVM` is the proof: the command ran inside a virtual machine.
Note that the **guest kernel version matches the host**, because OSC builds its
guest kernel from the same RHEL base, so `uname -r` is not a valid check.
