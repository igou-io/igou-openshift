---
name: scaffold-component-olm
description: Scaffold a new OLM operator component in components/ following repo conventions. Generates Namespace, OperatorGroup, Subscription, kustomization.yaml, and optionally ExternalSecret. Use when adding a new OLM operator to the platform.
argument-hint: <component-name>
disable-model-invocation: true
allowed-tools: Read, Write, Bash(kustomize build *), Bash(oc get packagemanifest *), Bash(ls *), Bash(cat *)
---

# Scaffold a new OLM operator component

Scaffold a new OLM operator component under `components/` following the exact conventions of this repo.

## Component name

The component to scaffold is: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask the user for the component name before proceeding.

## Step 1: PackageManifest lookup

Before asking the user anything, attempt to resolve the package from the live cluster.

The `package` name defaults to `component-name` (from `$ARGUMENTS`). Run:

```bash
oc get packagemanifest <package> -n openshift-marketplace -o jsonpath='{.status.defaultChannel} {.status.catalogSource} {.status.channels[*].name}'
```

**If the lookup succeeds**, extract:
- `default-channel` — use as the `channel` default
- `catalog-source` — use as the `catalog-source` default (e.g. `redhat-operators`)
- `available-channels` — list to show the user

Report back: "Found package `<package>` in `<catalog-source>`. Default channel: `<default-channel>`. Available channels: `<list>`."

**If the lookup fails** (exit non-zero or empty output), the package name may differ from the component name, or the catalog may not be synced yet. Note this and ask the user to supply the correct package name, then retry the lookup with the corrected name before proceeding.

## Step 2: Gather remaining information

With channel and catalog-source pre-filled from the lookup (or supplied by the user after a failed lookup), ask for only the remaining unknowns in a single message:

| Field | Description | Default |
|-------|-------------|---------|
| `component-name` | Directory name under `components/` | from `$ARGUMENTS` |
| `namespace` | Kubernetes namespace for the operator | same as `component-name` |
| `package` | OLM package name (goes in `spec.name` of Subscription) | from lookup or `component-name` |
| `channel` | OLM channel | from PackageManifest default, or ask if lookup failed |
| `catalog-source` | Catalog source name | from PackageManifest, or ask if lookup failed |

**Channel validation**: if the user overrides the default channel, verify it exists in `available-channels` from the PackageManifest lookup. If it does not appear in the list, warn the user ("Channel `<channel>` was not found in the available channels for this package: `<list>`. Proceed anyway?") and wait for confirmation before continuing.
| `operator-group-scope` | `OwnNamespace` (targetNamespaces = [namespace]) or `AllNamespaces` (omit targetNamespaces) | `OwnNamespace` |
| `sync-wave` | ArgoCD sync-wave for the Namespace (OperatorGroup/Subscription will be wave+1) | `8` |
| `skip-dry-run` | Add `SkipDryRunOnMissingResource=true` commonAnnotation (`yes`/`no`) — needed when the operator installs its own CRDs | `no` |
| `external-secret` | Whether to scaffold an ExternalSecret stub (`yes`/`no`) | `no` |
| `external-secret-key` | 1Password item key (only if external-secret=yes) | — |

Do not ask for fields already resolved from the PackageManifest unless the user needs to override them.

## Step 3: File generation

Create directory `components/<component-name>/` and generate the files below. Apply all conventions exactly.

### Conventions (apply to every file)
- 2-space indentation
- Files start with `---`
- YAML 1.2 booleans: `true`/`false` only
- File names: `<metadata.name>-<kind>.yaml` (all lowercase, hyphens)
- Namespace annotation sync-wave = `sync-wave` value (quoted string, e.g. `'8'`)
- OperatorGroup and Subscription sync-wave = `sync-wave + 1` (quoted string)

### 1. `<namespace>-namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: <namespace>
  annotations:
    argocd.argoproj.io/sync-wave: '<sync-wave>'
```

### 2. `<component-name>-operatorgroup.yaml`

If scope is `OwnNamespace`:
```yaml
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: <component-name>
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-wave: '<sync-wave+1>'
spec:
  targetNamespaces:
    - <namespace>
```

If scope is `AllNamespaces`, omit `spec.targetNamespaces` entirely:
```yaml
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: <component-name>
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-wave: '<sync-wave+1>'
spec: {}
```

### 3. `<component-name>-subscription.yaml`

```yaml
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: <component-name>
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-wave: '<sync-wave+1>'
spec:
  channel: <channel>
  installPlanApproval: Automatic
  name: <package>
  source: <catalog-source>
  sourceNamespace: openshift-marketplace
```

### 4. `external-secret.yaml` (only if external-secret=yes)

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <component-name>-secret
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
    argocd.argoproj.io/sync-wave: '<sync-wave+2>'
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-sdk-ocp-pull
  target:
    name: <component-name>-secret
    creationPolicy: Owner
    deletionPolicy: Retain
  dataFrom:
    - extract:
        key: <external-secret-key>
        conversionStrategy: Default
        decodingStrategy: None
        metadataPolicy: None
```

### 5. `kustomization.yaml`

List resources in creation order: namespace first, then operatorgroup, then subscription, then external-secret (if present).

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - <namespace>-namespace.yaml
  - <component-name>-operatorgroup.yaml
  - <component-name>-subscription.yaml
  # - external-secret.yaml  (include uncommented if generated)
```

If `skip-dry-run=yes`, append:
```yaml
commonAnnotations:
  argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
```

## Step 4: Validation

After writing all files, run:
```bash
kustomize build components/<component-name>/
```

If kustomize build fails, diagnose and fix the issue before reporting completion.

## Step 5: Completion report

After successful validation, report:
1. Which files were created (list with paths)
2. The kustomize build output (condensed — resource kinds and names only)
3. Next step reminder: add the component to a cluster's `values.yaml` with the appropriate sync-wave
