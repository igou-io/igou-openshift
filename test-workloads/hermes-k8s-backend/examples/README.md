# Customizing the session pod

The `kubernetes` terminal backend takes one config key that matters:
`terminal.kubernetes.pod_template`, a `PodTemplateSpec`. Hermes builds a default
pod, merges yours over it, and submits the result. There is no allow-list of
supported fields: anything the Kubernetes API accepts in a pod, you can set.

Hermes performs no security or schema validation of the pod. That is deliberate.
SCC, Pod Security Admission, ValidatingAdmissionPolicy, NetworkPolicy and RBAC
do it authoritatively and are the cluster administrator's job, and every request
is sent with `fieldValidation=Strict`, so a typo comes back as a `400` naming
the exact JSON path rather than being silently dropped.

## The merge rule

**[RFC 7386 JSON merge patch](https://www.rfc-editor.org/rfc/rfc7386), with one
exception.**

| | Behaviour |
|---|---|
| Maps | merge recursively |
| `null` | removes the key |
| Lists | **replace wholesale** |
| `spec.containers`, `spec.initContainers` | merge element-wise by `name` |

The containers exception exists because without it, setting a memory limit would
force you to restate the image, command and volume mounts. Every other list
replaces, including `volumes`, `volumeMounts`, `env` and `tolerations`.

**The sharp edge is `volumeMounts`.** Adding one replaces the whole list, so you
must restate the workspace mount or the session's working directory will not
exist. Example 3 shows this.

One field is not yours: `app.kubernetes.io/managed-by: hermes-agent` is stamped
after the merge. Hermes uses it to find and adopt its own session pods, and the
NetworkPolicies in this directory select on it. Overriding it, setting it to
`null`, or nulling `metadata` entirely all leave it in place.

## The examples

| | Shows | Merge behaviour exercised |
|---|---|---|
| [01-kata-isolation](./01-kata-isolation) | per-session VM isolation | maps merge recursively |
| [02-container-tuning](./02-container-tuning) | resources, env, a sidecar | `containers` merge by `name` |
| [03-volumes-and-scheduling](./03-volumes-and-scheduling) | extra volume, priority, affinity | lists replace wholesale |

Each directory holds a patch you can apply to the `HermesInstance` in the parent
directory, plus the verification command and its recorded output.

Apply one with:

```bash
oc -n hermes-k8s-test patch hermesinstance hermes-k8s \
  --type merge --patch-file test-workloads/hermes-k8s-backend/examples/<name>/patch.yaml
oc -n hermes-k8s-test delete pod hermes-k8s-0     # pick up the new config
```

## Verifying any change

Session pods are ephemeral, so watch for them while a command runs:

```bash
oc -n hermes-k8s-test get pods -w | grep hermes-ws
```

Or read the rendered pod without a cluster at all, which is the fastest way to
check a merge did what you expected:

```python
from tools.environments.kubernetes import merge_kubernetes_config, render_pod_template, Resources
kcfg = merge_kubernetes_config({"pod_template": {...}})
print(render_pod_template(kcfg, persistent=False, image="x", resources=Resources(), pvc_name="x"))
```

## Not covered here

**Persistent workspaces.** `terminal.kubernetes.persistent: true` backs the
workspace with a PVC (`volume.size`, `volume.storage_class_name`) that outlives
the agent pod so sessions resume. It carries no ownerReference by design, so it
is never garbage-collected — reap them yourself. Adoption checks the Hermes
provenance labels, which anything holding `persistentvolumeclaims/create` in the
namespace could forge; that is an RBAC boundary, not a Hermes control.
