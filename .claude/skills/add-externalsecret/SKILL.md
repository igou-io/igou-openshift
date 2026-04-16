---
name: add-externalsecret
description: Add an ExternalSecret to an existing component or application. Creates the ExternalSecret YAML, patches kustomization.yaml, and verifies the 1Password item exists in the correct vault using the op CLI.
argument-hint: <component-or-app-path>
allowed-tools: Read, Edit, Write, Bash(kustomize build *), Bash(ls *), Bash(cat *), Bash(op *), Bash(oc get clustersecretstore *)
---

# Add an ExternalSecret to an existing component or application

Add an ExternalSecret resource to an existing directory under `components/` or `applications/`, update its `kustomization.yaml`, and verify the 1Password reference is valid.

## Target path

The target: **$ARGUMENTS**

Expected formats:
- `components/<name>` or `applications/<name>` — full path
- `<name>` — resolve by checking both `components/<name>/` and `applications/<name>/`
- If `$ARGUMENTS` is empty, ask the user for the target

## Step 1: Validate the target

1. Verify the directory exists and contains a `kustomization.yaml`
2. Read the existing `kustomization.yaml` to understand current resources
3. Read any existing namespace YAML to determine the namespace
4. Check if an ExternalSecret already exists in the directory — if so, warn the user and ask if they want to add another or replace it

## Step 2: Gather information

| Field | Description | Default |
|-------|-------------|---------|
| `secret-name` | ExternalSecret metadata.name and target Secret name | `<component-name>-secret` |
| `namespace` | Namespace for the ExternalSecret | auto-detected from existing namespace YAML or kustomization.yaml |
| `onepassword-key` | 1Password item key for `dataFrom.extract.key` | — (required) |
| `secret-store` | ClusterSecretStore name | `onepassword-sdk-ocp-pull` |
| `sync-wave` | ArgoCD sync-wave annotation value | auto-detect: highest wave in directory + 1 |
| `skip-dry-run` | Add `SkipDryRunOnMissingResource=true` sync-option annotation | `yes` |
| `use-template` | Whether to use a `target.template` for custom Secret data mapping (`yes`/`no`) | `no` |

If `use-template=yes`, also ask:

| Field | Description | Default |
|-------|-------------|---------|
| `template-keys` | Comma-separated list of `data` keys in the rendered Secret | — (required) |
| `template-values` | For each key, the Go template value (e.g. `{{ .password }}`) | — (required) |

Ask in a single message.

## Step 3: Verify 1Password references

Before generating any files, verify the 1Password item exists and its fields match what the ExternalSecret will reference.

### 3a. Resolve the vault from the ClusterSecretStore

Look up the ClusterSecretStore to find the 1Password vault name:
```bash
oc get clustersecretstore <secret-store> -o jsonpath='{.spec.provider.onepasswordSDK.vault}'
```

If the ClusterSecretStore doesn't exist or doesn't have a vault configured, warn the user and ask whether to proceed anyway.

### 3b. Verify the item exists in the vault

```bash
op item get "<onepassword-key>" --vault "<vault>" --format json 2>&1
```

**If the item exists**, extract and display:
- Item title
- Item category (Password, Login, Secure Note, etc.)
- Available field labels/keys (these are what `{{ .fieldname }}` references in templates)

Report: "Found 1Password item `<onepassword-key>` in vault `<vault>`. Available fields: `<field-list>`."

**If the item does NOT exist** (exit non-zero), warn the user clearly:
"1Password item `<onepassword-key>` was NOT found in vault `<vault>`. The ExternalSecret will fail to sync until this item is created."

Ask the user whether to:
1. Proceed anyway (create the ExternalSecret, fix the 1Password item later)
2. Use a different item key (re-enter)
3. Abort

### 3c. Validate template fields (if use-template=yes)

If the user is using a template, cross-reference the `{{ .fieldname }}` references in the template values against the actual fields returned by `op item get`. Warn about any template references that don't match an existing field:

"Template references `{{ .password }}` but the item's available fields are: `username`, `credential`, `hostname`. Did you mean `{{ .credential }}`?"

This is a warning, not a blocker — the user may plan to add the field later.

## Step 4: Generate the ExternalSecret

### Standard ExternalSecret (use-template=no):

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <secret-name>
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
    argocd.argoproj.io/sync-wave: '<sync-wave>'
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: <secret-store>
  target:
    name: <secret-name>
    creationPolicy: Owner
    deletionPolicy: Retain
  dataFrom:
    - extract:
        key: <onepassword-key>
        conversionStrategy: Default
        decodingStrategy: None
        metadataPolicy: None
```

If `skip-dry-run=no`, omit the `argocd.argoproj.io/sync-options` annotation.

### Templated ExternalSecret (use-template=yes):

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <secret-name>
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
    argocd.argoproj.io/sync-wave: '<sync-wave>'
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: <secret-store>
  target:
    name: <secret-name>
    creationPolicy: Owner
    deletionPolicy: Retain
    template:
      engineVersion: v2
      data:
        <key1>: <template-value1>
        <key2>: <template-value2>
  dataFrom:
    - extract:
        key: <onepassword-key>
        conversionStrategy: Default
        decodingStrategy: None
        metadataPolicy: None
```

### File naming

Name the file `<secret-name>-externalsecret.yaml`.

## Step 5: Update kustomization.yaml

Add the ExternalSecret file to the `resources:` list in the existing `kustomization.yaml`. Place it after the last existing resource (typically after the subscription or deployment).

Use the Edit tool to modify the existing `kustomization.yaml` — do NOT rewrite the entire file.

## Step 6: Validation

Run:
```bash
kustomize build <target-path>/
```

If kustomize build fails, diagnose and fix the issue before reporting completion.

## Completion report

Report:
1. **1Password verification**: whether the item was found, vault name, available fields
2. **File created** (path)
3. **kustomization.yaml updated** (show the diff — what was added)
4. **Kustomize build result**
5. **Template field validation** (if use-template=yes): any mismatched field references
6. **Warnings**: any issues that need manual attention (missing 1Password item, field mismatches)
