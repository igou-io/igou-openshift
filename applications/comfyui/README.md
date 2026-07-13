# comfyui

[ComfyUI](https://github.com/comfyanonymous/ComfyUI) — node-based Stable
Diffusion / Flux image-generation UI — running on an NVIDIA GPU on the
on-demand `casval` burst node.

- **URL**: <https://comfyui.apps.ocp.igou.systems>
- No app-level auth: internal admin-VLAN ingress only, same posture as the
  llmkube routes.
- Image: `docker.io/yanwk/comfyui-boot`, slim CUDA 13.0 family (digest-pinned,
  Renovate-managed). CUDA 13.0 runtime runs on casval's 595 driver (CUDA 13.2).

## Scaling (this is a manually-scaled, autoscale-aware app)

`casval` is an on-demand CAPI burst node; the cluster-autoscaler powers it down
when nothing needs it. A permanently-Running GPU pod would pin it on, so the
Deployment ships **`replicas: 0`** and ArgoCD ignores `/spec/replicas`
(`clusters/ocp/values.yaml`) — scale-ups are never reverted.

```bash
# Start it — a pending GPU pod triggers the autoscaler to boot casval.
oc -n comfyui scale deploy/comfyui --replicas=1

# Stop it when done so casval can power off.
oc -n comfyui scale deploy/comfyui --replicas=0
```

First start on an empty PVC copies the image-bundled ComfyUI into `/root`
(the PVC mount) and warms caches — the generous `startupProbe` allows up to
~15 min before liveness can act.

## GPU

- Requests/limits **`nvidia.com/gpu: 1`** — one of casval's two GPUs. The
  second stays free for llmkube (hermes qwen35-2b). ComfyUI is single-GPU per
  process: to use both, either bump to `2` plus the ComfyUI-MultiGPU custom
  node, or run a second instance.
- GPU metrics come from the existing DCGM exporter dashboards.

## Storage layout

One 300Gi RWO PVC (`freenas-nvmeof-ssd-csi`) mounted at `/root` — the image's
runner home. Everything ComfyUI writes lives under it:

```
/root/ComfyUI/models/<type>/   checkpoints, loras, vae, controlnet, upscale_models, ...
/root/ComfyUI/input/           uploaded images
/root/ComfyUI/output/          generated images
/root/ComfyUI/custom_nodes/    ComfyUI-Manager + installed nodes
/root/user-scripts/            optional set-proxy.sh / pre-start.sh hooks
```

### Getting models onto the PVC

- Sideload from a workstation into the running pod:
  ```bash
  oc -n comfyui rsync ./my-model.safetensors \
    comfyui-<pod>:/root/ComfyUI/models/checkpoints/
  # or: oc -n comfyui cp ./my-model.safetensors comfyui-<pod>:/root/ComfyUI/models/checkpoints/
  ```
- Or use ComfyUI-Manager's model downloader from the UI.

## Security context

Runs under OpenShift **restricted-v2** with an arbitrary namespace UID — no SCC
changes, no ServiceAccount RoleBinding. The image hardcodes `/root` as its home
and writes everything there; mounting the PVC at `/root` makes that tree
fsGroup-owned and group-writable, so the assigned UID can write it. `HOME` is
set to `/root` because the arbitrary UID has no `/etc/passwd` home. No
`runAsUser`/`fsGroup` is pinned — the SCC assigns them (pinned values break on
namespace recreation).

Verified empirically with rootless podman before writing this: the image starts
under a non-root UID it doesn't expect (no passwd entry, GID 0, writable `/root`)
and reaches ComfyUI's HTTP server — see the PR body for the command and output.
