# Agent Control Plane POC

This deploys the [Agent Control Plane](https://github.com/openshift-online/agent-control-plane) API, UI, and Kubernetes control plane from upstream revision `9d7246cb467b3e4d4060bff760b6256f6a368a50`. The UI is at `https://agent-control-plane.apps.ocp.igou.systems`. Only the UI has a public Route; the API and token service remain ClusterIP-only. The database is a single-instance CloudNative-PG cluster on `freenas-nvmeof-ssd-csi`.

The first POC uses ACP's native Kubernetes runner, not its optional OpenShell integration (`OPENSHELL_ENABLED=false`). Existing OpenShell remains independent. The ACP service account can create and delete project namespaces and manage runner resources cluster-wide, matching upstream's standard provisioner. Treat ACP administrators and any ability to create ACP projects as cluster-privileged until this is replaced by a constrained provisioner. This is not a multi-tenant production deployment.

## Bootstrap

1. Create a confidential `agent-control-plane` client in the `igou` Keycloak realm. Enable Authorization Code flow, client-credentials service accounts, and the redirect URI `https://agent-control-plane.apps.ocp.igou.systems/api/auth/sso/callback`; set the web origin to the UI origin. The realm's `KeycloakRealmImport` is import-only and will not apply new clients to the existing realm.
2. Store the Keycloak client secret, a fresh session secret, and a 32-byte AES-GCM keyring in the `lab_openshift` 1Password vault as the `agent-control-plane` item. Fields must be `CLIENT_SECRET`, `SESSION_SECRET`, and `CREDENTIAL_ENCRYPTION_KEYRING` (the last is JSON shaped like `{"1":"<base64-encoded-32-byte-key>"}`). External Secrets creates the Kubernetes Secret. Never put these values in Git or a PR.
3. Merge this app and sync `cluster` then `agent-control-plane` in Argo CD. Confirm the ExternalSecret is Ready, CNPG is healthy, deployments are Available, and a browser login reaches the UI. Create one disposable project and session, then check the session pod in its project namespace.

Keycloak's client secret and the 1Password `CLIENT_SECRET` field must match. The UI only allows the `igou.david@gmail.com` email in the API ACL for this POC. If Keycloak login works but an API request gets 403, inspect the email claim and ACL before widening access.

## Limitations

- No OpenShell sandbox integration or Kata runtime in this phase. Native runner pod confinement is only the OpenShift defaults, not OpenShell's sandbox boundary.
- No database backup policy or HA yet. Do not keep important sessions or credentials here.
- The cluster-wide ACP service account is a deliberate POC-only trust grant. Review upstream's namespace provisioner and narrow it before granting anyone else access.
- The realm client is bootstrapped through the Keycloak admin API because `KeycloakRealmImport` does not reconcile existing realms. Keep the realm bootstrap record aligned separately.
