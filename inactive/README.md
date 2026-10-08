# Inactive workloads

These workloads are retained for possible reuse but are not registered in the
cluster app-of-apps. `make test` still lints, checks manifest filenames, builds,
and validates their schemas. Renovate still maintains their dependencies.

| Path | Purpose |
| --- | --- |
| `applications/lidarr/` | Music library management |
| `applications/minecraft-server/` | Minecraft server and manual recovery helper |
| `applications/ntfy/` | Push notifications |
| `applications/ollama/` | Standalone Ollama serving |
| `applications/omnigent/` | Managed SRE agent sessions and Slack integration |
| `components/openshift-ai/` | OpenShift AI operator and instance |
| `components/openshift-dev-spaces/` | Separate Dev Spaces operator; the managed stack uses `components/devspaces/` |
| `components/openshift-mtv/` | Migration Toolkit for Virtualization |
| `components/rhcl-operator/` | Red Hat Connectivity Link operator |

Before activation, review secrets, storage, chart compatibility, namespaces, and
any retained resources or data. Move the workload back to `applications/` or
`components/`, update path references, and add its app-of-apps entry. Active
Kustomizations and Applications must not reference `inactive/`.

```bash
kustomize build --enable-helm inactive/applications/minecraft-server
make test
```

Workloads that are still registered for rollback, such as Calibre-Web with zero
replicas, remain beside active workloads. Retired source files can be removed;
Git history preserves them. See the
[lifecycle inventory](https://github.com/igou-io/igou-docs/blob/main/reference/igou-openshift%20Workload%20Lifecycle%20and%20Cleanup.md)
for status and retirement procedures.
