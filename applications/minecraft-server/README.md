# Minecraft server

This workload is dormant: it is not registered in the cluster app-of-apps.
See `docs/workload-lifecycle.md` before activating or retiring it.

`kustomization.yaml` contains site overrides for the pinned chart. It retains
the game settings, image digest pins, worker preference, security contexts,
resource sizing, persistent storage, RCON secret references, exporter sidecar,
and backup settings. Omitted settings follow the chart defaults.

The backup configuration still contains a `CHANGEME` placeholder. Review its
secret delivery before activating this workload; the values cleanup does not
change that existing configuration.

Run `kustomize build --enable-helm applications/minecraft-server` and `make test`
from the repository root when changing these values.
