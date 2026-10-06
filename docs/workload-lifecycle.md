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

## Files marked for removal

The 2026-10-06 file audit checked tracked files against Kustomize resources,
patches, generators, Helm values, object-name consumers, and local references
in igou-containers, igou-ansible, igou-inventory, igou-skills, and igou-docs.
The following 14 files are source-removal candidates. They remain in this PR
for review; none have been deleted. These marks do not authorize live cleanup.

| File | Evidence |
| --- | --- |
| `applications/omnigent/omnigent-codex-auth-pvc.yaml` | Old `openshell` namespace claim; not in Kustomize or mounted by the current configuration. The README identifies `omnigent-sre-codex-auth` in `omnigent-sandboxes` as the current claim. |
| `applications/omnigent/omnigent-openshell-client-externalsecret.yaml` | No Kustomize inclusion or remaining consumer of `omnigent-openshell-client`. Current server uses `omnigent-machine-client`. |
| `applications/omnigent/omnigent-openshell-gateway-configmap.yaml` | No Kustomize inclusion or remaining consumer of `omnigent-openshell-gateway`. |
| `applications/omnigent/omnigent-test-agent-configmap.yaml` | No Kustomize inclusion or remaining consumer of `omnigent-test-agent`; current agent configuration comes from the SRE bundle. |
| `applications/omnigent/Containerfile.openshell` | Standalone old build recipe with no build/CI/documentation caller found. Current sandbox configuration uses `provider: agent_sandbox`. Remove with its two patch scripts after confirming no OpenShell rollback is intended. |
| `applications/omnigent/patch_openshell_policy.py` | Its only filename reference is the obsolete `Containerfile.openshell`. |
| `applications/omnigent/patch_openshell_service_auth.py` | Its only filename reference is the obsolete `Containerfile.openshell`. |
| `applications/omnigent/openshell-host-policy.yaml` | No generator/file reference found. Its old policy environment variable is used only by the obsolete OpenShell patch. |
| `components/nvidia-gpu-operator/time-slicing-config-configmap.yaml` | Absent from Kustomize, and ClusterPolicy does not reference `time-slicing-config`. The July component review already records it as orphaned and unwired. |
| `PR_REVIEW.md` | Unreferenced March 20 review of old dependency branches, not current repository guidance. |
| `docs/superpowers/plans/2026-05-07-gitea-mirror-gitops.md` | Implementation plan for Gitea Mirror, removed in #1077. No external filename references found. Remove together with its spec, or keep both explicitly as history. |
| `docs/superpowers/specs/2026-05-07-gitea-mirror-gitops-design.md` | Spec for the same retired application. |
| `docs/superpowers/plans/2026-06-14-hermes-agent-poc-phase1-guardrails.md` | Plan for the old `applications/hermes-agent` VM deployment, removed in #774. igou-docs records completed VM retirement. |
| `docs/superpowers/specs/2026-06-14-hermes-agent-kubevirt-vm-deployment-design.md` | Spec referenced by the retired VM plan; retire the pair together. Keep the actual incident/recovery runbooks. |

For the Omnigent bundle, confirm the final migration and rollback requirements
before deleting source files. Do not delete the old auth PVC or its data as part
of this repository cleanup. Removing orphaned source files does not establish
that corresponding live resources have been removed.

## README and example review

No README was established as unused solely from the reference audit.

| Path | Disposition | Reason |
| --- | --- | --- |
| `misc/minecraft/README.md` | Consolidate, then consider removal | Old standalone restore instructions. Move any still-needed recovery procedure beside `applications/minecraft-server/README.md` before removing this README. Its restore pod may still be useful for the dormant server. |
| `docs/udn/README.md` and its four example READMEs | Keep; repair | Referenced by cluster configuration and several igou-docs pages. The hub's production link uses `../clusters/ocp/udn/` instead of `../../clusters/ocp/udn/`. The IPAM README also names a removed `jellyfin-cudn.yaml`. |
| `clusters/ocp/udn/README.md` | Keep; repair | Documents the managed production CUDN. Its example link needs `../../../docs/udn/cudn-localnet-no-ipam/`, not `../../docs/...`. |
| `test-workloads/hermes-k8s-backend/README.md` | Keep; repair | Explicitly retained sandbox test path. Its layout table still lists filenames from before the one-object-per-file rename. |
| `misc/examples/` | Optional archive | Ten self-contained affinity demo files; no external caller found. Manual examples are not proven dead merely because ArgoCD does not deploy them. |
| `test-workloads/virtualmachine-devhosttest/` | Keep | Standalone VM example explicitly listed in the igou-docs scenario library. |

The documented bootstrap Job under `applications/sands-of-time/`, all Grafana
dashboard JSON sources, and the monitoring/UDN runbooks also have consumers or
documented manual uses. They are not removal candidates from this audit.

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
