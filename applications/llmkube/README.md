# llmkube

Deploys the [LLMKube](https://github.com/defilantech/LLMKube) operator via Helm (chart v0.7.5) and a
Qwen3.6-35B-A3B inference workload targeting the casval burst baremetal node.

## Directory layout

```
applications/llmkube/
├── kustomization.yaml                    # Helm chart + inline values + CR references
├── llmkube-system-namespace.yaml         # Namespace
├── qwen3-35b-a3b-model.yaml             # Model CR (downloads GGUF from HuggingFace)
├── qwen3-35b-a3b-inferenceservice.yaml  # InferenceService CR (deploys llama.cpp server)
└── qwen3-35b-a3b-route.yaml             # OpenShift Route exposing the model externally
```

## CRD Reference

API group: `inference.llmkube.dev` / version: `v1alpha1`

---

### Model

Defines where a model comes from and what hardware it targets. The operator
downloads the GGUF file into the shared model-cache PVC so it can be reused
across InferenceService pods.

```yaml
apiVersion: inference.llmkube.dev/v1alpha1
kind: Model
metadata:
  name: <string>
  namespace: <string>
spec:
  # --- Source ---
  source: <string>          # REQUIRED. HTTP/HTTPS URL, file path, or pvc:// URI pointing to the GGUF file.
  sha256: <string>          # Optional SHA-256 hex digest for integrity verification (64 chars).

  # --- Format & quantization ---
  format: <string>          # gguf | mlx | safetensors | pytorch | custom  (default: gguf)
  quantization: <string>    # Quantization label recorded in status (e.g. Q4_K_M, Q8_0, F16).
                            # Informational — the actual quant is baked into the GGUF file.

  # --- Hardware ---
  hardware:
    accelerator: <string>   # cpu | metal | cuda | rocm  (default: cpu)
    gpu:
      enabled: <bool>
      count: <int>          # 0–8. Number of GPUs to use.
      vendor: <string>      # nvidia | amd | intel  (default: nvidia)
      memory: <string>      # e.g. "16Gi". Optional VRAM hint.
      layers: <int>         # Layers to offload to GPU. -1 = auto (all that fit).
      sharding:
        strategy: <string>  # layer | tensor | row | pipeline | none  (default: layer)
        layerSplit: []      # Per-GPU layer counts for manual splits.
    memoryBudget: <string>  # Absolute system RAM limit (e.g. "64Gi").
    memoryFraction: <float> # Fraction of system RAM to use (0.0–1.0).

  # --- Pod resource requests for the download init container ---
  resources:
    cpu: <string>           # e.g. "2"
    memory: <string>        # e.g. "8Gi"
```

**Status fields**

| Field | Description |
|---|---|
| `phase` | `Pending` / `Downloading` / `Copying` / `Ready` / `Failed` |
| `size` | Downloaded file size |
| `path` | Path inside the model-cache PVC |
| `cacheKey` | SHA-256 prefix used as the cache directory name |
| `sha256` | Computed hash after download |
| `acceleratorReady` | Whether hardware acceleration is confirmed available |
| `gguf.*` | Metadata extracted from the GGUF header (architecture, layers, context length, etc.) |
| `conditions` | Standard Kubernetes conditions: `Available`, `Progressing`, `Degraded` |

---

### InferenceService

Deploys one or more pods running the inference runtime (llama.cpp by default)
against a referenced `Model`. Manages an HPA if autoscaling is configured and
exposes an OpenAI-compatible HTTP endpoint.

```yaml
apiVersion: inference.llmkube.dev/v1alpha1
kind: InferenceService
metadata:
  name: <string>
  namespace: <string>
spec:
  # --- Model reference ---
  modelRef: <string>        # REQUIRED. Name of a Model CR in the same namespace.

  # --- Runtime ---
  runtime: <string>         # llamacpp | vllm | tgi | personaplex | generic  (default: llamacpp)
  image: <string>           # Override the default runtime image.
  command: []               # Override entrypoint (generic runtime only).
  args: []                  # Override arguments (generic runtime only).
  env: []                   # Extra environment variables (standard Kubernetes EnvVar).
  containerPort: <int>      # 1–65535  (default: 8080)

  # --- Scaling ---
  replicas: <int>           # 0–10 desired pods  (default: 1)
  autoscaling:
    minReplicas: <int>      # 1–10  (default: 1)
    maxReplicas: <int>      # 1–100  REQUIRED when autoscaling is set
    metrics:
      - type: <string>      # Pods | Resource
        name: <string>
        targetAverageValue: <string>        # for type: Pods
        targetAverageUtilization: <int>     # for type: Resource

  # --- Endpoint ---
  endpoint:
    port: <int>             # 1–65535  (default: 8080)
    path: <string>          # Default: /v1/chat/completions
    type: <string>          # ClusterIP | NodePort | LoadBalancer  (default: ClusterIP)

  # --- Resource requirements ---
  resources:
    gpu: <int>              # 0–8. nvidia.com/gpu units requested per pod.
    cpu: <string>           # e.g. "4"
    memory: <string>        # e.g. "16Gi". System RAM.
    hostMemory: <string>    # System RAM for hybrid CPU/GPU offloading (e.g. "64Gi").
    gpuMemory: <string>     # VRAM limit hint (e.g. "24Gi").

  # --- Scheduling ---
  nodeSelector: {}          # Standard Kubernetes node label selector.
  tolerations: []           # Standard Kubernetes tolerations.
  priority: <string>        # critical | high | normal | low | batch  (default: normal)
  priorityClassName: <string> # Override with a custom PriorityClass name.

  # --- Security ---
  imagePullSecrets: []
  podSecurityContext: {}    # Standard Kubernetes PodSecurityContext.
  securityContext: {}       # Standard Kubernetes SecurityContext.

  # --- llama.cpp tuning ---
  contextSize: <int>        # 128–2,097,152 tokens. Context window size.
  parallelSlots: <int>      # 1–64. Concurrent request slots.
  flashAttention: <bool>    # Enable FlashAttention kernel.
  jinja: <bool>             # Enable Jinja2 chat template rendering (required for thinking models).
  batchSize: <int>          # 1–16384. Prompt evaluation batch size.
  uBatchSize: <int>         # Micro-batch size for decoding.
  cacheTypeK: <string>      # KV cache key type: f16 | f32 | q8_0 | q4_0 | q4_1 | q5_0 | q5_1 | iq4_nl
  cacheTypeV: <string>      # KV cache value type: same options as cacheTypeK
  cacheTypeCustomK: <string> # Custom KV cache type for keys (TurboQuant, etc.)
  cacheTypeCustomV: <string> # Custom KV cache type for values
  moeCPUOffload: <bool>     # Offload MoE expert layers to system RAM (reduces VRAM usage).
  moeCPULayers: <int>       # Number of MoE expert layers to offload (0 = all).
  noKvOffload: <bool>       # Keep KV cache in system RAM instead of VRAM.
  noWarmup: <bool>          # Skip the startup warmup inference pass.
  reasoningBudget: <int>    # Max tokens for the thinking phase (thinking/reasoning models).
  reasoningBudgetMessage: <string> # Message returned when the reasoning budget is exhausted.
  metadataOverrides: []     # GGUF metadata overrides in "key=type:value" format.
  tensorOverrides: []       # Tensor placement overrides.
  extraArgs: []             # Additional raw CLI arguments passed to the server.
  skipModelInit: <bool>     # Skip the model-downloader init container (model already cached).

  # --- Health probe overrides ---
  probeOverrides:
    startup: {}             # Standard Kubernetes Probe.
    liveness: {}
    readiness: {}

  # --- vLLM-specific config ---
  vllmConfig:
    tensorParallelSize: <int>       # GPUs for tensor parallelism.
    maxModelLen: <int>              # Max context length.
    quantization: <string>          # awq | gptq | squeezellm | fp8 | nvfp4 | compressed-tensors
    dtype: <string>                 # auto | float16 | bfloat16
    kvCacheDtype: <string>          # auto | fp8_e5m2 | fp8_e4m3  (default: auto)
    kvCacheCustomDtype: <string>
    enablePrefixCaching: <bool>
    enableChunkedPrefill: <bool>
    maxNumBatchedTokens: <int>      # Min 512.
    attentionBackend: <string>      # FLASH_ATTN | FLASHINFER | XFORMERS | torch_sdpa
    enableExpertParallel: <bool>    # Distribute MoE experts across GPUs.
    speculative:
      enabled: <bool>
      model: <string>               # Draft Model CR name.
      numSpeculativeTokens: <int>   # 1–16  (default: 4)
    hfTokenSecretRef:
      name: <string>
      key: <string>

  # --- TGI-specific config ---
  tgiConfig:
    quantize: <string>              # bitsandbytes | gptq | awq | eetq
    maxInputLength: <int>
    maxTotalTokens: <int>
    dtype: <string>                 # float16 | bfloat16
    hfTokenSecretRef:
      name: <string>
      key: <string>

  # --- PersonaPlex (Moshi)-specific config ---
  personaPlexConfig:
    quantize4Bit: <bool>            # NF4 4-bit quantization.
    cpuOffload: <bool>              # Offload weights to CPU.
    hfTokenSecretRef:
      name: <string>
      key: <string>
```

**Status fields**

| Field | Description |
|---|---|
| `phase` | `Pending` / `Creating` / `Progressing` / `Ready` / `WaitingForGPU` / `Failed` |
| `readyReplicas` | Number of ready inference pods |
| `desiredReplicas` | Configured replica count |
| `endpoint` | ClusterIP service URL |
| `modelReady` | Whether the referenced Model CR is in the `Ready` phase |
| `schedulingStatus` | Short reason when pods cannot be scheduled (e.g. `InsufficientGPU`) |
| `schedulingMessage` | Human-readable scheduling detail |
| `queuePosition` | Position in the pending queue (0 = not queued) |
| `waitingFor` | Resource constraint string (e.g. `nvidia.com/gpu: 2`) |
| `effectivePriority` | Resolved numeric priority after class lookup |
| `conditions` | Standard Kubernetes conditions: `Available`, `Progressing`, `Degraded` |

---

## Scaling and ArgoCD replica management

`InferenceService` CRs in this repo default to `replicas: 0`. Scale up manually
when you want to run inference:

```bash
oc patch inferenceservice qwen3-35b-a3b -n llmkube-system \
  --type merge -p '{"spec":{"replicas":1}}'
```

### Preventing ArgoCD from resetting replicas

ArgoCD's self-heal loop will revert `spec.replicas` back to `0` on the next
sync unless you tell it to ignore that field. The `argocd-app-of-app` chart
used by this cluster supports per-application `ignoreDifferences`; add the
following to the llmkube entry in `clusters/ocp/values.yaml`:

```yaml
applications:
  llmkube:
    # ... existing fields ...
    ignoreDifferences:
      - group: inference.llmkube.dev
        kind: InferenceService
        jsonPointers:
          - /spec/replicas
```

ArgoCD also needs `RespectIgnoreDifferences=true` in the Application's
`syncOptions` for the ignore to take effect during a sync (not just for diff
display). This option is already set as a global default in the cluster's
`values.yaml`, so no extra work is needed.

With both in place ArgoCD will:
- Show the CR as **Synced** even when live replicas differ from git
- Not overwrite `spec.replicas` during a sync or self-heal

The same pattern is already used for the casval `MachineSet` replicas (managed
by the cluster-autoscaler) in the `cluster-api` application entry.

---

## Scheduling on casval

The casval baremetal MachineSet (`clusters/ocp/cluster-api/casval-worker-machineset.yaml`)
provisions a single burst node with a `workload=burst:NoSchedule` taint and the
`node-role.kubernetes.io/burst` label. The cluster autoscaler scales it from 0→1
when a matching Pending pod appears and back to 0 once it drains.

All InferenceService CRs that should run on casval must include:

```yaml
spec:
  nodeSelector:
    node-role.kubernetes.io/burst: ""
  tolerations:
    - key: workload
      operator: Equal
      value: burst
      effect: NoSchedule
```

Casval node capacity (used for autoscaler simulation):

| Resource | Value |
|---|---|
| CPU | 192 cores |
| Memory | 428 Gi |
| `nvidia.com/gpu` | 8 slots (2 physical × 4 time-sliced) |

---

## Using the Qwen3.6-35B-A3B endpoint with opencode

The `qwen3-35b-a3b` Route exposes the OpenAI-compatible llama.cpp server at:

```
https://qwen3-35b-a3b-llmkube-system.apps.ocp.igou.systems/v1
```

(verify with `oc get route qwen3-35b-a3b -n llmkube-system -o jsonpath='{.spec.host}'`)

### Server-side tuning summary

The InferenceService is configured for the model + hardware combination
(2x RTX 4060 Ti 16 GiB, MoE A3B Q4_K_M):

| Setting | Value | Why |
|---|---|---|
| `flashAttention` | `true` | Required to enable V-cache quantization; ~30% attention VRAM savings |
| `cacheTypeK` / `cacheTypeV` | `q8_0` / `q8_0` | Essentially lossless, ~halves KV VRAM, lets us run 64k ctx |
| `contextSize` | `65536` | Fits comfortably in remaining VRAM after 20 GiB weights + Q8 KV |
| `jinja` | `true` | Qwen3.6 chat template is jinja-only (thinking tags) |
| `parallelSlots` | `1` | Single coding-assistant user; more slots split ctx across slots |
| `batchSize` / `uBatchSize` | `2048` / `512` | llama.cpp defaults, balanced for prompt eval throughput |
| `--split-mode layer` + `--tensor-split 1,1` | (operator-default) | `row` mode hurts MoE; equal layer split across both GPUs |
| `--reasoning-format deepseek` | extraArgs | Parses `<think>` into OpenAI `reasoning_content` field |
| Sampler | `temp=0.7 top_p=0.8 top_k=20 min_p=0 presence=1.5` | Unsloth Qwen3 non-thinking defaults |

### opencode configuration

Recommended invocation is via the hardened `opencode` container shipped from
`igou-containers` and launched by `opencode-run` (in `igou-devenv/bin/`). The
launcher bind-mounts `~/.config/opencode/` from the host into the container,
so you only need to write the config once.

Add the following to your `~/.config/opencode/opencode.jsonc` (or `opencode.jsonc`
at the project root). It uses the OpenAI-compatible adapter as documented at
[opencode.ai/docs/providers/#llamacpp](https://opencode.ai/docs/providers/#llamacpp):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "llama.cpp": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "llama-server (igou.systems)",
      "options": {
        "baseURL": "https://qwen3-35b-a3b-llmkube-system.apps.ocp.igou.systems/v1"
      },
      "models": {
        "qwen3.6-35b-a3b": {
          "name": "Qwen3.6-35B-A3B (local)",
          "limit": { "context": 65536, "output": 32768 },
          "reasoning": true,
          "tools": true,
          "temperature": true,
          "options": { "temperature": 0.7, "top_p": 0.8 }
        }
      }
    }
  }
}
```

Key points:
- The model id (`qwen3.6-35b-a3b`) must match the `--alias` set in
  `qwen3-35b-a3b-inferenceservice.yaml` `extraArgs`.
- `reasoning: true` paired with the server's `--reasoning-format deepseek`
  causes opencode to render `<think>...</think>` blocks as collapsible reasoning
  rather than leaking them into the chat output.
- `tools: true` enables function/tool calling, which Qwen3.6 supports.
- The Route uses `edge` TLS termination — opencode talks plain HTTPS to the
  router, the router talks HTTP to the in-cluster service.
- The Route has a `haproxy.router.openshift.io/timeout: 10m` annotation so
  long thinking-mode generations don't hit the default 30s router timeout.

### Launching opencode

From inside the devcontainer:

```bash
make -C ~/igou-devenv opencode-build   # one-time (or after a Containerfile change)
opencode-run                           # launches against the configured provider
opencode-run --shell                   # drop into bash inside the container
```

`opencode-run` is on `$PATH` via `~/bin` (see igou-devenv `post-create.sh`). It
applies the same hardening profile as `claude-run` / `cursor-run`
(`--cap-drop=ALL`, noexec /tmp, rootless `--userns=keep-id`) and resolves
1Password environments via `-e ENV` for cluster credentials. See
`igou-devenv/README.md` for the full opencode container reference.

### Quick sanity check

```bash
ROUTE=$(oc get route qwen3-35b-a3b -n llmkube-system -o jsonpath='{.spec.host}')
curl -sS "https://${ROUTE}/v1/models" | jq
curl -sS "https://${ROUTE}/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d '{"model":"qwen3.6-35b-a3b","messages":[{"role":"user","content":"hello"}]}' | jq
```
