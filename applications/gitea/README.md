---
# Gitea (retired)

Removed from cluster GitOps on 2026-05-04 in favor of [Forgejo](../forgejo/).
Manifests are kept here for reference only — no ArgoCD Application points at this
path anymore.

## Live cluster cleanup

The chart default is `autoSyncPrune: false` and no `resources-finalizer.argocd.argoproj.io`
is set on managed Applications, so removing the entry from `clusters/ocp/values.yaml`
deletes the `gitea` Application object but **orphans** the live resources in the
`gitea` namespace (Deployment, CNPG `gitea-pg` cluster + PVC, ExternalSecret,
Route, valkey StatefulSet, Namespace). Tear them down manually once data has been
migrated to Forgejo:

```sh
oc delete namespace gitea
```
