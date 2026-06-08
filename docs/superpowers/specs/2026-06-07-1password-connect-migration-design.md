# 1Password SDK → Connect migration (ESO + Ansible) — design

- **Status:** Approved design — not yet implemented
- **Date:** 2026-06-07
- **Scope:** `igou-openshift` (hub, single-node OKD) + `igou-ansible` bootstrap
- **Reader-friendly walkthrough:** an HTML version was generated at `/tmp/1password-connect-migration.html` (ephemeral; this spec is the durable record).

## Problem

Every ESO secret read currently goes out to `api.1password.com` via the `onepasswordSDK` provider (service-account token). On the Personal/Families plan the read path is **rate-limited and times out**, to the point that `bootstrap_gitops.yaml` carries an ArgoCD health-check override forcing `ClusterSecretStore`/`ExternalSecret` healthy "because 1Password SDK rate limiting … breaks the app-of-apps reconciliation loop," plus per-store `cache.ttl: 2h`. External Ansible lookups hit the same metered API via the `op` CLI.

## Goal

Move ESO **and** external Ansible lookups onto a self-hosted **1Password Connect** server so per-call traffic terminates at an in-cluster, cache-backed service instead of the public API — eliminating the timeout/rate-limit pain.

## Key findings (researched, cited in the HTML walkthrough)

- **Plan tier:** As of 2025-02-27, Connect is available to all 1Password customers incl. Personal/Families — same availability as service accounts. Only group/environment permission delegation is Business/Teams. Connect cannot read built-in Personal/Private/Shared/default vaults (N/A — we use dedicated vaults).
- **Operator not needed:** ESO's `onepassword` provider calls Connect's REST API directly. Deploy only the server (`operator.create: false`, chart default). The 1Password K8s operator (Secrets Injector) is an alternative consumer, not a dependency.
- **Timeout fix is structural:** ESO reads from the local `connect-api` (served from the shared cache); only `connect-sync` talks upstream. Connect has no client-side rate limits/quotas (service accounts do).
- **Write path safe for big-bang:** ESO Connect provider source returns `SecretStoreReadWrite` and implements `PushSecret`/`DeleteSecret` (and `GetAllSecrets`); `SecretExists` is unimplemented (irrelevant — no existence-check push strategies in use). Repo uses only `dataFrom.extract` with plain item-title keys and zero `find`, so **ExternalSecret bodies don't change** — only the 3 store objects do.
- **Propagation timing:** `connect-sync` cadence is **undocumented** (only `OP_SYNC_TIMEOUT` for initial sync). The "few hours" figure = upstream usage telemetry; the "10 min" figure = the *operator's* `POLLING_INTERVAL`, not connect-sync. Must be measured on the deployment.
- **Ansible:** `onepassword.connect` (v2.4.0) is REST-native (no `op` binary) but **module-only** (`item_info`/`field_info`/`generic_item`, used with `register`) — **no lookup plugins**. `community.general.onepassword` keeps inline `lookup()` but wraps the `op` CLI.

## Decisions

| Decision | Chosen | Consequence |
|---|---|---|
| Cutover | **Big-bang** | All 3 ClusterSecretStores flip `onepasswordSDK` → `onepassword` at once; Connect must be healthy before cutover. |
| Transport | **Edge Route (LE) + HTTP in-cluster** | Route uses `edge` termination, inherits the `acme-apps` Let's Encrypt wildcard → external clients need no custom CA. In-cluster hops are plaintext HTTP (never leave the SNO host); NetworkPolicy + bearer token are the controls. |
| Ansible client | **Both, by phase** | `op` CLI/service account only for bootstrap seed; `onepassword.connect` for steady-state. |
| Store names | **Keep existing** | Rewrite the 3 store objects in place; ~30 ExternalSecrets untouched. |
| Service accounts | **Retain one** | One SA kept for bootstrap seed + break-glass; retire the rest after cutover. |

### Transport rationale

The cluster's `IngressController` defaultCertificate is `acme-apps` (cert-manager `cluster-acme` ClusterIssuer = Let's Encrypt DNS-01/Cloudflare), and every app Route in the repo uses `termination: edge`. The Connect chart serves HTTP **xor** HTTPS on one Service; edge requires an HTTP backend, so `connect.tls.enabled: false` and the in-cluster ESO leg is also HTTP. On a single node, ESO/router/Connect are co-located — that traffic never reaches a physical wire, OVN-K does not encrypt pod traffic by default, and node-level compromise (the only way to sniff it) already exposes K8s Secrets. **Do not** reintroduce service-CA/internal-CA/`SSL_CERT_FILE`/`destinationCACertificate` machinery for this; if encryption is later required, switch the Route to `reencrypt` with a service-CA backend, or enable OVN-K IPsec once multi-node.

