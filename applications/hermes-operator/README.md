# hermes-operator — shared Hermes plumbing

Owns what every purpose-scoped Hermes instance shares: the `hermes-operator`
OCI chart (namespace `hermes-operator`), the `hermes-agent-root`
SecurityContextConstraints and the `system:openshift:scc:hermes-agent-root`
ClusterRole. ArgoCD app `hermes-operator` (wave 15) syncs before the instances
(wave 20). Was part of `applications/hermes-k8s` until the split cutover.
