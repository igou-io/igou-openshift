# Pull Request Review

## Open Branches / PRs Reviewed

Date: 2026-03-20

The following remote branches were reviewed:

---

### 1. `renovate/external-secrets-2.x` — Bump external-secrets Helm chart to v2.2.0

**File changed:** `components/external-secrets-operator/kustomization.yaml`

**Change:** `version: 2.0.1` → `version: 2.2.0`

**Assessment: ✅ APPROVE**

- Minor/patch version bump within the 2.x series — low risk.
- No values changes; only the Helm chart version is updated.
- The image tags in `valuesInline` remain pinned to digest
  `v1.1.0@sha256:33b96dad...` (set separately), so the actual running
  image does not change unless the chart's appVersion is used.
- **Note:** The pinned image tag `v1.1.0` in `valuesInline` may be stale
  relative to chart v2.2.0. Verify the chart's `appVersion` for v2.2.0 and
  consider aligning the image tag with the new chart's default if they diverge.

---

### 2. `renovate/minecraft-5.x` — Bump minecraft Helm chart to v5.1.2

**File changed:** `applications/minecraft-server/kustomization.yaml`

**Change:** `version: 4.26.4` → `version: 5.1.2`

**Assessment: ⚠️ REVIEW CAREFULLY — Major version bump**

- This is a **major version bump** (4.x → 5.x) from the
  [itzg/minecraft-server-charts](https://github.com/itzg/minecraft-server-charts).
  Major chart version bumps can include breaking changes to value schemas,
  new required fields, or removed defaults.
- The values in the `kustomization.yaml` are extensive (StatefulSet config,
  backup config, security contexts, sidecars, etc.). These should be validated
  against the v5 chart's `values.yaml` schema.
- Key areas to verify against v5 chart changelog:
  - `sidecarContainers` field (was `extraContainers` in some versions)
  - `mcbackup` subchart values structure
  - `minecraftServer.version: "1.21.8"` — ensure the new chart supports this MC version
  - StatefulSet behavior changes
- The existing security context configuration (`runAsNonRoot: true`,
  `readOnlyRootFilesystem: true`) may need adjustment if the chart adds new
  containers.
- **Recommend:** Check the v5 chart release notes/CHANGELOG before merging.

---

### 3. `renovate/ollama-1.x` — Bump ollama Helm chart to v1.52.0

**File changed:** `applications/ollama/kustomization.yaml`

**Change:** `version: 1.45.0` → `version: 1.52.0`

**Assessment: ✅ APPROVE**

- Minor version bump within 1.x — low risk.
- The Docker image tag is already explicitly pinned to
  `0.18.1@sha256:5949ec04...` in `valuesInline`, so the running image is
  unchanged regardless of chart `appVersion`.
- GPU configuration (`nvidia.com/gpu`, `type: nvidia`), model pulls
  (`deepseek-r1:14b`, `qwen2.5-coder:14b`, etc.), and persistent volume
  settings are unchanged.
- No values structure changes expected for a minor bump.

---

### 4. `renovate/pin-dependencies` — Pin dependencies

**Assessment: ⚠️ SKIP / INVESTIGATE**

- This branch has **no common merge base with `main`** — it appears to be
  from an independent or very old diverged history.
- Contains dozens of commits including infrastructure changes unrelated to
  the current `main` tree.
- Cannot be merged into `main` without significant conflict resolution.
- This branch should be investigated for whether it represents
  in-progress work that needs to be rebased, or can be closed.

---

### 5. `revert-23-renovate/clustersecretstore-1.x` & `revert-25-renovate/externalsecret-1.x`

**Assessment: ✅ ALREADY MERGED**

- Both revert branches are present in the `main` commit history
  (via merged PRs #23, #25, #29).
- These branches are stale and can be deleted.

---

## Summary Table

| Branch | Change | Recommendation |
|---|---|---|
| `renovate/external-secrets-2.x` | external-secrets: 2.0.1 → 2.2.0 | ✅ Approve (check image tag alignment) |
| `renovate/minecraft-5.x` | minecraft chart: 4.26.4 → 5.1.2 | ⚠️ Review changelog before merging |
| `renovate/ollama-1.x` | ollama chart: 1.45.0 → 1.52.0 | ✅ Approve |
| `renovate/pin-dependencies` | Many infra changes, no merge base | ⚠️ Investigate / skip |
| `revert-23-*` / `revert-25-*` | Already merged | 🗑️ Delete stale branches |
