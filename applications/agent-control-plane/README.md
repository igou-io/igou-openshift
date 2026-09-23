# Agent Control Plane POC

This deploys the [Agent Control Plane](https://github.com/openshift-online/agent-control-plane) API, UI, and Kubernetes control plane from upstream revision `9d7246cb467b3e4d4060bff760b6256f6a368a50`. The UI is at `https://agent-control-plane.apps.ocp.igou.systems`. Only the UI has a public Route; the API and token service remain ClusterIP-only. The database is a single-instance CloudNative-PG cluster on `freenas-nvmeof-ssd-csi`.

This ACP revision always provisions sessions through an OpenShell gateway. The `acp-poc` project has a dedicated, internal-only gateway in `applications/acp-poc-gateway`; it does not reuse or alter the existing user-facing OpenShell gateway. The ACP service account can create and delete project namespaces and manage runner resources cluster-wide, matching upstream's standard provisioner. Treat ACP administrators and any ability to create ACP projects as cluster-privileged until this is replaced by a constrained provisioner. This is not a multi-tenant production deployment.

The pinned ACP revision injects sandbox network rules for the upstream Service names `ambient-control-plane` and `ambient-api-server`. The matching ClusterIP aliases in this directory point at the same pods as the existing `agent-control-plane-*` Services. Runner-facing token and gRPC URLs must use the full `.svc.cluster.local` aliases: the sandbox's OpenShell network proxy could match a short `.svc` alias to the policy but could not resolve it. Other Service names are denied even though policy injection reports success.

## Bootstrap

1. Create a confidential `agent-control-plane` client in the `igou` Keycloak realm. Enable Authorization Code flow, client-credentials service accounts, and the redirect URI `https://agent-control-plane.apps.ocp.igou.systems/api/auth/sso/callback`; set the web origin to the UI origin. Add an access-token audience mapper for `agent-control-plane` and grant the client's service account the `openshell-admin` realm role, so it can authenticate to the project gateway. The realm's `KeycloakRealmImport` is import-only and will not apply new clients to the existing realm.
2. Store the Keycloak client secret, a fresh session secret, and a 32-byte AES-GCM keyring in the `lab_openshift` 1Password vault as the `agent-control-plane` item. Fields must be `CLIENT_SECRET`, `SESSION_SECRET`, and `CREDENTIAL_ENCRYPTION_KEYRING` (the last is JSON shaped like `{"1":"<base64-encoded-32-byte-key>"}`). External Secrets creates the Kubernetes Secret. Never put these values in Git or a PR.
3. Merge this app and sync `root-applications`, `agent-control-plane`, and `acp-poc-gateway` in Argo CD. Confirm the ExternalSecrets are Ready, CNPG is healthy, deployments and gateway StatefulSet are Available, and a browser login reaches the UI. Create one disposable project and session, then check the Sandbox CR in its project namespace.

The gateway gets its encryption key from the existing `lab_agents/openshell` 1Password item via a separate ExternalSecret. cert-manager issues its own namespace-local CA, server, and client certificates. Its client certificate stays in the `acp-poc` namespace; no private key is copied from the existing OpenShell installation. The `acp-poc` namespace is intentionally static for this single-project POC. Other projects need their own gateway application before they can run sessions.

Keycloak's client secret and the 1Password `CLIENT_SECRET` field must match. The UI only allows the `igou.david@gmail.com` email in the API ACL for this POC. If Keycloak login works but an API request gets 403, inspect the email claim and ACL before widening access.

## OpenCode Go provider

The Keycloak client secret, UI session secret, and ACP encryption keyring are in the `lab_openshift/agent-control-plane` 1Password item. The OpenCode Go API key is separately in `lab_agents/opencode-go-api-key` (`password` field). The non-secret provider profile is versioned at `applications/openshell/provider-profiles/opencode-go-codex.yaml` and uses `https://opencode.ai/zen/go/v1`. The `acp-poc` gateway stores the key encrypted on its persistent volume; it is not shared with the original `openshell` gateway.

The POC provider was bootstrapped with the OpenShell CLI over a local `oc port-forward` to `svc/openshell-gateway` in `acp-poc`, using the Keycloak `agent-control-plane` client's OIDC client-credentials grant. Register the gateway with the `igou` issuer, client ID and audience `agent-control-plane`; set `OPENSHELL_OIDC_CLIENT_SECRET` from the `CLIENT_SECRET` field in 1Password before login. Import the versioned profile, then create `opencode-go` with `--type opencode-go-codex --credential OPENAI_API_KEY`, loading `OPENAI_API_KEY` from the 1Password item's `password` field. Use `--gateway-insecure` only on the loopback port-forward because its certificate is issued for the in-cluster service name. Unset both secret-bearing environment variables afterward. `openshell provider get opencode-go` shows only credential key names, never the value. Re-run this bootstrap after replacing the gateway database or rotating the API key.

For the Codex smoke test, create a disposable sandbox with `--provider opencode-go`, then remove its overlapping default L4 network rule with `openshell policy update <sandbox> --remove-rule opencode --wait` before calling Codex. The custom profile supplies the inspected OpenCode endpoint rule. A one-prompt test returned `OK` using `gpt-5.6-luna`; the sandbox was deleted afterward. Client-credentials CLI login has no refresh token, so re-run `openshell gateway login acp-poc` when its access token expires.

This enables OpenShell/Codex sandboxes on the dedicated gateway. It does **not** make ACP sessions use OpenCode Go: this ACP revision maps custom provider types to `generic`, does not mark them inference-capable, and its shipped runner does not provide an active Codex bridge. An ACP model-response POC needs upstream provider and runner integration.

## Limitations

- The gateway uses ordinary CRI-O containers, not Kata. OpenShell 0.0.116 still requires the sandbox ServiceAccount to use the privileged SCC, so this is not a production security boundary.
- Only `acp-poc` has a gateway. The upstream control plane assumes one gateway per project namespace; creating another project without deploying its gateway leaves sessions Pending.
- The `opencode-go` provider is manually bootstrapped in this gateway's database, not reconciled from GitOps. ACP cannot yet use it for model responses.
- No database backup policy or HA yet. Do not keep important sessions or credentials here.
- The cluster-wide ACP service account is a deliberate POC-only trust grant. Review upstream's namespace provisioner and narrow it before granting anyone else access.
- The realm client is bootstrapped through the Keycloak admin API because `KeycloakRealmImport` does not reconcile existing realms. Keep the realm bootstrap record aligned separately.
