---
name: scaffold-app
description: Scaffold a new user-facing application in applications/ following repo conventions. Generates Namespace, kustomization.yaml with helmCharts stanza, and optionally ExternalSecret. Use when adding a new self-hosted app to the platform.
argument-hint: <app-name>
disable-model-invocation: true
allowed-tools: Read, Write, Bash(kustomize build *), Bash(helm show values *), Bash(ls *), Bash(cat *)
---

# Scaffold a new application

Scaffold a new application under `applications/` following the exact conventions of this repo.

## App name

The application to scaffold is: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask the user for the app name before proceeding.

## Information to gather

Before generating any files, collect the following. If the user provided all of it inline, proceed directly. Otherwise ask in a single message — do not ask one question at a time.

| Field | Description | Default |
|-------|-------------|---------|
| `app-name` | Directory name under `applications/` and Helm release name | from `$ARGUMENTS` |
| `namespace` | Kubernetes namespace | same as `app-name` |
| `chart-name` | Helm chart name | same as `app-name` |
| `chart-version` | Helm chart version (e.g. `1.2.3`) | — (required) |
| `chart-repo` | Helm repo URL (e.g. `https://charts.example.com/`) | — (required) |
| `external-secret` | Whether to scaffold an ExternalSecret (`yes`/`no`) | `no` |
| `external-secret-key` | 1Password item key (only if external-secret=yes) | — |

## File generation

Create directory `applications/<app-name>/` and generate the files below.

### Conventions (apply to every file)
- 2-space indentation
- Files start with `---`
- YAML 1.2 booleans: `true`/`false` only
- File names: `<metadata.name>-<kind>.yaml` (all lowercase, hyphens)
- The `kustomization.yaml` does NOT start with `---` (kustomize convention)
- Namespace has no sync-wave annotation (applications deploy at wave 20+ and the Namespace is bundled with the app)

### 1. `<namespace>-namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: <namespace>
```

### 2. `kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <namespace>
resources:
  - <namespace>-namespace.yaml
  # - <app-name>-secrets-externalsecret.yaml  (uncomment if external-secret=yes)
helmCharts:
- name: <chart-name>
  namespace: <namespace>
  version: <chart-version>
  releaseName: <app-name>
  repo: <chart-repo>
  valuesInline: {}
```

If `external-secret=yes`, uncomment that line.

### 3. `<app-name>-secrets-externalsecret.yaml` (only if external-secret=yes)

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <app-name>-secrets
  namespace: <namespace>
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-sdk-ocp-pull
  target:
    name: <app-name>-secrets
    creationPolicy: Owner
    deletionPolicy: Retain
  dataFrom:
    - extract:
        key: <external-secret-key>
        conversionStrategy: Default
        decodingStrategy: None
        metadataPolicy: None
```

Note: no sync-wave or SkipDryRunOnMissingResource annotations here — applications are self-contained and deploy as a unit.

## After generating files

1. Run `kustomize build applications/<app-name>/` to validate the scaffold builds cleanly.

2. If kustomize build fails because it can't fetch the chart (network or auth error), that's expected in an air-gapped environment — note it clearly but do not treat it as a blocker.

3. If kustomize build fails for a YAML/structure reason, diagnose and fix it before reporting.

## Completion report

After generating files, report:
1. Files created (list with paths)
2. Kustomize build result (pass / expected network failure / structural error)
3. Remind the user of the two next steps:
   - Fill in `valuesInline:` in `kustomization.yaml` with the chart's actual configuration
   - Add the app to a cluster's `values.yaml` under `applications:` with the path `applications/<app-name>` and an appropriate sync-wave (wave 20+ for user apps)
