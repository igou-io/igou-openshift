---
name: add-to-cluster
description: Add a component or application to a cluster's values.yaml for the ArgoCD app-of-apps pattern. Reads the existing values.yaml, determines the correct insertion point by sync-wave ordering, and adds the entry.
argument-hint: <path> [cluster]
allowed-tools: Read, Edit, Write, Bash(ls *), Bash(cat *), Bash(kustomize build *)
---

# Add component/application to a cluster

Add an existing component or application to a cluster's `values.yaml` for ArgoCD app-of-apps management.

## Arguments

The path and optional cluster: **$ARGUMENTS**

Expected formats:
- `components/<name>` or `applications/<name>` — adds to default cluster (`hub`)
- `components/<name> hub` or `components/<name> casval` — adds to specified cluster
- `<name>` — attempt to resolve: check if `components/<name>/` or `applications/<name>/` exists
- If `$ARGUMENTS` is empty, ask the user for the path and cluster

## Step 1: Resolve the path

1. Parse `$ARGUMENTS` to extract the path and optional cluster name (default: `hub`)
2. Verify the directory exists — check for a `kustomization.yaml` inside it
3. If the path is just a name (no prefix), check both `components/<name>/` and `applications/<name>/`. If both exist, ask the user which one. If neither exists, report the error.
4. Determine the source path to use in values.yaml:
   - For `components/<name>`: source path is `components/<name>`
   - For `applications/<name>`: source path is `applications/<name>`
   - If a cluster-specific overlay exists at `clusters/<cluster>/<name>/`, use that path instead (e.g. `clusters/hub/<name>`)

## Step 2: Read existing values.yaml

Read `clusters/<cluster>/values.yaml` and understand the current structure:
- List all existing application entries
- Note the sync-wave ordering
- Identify the namespace used by the component (from kustomization.yaml or namespace.yaml)

## Step 3: Gather information

With context from the directory contents, ask the user to confirm or override:

| Field | Description | Default |
|-------|-------------|---------|
| `entry-name` | Key name in values.yaml `applications:` map | directory name (e.g. `openshift-dev-spaces`) |
| `sync-wave` | ArgoCD sync-wave (quoted string) | `'10'` for components, `'20'` for applications |
| `namespace` | `destination.namespace` — only include if the component's namespace differs from the entry name or if it's a cluster-specific convention | auto-detected from namespace YAML or kustomization.yaml |
| `include-namespace` | Whether to include `destination.namespace` in the entry | `yes` if namespace differs from entry-name, `no` otherwise |
| `compare-options` | Include `argocd.argoproj.io/compare-options: IgnoreExtraneous` annotation | `yes` |

Present defaults and ask user to confirm or adjust in a single message.

## Step 4: Add the entry

Insert the new entry into `clusters/<cluster>/values.yaml` under the `applications:` key. Position it according to sync-wave order (insert after the last entry with a sync-wave <= this entry's sync-wave).

### Entry format (with namespace):
```yaml
  <entry-name>:
    annotations:
      argocd.argoproj.io/compare-options: IgnoreExtraneous
      argocd.argoproj.io/sync-wave: '<sync-wave>'
    destination:
      namespace: <namespace>
    source:
      path: <source-path>
```

### Entry format (without namespace):
```yaml
  <entry-name>:
    annotations:
      argocd.argoproj.io/compare-options: IgnoreExtraneous
      argocd.argoproj.io/sync-wave: '<sync-wave>'
    source:
      path: <source-path>
```

If `compare-options=no`, omit the `argocd.argoproj.io/compare-options` annotation line.

## Step 5: Validation

1. Verify the YAML is valid by reading back the modified file
2. Confirm the entry was inserted at the correct position

## Completion report

Report:
1. Which cluster's values.yaml was modified
2. The entry that was added (show the YAML block)
3. The sync-wave and position relative to neighboring entries
4. Reminder: ArgoCD will pick up the change on next sync (or push to trigger it)
