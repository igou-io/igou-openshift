# OpenShift Pipelines as Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up OpenShift Pipelines as Code on the OCP cluster with a Helm-templated per-tenant model, hardened-by-default per-repo namespaces, two onboarding skills, and a smoke-tested first migration of `igou-openshift`'s own `validate.yml`.

**Architecture:** Existing operator Subscription stays. New: a TektonConfig CR that pins behavior (pruner, resolvers, Chains, PaC settings); a Tailscale-Funnel-fronted Service for the PaC controller webhook; ExternalSecrets for the GitHub App + cosign keypair; a `pac-tenant` Helm chart instantiated once at `clusters/ocp/pac-tenants/` whose values.yaml defines the entire CI fleet; two Claude skills (`/scaffold-pac-tenant`, `/convert-gha-workflow`).

**Tech Stack:** OpenShift Pipelines operator, Tekton (Pipelines + Triggers + PaC + Chains), External Secrets Operator + 1Password ClusterSecretStore, ArgoCD app-of-apps, Helm 3, kustomize+helm, kubeconform, yamllint, Tailscale operator, Claude skills (markdown prompts).

**Spec:** `docs/superpowers/specs/2026-05-09-pipelines-as-code-design.md`

**Manual prerequisites the agent cannot do (Phase 0 below flags these as user-action checkpoints):**
- Create the GitHub App on github.com.
- Drop App credentials + cosign keypair into 1Password.
- Edit Tailscale ACL to grant `funnel` to the operator's tag.
- Install the GitHub App on each repo to be onboarded.

---

## Phase 0 — Manual prerequisites (user, not subagent)

These are gates. The plan **stops** here for each step and waits for the user to confirm completion before the dependent tasks proceed.

