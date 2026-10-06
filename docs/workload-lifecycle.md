# Workload lifecycle

The `clusters/ocp` app-of-apps dependency graph defines managed workloads.
Follow both `clusters/ocp/values.yaml` and `groups/all/values.yaml`, then each
source directory's Kustomize resources/components. A component can be managed
through another workload without having its own Application entry.

This inventory was checked against `origin/main` on 2026-10-06. It describes
repository wiring, not live namespace or data status.

| Status | Meaning | Validation |
| --- | --- | --- |
| Managed | Reachable from the cluster root | Full repository gate |
| Rollback | Registered but intentionally stopped for migration recovery | Full repository gate |
| Dormant | Available manifests, absent from the cluster root | Full repository gate; explicit registration required to deploy |
| Retired | Retirement is confirmed; manifests removed or moved under `archive/` | Archived content excluded from normal lint/render checks |

## Rollback workload

| Path | Reason |
| --- | --- |
| `applications/calibre-web` | Calibre-Web Automated owns library management. Stock Calibre-Web remains registered with `replicas: 0`; follow its README before rollback. |

## Dormant workloads

These paths are not reachable from the current local root. Keep them dormant
until their intended use and any live resources or retained data are checked.
Their absence from the app registry does not establish a completed retirement.

| Path | Content |
| --- | --- |
| `applications/lidarr` | Music library management |
| `applications/minecraft-server` | Minecraft server |
| `applications/ntfy` | Push notifications |
| `applications/ollama` | Standalone Ollama serving |
| `components/openshift-ai` | OpenShift AI operator and instance |
| `components/openshift-dev-spaces` | Separate Dev Spaces operator install; the managed stack uses `components/devspaces` |
| `components/openshift-mtv` | Migration Toolkit for Virtualization |
| `components/rhcl-operator` | Red Hat Connectivity Link operator |

## Completed retirements

Gitea, Gitea Mirror, n8n, and standalone Temporal were removed in PR #1077.
Their historical manifests remain available in Git history. No additional
retirements are inferred by this cleanup.

## Changing lifecycle

To activate a dormant workload, review its chart, secrets, storage, and namespace
requirements, add the app-of-apps entry, and remove it from the dormant table.
Run `make test` and inspect the rendered Application before merging.

To retire a workload, establish its replacement and data disposition first.
Removing an app-of-apps entry is not proof that its live resources were deleted:
child Applications default to pruning disabled. Record the disposition here,
then remove the files or move historical manifests under `archive/`. Update
relative references when moving files. Never reference `archive/` from an active
Kustomization. Live cleanup requires a separately authorized operation.
