# rk8s (k3s) triage

Prefix everything: `kubectl --context rk8s-cluster-reader ...`. Its
The old Hermes alert relay remains separate. This skill handles manual
rk8s investigations; `ocp-alerts` and `ocp-logs` are OCP-only. Use
kubectl and rk8s metrics here.

1. `kubectl --context rk8s-cluster-reader get nodes -o wide`, then the
   namespace/pod/events pass from the main triage skill.
2. k3s differences that masquerade as app bugs: default StorageClass is
   `local-path` (node-local! a PVC without explicit storageClassName is
   pinned to one node), no SCC (workloads need explicit numeric
   runAsUser), and the ArgoCD app-of-apps has selfHeal but
   autoSyncPrune=false — removed sub-components linger until a manual
   pruning sync, so "deleted but still running" is expected drift.
3. GitOps source is igou-io/igou-kubernetes (default branch `master`);
   MetalLB pool split and alertmanager-config live there.
