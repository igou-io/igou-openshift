# Standalone Ollama

This workload is dormant: it is not registered in the cluster app-of-apps.
See `https://github.com/igou-io/igou-docs/blob/main/reference/igou-openshift%20Workload%20Lifecycle%20and%20Cleanup.md` before activating or retiring it.

`kustomization.yaml` contains site overrides for the pinned chart. Keep the
image digest pin, two-GPU request, model preload, environment, persistent volume,
and burst-node placement when updating the chart. Omitted settings follow the
chart defaults. These values were reduced by comparing parsed rendered objects
at the same chart version.

Run `kustomize build --enable-helm applications/ollama` and `make test` from the
repository root when changing these values.
