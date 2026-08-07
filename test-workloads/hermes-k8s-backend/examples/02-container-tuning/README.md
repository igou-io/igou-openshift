# Container resources, env, and a sidecar

Sets CPU/memory on the workspace container, injects an environment variable, and
adds a second container alongside it.

**Merge behaviour: `spec.containers` is the one list that merges by `name`.**
The `workspace` entry merges into the base container, so its image, command,
volume mounts and security context are preserved and only `resources` and `env`
are added. The `notes` entry matches no base container, so it is appended.

This exception exists precisely for this case. Under strict RFC 7386 the list
would replace, and setting a memory limit would force you to restate the image,
the command and every mount.

`container_name` still selects `workspace` as the exec target, so the sidecar
never receives commands. It is useful for anything that should share the pod's
network and lifecycle — a proxy, a log shipper, a credential broker.

## Verify

```bash
oc -n hermes-k8s-test exec hermes-k8s-0 -- runuser -u hermes -- bash -c '
  export HERMES_HOME=/opt/data HOME=/opt/data
  cd /opt/hermes && .venv/bin/python -c "
from hermes_cli.config import apply_terminal_config_to_env; apply_terminal_config_to_env()
from tools.terminal_tool import terminal_tool
print(terminal_tool(command=\"printenv EXAMPLE_MARKER; cat /sys/fs/cgroup/memory.max\"))"'
```

Observed 2026-08-07:

```
EXIT: 0
container-tuning
4294967296
```

`4294967296` is 4 GiB, the limit from the patch, which confirms the merge landed
on the base container rather than replacing it. The sidecar appears in the pod's
events:

```
Normal  Created  pod/hermes-ws-4e85ab77-default  Created container: notes
Normal  Started  pod/hermes-ws-4e85ab77-default  Started container notes
```
