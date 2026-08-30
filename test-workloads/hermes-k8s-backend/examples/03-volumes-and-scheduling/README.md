# Extra volumes, priority, and node affinity

Adds a memory-backed scratch volume and controls where the session pod lands and
what it may preempt.

**Merge behaviour: lists replace wholesale.** This is the sharp edge of the
rule, and this example exists mainly to show it.

Because `volumes` and the container's `volumeMounts` are lists, the patch
restates the `workspace` and `tmp` entries alongside the new `scratch` one. That
repetition is deliberate. Omit them and you get a pod with only `/scratch`
mounted, whose working directory does not exist, and every command fails with
"no such file or directory" — a runtime failure, not a config error, because
Hermes does not inspect the pod.

`priorityClassName` and `affinity` demonstrate the wider point: neither existed
in the old enumerated schema, and neither required a Hermes change. Any field
the Kubernetes API accepts in a PodSpec works, including fields added to
Kubernetes after this backend was written.

`llmkube-low` keeps ephemeral agent sandboxes below real workloads, so they are
preemptible under pressure. The node affinity pins sessions to the Kata pool,
which is useful when only some nodes carry the runtime.

## Verify

```bash
oc -n hermes-k8s-test exec hermes-k8s-0 -- runuser -u hermes -- bash -c '
  export HERMES_HOME=/opt/data HOME=/opt/data
  cd /opt/hermes && .venv/bin/python -c "
from hermes_cli.config import apply_terminal_config_to_env; apply_terminal_config_to_env()
from tools.terminal_tool import terminal_tool
print(terminal_tool(command=\"pwd; touch /scratch/x && echo scratch-writable; df -h /scratch | tail -1\"))"'
```

Observed 2026-08-07:

```
EXIT: 0
/workspace
scratch-writable
tmpfs            64M     0   64M   0% /scratch
```

`pwd` returning `/workspace` is what proves the restated mounts worked; the
tmpfs line confirms `medium: Memory` and `sizeLimit: 64Mi` reached the API.

Inspecting the session pod while a command runs:

```
node=p330.igou.systems
priorityClassName=llmkube-low
priority=1000
volumes=workspace tmp scratch
mounts=/workspace /tmp /scratch
```
