# ace-step

[ACE-Step](https://github.com/ace-step/ACE-Step) 1.5 Gradio UI on the
on-demand `casval` burst node.

- **URL**: <https://ace-step.apps.ocp.igou.systems>
- Image: `ghcr.io/ace-step/ace-step-1.5` (digest-pinned). The container
  starts with `uv run --no-sync` so OpenShift's arbitrary UID does not try
  to rewrite the image's frozen environment.

## GPU

Requests/limits **`nvidia.com/gpu: 2`** pin the pod to casval (the only
node advertising two NVIDIA GPUs) and exclude the 2 GiB P620 on p330. The
pod also carries the burst nodeSelector and `workload=burst` toleration.

Claiming both GPUs means ComfyUI and casval-hosted llmkube models
(`qwen3-35b`, `qwen38-27b`) cannot run concurrently. Scale those to `0`
before leaving ACE-Step at `1`.

ArgoCD ignores `/spec/replicas` so a live scale-down is not reverted.

## Persistence

- `ace-step-checkpoints` (100Gi, `freenas-nvmeof-ssd-csi`, RWO) at
  `/app/checkpoints` — Hugging Face `ACE-Step/Ace-Step1.5` bundle plus
  `HF_HOME`. Scale 0→1 must not redownload.
- `ace-step-output` (20Gi, same class) at `/app/gradio_outputs` — generated
  songs. `/app/output` stays emptyDir (unused by 1.5). `/tmp` stays emptyDir.

```bash
# After casval is Ready (a Pending GPU pod also drives the autoscaler).
oc -n ace-step scale deploy/ace-step --replicas=1

# Stop ACE-Step; the casval lease / autoscaler can release the node.
oc -n ace-step scale deploy/ace-step --replicas=0
```
