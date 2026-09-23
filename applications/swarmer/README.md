# Swarmer on OpenShell

Swarmer 1.4.7 runs in the existing `openshell` namespace. It uses the existing
OpenShell 0.0.116 gateway for sandbox lifecycle and a 5 Gi SQLite PVC for its
own state. The app is reachable at <https://swarmer.apps.ocp.igou.systems>.
The OAuthClient lets cluster users log in with OpenShift credentials.

`Containerfile` makes a one-function patch to upstream 1.4.7. Its workspace
list otherwise returns HTTP 500 after a gateway is attached because provider
probing expires ORM attributes before serialization. The image is stored in the
OpenShift internal registry and pinned by digest. Rebuild and push the image
after changing the patch, then update the digest in `kustomization.yaml`.

The `swarmer-openshell` Keycloak service account is a platform administrator
because Swarmer's gateway connection test, provider profile import, and
cross-workspace sandbox management require that role. Its client secret and
Swarmer's encryption key are stored in the `lab_agents/swarmer` 1Password item;
External Secrets delivers the encryption key to the app. The OpenCode Go key
stays in OpenShell's encrypted provider store and is injected into sandboxes
through its provider API, rather than into a Kubernetes Secret or Swarmer DB.

## Bootstrap after sync or gateway restore

The `KeycloakRealmImport` records the service client for new realm imports but
does not reconcile an existing realm. On this cluster the client and its realm
roles were created through the Keycloak admin API. Confirm the client has both
`openshell-admin` and `openshell-user` before running the bootstrap. The
`lab_agents/swarmer` item needs `SWARMER_SECRET_KEY` and
`OPENSHELL_CLIENT_SECRET` fields.

From the devcontainer, with the `ocp` credential profile active and `op` vault
access, run:

```bash
python3 applications/swarmer/bootstrap.py
```

The script creates the `swarmer-lab` workspace if absent, saves the internal
gateway URL and verified TLS/OIDC credentials, imports the versioned
`opencode-go-for-swarmer` provider profile, stores the Go subscription key in
OpenShell, and configures OpenCode for `openai/gpt-5.6-luna`. It is safe to
rerun after key rotation. `OPENCODE_CONFIG_CONTENT` carries only non-secret
provider settings; OpenShell injects `OPENAI_API_KEY` at agent launch.

Swarmer 1.4.7 supports only `claude`, `gemini`, and `openai` preset families.
The OpenCode Go integration uses its `openai` family with the Go Responses
endpoint. GLM models use chat completions and fail with this release's
hardcoded OpenAI adapter. A future Swarmer version with a dedicated Go provider
would allow the `opencode-go/<model>` identifiers directly.

The pod's global OpenShell URL is used for startup checks, but it has no OIDC
bearer token and its global sandbox GC will log authorization warnings. Session
operations use the workspace's stored OIDC connection. Inspect and remove
orphaned evaluation sandboxes manually until upstream supports OIDC for the
global gateway client.

## Verify

```bash
oc whoami --show-server
oc whoami
oc -n openshell rollout status deployment/swarmer
oc -n openshell get externalsecret swarmer-secret
oc -n openshell get ingress swarmer
```

The initial prompt-mode smoke test used `openai/gpt-5.6-luna` and returned
`SWARMER_GO_OK` through Swarmer → OpenShell → OpenCode Go on 2026-09-23.

This is an evaluation deployment. OpenShell sandboxes currently use ordinary
CRI-O and the `openshell-sandbox` ServiceAccount has the privileged SCC, as
described in `applications/openshell/README.md`.