## Architecture

```
1Password.com (vaults: ocp-pull, ocp-push, claude)
        ▲▼  connect-sync  (interval undocumented)
┌─────────────────── OpenShift (single node) ───────────────────┐
│  Connect server (ns onepassword-connect)                       │
│    connect-api :8080 (HTTP) · connect-sync · emptyDir cache    │
│      ▲ HTTP, in-cluster (NetworkPolicy: ESO + router only)     │
│  External Secrets Operator ── onepassword provider             │
│  OpenShift Route (edge, acme-apps LE)  ── external clients     │
└────────────────────────────────────────────────────────────────┘
        ▲ HTTPS via Route (Let's Encrypt, no custom CA)
   Ansible control node (onepassword.connect)
   Ansible bootstrap (op CLI) ··one-time··▶ seeds op-credentials + token
```

## Implementation

### New component `components/onepassword-connect/`

`kustomization.yaml` (helm chart 2.4.1 / app 1.8.2):

```yaml
helmCharts:
  - name: connect
    repo: https://1password.github.io/connect-helm-charts
    version: 2.4.1
    releaseName: onepassword-connect
    namespace: onepassword-connect
    valuesInline:
      operator: { create: false }
      connect:
        create: true
        serviceType: ClusterIP
        credentialsName: op-credentials
        credentialsKey: 1password-credentials.json
        tls: { enabled: false }          # edge Route terminates TLS; pod serves HTTP :8080
        nodeSelector: { node-role.kubernetes.io/control-plane: "" }
        tolerations:
          - { key: node-role.kubernetes.io/master,        operator: Exists, effect: NoSchedule }
          - { key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule }
resources:
  - onepassword-connect-namespace.yaml
  - networkpolicy.yaml
  - route.yaml
patches:
  - path: scc-uid-patch.yaml
```

Wire into `clusters/ocp` app-of-apps `values.yaml` at an early sync-wave (with/just after external-secrets-operator, wave 0).

