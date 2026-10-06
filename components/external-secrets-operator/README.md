# External Secrets Operator

The operator is managed through `clusters/ocp/external-secrets-operator`, which
adds the cluster's 1Password stores. `kustomization.yaml` holds site overrides
for the pinned Helm chart rather than a copy of all upstream defaults.

Keep the control-plane placement, OpenShift security adaptation, three image
digest pins, explicit security contexts/RBAC, and ServiceMonitor configuration
when updating the chart. CRDs use server-side apply. Values matching upstream
defaults were removed after comparing parsed rendered objects; omitted settings
now follow the pinned chart's defaults.

Validate a change from the repository root:

```bash
kustomize build --enable-helm clusters/ocp/external-secrets-operator
make test
```