### Task 0.1: GitHub App created
- [ ] User creates a GitHub App at https://github.com/settings/apps/new with these settings:
  - Name: `ocp-pac-igou` (or similar; the exact name doesn't matter)
  - Homepage URL: `https://github.com/igou-io`
  - Webhook URL: `https://placeholder.example.com` (will be updated after Phase 3)
  - Webhook secret: (generate a 32-byte random string; save it)
  - Permissions: `Checks: Read & Write`, `Contents: Read`, `Issues: Read & Write`, `Metadata: Read`, `Pull requests: Read & Write`
  - Subscribe to events: `Check run`, `Check suite`, `Commit comment`, `Issue comment`, `Pull request`, `Push`
  - Where can this be installed: `Only on this account`
- [ ] User downloads the App's private key (`.pem` file)
- [ ] User notes the App ID (visible on the App settings page)

### Task 0.2: GitHub App credentials in 1Password
- [ ] User creates 1Password item `pac-github-app` in the homelab vault with three fields:
  - `app-id` (the numeric App ID)
  - `private-key` (paste the entire `.pem` file contents, including BEGIN/END lines)
  - `webhook-secret` (the random string from Task 0.1)

### Task 0.3: Cosign signing keypair in 1Password
- [ ] User runs locally: `cosign generate-key-pair` (passphrase prompted, save it)
- [ ] User creates 1Password item `tekton-chains-signing` with three fields:
  - `cosign.key` (contents of `cosign.key`)
  - `cosign.password` (the passphrase)
  - `cosign.pub` (contents of `cosign.pub`)

### Task 0.4: Tailscale ACL updated
- [ ] User edits the tailnet ACL (https://login.tailscale.com/admin/acls) to grant `funnel` to the operator's device tag. Add to `nodeAttrs`:
  ```jsonc
  {
    "target": ["tag:k8s"],
    "attr": ["funnel"]
  }
  ```
  (Verify the actual tag the tailscale-operator uses — check `mcp__kubernetes__resources_get` on the operator's `Connector` or similar; common defaults are `tag:k8s` or `tag:k8s-operator`.)

**Checkpoint:** All four 0.x tasks complete before Phase 1 starts.

---

## Phase 1 — Operator-side resources

Adds the TektonConfig, ExternalSecrets, Funnel Service, and PriorityClass to the existing `components/openshift-pipelines/` component.

### Task 1.1: PriorityClass for low-priority CI pods

**Files:**
- Create: `components/openshift-pipelines/tekton-ci-low-priorityclass.yaml`

- [ ] **Step 1: Write the PriorityClass manifest**

```yaml
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: tekton-ci-low
  annotations:
    argocd.argoproj.io/sync-wave: "10"
value: 100
globalDefault: false
description: PR PipelineRun pods. Preempted under cluster pressure.
preemptionPolicy: PreemptLowerPriority
```

- [ ] **Step 2: Validate the manifest with kubeconform**

Run: `kubeconform -strict -summary components/openshift-pipelines/tekton-ci-low-priorityclass.yaml`
Expected: `Summary: 1 resource found in 1 file - Valid: 1, Invalid: 0, Errors: 0, Skipped: 0`

- [ ] **Step 3: Commit**

```bash
git add components/openshift-pipelines/tekton-ci-low-priorityclass.yaml
git commit -m "Add tekton-ci-low PriorityClass for PR PipelineRun pods"
```

### Task 1.2: TektonConfig CR

**Files:**
- Create: `components/openshift-pipelines/tektonconfig.yaml`

- [ ] **Step 1: Write the TektonConfig manifest**

```yaml
---
apiVersion: operator.tekton.dev/v1alpha1
kind: TektonConfig
metadata:
  name: config
  annotations:
    argocd.argoproj.io/sync-wave: "11"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true,ServerSideApply=true
spec:
  profile: all
  targetNamespace: openshift-pipelines
  pruner:
    disabled: false
    schedule: "0 4 * * *"
    keep: 20
    keep-since: 10080
    resources:
      - pipelinerun
      - taskrun
  pipeline:
    enable-bundles-resolver: true
    enable-cluster-resolver: true
    enable-git-resolver: true
    enable-hub-resolver: true
    default-service-account: pipeline-sa
    default-timeout-minutes: 60
    enable-step-actions: true
    default-pod-template:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      automountServiceAccountToken: false
      enableServiceLinks: false
      priorityClassName: tekton-ci-low
  chain:
    artifacts.taskrun.format: in-toto
    artifacts.taskrun.storage: oci
    artifacts.pipelinerun.format: in-toto
    artifacts.pipelinerun.storage: oci
    artifacts.oci.storage: oci
    transparency.enabled: false
    signers.x509.fulcio.enabled: false
  platforms:
    openshift:
      pipelinesAsCode:
        enable: true
        settings:
          application-name: OpenShift Pipelines (homelab)
          auto-configure-new-github-repo: false
          secret-auto-create: true
          remote-tasks: true
          max-keep-runs: "10"
          enable-cancel-in-progress: "true"
          custom-console-name: OpenShift Console
          custom-console-url: https://console-openshift-console.apps.ocp.igou.systems
          custom-console-url-pr-details: |
            {{.openshift_console_url}}/k8s/ns/{{.namespace}}/tekton.dev~v1~PipelineRun/{{.pr}}
          custom-console-url-pr-tasklog: |
            {{.openshift_console_url}}/k8s/ns/{{.namespace}}/tekton.dev~v1~PipelineRun/{{.pr}}/logs/{{.task}}
```

- [ ] **Step 2: Verify the schema is fetchable** (TektonConfig CRD lives in operator.tekton.dev/v1alpha1 — datreeio/CRDs-catalog has it; if not, kubeconform will skip with `-ignore-missing-schemas`)

Run: `kubeconform -strict -ignore-missing-schemas -summary components/openshift-pipelines/tektonconfig.yaml`
Expected: `Valid: 1` OR `Skipped: 1` (skipped is acceptable; the operator validates on apply).

- [ ] **Step 3: yamllint passes**

Run: `yamllint -c .yamllint components/openshift-pipelines/tektonconfig.yaml`
Expected: no output (clean) or only document-start warnings (already accepted by the project config).

- [ ] **Step 4: Commit**

```bash
git add components/openshift-pipelines/tektonconfig.yaml
git commit -m "Add TektonConfig with PaC, Chains, pruner, and resolver tuning"
```

### Task 1.3: GitHub App ExternalSecret

**Files:**
- Create: `components/openshift-pipelines/pac-github-app-externalsecret.yaml`

- [ ] **Step 1: Verify the existing 1Password ClusterSecretStore name**

Run: `mcp__kubernetes__resources_list` for `external-secrets.io/v1beta1 ClusterSecretStore` and confirm the name is `onepassword`. If different, use that name in step 2.

- [ ] **Step 2: Write the ExternalSecret**

```yaml
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: pipelines-as-code-secret
  namespace: openshift-pipelines
  annotations:
    argocd.argoproj.io/sync-wave: "12"
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: pipelines-as-code-secret
    creationPolicy: Owner
  data:
    - secretKey: github-application-id
      remoteRef:
        key: pac-github-app
        property: app-id
    - secretKey: github-private-key
      remoteRef:
        key: pac-github-app
        property: private-key
    - secretKey: webhook.secret
      remoteRef:
        key: pac-github-app
        property: webhook-secret
```

- [ ] **Step 3: Validate**

Run: `kubeconform -strict -ignore-missing-schemas -summary components/openshift-pipelines/pac-github-app-externalsecret.yaml`
Expected: `Valid: 1` or `Skipped: 1`.

- [ ] **Step 4: Commit**

```bash
git add components/openshift-pipelines/pac-github-app-externalsecret.yaml
git commit -m "Add ExternalSecret for PaC GitHub App credentials"
```

### Task 1.4: Cosign signing ExternalSecret

**Files:**
- Create: `components/openshift-pipelines/chains-signing-externalsecret.yaml`

- [ ] **Step 1: Write the ExternalSecret**

The `tekton-chains` namespace is created by the operator when Chains is enabled (via `profile: all` + `chain:` settings). The ExternalSecret targets that namespace.

```yaml
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: signing-secrets
  namespace: tekton-chains
  annotations:
    argocd.argoproj.io/sync-wave: "12"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: signing-secrets
    creationPolicy: Owner
  data:
    - secretKey: cosign.key
      remoteRef:
        key: tekton-chains-signing
        property: cosign.key
    - secretKey: cosign.password
      remoteRef:
        key: tekton-chains-signing
        property: cosign.password
    - secretKey: cosign.pub
      remoteRef:
        key: tekton-chains-signing
        property: cosign.pub
```

- [ ] **Step 2: Validate**

Run: `kubeconform -strict -ignore-missing-schemas -summary components/openshift-pipelines/chains-signing-externalsecret.yaml`
Expected: `Valid: 1` or `Skipped: 1`.

- [ ] **Step 3: Commit**

```bash
git add components/openshift-pipelines/chains-signing-externalsecret.yaml
git commit -m "Add ExternalSecret for Tekton Chains cosign signing key"
```

### Task 1.5: Funnel Service for PaC controller

**Files:**
- Create: `components/openshift-pipelines/pac-controller-funnel-service.yaml`

- [ ] **Step 1: Verify the live PaC controller Service selector labels**

Run: `mcp__kubernetes__resources_get` for `v1 Service` named `pipelines-as-code-controller` in `openshift-pipelines` namespace (only works after operator reconciles the existing Subscription). Read `.spec.selector` and capture the actual labels — they may differ from the spec's assumption.

If the namespace doesn't exist yet (operator hasn't installed PaC because TektonConfig isn't synced), use the spec's assumed labels (`app.kubernetes.io/name: controller`, `app.kubernetes.io/part-of: pipelines-as-code`) and verify after sync.

- [ ] **Step 2: Write the Funnel Service**

```yaml
---
apiVersion: v1
kind: Service
metadata:
  name: pac-controller-funnel
  namespace: openshift-pipelines
  annotations:
    tailscale.com/expose: "true"
    tailscale.com/funnel: "true"
    tailscale.com/hostname: pac-ocp
    argocd.argoproj.io/sync-wave: "13"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: controller
    app.kubernetes.io/part-of: pipelines-as-code
  ports:
    - name: http
      port: 8080
      targetPort: 8080
      protocol: TCP
```

- [ ] **Step 3: Validate**

Run: `kubeconform -strict -summary components/openshift-pipelines/pac-controller-funnel-service.yaml`
Expected: `Valid: 1`.

- [ ] **Step 4: Commit**

```bash
git add components/openshift-pipelines/pac-controller-funnel-service.yaml
git commit -m "Expose PaC controller via Tailscale Funnel"
```

### Task 1.6: Update component kustomization

**Files:**
- Modify: `components/openshift-pipelines/kustomization.yaml`

- [ ] **Step 1: Read the current file**

Current contents:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- openshift-pipelines-operator-subscription.yaml
```

- [ ] **Step 2: Add all new resources**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - openshift-pipelines-operator-subscription.yaml
  - tekton-ci-low-priorityclass.yaml
  - tektonconfig.yaml
  - pac-github-app-externalsecret.yaml
  - chains-signing-externalsecret.yaml
  - pac-controller-funnel-service.yaml
```

- [ ] **Step 3: Validate the kustomization builds**

Run: `kustomize build --enable-helm components/openshift-pipelines/ > /tmp/pipelines-render.yaml && wc -l /tmp/pipelines-render.yaml`
Expected: 100+ lines. No errors.

- [ ] **Step 4: Validate rendered output with kubeconform**

Run: `kustomize build --enable-helm components/openshift-pipelines/ | kubeconform -strict -ignore-missing-schemas -summary`
Expected: All resources Valid or Skipped (Subscription/TektonConfig may skip due to missing schemas; Service/PriorityClass/ExternalSecret should validate).

- [ ] **Step 5: yamllint passes for the whole component**

Run: `yamllint -c .yamllint components/openshift-pipelines/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add components/openshift-pipelines/kustomization.yaml
git commit -m "Wire new openshift-pipelines resources into kustomization"
```

### Task 1.7: Run repo-wide make test

- [ ] **Step 1: Run all validators**

Run: `make test`
Expected: lint, validate-kustomize, validate-schemas all pass. The new pipelines component appears in the output as `✅ components/openshift-pipelines`.

If any failure: read the error, fix, re-run. Do not commit the fix as a separate task — amend the most recent commit if the failure is in code added in this phase, or fix-forward with a new commit if it's pre-existing.

---

## Phase 2 — pac-tenant Helm chart

Builds the chart at `.helm/charts/pac-tenant/` with templates iterating over a `tenants:` list. Each subtask develops one template + a fixture-based render test.

**Files in this phase:**
- Create: `.helm/charts/pac-tenant/Chart.yaml`
- Create: `.helm/charts/pac-tenant/values.yaml`
- Create: `.helm/charts/pac-tenant/templates/_helpers.tpl`
- Create: `.helm/charts/pac-tenant/templates/namespace.yaml`
- Create: `.helm/charts/pac-tenant/templates/serviceaccount.yaml`
- Create: `.helm/charts/pac-tenant/templates/networkpolicies.yaml`
- Create: `.helm/charts/pac-tenant/templates/resourcequota.yaml`
- Create: `.helm/charts/pac-tenant/templates/limitrange.yaml`
- Create: `.helm/charts/pac-tenant/templates/repository.yaml`
- Create: `.helm/charts/pac-tenant/templates/externalsecrets.yaml`
- Create (test fixture): `.helm/charts/pac-tenant/test-values.yaml` (gitignored or kept; we keep it for repeatable testing)

### Task 2.1: Chart skeleton

- [ ] **Step 1: Create Chart.yaml**

File: `.helm/charts/pac-tenant/Chart.yaml`

```yaml
apiVersion: v2
name: pac-tenant
version: 0.1.0
description: Per-repository OpenShift Pipelines as Code tenant resources — namespace, ServiceAccount, NetworkPolicies, ResourceQuota, LimitRange, Repository CR, and optional ExternalSecrets, defined declaratively as a list in values.tenants.
type: application
kubeVersion: '>=1.28.0'
maintainers:
  - name: David Igou
```

- [ ] **Step 2: Create values.yaml with schema + empty list**

File: `.helm/charts/pac-tenant/values.yaml`

```yaml
---
defaults:
  concurrencyLimit: 2
  cancelInProgress: true

  policy:
    pullRequest:
      - igou-david
    okToTest:
      - igou-david

  quota:
    requests.cpu: "8"
    requests.memory: 16Gi
    limits.cpu: "16"
    limits.memory: 32Gi
    pods: "20"
    persistentvolumeclaims: "5"
    requests.storage: 50Gi

  limitRange:
    defaultRequest:
      cpu: 100m
      memory: 256Mi
    default:
      cpu: 500m
      memory: 1Gi
    max:
      cpu: "4"
      memory: 8Gi

  egressBlockedCIDRs:
    - 10.128.0.0/14
    - 172.30.0.0/16
    - 169.254.169.254/32
    - 192.168.0.0/16
    - 10.0.0.0/8

# tenants is the list of onboarded repositories. Each entry can override
# any field from defaults; unspecified fields inherit defaults.
#
# Schema:
#   - name: <slug used for namespace name>             # required, matches ^[a-z0-9-]+$
#     url:  <full https github URL of the repo>        # required
#     concurrencyLimit: <int>                          # optional, defaults to 2
#     cancelInProgress: <bool>                         # optional
#     policy:
#       pullRequest: [<gh-username>, ...]              # optional
#       okToTest:    [<gh-username>, ...]              # optional; auto-collapsed to pullRequest when secrets present
#     quota: { ... }                                   # optional, full ResourceQuota.spec.hard map
#     limitRange: { ... }                              # optional
#     egressBlockedCIDRs: [<cidr>, ...]                # optional
#     secrets:
#       imagePullSecrets:                              # attached to pipeline-sa.imagePullSecrets
#         - name: <k8s-secret-name>
#           onepasswordItem: <1pwd-item-name>
#       workspaceSecrets:                              # available to PipelineRun via workspace mount
#         - name: <k8s-secret-name>
#           onepasswordItem: <1pwd-item-name>
tenants: []

# Cluster constants — usually no need to override.
clusterSecretStore: onepassword
namespacePrefix: ci-
```

- [ ] **Step 3: Create test-values.yaml fixture (used for render testing throughout Phase 2)**

File: `.helm/charts/pac-tenant/test-values.yaml`

```yaml
---
tenants:
  - name: simple-tenant
    url: https://github.com/igou-io/simple-tenant

  - name: secrets-tenant
    url: https://github.com/igou-io/secrets-tenant
    secrets:
      imagePullSecrets:
        - name: ghcr-readonly
          onepasswordItem: ci-ghcr-readonly
      workspaceSecrets:
        - name: snyk-org-token
          onepasswordItem: ci-snyk-org

  - name: heavy-tenant
    url: https://github.com/igou-io/heavy-tenant
    quota:
      requests.cpu: "16"
      requests.memory: 32Gi
      limits.cpu: "32"
      limits.memory: 64Gi
    concurrencyLimit: 1
```

- [ ] **Step 4: Verify the chart skeleton parses**

Run: `helm lint .helm/charts/pac-tenant/`
Expected: `[INFO] Chart.yaml: ...`, `1 chart(s) linted, 0 chart(s) failed`. (Chart has no templates yet — that's fine.)

- [ ] **Step 5: Commit**

```bash
git add .helm/charts/pac-tenant/Chart.yaml .helm/charts/pac-tenant/values.yaml .helm/charts/pac-tenant/test-values.yaml
git commit -m "Add pac-tenant Helm chart skeleton with values schema"
```

### Task 2.2: _helpers.tpl with merge logic and shared computations

**Files:**
- Create: `.helm/charts/pac-tenant/templates/_helpers.tpl`

- [ ] **Step 1: Write _helpers.tpl**

```yaml
{{/*
pac-tenant.merged — returns the per-tenant config with defaults merged underneath.
Per-tenant values take precedence. Use:
  {{- $cfg := include "pac-tenant.merged" (dict "root" . "tenant" $tenant) | fromYaml -}}
*/}}
{{- define "pac-tenant.merged" -}}
{{- $defaults := deepCopy .root.Values.defaults -}}
{{- $tenant := .tenant -}}
{{- $merged := mergeOverwrite $defaults (deepCopy $tenant) -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
pac-tenant.namespace — derives the namespace name from tenant.name + namespacePrefix.
*/}}
{{- define "pac-tenant.namespace" -}}
{{- printf "%s%s" .root.Values.namespacePrefix .tenant.name -}}
{{- end -}}

{{/*
pac-tenant.hasSecrets — returns "true" if the tenant declares any secrets, "" otherwise.
*/}}
{{- define "pac-tenant.hasSecrets" -}}
{{- $s := .tenant.secrets | default dict -}}
{{- if or (and $s.imagePullSecrets (gt (len $s.imagePullSecrets) 0)) (and $s.workspaceSecrets (gt (len $s.workspaceSecrets) 0)) -}}
true
{{- end -}}
{{- end -}}

{{/*
pac-tenant.okToTest — returns the effective ok-to-test list for a tenant.
If the tenant has any secrets, this collapses to the pullRequest list (no widening allowed).
Otherwise returns the configured okToTest (default merged).
*/}}
{{- define "pac-tenant.okToTest" -}}
{{- $cfg := include "pac-tenant.merged" (dict "root" .root "tenant" .tenant) | fromYaml -}}
{{- if include "pac-tenant.hasSecrets" (dict "tenant" .tenant) -}}
{{- toYaml $cfg.policy.pullRequest -}}
{{- else -}}
{{- toYaml $cfg.policy.okToTest -}}
{{- end -}}
{{- end -}}

{{/*
pac-tenant.labels — labels applied to every resource the chart produces.
*/}}
{{- define "pac-tenant.labels" -}}
app.kubernetes.io/managed-by: helm
app.kubernetes.io/part-of: pac-tenants
igou.systems/pac-tenant: {{ .tenant.name | quote }}
{{- end -}}
```

- [ ] **Step 2: Verify chart still lints**

Run: `helm lint .helm/charts/pac-tenant/`
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add .helm/charts/pac-tenant/templates/_helpers.tpl
git commit -m "Add _helpers.tpl with merge, namespace, ok-to-test logic"
```

### Task 2.3: namespace.yaml template

**Files:**
- Create: `.helm/charts/pac-tenant/templates/namespace.yaml`

- [ ] **Step 1: Write the template**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
---
apiVersion: v1
kind: Namespace
metadata:
  name: {{ $ns | quote }}
  labels:
    igou.systems/tenant-type: pac-ci
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
  annotations:
    openshift.io/description: "PaC CI tenant for {{ $tenant.url }}"
    argocd.argoproj.io/sync-wave: "20"
{{- end }}
```

- [ ] **Step 2: Render with the test fixture**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/namespace.yaml > /tmp/ns.yaml && cat /tmp/ns.yaml`
Expected: 3 Namespace documents (`ci-simple-tenant`, `ci-secrets-tenant`, `ci-heavy-tenant`), each with the PSA labels and the part-of/managed-by labels.

- [ ] **Step 3: Validate the render**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/namespace.yaml | kubeconform -strict -summary`
Expected: `Valid: 3`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/pac-tenant/templates/namespace.yaml
git commit -m "Add namespace template to pac-tenant chart"
```

### Task 2.4: serviceaccount.yaml template

**Files:**
- Create: `.helm/charts/pac-tenant/templates/serviceaccount.yaml`

- [ ] **Step 1: Write the template**

The SA is `pipeline-sa` per tenant. If the tenant declares `secrets.imagePullSecrets`, those names are appended to `imagePullSecrets`. `automountServiceAccountToken: false` always.

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $imagePullSecrets := list }}
{{- if $tenant.secrets }}
{{- range $secret := ($tenant.secrets.imagePullSecrets | default list) }}
{{- $imagePullSecrets = append $imagePullSecrets (dict "name" $secret.name) }}
{{- end }}
{{- end }}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pipeline-sa
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
automountServiceAccountToken: false
{{- if $imagePullSecrets }}
imagePullSecrets:
{{- toYaml $imagePullSecrets | nindent 2 }}
{{- end }}
{{- end }}
```

- [ ] **Step 2: Render and inspect**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/serviceaccount.yaml`
Expected:
- `simple-tenant` SA: no imagePullSecrets stanza.
- `secrets-tenant` SA: `imagePullSecrets: [{name: ghcr-readonly}]`.
- `heavy-tenant` SA: no imagePullSecrets stanza.
- All three: `automountServiceAccountToken: false`.

- [ ] **Step 3: Validate**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/serviceaccount.yaml | kubeconform -strict -summary`
Expected: `Valid: 3`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/pac-tenant/templates/serviceaccount.yaml
git commit -m "Add pipeline-sa template with optional imagePullSecrets"
```

### Task 2.5: networkpolicies.yaml template

**Files:**
- Create: `.helm/charts/pac-tenant/templates/networkpolicies.yaml`

- [ ] **Step 1: Write the template — three NetworkPolicies per tenant**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "pac-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
# Default-deny all ingress and egress.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
# Allow DNS to openshift-dns.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
---
# Allow external HTTPS/HTTP egress, block intra-cluster + LAN.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-egress
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
{{- range $cidr := $cfg.egressBlockedCIDRs }}
              - {{ $cidr | quote }}
{{- end }}
      ports:
        - port: 443
          protocol: TCP
        - port: 80
          protocol: TCP
{{- end }}
```

- [ ] **Step 2: Render and inspect**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/networkpolicies.yaml | grep -c '^kind: NetworkPolicy'`
Expected: `9` (3 NetworkPolicies × 3 tenants).

- [ ] **Step 3: Spot-check that egressBlockedCIDRs are inserted correctly**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/networkpolicies.yaml | grep -c '192.168.0.0/16'`
Expected: `3` (one per tenant; defaults applied).

- [ ] **Step 4: Validate**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/networkpolicies.yaml | kubeconform -strict -summary`
Expected: `Valid: 9`.

- [ ] **Step 5: Commit**

```bash
git add .helm/charts/pac-tenant/templates/networkpolicies.yaml
git commit -m "Add NetworkPolicy template (default-deny + DNS + external)"
```

### Task 2.6: resourcequota.yaml template

**Files:**
- Create: `.helm/charts/pac-tenant/templates/resourcequota.yaml`

- [ ] **Step 1: Write the template**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "pac-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: ci-quota
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  hard:
{{- range $key, $value := $cfg.quota }}
    {{ $key }}: {{ $value | quote }}
{{- end }}
{{- end }}
```

- [ ] **Step 2: Render and verify per-tenant overrides**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/resourcequota.yaml`
Expected:
- `simple-tenant` and `secrets-tenant` show defaults (`requests.cpu: "8"`).
- `heavy-tenant` shows override (`requests.cpu: "16"`, `limits.memory: 64Gi`).

- [ ] **Step 3: Validate**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/resourcequota.yaml | kubeconform -strict -summary`
Expected: `Valid: 3`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/pac-tenant/templates/resourcequota.yaml
git commit -m "Add ResourceQuota template with per-tenant override support"
```

### Task 2.7: limitrange.yaml template

**Files:**
- Create: `.helm/charts/pac-tenant/templates/limitrange.yaml`

- [ ] **Step 1: Write the template**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "pac-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
---
apiVersion: v1
kind: LimitRange
metadata:
  name: ci-limits
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  limits:
    - type: Container
      defaultRequest:
{{- toYaml $cfg.limitRange.defaultRequest | nindent 8 }}
      default:
{{- toYaml $cfg.limitRange.default | nindent 8 }}
      max:
{{- toYaml $cfg.limitRange.max | nindent 8 }}
{{- end }}
```

- [ ] **Step 2: Render**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/limitrange.yaml`
Expected: 3 LimitRange resources, defaults applied for all (no override tenant in fixture).

- [ ] **Step 3: Validate**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/limitrange.yaml | kubeconform -strict -summary`
Expected: `Valid: 3`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/pac-tenant/templates/limitrange.yaml
git commit -m "Add LimitRange template"
```

### Task 2.8: repository.yaml template (PaC Repository CR)

**Files:**
- Create: `.helm/charts/pac-tenant/templates/repository.yaml`

- [ ] **Step 1: Write the template**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- $cfg := include "pac-tenant.merged" (dict "root" $ "tenant" $tenant) | fromYaml }}
{{- $okToTest := include "pac-tenant.okToTest" (dict "root" $ "tenant" $tenant) | fromYamlArray }}
---
apiVersion: pipelinesascode.tekton.dev/v1alpha1
kind: Repository
metadata:
  name: {{ $tenant.name | quote }}
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "22"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  url: {{ $tenant.url | quote }}
  concurrency_limit: {{ $cfg.concurrencyLimit }}
  policy:
    pull_request:
{{- range $user := $cfg.policy.pullRequest }}
      - {{ $user | quote }}
{{- end }}
    ok_to_test:
{{- range $user := $okToTest }}
      - {{ $user | quote }}
{{- end }}
  settings:
    cancel-in-progress: {{ $cfg.cancelInProgress }}
{{- end }}
```

- [ ] **Step 2: Render and verify ok-to-test collapse for the secrets tenant**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/repository.yaml`
Expected:
- `simple-tenant` Repository: `pull_request: [igou-david]`, `ok_to_test: [igou-david]`.
- `secrets-tenant` Repository: `pull_request: [igou-david]`, `ok_to_test: [igou-david]` (same — collapse rule applied because secrets present).
- `heavy-tenant` Repository: `concurrency_limit: 1`.

- [ ] **Step 3: Validate**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/repository.yaml | kubeconform -strict -ignore-missing-schemas -summary`
Expected: `Valid: 3` or `Skipped: 3` (Repository CRD may not be in datreeio catalog).

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/pac-tenant/templates/repository.yaml
git commit -m "Add Repository template with auto-collapsed ok-to-test"
```

### Task 2.9: externalsecrets.yaml template

**Files:**
- Create: `.helm/charts/pac-tenant/templates/externalsecrets.yaml`

- [ ] **Step 1: Write the template — one ES per imagePullSecret + workspaceSecret**

```yaml
{{- range $tenant := .Values.tenants }}
{{- $ns := include "pac-tenant.namespace" (dict "root" $ "tenant" $tenant) }}
{{- if $tenant.secrets }}

{{- range $secret := ($tenant.secrets.imagePullSecrets | default list) }}
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ $secret.name | quote }}
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: {{ $.Values.clusterSecretStore | quote }}
  target:
    name: {{ $secret.name | quote }}
    creationPolicy: Owner
    template:
      type: kubernetes.io/dockerconfigjson
      data:
        .dockerconfigjson: "{{ `{{ .dockerconfigjson }}` }}"
  data:
    - secretKey: dockerconfigjson
      remoteRef:
        key: {{ $secret.onepasswordItem | quote }}
        property: dockerconfigjson
{{- end }}

{{- range $secret := ($tenant.secrets.workspaceSecrets | default list) }}
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ $secret.name | quote }}
  namespace: {{ $ns | quote }}
  annotations:
    argocd.argoproj.io/sync-wave: "21"
  labels:
    {{- include "pac-tenant.labels" (dict "tenant" $tenant) | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: {{ $.Values.clusterSecretStore | quote }}
  target:
    name: {{ $secret.name | quote }}
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: {{ $secret.onepasswordItem | quote }}
{{- end }}

{{- end }}
{{- end }}
```

- [ ] **Step 2: Render and verify**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/externalsecrets.yaml`
Expected:
- `simple-tenant` and `heavy-tenant` produce no output (no `secrets:` block).
- `secrets-tenant` produces 2 ExternalSecrets:
  - `ghcr-readonly` (type dockerconfigjson, points at 1pwd item `ci-ghcr-readonly`).
  - `snyk-org-token` (type Opaque via dataFrom.extract, points at `ci-snyk-org`).

- [ ] **Step 3: Validate**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml --show-only templates/externalsecrets.yaml | kubeconform -strict -ignore-missing-schemas -summary`
Expected: `Valid: 2` or `Skipped: 2`.

- [ ] **Step 4: Commit**

```bash
git add .helm/charts/pac-tenant/templates/externalsecrets.yaml
git commit -m "Add ExternalSecret template for imagePullSecrets and workspaceSecrets"
```

### Task 2.10: End-to-end chart render test

- [ ] **Step 1: Render the entire chart with the test fixture**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml > /tmp/all.yaml && wc -l /tmp/all.yaml`
Expected: 200+ lines, no errors.

- [ ] **Step 2: Resource counts**

Run: `grep -c '^kind:' /tmp/all.yaml`
Expected: `17` (3 Namespace + 3 SA + 9 NetworkPolicy + 3 ResourceQuota + 3 LimitRange + 3 Repository + 2 ExternalSecret = 26... wait, recount).

Verify the breakdown:
```bash
grep '^kind:' /tmp/all.yaml | sort | uniq -c
```
Expected:
```
   2 ExternalSecret
   3 LimitRange
   3 Namespace
   9 NetworkPolicy
   3 Repository
   3 ResourceQuota
   3 ServiceAccount
```
Total: 26 resources.

- [ ] **Step 3: Render with empty tenants (the production-bootstrap case)**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ > /tmp/empty.yaml && grep -c '^kind:' /tmp/empty.yaml || true`
Expected: `0` (empty `tenants: []` from default values renders no resources).

- [ ] **Step 4: Validate the full render with kubeconform**

Run: `helm template pac-tenants .helm/charts/pac-tenant/ -f .helm/charts/pac-tenant/test-values.yaml | kubeconform -strict -ignore-missing-schemas -summary`
Expected: All Valid or Skipped, zero Invalid.

- [ ] **Step 5: helm lint**

Run: `helm lint .helm/charts/pac-tenant/`
Expected: passes.

- [ ] **Step 6: yamllint the chart**

Run: `yamllint -c .yamllint .helm/charts/pac-tenant/`
Expected: clean (the chart itself is plain YAML; templates are excluded by Helm convention but yamllint may complain about Go template syntax — if so, add `.helm/charts/pac-tenant/templates/` to `.yamllint` ignore list).

If yamllint complains about templates: edit `.yamllint` and add `.helm/charts/*/templates/` to the `ignore:` list. Commit that change separately.

- [ ] **Step 7: Commit (if test-values.yaml or .yamllint changed)**

If no changes are needed (clean state from Tasks 2.1–2.9), skip this step.

```bash
git add .yamllint  # if modified
git commit -m "Exclude helm chart templates from yamllint"
```

---

## Phase 3 — Cluster instantiation

### Task 3.1: Create clusters/ocp/pac-tenants/ kustomization

**Files:**
- Create: `clusters/ocp/pac-tenants/kustomization.yaml`
- Create: `clusters/ocp/pac-tenants/values.yaml`

- [ ] **Step 1: Create kustomization.yaml that wraps the chart**

Path: `clusters/ocp/pac-tenants/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
helmCharts:
  - name: pac-tenant
    path: ../../../.helm/charts/pac-tenant
    releaseName: pac-tenants
    valuesFile: values.yaml
    includeCRDs: false
```

- [ ] **Step 2: Create empty cluster values**

Path: `clusters/ocp/pac-tenants/values.yaml`

```yaml
---
# PaC tenants for the OCP cluster.
# Schema and defaults: see .helm/charts/pac-tenant/values.yaml
#
# Tenants are added/removed via the /scaffold-pac-tenant skill.
tenants: []
```

- [ ] **Step 3: Build and verify**

Run: `kustomize build --enable-helm clusters/ocp/pac-tenants/`
Expected: empty output (no tenants → no resources).

- [ ] **Step 4: Commit**

```bash
git add clusters/ocp/pac-tenants/
git commit -m "Add empty pac-tenants instantiation for OCP cluster"
```

### Task 3.2: Wire pac-tenants into the cluster app-of-apps

**Files:**
- Modify: `clusters/ocp/values.yaml`

- [ ] **Step 1: Read the current `clusters/ocp/values.yaml`**

The file uses the app-of-apps pattern with one entry per app. New entry goes alongside `openshift-pipelines`.

- [ ] **Step 2: Add the pac-tenants entry**

Append after the `openshift-pipelines:` block (find that block first, place this immediately after, preserving alphabetical-ish ordering since neighboring entries already mix it):

```yaml
  pac-tenants:
    annotations:
      argocd.argoproj.io/sync-wave: '20'
    source:
      path: clusters/ocp/pac-tenants
```

- [ ] **Step 3: Validate the full app-of-apps render**

Run: `make validate-kustomize`
Expected: all kustomizations build successfully, including `clusters/ocp/pac-tenants` (will appear in the output).

- [ ] **Step 4: Validate schemas**

Run: `make validate-schemas`
Expected: clean (the empty render produces nothing for kubeconform to fail on).

- [ ] **Step 5: Commit**

```bash
git add clusters/ocp/values.yaml
git commit -m "Wire pac-tenants Application into OCP app-of-apps"
```

---

## Phase 4 — Makefile updates

### Task 4.1: Add `lint-helm` target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add a new lint-helm target after `lint:`**

Insert after the `lint:` target (line 6 in current file):

```makefile
.PHONY: lint-helm
lint-helm: ## Lint all Helm charts under .helm/charts/
	@find $(REPO_ROOT)/.helm/charts -mindepth 1 -maxdepth 1 -type d -print0 | \
		xargs -0 -I{} sh -c 'echo "--- helm lint: {}"; helm lint "{}"'
```

- [ ] **Step 2: Update the `test:` target to include lint-helm**

Change:
```makefile
.PHONY: test
test: lint validate-kustomize validate-schemas ## Run all tests (lint, validate-kustomize, validate-schemas)
```

To:
```makefile
.PHONY: test
test: lint lint-helm validate-kustomize validate-schemas ## Run all tests (lint, lint-helm, validate-kustomize, validate-schemas)
```

- [ ] **Step 3: Verify the new target works**

Run: `make lint-helm`
Expected: each chart in `.helm/charts/` (argocd-app-of-app, ocp-base-config, pac-tenant) is linted and reports `1 chart(s) linted, 0 chart(s) failed`.

- [ ] **Step 4: Verify make test still passes end-to-end**

Run: `make test`
Expected: all four sub-targets pass.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "Add make lint-helm target and chain into make test"
```

---

## Phase 5 — Skills

The skills follow this repo's existing convention: each lives at `.claude/skills/<name>/SKILL.md`, with YAML frontmatter (`name`, `description`, `argument-hint`, `disable-model-invocation: true`, `allowed-tools`).

### Task 5.1: /scaffold-pac-tenant skill

**Files:**
- Create: `.claude/skills/scaffold-pac-tenant/SKILL.md`

- [ ] **Step 1: Write the skill prompt**

```markdown
---
name: scaffold-pac-tenant
description: Add a new PaC tenant entry to clusters/ocp/pac-tenants/values.yaml. Verifies the GitHub repo exists, derives a name from the URL, applies defaults, supports optional --imagePullSecret and --workspaceSecret flags. Validates the rendered chart with helm template + kubeconform before reporting completion. Does NOT commit — user reviews diffs first.
argument-hint: <github-url-or-owner/repo> [--imagePullSecret name:1pwd-item] [--workspaceSecret name:1pwd-item ...]
disable-model-invocation: true
allowed-tools: Read, Edit, Bash(gh repo view *), Bash(yq *), Bash(helm template *), Bash(kubeconform *), Bash(grep *), Bash(cat *), Bash(ls *)
---

# Scaffold a PaC tenant

Add one tenant entry to `clusters/ocp/pac-tenants/values.yaml`. The entry will be picked up by ArgoCD on next sync of the `pac-tenants` Application.

## Parsing arguments

`$ARGUMENTS` may contain:
- A GitHub URL (`https://github.com/<owner>/<repo>`) or `<owner>/<repo>` shorthand. Required.
- Zero or more `--imagePullSecret <name>:<1pwd-item>` flags.
- Zero or more `--workspaceSecret <name>:<1pwd-item>` flags.

Examples:
- `https://github.com/igou-io/igou-openshift`
- `igou-io/llmkube --imagePullSecret ghcr-readonly:ci-ghcr-readonly`
- `igou-io/foo --workspaceSecret snyk:ci-snyk-org --workspaceSecret codecov:ci-codecov`

## Step 1: Resolve repo

If the input is a shorthand `owner/repo`, expand to `https://github.com/owner/repo`.

Derive `<tenant-name>` from the repo path (last segment of the URL, lowercase, with non-`[a-z0-9-]` characters replaced by `-`). Confirm the derived name with the user before proceeding.

Verify the repo exists:
```bash
gh repo view <owner>/<repo> --json name,visibility,isPrivate
```
Refuse to proceed if the command fails.

## Step 2: Check existing values.yaml

Read `clusters/ocp/pac-tenants/values.yaml`. If a tenant with the derived name already exists under `tenants:`, abort with a clear error: "Tenant `<name>` is already defined at line <N> — use Edit to modify it."

## Step 3: Build the new entry

Construct the entry. Minimum:
```yaml
- name: <tenant-name>
  url: <full-https-url>
```

If `--imagePullSecret name:1pwd-item` flags were passed, add a `secrets.imagePullSecrets:` list. If `--workspaceSecret` flags, add `secrets.workspaceSecrets:`.

Tell the user explicitly: "This tenant has secrets — `okToTest` will be auto-collapsed to the `pullRequest` allowlist by the chart. Adding contributors will require a kustomization commit, not a PR comment."

## Step 4: Insert the entry alphabetically

Edit `clusters/ocp/pac-tenants/values.yaml`. The `tenants:` list should be ordered alphabetically by `name` to keep diffs stable. Insert the new entry at the correct position.

If the list is currently empty (`tenants: []`), replace with `tenants:` on its own line followed by the new entry.

## Step 5: Validate the rendered chart

Run from the repo root:
```bash
helm template pac-tenants .helm/charts/pac-tenant/ -f clusters/ocp/pac-tenants/values.yaml > /tmp/pac-render.yaml
echo "Rendered $(grep -c '^kind:' /tmp/pac-render.yaml) resources"
kubeconform -strict -ignore-missing-schemas -summary /tmp/pac-render.yaml
```

If kubeconform reports any Invalid resources, abort and report the errors. Do not leave a broken values.yaml in place; revert the edit.

## Step 6: Report completion

Print to the user:
- Path of the file modified.
- Diff of the change (use `git diff` on the file).
- Reminder: "GitHub App must be installed on this repo. Install URL: <App-page-from-github>/installations/new"
- Reminder: "Run `/convert-gha-workflow` against the target repo to generate `.tekton/pull-request.yaml`."
- "User must review and commit. Skill does not auto-commit."
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/scaffold-pac-tenant/
git commit -m "Add scaffold-pac-tenant skill"
```

### Task 5.2: /convert-gha-workflow mappings.yaml

**Files:**
- Create: `.claude/skills/convert-gha-workflow/mappings.yaml`

- [ ] **Step 1: Write the mapping table**

```yaml
---
# GitHub Actions → Tekton mapping table.
# Used by the /convert-gha-workflow skill.
#
# Format:
#   <action-name>:
#     mode: image | hub-task | inline | drop | flag-publish | flag-unmapped
#     image: <image-ref>          # for mode=image
#     hubTask: <task-name>        # for mode=hub-task
#     inlineSnippet: |            # for mode=inline (Tekton step yaml fragment)
#       ...
#     note: <human-readable note shown in migration report>

actions/checkout:
  mode: drop
  note: Checkout is implicit — PaC pre-populates the source workspace with the PR HEAD.

actions/setup-go:
  mode: image
  imageTemplate: docker.io/golang:{{ .with.go-version | default "1.22" }}
  note: setup-go becomes a container image; the rest of the steps in the same job inherit it.

actions/setup-node:
  mode: image
  imageTemplate: docker.io/node:{{ .with.node-version | default "20" }}-bookworm

actions/setup-python:
  mode: image
  imageTemplate: docker.io/python:{{ .with.python-version | default "3.12" }}

actions/setup-java:
  mode: image
  imageTemplate: docker.io/eclipse-temurin:{{ .with.java-version | default "21" }}

actions/cache:
  mode: flag-unmapped
  note: Cache via Tekton workspace PVC + cache-key script. Manual translation needed.

docker/setup-buildx-action:
  mode: drop
  note: buildah handles cross-platform natively.

docker/setup-qemu-action:
  mode: flag-unmapped
  note: Multi-arch buildah is non-trivial. Out of scope for v1; flag for manual.

docker/login-action:
  mode: flag-imagePullSecret
  note: Add the registry credential to the tenant's secrets.imagePullSecrets in values.yaml.

docker/build-push-action:
  mode: hub-task
  hubTask: buildah
  note: Use Hub task buildah with --isolation=chroot. Push step is publish; flag for GHA-stays.

docker/metadata-action:
  mode: inline
  inlineSnippet: |
    - name: derive-tags
      image: docker.io/alpine/git:latest
      script: |
        SHA=$(params.revision)
        SHORT=${SHA:0:7}
        REF=$(params.git-ref)
        echo -n "$SHORT" > $(results.short-sha.path)
        echo -n "$REF"   > $(results.ref.path)
  note: Replaces docker/metadata-action — exposes short-sha and ref as Tekton results.

golangci/golangci-lint-action:
  mode: image
  imageTemplate: docker.io/golangci/golangci-lint:v1-alpine
  note: golangci-lint runs from a published image.

pre-commit/action:
  mode: inline
  inlineSnippet: |
    - name: pre-commit
      image: docker.io/python:3.12
      workingDir: $(workspaces.source.path)
      script: |
        pip install pre-commit
        pre-commit run --all-files

azure/setup-helm:
  mode: image
  imageTemplate: docker.io/alpine/helm:{{ .with.version | default "3.16" }}

imranismail/setup-kustomize:
  mode: image
  imageTemplate: registry.k8s.io/kustomize/kustomize:v5.4.3

yannh/kubeconform:
  mode: inline
  inlineSnippet: |
    - name: kubeconform
      image: docker.io/alpine:3.20
      workingDir: $(workspaces.source.path)
      script: |
        wget -qO- https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-linux-amd64.tar.gz | tar xz -C /usr/local/bin
        find . -name 'kustomization.yaml' -exec dirname {} \; | xargs -I{} kubeconform -strict {}

actions/github-script:
  mode: flag-unmapped
  note: Would need GitHub App API call from the cluster pod. Out of scope for v1 — leave in GHA.

actions/upload-artifact:
  mode: flag-unmapped
  note: No native artifact storage in Tekton. Either persist via workspace PVC or skip.

redhat-actions/podman-login:
  mode: flag-imagePullSecret
  note: Same as docker/login-action — add the registry credential to tenant secrets.

redhat-actions/push-to-registry:
  mode: flag-publish
  note: This is a publish step. Stays in GHA, scoped to push:main.

bjw-s-labs/action-changed-files:
  mode: inline
  inlineSnippet: |
    - name: changed-files
      image: docker.io/alpine/git:latest
      workingDir: $(workspaces.source.path)
      script: |
        git diff --name-only $(params.base-revision)...$(params.revision) > $(results.changed-files.path)

anchore/sbom-action:
  mode: hub-task
  hubTask: syft-sbom
  note: Generate SBOM with syft (Hub task) or inline syft on docker.io/anchore/syft.

devcontainers/ci:
  mode: flag-unmapped
  note: Recursive devcontainer build. Stays in GHA.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/convert-gha-workflow/mappings.yaml
git commit -m "Add convert-gha-workflow mapping table"
```

### Task 5.3: /convert-gha-workflow skill

**Files:**
- Create: `.claude/skills/convert-gha-workflow/SKILL.md`

- [ ] **Step 1: Write the skill prompt**

```markdown
---
name: convert-gha-workflow
description: Convert a target repo's .github/workflows/*.yml into .tekton/*.yaml for OpenShift Pipelines as Code, prune the GHA workflows to publish-on-main only, and emit a secret-migration report. Operates on a target repo path; refuses to run on igou-openshift unless explicitly --target=. is passed.
argument-hint: [path-to-target-repo] [--auto|-y]
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash(yq *), Bash(find *), Bash(ls *), Bash(cat *), Bash(git *)
---

# Convert GitHub Actions workflows to Tekton PipelineRuns

Reads `.github/workflows/*.yml` in the target repo, categorizes each job, generates `.tekton/pull-request.yaml`, prunes the GHA workflow to publish-on-main, and emits a migration report.

## Parsing arguments

`$ARGUMENTS` may contain:
- A path to the target repo. If omitted, use `$PWD`.
- `--auto` or `-y` to skip confirmations (use cautiously).

If `$PWD` is the `igou-openshift` repo, refuse unless the user explicitly passed `--target=.` — otherwise the user is probably running the skill from the wrong directory.

## Step 1: Discover workflows

```bash
find <target>/.github/workflows -maxdepth 1 \( -name '*.yml' -o -name '*.yaml' \) -type f
```

For each workflow file, parse with `yq '.'` and extract:
- Top-level `on:` triggers (push branches, pull_request events, workflow_dispatch).
- Each `jobs.<name>`: its `runs-on`, `steps`, `strategy.matrix`, `if:`, `env:`, secret references (`${{ secrets.X }}`).
- Every `uses:` reference (the action name and the `with:` block).
- Every `run:` block (verbatim shell).

## Step 2: Categorize each job

| Bucket | Heuristics | Destination |
|--------|------------|-------------|
| PR-checkable | name contains lint/format/test/check, or all steps are read-only | `.tekton/pull-request.yaml` |
| Build, no publish | `go build`, `npm build`, image build with `push: false` | `.tekton/pull-request.yaml` |
| Publish | docker push, npm publish, github release, deploy ssh, pages, helm push | stays in GHA |
| Unsupported | self-hosted runner, github-script, devcontainers/ci | flagged, stays in GHA |

If unclear, ask the user per job.

## Step 3: Load mappings

Read `.claude/skills/convert-gha-workflow/mappings.yaml`. For each `uses:` reference, look up the action (without `@version`); fall back to `flag-unmapped` mode if not found.

## Step 4: Generate .tekton/pull-request.yaml

For each PR-bucket job, generate a Tekton Task in a `pipelineSpec.tasks[]` list. Use this skeleton:

```yaml
---
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  name: pr
  annotations:
    pipelinesascode.tekton.dev/on-event: "[pull_request]"
    pipelinesascode.tekton.dev/on-target-branch: "[main]"
    pipelinesascode.tekton.dev/max-keep-runs: "5"
spec:
  params:
    - name: revision
      value: "{{ revision }}"
    - name: repo-url
      value: "{{ repo_url }}"
    - name: git-ref
      value: "{{ source_branch }}"
  pipelineSpec:
    params:
      - name: revision
        type: string
      - name: repo-url
        type: string
      - name: git-ref
        type: string
    workspaces:
      - name: source
    tasks:
      # ... one entry per migrated job ...
  workspaces:
    - name: source
      volumeClaimTemplate:
        spec:
          accessModes: [ReadWriteOnce]
          resources:
            requests:
              storage: 1Gi
          storageClassName: freenas-nvmeof-ssd-csi
```

Each task in `tasks[]`:
```yaml
- name: <gha-job-name>
  workspaces:
    - name: source
      workspace: source
  taskSpec:
    workspaces:
      - name: source
    params:
      - name: revision
        type: string
    steps:
      # ... transformed steps ...
```

For each step in the GHA job:
- If `uses:` matches a `mode: drop` entry — skip the step entirely.
- If `uses:` matches `mode: image` — set the *next* step's `image:` to the rendered image template, drop this step.
- If `uses:` matches `mode: inline` — inline the snippet from mappings.yaml.
- If `uses:` matches `mode: hub-task` — emit a `taskRef.resolver: hub` reference.
- If `uses:` matches `mode: flag-imagePullSecret` — emit a comment `# imagePullSecret required: <action> — add to tenant.secrets.imagePullSecrets` and skip the step.
- If `uses:` matches `mode: flag-publish` or `mode: flag-unmapped` — emit a comment `# UNMAPPED ACTION: <action> — implement manually` and a stub step.
- If the step is `run:` — wrap in a Tekton step:
  ```yaml
  - name: <derived-name>
    image: <inherited-or-default>
    workingDir: $(workspaces.source.path)
    script: |
      <verbatim-run-content>
  ```

For matrix strategies (Tekton 0.50+):
```yaml
- name: <job-name>
  matrix:
    params:
      - name: <matrix-key>
        value: [<v1>, <v2>, ...]
  ...
```

Inside the task, parameterize the image: `image: docker.io/golang:$(params.go-version)`.

## Step 5: Prune the original GHA workflow

For each workflow file:
- If ALL jobs were migrated to PaC: rename the file to `<base>-publish.yml` and either delete it (if empty after pruning) or leave a stub.
- If SOME jobs were migrated: remove the migrated jobs from the file, restrict `on:` to `push: branches: [main]` only.
- If NO jobs were migrated (all publish): leave the file alone but restrict `on:` to `push: branches: [main]` (it should already be).

## Step 6: Generate .tekton/README.md

Write a brief `.tekton/README.md` summarizing what was migrated, when, and how to test:

```markdown
# Tekton PipelineRuns

This directory is consumed by OpenShift Pipelines as Code on the homelab cluster.

- `pull-request.yaml` runs on every PR opened against `main`.
- Status reported back to GitHub via the Checks API.

To test locally, install `tkn pac` CLI and run `tkn pac resolve -f .tekton/pull-request.yaml`.

Migrated from `.github/workflows/<file>.yml` on <date> by /convert-gha-workflow.
```

## Step 7: Print migration report

Print to terminal:
```
Migration of <repo>:
  ✓ Job '<name>' → .tekton/pull-request.yaml (Task: <name>)
  ↩ Job '<name>' → stays in .github/workflows/<file>.yml (push:main only)
  ⚠ Job '<name>' uses <action> — flagged: <reason>

Secret migration:
  <SECRET>  → tenant.secrets.<mode> (1Password: <suggested-item>)

Next steps:
  1. Review .tekton/pull-request.yaml for unmapped steps (search 'UNMAPPED ACTION')
  2. In igou-openshift: /scaffold-pac-tenant <owner>/<repo>  (if not already onboarded)
  3. Add secret entries to clusters/ocp/pac-tenants/values.yaml under tenant '<name>'
  4. Add secrets to 1Password if not already present
  5. Commit + push both repos; verify PaC fires on first PR.
```

The skill does NOT commit, NOT push, and NOT install the GitHub App. User does those after reviewing diffs.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/convert-gha-workflow/SKILL.md
git commit -m "Add convert-gha-workflow skill"
```

---

## Phase 6 — Smoke test (gated on Phase 0)

Onboards `igou-openshift` itself as the first PaC tenant, migrates `validate.yml`, and verifies the round-trip.

### Task 6.1: Confirm Phase 0 prerequisites

- [ ] **Step 1: Check 1Password items exist**

Run: `op item get pac-github-app --vault <homelab-vault>`
Expected: returns the item with `app-id`, `private-key`, `webhook-secret` fields.

Run: `op item get tekton-chains-signing --vault <homelab-vault>`
Expected: returns the item with `cosign.key`, `cosign.password`, `cosign.pub` fields.

- [ ] **Step 2: Confirm Tailscale ACL has funnel attr**

Ask the user to confirm the ACL was edited per Task 0.4.

- [ ] **Step 3: Confirm GitHub App exists**

Ask the user for the App installation URL (https://github.com/settings/apps/<app-name>).

If any prerequisite is missing, stop and surface it. Do not proceed.

### Task 6.2: Wait for Phase 1 sync to complete on cluster

The component changes from Phase 1 should be auto-synced by ArgoCD.

- [ ] **Step 1: Verify ArgoCD synced openshift-pipelines**

Run: `argocd app get openshift-pipelines -o json | jq '.status.sync.status, .status.health.status'`
Expected: `"Synced"`, `"Healthy"`.

If not synced: `argocd app sync openshift-pipelines --prune` (with user authorization).

- [ ] **Step 2: Verify TektonConfig is reconciled on the cluster**

Run via MCP: `mcp__kubernetes__resources_get` for `operator.tekton.dev/v1alpha1 TektonConfig` named `config`.
Expected: `.status.conditions[?(@.type=="Ready")].status` is `True`.

- [ ] **Step 3: Verify pipelines-as-code-secret exists in openshift-pipelines**

Run via MCP: `mcp__kubernetes__resources_get` for `v1 Secret` named `pipelines-as-code-secret` in `openshift-pipelines`.
Expected: present, with three keys.

- [ ] **Step 4: Verify Funnel hostname is up**

Run via MCP: get `Service/pac-controller-funnel` annotations. Look for `tailscale.com/operator-status: ready` or similar.
Expected: ready, with the URL `pac-ocp.<tailnet>.ts.net` resolvable via `dig +short pac-ocp.<tailnet>.ts.net`.

If any of these fail: troubleshoot before continuing. Common failure: webhook secret mismatch; verify the 1Password value matches what was set in the GitHub App.

### Task 6.3: Update GitHub App webhook URL

- [ ] **Step 1: Ask user to update the webhook URL**

Tell the user: "GitHub App's webhook URL needs to be updated to `https://pac-ocp.<tailnet>.ts.net/`. Go to https://github.com/settings/apps/<app-name> → Webhook → URL field. Save changes."

Wait for user confirmation.

### Task 6.4: Install GitHub App on igou-openshift

- [ ] **Step 1: Ask user to install the App**

Tell the user: "Install the GitHub App on the `igou-io/igou-openshift` repo. Go to the App's installation URL (find it on the App settings page → Install App) → Install only on `igou-io/igou-openshift` for the smoke test."

Wait for user confirmation.

### Task 6.5: Onboard igou-openshift via /scaffold-pac-tenant

- [ ] **Step 1: Run the skill**

User runs: `/scaffold-pac-tenant igou-io/igou-openshift`

Expected: skill adds an entry to `clusters/ocp/pac-tenants/values.yaml`, runs `helm template` + `kubeconform`, prints diff.

- [ ] **Step 2: User reviews + commits**

User reviews the diff, commits with a message like:
```
Onboard igou-openshift as first PaC tenant
```
and pushes.

- [ ] **Step 3: Verify ArgoCD picks up the change**

Run: `argocd app sync pac-tenants --prune=false` (after user authorization).
Expected: namespace `ci-igou-openshift`, `pipeline-sa`, three NetworkPolicies, ResourceQuota, LimitRange, Repository CR all created.

- [ ] **Step 4: Verify the namespace looks right**

Run via MCP: `mcp__kubernetes__resources_list` for `NetworkPolicy` in `ci-igou-openshift`.
Expected: 3 entries (default-deny-all, allow-dns, allow-external-egress).

### Task 6.6: Migrate igou-openshift's validate.yml

This skill operates on the target repo. Since the target repo IS `igou-openshift`, the skill must be invoked with the explicit `--target=.` flag.

- [ ] **Step 1: Run the skill**

User runs: `/convert-gha-workflow . --target=.`

Expected: skill writes:
- `.tekton/pull-request.yaml` containing PipelineRun with three tasks (lint, validate-kustomize, validate-schemas) — analogous to the three GHA jobs.
- `.tekton/README.md`.
- Modifies `.github/workflows/validate.yml`: nothing to prune in the strict sense (validate.yml has no publish work), but trigger restricted to `push: branches: [main]` (drop `pull_request`).

- [ ] **Step 2: User reviews diffs**

The user inspects `.tekton/pull-request.yaml`. Particular check: the `imranismail/setup-kustomize` and `azure/setup-helm` actions must have been mapped to the correct images.

- [ ] **Step 3: User opens a PR**

User creates a branch, commits, and opens a PR against `main`.

### Task 6.7: Verify PaC fires and reports green

- [ ] **Step 1: Watch the PaC controller logs**

Run via MCP: `mcp__kubernetes__pods_log` for the `pipelines-as-code-controller` pod in `openshift-pipelines`.
Expected: webhook received, signature validated, PipelineRun created in `ci-igou-openshift`.

- [ ] **Step 2: Verify PipelineRun appears in tenant namespace**

Run via MCP: `mcp__kubernetes__resources_list` for `tekton.dev/v1 PipelineRun` in `ci-igou-openshift`.
Expected: one PipelineRun, status condition `Succeeded`.

- [ ] **Step 3: Verify TaskRun pod hardening**

Run via MCP: `mcp__kubernetes__pods_get` for one of the TaskRun pods in `ci-igou-openshift` (find via `mcp__kubernetes__pods_list_in_namespace`).
Verify the spec contains:
- `automountServiceAccountToken: false`
- `securityContext.runAsNonRoot: true`
- `priorityClassName: tekton-ci-low`
- `enableServiceLinks: false`

- [ ] **Step 4: Verify NetworkPolicy enforcement**

Spawn a debug pod in `ci-igou-openshift` (with user authorization) and try to reach `192.168.1.1:22`:
```bash
oc -n ci-igou-openshift run nettest --rm -it --image=alpine:3.20 --restart=Never -- sh -c 'apk add --no-cache busybox-extras; nc -zv 192.168.1.1 22'
```
Expected: hangs / times out (NetworkPolicy blocks 192.168.0.0/16).

Then test that github.com is reachable:
```bash
oc -n ci-igou-openshift run nettest --rm -it --image=alpine:3.20 --restart=Never -- sh -c 'wget -qO- https://api.github.com/zen'
```
Expected: returns a string (egress to public internet works).

- [ ] **Step 5: Verify GitHub PR shows the check**

Open the PR in GitHub. Expected: check named "OpenShift Pipelines (homelab) / pr" reports green.

- [ ] **Step 6: Merge the PR (user decision)**

If everything is green, the user merges the PR. After merge, `validate.yml` should run on `push: main` via GitHub Actions (still works) and PaC should NOT fire (because the PR is closed/merged).

---

## Phase 7 — Onboard remaining repos (incremental, post-smoke-test)

After the smoke test, onboard each of the four remaining active-CI repos in sequence. Each is a tiny task: scaffold the tenant, convert the workflow, open a PR, verify, merge.

### Task 7.1: igou-inventory (lint.yml)

Repeat Tasks 6.4–6.7 with `igou-io/igou-inventory`. Workflow uses `actions/setup-python` and pre-commit (likely) — both are mapped.

### Task 7.2: igou-ansible (lint.yml + syntax-check.yml)

Repeat for `igou-io/igou-ansible`. Two PR-side workflows; the three EE-build publishers stay in GHA.

### Task 7.3: igou-containers (build-containers.yml — split)

This one is mixed. The user must explicitly review which parts of `build-containers.yml` are PR-side (build, no push) vs publish (build + push).

The skill will categorize as best it can; user should adjust before committing.

---

## Self-review

**Spec coverage:** Each spec section maps to tasks:
- Architecture overview → Phase 1 + Phase 2 + Phase 3 (the manifests)
- Per-repo namespace hardening → Tasks 2.3–2.7 (chart templates implementing it)
- Operator install + TektonConfig → Phase 1 (Tasks 1.1–1.7)
- Tailscale Funnel exposure → Task 1.5 + 1.6 + Phase 0.4
- Per-tenant onboarding chart → Phase 2
- Secret access → Task 2.4 (SA + imagePullSecrets), Task 2.9 (ExternalSecrets), Task 2.8 (auto-collapsed okToTest)
- Conversion skill → Phase 5 (Tasks 5.1–5.3)
- Rollout sequence → Phases ordered to match
- Validation → Phase 4 (Makefile)
- Smoke test → Phase 6

**Placeholder scan:** No "TBD"; all code blocks complete; commands have expected outputs.

**Type consistency:** SA name `pipeline-sa` is consistent across TektonConfig (`default-service-account`), chart template, and skill prompts. Namespace prefix `ci-` consistent. Resource names (`default-deny-all`, `allow-dns`, `allow-external-egress`, `ci-quota`, `ci-limits`) consistent across spec, plan, and chart templates.

**Open verification points the agent must handle at runtime (not plan defects):**
- Cluster pod/service CIDRs (Task 1.x notes verification command).
- Tailscale operator's actual device tag (Task 0.4 notes verification).
- PaC controller Service selector labels (Task 1.5 notes verification).
- 1Password ClusterSecretStore name (Task 1.3 notes verification).
- TektonConfig schema availability in datreeio catalog (Task 1.2 notes graceful skip).
