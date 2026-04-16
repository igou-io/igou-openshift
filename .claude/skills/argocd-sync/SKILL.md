---
name: argocd-sync
description: Refresh and sync ArgoCD applications. Can target all apps, a specific app, or filter by sync status (OutOfSync, Degraded, etc.). Shows sync status before and after.
argument-hint: [app-name | all | out-of-sync]
allowed-tools: Bash(argocd *), Bash(oc get application*)
---

# Refresh and sync ArgoCD applications

Refresh and optionally sync ArgoCD applications managed by this cluster.

## Arguments

The target: **$ARGUMENTS**

Expected formats:
- `all` — refresh and sync all applications
- `out-of-sync` — refresh all, then sync only OutOfSync applications
- `degraded` — refresh all, then sync only Degraded applications
- `refresh` or `refresh-only` — refresh all applications without syncing (just update status)
- `<app-name>` — refresh and sync a specific application by name
- Empty — show current status of all apps and ask what to do

## Step 1: Authentication check

Verify the ArgoCD CLI can reach the server:
```bash
argocd app list --output name 2>&1 | head -5
```

If this fails with an auth error, try logging in via the cluster:
```bash
argocd login --core
```

If `--core` mode works (ArgoCD is on the same cluster), proceed. If not, report the auth issue and stop.

## Step 2: Current status

List all applications with their sync and health status:
```bash
argocd app list -o wide
```

Parse and present a summary table:
- App name
- Sync status (Synced / OutOfSync / Unknown)
- Health status (Healthy / Degraded / Progressing / Missing / Unknown)
- Last sync time

Highlight any apps that are OutOfSync, Degraded, or in an error state.

## Step 3: Execute the action

### If `all`:

First hard-refresh all apps to pick up git changes, then sync:
```bash
argocd app list -o name | xargs -I{} argocd app get {} --hard-refresh > /dev/null 2>&1
```

Then sync all:
```bash
argocd app list -o name | xargs -I{} argocd app sync {} --async --retry-limit 3
```

Use `--async` so syncs run in parallel. The `--retry-limit 3` handles transient failures.

### If `out-of-sync`:

Refresh all first:
```bash
argocd app list -o name | xargs -I{} argocd app get {} --hard-refresh > /dev/null 2>&1
```

Then sync only OutOfSync apps:
```bash
argocd app list -o name --status OutOfSync | xargs -I{} argocd app sync {} --async --retry-limit 3
```

If no apps are OutOfSync after refresh, report that everything is in sync.

### If `degraded`:

Refresh, then sync only Degraded apps:
```bash
argocd app list -o name | xargs -I{} argocd app get {} --hard-refresh > /dev/null 2>&1
argocd app list -o name --health-status Degraded | xargs -I{} argocd app sync {} --async --retry-limit 3
```

### If `refresh` or `refresh-only`:

Only refresh, do not sync:
```bash
argocd app list -o name | xargs -I{} argocd app get {} --hard-refresh > /dev/null 2>&1
```

Then show updated status.

### If `<app-name>`:

Refresh and sync the specific app:
```bash
argocd app get <app-name> --hard-refresh
argocd app sync <app-name> --retry-limit 3
```

Show the detailed sync result including resource-level status.

## Step 4: Post-sync status

After syncing, wait a few seconds then check status again:
```bash
argocd app list -o wide
```

Compare before/after and report:
- Which apps were synced
- Which apps changed status
- Any apps still OutOfSync or Degraded (these may need manual intervention)

## Step 5: Report

Present a summary:
1. **Action taken**: what was refreshed/synced
2. **Before**: count of Synced/OutOfSync/Degraded apps
3. **After**: count of Synced/OutOfSync/Degraded apps
4. **Still unhealthy**: list any apps that remain OutOfSync or Degraded with their status details
5. **Recommendation**: if any apps are still unhealthy, suggest using `/troubleshoot <namespace>` to diagnose
