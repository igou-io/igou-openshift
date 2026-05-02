# llmkube

Deploys the [LLMKube](https://github.com/defilantech/LLMKube) operator via Helm (chart v0.7.5) and a
Qwen3.6-35B-A3B inference workload targeting the casval burst baremetal node.

## Directory layout

```
applications/llmkube/
├── kustomization.yaml                    # Helm chart + inline values + CR references
├── llmkube-system-namespace.yaml         # Namespace
├── qwen3-35b-a3b-model.yaml             # Model CR (downloads GGUF from HuggingFace)
└── qwen3-35b-a3b-inferenceservice.yaml  # InferenceService CR (deploys llama.cpp server)
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