**SCC friction (must validate):** chart hardcodes `runAsUser/runAsGroup/fsGroup: 999` (collides with `restricted-v2`); open bug [#282](https://github.com/1Password/connect-helm-charts/issues/282) — binary refuses to start because `/home/opuser/.op` isn't owned by the runtime UID.
- **Option A (recommended):** bind a custom SCC granting `RunAsUser: 999` to the Connect ServiceAccount; keep the chart's 999 (image is built for it).
- **Option B:** post-render patch removing the UID fields + an `emptyDir` over `/home/opuser/.op` so the random UID owns it (per #282).

Route (edge, inherits `acme-apps`):

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata: { name: onepassword-connect, namespace: onepassword-connect }
spec:
  to: { kind: Service, name: onepassword-connect }
  port: { targetPort: connect-api }     # 8080
  tls: { termination: edge, insecureEdgeTerminationPolicy: Redirect }
  # no spec.host / cert → default hostname under *.apps.ocp.igou.systems, acme-apps cert
```

NetworkPolicy (confirm the chart's actual pod label):

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: connect-allow-eso-and-router, namespace: onepassword-connect }
spec:
  podSelector: { matchLabels: { app: onepassword-connect } }
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: external-secrets-operator } }
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: openshift-ingress } }
      ports: [ { protocol: TCP, port: 8080 } ]
```

### Rewrite the 3 ClusterSecretStores in place (same names)

`clusters/ocp/external-secrets-operator/onepassword-sdk-ocp-pull-clustersecretstore.yaml` (repeat for `-ocp-push` → `ocp-push`, `-claude` → `claude`):

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-sdk-ocp-pull            # NAME UNCHANGED → ExternalSecrets untouched
spec:
  refreshInterval: 3600                      # safe to lower post-migration
  provider:
    onepassword:                             # was: onepasswordSDK
      connectHost: http://onepassword-connect.onepassword-connect.svc:8080
      vaults: { ocp-pull: 1 }                # was: vault: ocp-pull
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            key: token
            namespace: external-secrets-operator   # REQUIRED for ClusterSecretStore
```

All 3 reference the same token Secret; the token's per-vault scopes (`ocp-pull:read`, `ocp-push:read_write`, `claude:read_write`) do the least-privilege work. Remove the per-store `cache` blocks after cutover (Connect is the cache).

### One-time operator setup (human)

The Connect server's own credentials live in a **dedicated, isolated vault** (`ocp-connect-bootstrap`) — deliberately NOT a vault Connect serves and NOT in the Connect token's scope — read by a **service account scoped read-only to only that vault** for the bootstrap playbook. This keeps the keys-to-Connect out of the operational vaults Connect distributes.

```
op connect server create ocp-hub --vaults ocp-pull,ocp-push,claude
op connect token create eso --server ocp-hub \
  --vault ocp-pull:read --vault ocp-push:read_write --vault claude:read_write
# Store the Connect server's OWN credentials in a SEPARATE privileged vault
# (not ocp-pull/ocp-push/claude, and not in the Connect token scope above):
op document create 1password-credentials.json --vault ocp-connect-bootstrap --title ocp-connect-credentials
op item create --category password --vault ocp-connect-bootstrap --title ocp-connect-token token=<TOKEN>
# Then on 1Password.com → Developer → service accounts: create an SA scoped
# READ-ONLY to ocp-connect-bootstrap only. You paste its token at the playbook's
# vars_prompt at runtime — it is NOT stored in any vault the playbook reads.
```

### Bootstrap changes (`igou-ansible` `playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`)

Chicken-egg: ESO needs Connect; Connect needs its credentials Secret; that Secret can't come from ESO. The seed stays **imperative** (same pattern as today's SDK token), just different contents:

- Remove the `onepassword_tokens` loop that creates `1password-token` SDK Secrets.
- Create namespace `onepassword-connect`.
- Phase-1 client (`op` CLI, authenticated as the **read-only `ocp-connect-bootstrap` service account** via `OP_SERVICE_ACCOUNT_TOKEN` **prompted at runtime with `vars_prompt`**) reads the `ocp-connect-credentials` document + `ocp-connect-token` from that dedicated vault and creates:
  - `op-credentials` (`1password-credentials.json`) in `onepassword-connect`,
  - `onepassword-connect-token` (`token`) in `external-secrets-operator`.
- Connect comes up at wave 0/1 (serves HTTP :8080 — no cert dependency), ESO stores go Ready.
- **Remove the SDK rate-limit `resourceHealthChecks` Lua overrides** from the embedded ArgoCD config once cutover is verified (they now hide real failures).

### Ansible steady-state (phase 2)

`ansible-galaxy collection install onepassword.connect`; configure via `OP_CONNECT_HOST=https://onepassword-connect.apps.ocp.igou.systems` + `OP_CONNECT_TOKEN`. No custom CA (LE is publicly trusted). Module-based (`field_info`/`item_info`/`generic_item` + `register`) — no inline `lookup()`. Optionally migrate `sync_1pasword_secrets.yml` writes to `onepassword.connect.generic_item`; otherwise it keeps the `op` CLI.

## Migration runbook (big-bang)

0. One-time `op connect server/token create`; store credentials + token in a dedicated `ocp-connect-bootstrap` vault and create a read-only service account scoped to only that vault.
1. Add `components/onepassword-connect/`; wire into app-of-apps at an early wave. Resolve SCC (1b).
2. Rewrite the 3 ClusterSecretStores in place.
3. Edit `bootstrap_gitops.yaml` (seed creds/token; drop SDK seed + SDK health-check override).
4. Cut over & verify: stores `Ready`, ExternalSecrets `SecretSynced`, a PushSecret still writes.
5. Decommission SDK token Secrets; retire surplus service accounts.
6. Measure propagation latency; lower `refreshInterval`; remove per-store `cache`.

## Risks

- **Big-bang blast radius** (High): every secret depends on Connect at cutover. ESO retains last-synced values on a blip; validate stores Ready + a PushSecret before deleting SDK seeds; keep break-glass SA.
- **Chart UID 999 vs restricted-v2 + #282** (High): resolve via step 1b; validate pod starts.
- **Plaintext in-cluster** (Low–Med): accepted on SNO (on-host, NetworkPolicy-gated, token-authed); revisit multi-node (IPsec or reencrypt).
- **Undocumented propagation latency** (Med): measure; don't promise an SLA.

## Open questions (verify on deployment)

- Does `connect-sync` upstream traffic count against the Personal/Families 24h aggregate? (Docs silent; watch `op service-account ratelimit`.)
- Exact connect-sync interval (measure with a throwaway item).
- Connect chart's actual pod label for the NetworkPolicy selector.
- Whether granting Connect a new vault needs a token refresh/restart.
