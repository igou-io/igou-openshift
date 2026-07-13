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

- Requests/limits **`nvidia.com/gpu: 2`** — **both** of casval's GPUs back one
  ComfyUI process. ComfyUI core is single-GPU per process and execution stays
  sequential; the [ComfyUI-MultiGPU](https://github.com/pollockjj/ComfyUI-MultiGPU)
  custom node spreads a model's **components** across the two cards for VRAM
  headroom — e.g. UNet on `cuda:0`, CLIP/VAE on `cuda:1`, with DisTorch layer
  offload — so bigger models fit than either 16 GB card holds alone.
- **Contention**: claiming both GPUs means llmkube's casval-hosted models (e.g.
  `qwen3-35b`) **cannot run concurrently** with ComfyUI. Scale comfyui to `0`
  before starting them (and vice-versa).
- ComfyUI-MultiGPU is auto-installed on first boot by the `pre-start.sh` hook
  (see below) — a SHA-pinned `git clone`, zero extra pip deps. It auto-discovers
  both cards via `torch.cuda.device_count()`; **do not** set `--cuda-device` in
  `CLI_ARGS` or it only sees one.
- **Bumping the node**: it has no upstream release tags and Renovate can't manage
  a raw `git clone`, so the pin lives in
  `comfyui-user-scripts-configmap.yaml` (`MULTIGPU_PIN`). Edit that SHA to
  update; the next pod restart re-pins the PVC checkout.
- GPU metrics come from the existing DCGM exporter dashboards.

## Storage layout

Two RWO PVCs, split by access pattern:

- **`comfyui-data`** — 300Gi on `freenas-nvmeof-ssd-csi` (fast ssd pool),
  mounted at `/root`. The app home: the ComfyUI app bundle, custom_nodes,
  input/output, user config, and `.cache`/`.local`. 300Gi is oversized for a
  home-only volume (an artifact of the original single-PVC layout) and could be
  reduced on a future clean recreate.
- **`comfyui-models`** — 200Gi on `freenas-nvmeof-cold-csi` (cheaper cold
  pool), mounted at the deeper `/root/ComfyUI/models`. The bulk model weights
  (checkpoints, unets, GGUF, text-encoders, VAEs, LoRAs). Model loads are large
  sequential reads that tolerate the cold pool fine.

The `/root/ComfyUI/models` mount is deeper than the `/root` mount and
**shadows** the ssd copy — intentional, so models never consume ssd space.

```
/root/ComfyUI/models/<type>/   checkpoints, loras, vae, controlnet, upscale_models, ...   [cold PVC]
/root/ComfyUI/input/           uploaded images                                            [ssd PVC]
/root/ComfyUI/output/          generated images                                           [ssd PVC]
/root/ComfyUI/custom_nodes/    ComfyUI-Manager + installed nodes                          [ssd PVC]
/root/user-scripts/            pre-start.sh hook (seeded from ConfigMap each boot)         [ssd PVC]
```

`pre-start.sh` is **not** hand-edited on the PVC. The `seed-user-scripts`
initContainer copies it (`cp -f`) from the `comfyui-user-scripts` ConfigMap onto
the PVC on **every** start, so the ConfigMap in git is the source of truth and
any manual PVC edit is overwritten. The copy is what lets the entrypoint
`chmod +x` the file (a read-only ConfigMap mount would fail that chmod under
`set -e`); it lands owned by the pod's UID because init and main containers share
the SCC-assigned `runAsUser`.

### Getting models onto the PVC

Models land on the `comfyui-models` cold PVC — `/root/ComfyUI/models` in the
pod is that PVC, not the ssd home.

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
