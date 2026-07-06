# Secrets vault migration — `awx` → per-entity Connect tokens + context vaults

Status: **PLAN / in progress.** Authored 2026-07-06.

Migrates the homelab off the monolithic `awx` (and shrinks `ocp-pull`/`ocp-push`)
onto a model where each **consuming entity** holds a single 1Password **Connect
token** scoped to only the vaults it needs, and secrets live in **context
vaults** named for the data they hold. This runbook spans four repos:
`igou-openshift`, `igou-openshift-remote-tenant`, `igou-kubernetes`,
`igou-inventory`/`igou-ansible`, plus `igou-devenv`.

**End goal:** `awx` holds nothing; dynamic items (SA tokens) are written by their
owner (OpenShift → `lab_serviceaccounts`) and read by consumers.

---

## 1. Target model

### Entities and vault grants (from `~/.op-migration-PERMISSIONS`)

| Entity | Reads | Read/Writes | Consumes via |
|---|---|---|---|
| **openshift** | lab_aap, lab_agents, lab_container_registries, lab_external_api_keys, lab_forgejo, lab_github, lab_redhat, lab_rk8s, lab_routeros, lab_s3, lab_truenas, ocp-pull | claude, lab_openshift, lab_serviceaccounts, ocp-push | ESO ClusterSecretStores on the OCP hub |
| **rk8s** | claude, lab_agents, lab_external_api_keys, lab_forgejo, lab_github, lab_s3, lab_serviceaccounts | lab_rk8s | ESO on the rk8s cluster (Connect host = OCP route) |
| **aap** | claude, lab_agents, lab_container_registries, lab_external_api_keys, lab_github, lab_openshift, lab_redhat, lab_routeros, lab_serviceaccounts, lab_ssh, lab_truenas, lab_unifi, ocp-pull, ocp-push, `awx`* | lab_aap, lab_forgejo, lab_rk8s, lab_s3 | AAP Connect credential (job env `OP_CONNECT_*`) |
| **vscode** | ocp-pull, `awx`* | claude, lab_* (all), ocp-push | devcontainer `op` CLI |

`*` `awx` read is **transitional only** — removed in Phase 5.
`homelab services` is **out of scope**; nothing is placed there.

### Design decisions (locked 2026-07-06)

1. **Entity tokens already minted** — this runbook seeds them into 4 sinks and repoints; it does not create them.
2. **Store topology = one ClusterSecretStore per vault** (explicit single-vault ref), matching how OCP already works. No multi-vault priority stores (they resolve by item title across vaults = collision/security hazard).
3. **Leave-as-placed for semantic edge cases** — the `truenas` item is OpenShift's CSI driver config and **stays in `lab_openshift`**; `tailscale-oauth` stays in `lab_openshift` ("openshift's tailscale oauth key"). Split later only if a value turns out to be shared.
4. **All ServiceAccount tokens → `lab_serviceaccounts`**, including the kubevirt `ocp-virtualmachine-ops` token. This **supersedes** the just-merged `igou-inventory#133` (which moved it `awx`→`ocp-push`); it moves once more to its final home.
5. **Quay `config-bundle-secret` lives entirely in `lab_openshift`** — co-locate `quay-user-rustfs-cold` there (with `quay-pg-credentials` + `quay-clair-pg-credentials`) so the one ExternalSecret reads a single vault. Resolves the Quay span blocker.
6. **Entity tokens are created and stored in the `ocp-connect-bootstrap` vault.** Seeding them into the 4 sinks is a **separate job**, out of scope for this migration. (The migration SA token cannot read `ocp-connect-bootstrap`.)
7. **Tailscale is deferred** — `tailscale-oauth` (OpenShift ES) and the rk8s tailscale ES stay on their current vaults until the entity tokens are re-minted with finer granularity. This defers the bulk of Phase 2 (rk8s's only live ES is tailscale).
8. **`pikvm` is out of scope** (user) — `awx` retains it as an accepted exception; not a migration blocker.

---

## 2. Authoritative item → target-vault map

Organized by target vault. **copy** = item not yet in the target vault (Phase 0);
**dupe** = duplicate title to resolve before wiring the store.

### `lab_openshift` (openshift RW · aap R)
casval_bmc, gotify-admin, gotify-bridge-token, guacamole-postgres, htpasswd,
minecraft-secrets, open-webui-secrets, quay-pg-credentials,
quay-clair-pg-credentials, rhdh-backend-secret, rhdh-postgres-credentials,
tekton-chains-signing, **truenas** (CSI driver config),
**quay-user-rustfs-cold** *(copy from lab_s3 — co-locate for the Quay config-bundle ES, decision 5)*,
**tailscale-oauth** *(DEFERRED — decision 7)*,
searxng-secrets *(copy from ocp-pull)*, n8n-secrets *(LOCATE — not found in any
vault)*, dns-token *(dedupe vs lab_external_api_keys)*, slack_notification_password
*(dedupe vs lab_external_api_keys)*. **⚠ `hub-cluster-read-only` ×2 — delete the dup.**

### `lab_redhat` (openshift R · aap R)
redhat-login, redhat_pullsecret, rh-automationhub-credentials, rhsm-api,
rhsm *(⚠ ×2 — delete the dup)*.

### `lab_container_registries`
quay, ci-quay-shared, igou-quay, igouvscodeserver_quay_robot, redhat-registry.

### `lab_forgejo`
ci-forgejo-igou-ansible, forgejo-admin, gitea-mirror-forgejo-pat,
gitea-admin *(LOCATE — not found anywhere; verify app live)*.

### `lab_github`
gitea-mirror.

### `lab_s3`
routeros-backups-rustfs-cold,
cnpg-s3-backup *(copy from ocp-pull — consumed by forgejo/quay/rhdh/temporalio)*.
*(`quay-user-rustfs-cold` relocates to `lab_openshift` for the Quay config-bundle — decision 5.)*

### `lab_routeros`
mktxp-exporter, crs310-api, crs317-api, crs328-api, rb5009-api *(copy all 4 device items from awx)*.

### `lab_external_api_keys`
acme-key, awx-inventory-key, awx-terraformer, mullvad_key, terraform,
sg-updater, slackurl, tailscale-oauthkey-pettingzoo,
tailscale-ansible-vps-token *(copy)*, cloudflare-dns-token-igou-io *(copy)*,
dns-token / slack_notification_password *(dedupe — pick one home vs lab_openshift)*.

### `lab_aap` (aap RW)
aap, aap-admin-password, igou-inventory-awx-github-pat,
aap-eda-alertmanager-event-stream-token *(copy from ocp-pull)*,
vault *(copy — ansible-vault password)*,
aap_ansiblecfg *(CREATE — missing everywhere; lookup already failing)*.

### `lab_ssh`
ansible-ssh-ed25519, ansible-ssh-rsa2048, ansible-ssh-rsa4096
*(currently in lab_aap; move here, OR keep in lab_aap and skip lab_ssh — aap reads both. Field parity: ed25519 field is `private key-openssh`, rsa is `private key`).*

### `lab_agents`
hermes, opencode-go-api-key *(copy both from awx)*.
*(openrouter-*/claude-* agent keys already live in `claude`; leave them.)*

### `lab_serviceaccounts` (openshift W · aap/rk8s R)
ocp-virtualmachine-ops, ns-agent, ocp-cluster-read-only, ocp-cluster-edit,
ocp-claude-edit, ocp-ansible-molecule *(all written by OCP PushSecrets)*,
molecule-testing-onepassword-token *(copy)*. Currently EMPTY — PushSecrets create these.

### `lab_truenas`
romm *(already there; truenas CSI config stays in lab_openshift per decision 3)*.

### `lab_unifi`
igou, igou_admin, igou_iot, unifi *(unifi copy from awx; not referenced in scanned repos — verify consumer before deleting awx copy)*.

### `claude` (KEPT — kubeconfigs + edit tokens)
ocp-*/hub-*/rk8s/rosa kubeconfigs & edit tokens, openrouter-*, github tokens,
sands-of-time-basic-auth, upsmonitor-nut, igou-dev-github-app. No change except
the 4 SA-token items that move to `lab_serviceaccounts` (readers follow — §5).

### `ocp-pull` / `ocp-push` (RETAINED, shrinking)
`ocp-pull` keeps `1password-connect-token`, `aap-eda-...` (until copied). `ocp-push`
empties once its 2 PushSecrets repoint to `lab_serviceaccounts`.

---

## 3. Store topology to build

### OpenShift (`clusters/ocp/external-secrets-operator/`) — replace 3 stores with per-vault stores
All share `connectHost: http://onepassword-connect.onepassword-connect.svc:8080`
and the **openshift-entity** Connect token in secret `onepassword-connect-token`
(key `token`, ns `external-secrets-operator`).

Read stores: `…-lab-openshift`, `…-lab-redhat`, `…-lab-container-registries`,
`…-lab-forgejo`, `…-lab-github`, `…-lab-s3`, `…-lab-routeros`,
`…-lab-external-api-keys`, `…-lab-aap`, keep `…-ocp-pull` (transitional).
Write stores: `…-lab-serviceaccounts` (RW), `…-lab-openshift` (RW), `…-ocp-push`
(transitional). Add each to that dir's `kustomization.yaml`.

### rk8s (`igou-kubernetes/components/external-secrets-operator/`)
Delete the multi-vault `onepassword` store. Create per-vault stores for the rk8s
grants (`claude`, `lab_agents`, `lab_external_api_keys`, `lab_forgejo`,
`lab_github`, `lab_rk8s`, `lab_s3`, `lab_serviceaccounts`), all pointing at the
OCP Connect route with the **rk8s-entity** token. **DEFERRED (decision 7):** the
only live rk8s ES is `operator-oauth` (tailscale), so the store swap + repoint
waits until the entity tokens are re-minted; until then rk8s keeps the current
multi-vault store.

### remote-tenant
Same store set as OpenShift. PushSecrets are 5 standalone files under
`clusters/ocp/service-accounts/` (no `ns-agent`) — repoint each `secretStoreRef`.

---

## 4. Phased execution

**Phase 0 — Prerequisites (no repoints; nothing breaks)**
- Copy the **copy**-flagged items into their target vaults *with exact field-name parity* (§6 risk 5). Use the migration SA token.
- **De-dupe**: delete `lab_openshift/hub-cluster-read-only` dup, `lab_redhat/rhsm` dup; resolve `dns-token` & `slack_notification_password` cross-vault dups (pick one home).
- **Locate/fix already-broken items**: `gitea-admin`, `n8n-secrets`, `aap_ansiblecfg`, devenv `github`/`k8s-internal`, the `minecraft` store typo (`onepassword-sdk-ocp`) + malformed `apiVersion`.

**Phase 1 — OpenShift** — build per-vault stores, seed openshift token, repoint every ES + PushSecret, resolve the two multi-vault-span blockers (§6 risk 2). One PR; verify stores Valid + apps Synced.

**Phase 2 — rk8s (DEFERRED, decision 7)** — swap store set, seed rk8s token, repoint tailscale ES. Waits on entity-token re-mint; rk8s's only live ES is tailscale.

**Phase 3 — AAP/Ansible** — re-mint AAP Connect credential 16 with the aap scope; flip `vault='awx'`→`vault='lab_*'` in `auth.yml`, `credentials.yml`, `workflows.yml`, `notifications.yml`, `hermes.yml`, host_vars, and the routeros/tailscale/rhsm/terraform/letsencrypt playbooks. **Keep `request_timeout: "30"`.** Verify with `onepassword_smoke_test` JT, then `aap_configure_all`.

**Phase 4 — devcontainer** — seed vscode token; repoint `igou-devenv/envs/*.env` (`op://awx/…`→`op://lab_*/…`).

**Phase 5 — Decommission** — remove `awx` read grants from aap/vscode; delete migrated `awx` items; retire legacy stores + `onepassword-sdk-*-token` items; fix docs that still name `awx` / the drifted bootstrap playbook.

---

## 5. Reader-follows-writer coupling (SA token move)

Four items move `claude` → `lab_serviceaccounts` because they are PushSecret
targets: `ocp-cluster-read-only`, `ocp-cluster-edit`, `ocp-claude-edit`,
`ocp-ansible-molecule`. Any reader must repoint too — known readers:
`igou-devenv/envs/ocp-hub-cluster-reader.env`, `…-cluster-edit.env`,
`…-claude-edit.env`, `ocp-hub-ansible-molecule*.env`, and the molecule scenarios.
Confirm each before deleting the `claude` copy.

---

## 6. Risks / things to get right

1. **Token bootstrap — HANDLED separately.** The 4 entity tokens are created and stored in the `ocp-connect-bootstrap` vault; seeding them into the 4 sinks (OCP secret, rk8s secret, AAP cred 16, devcontainer host file) is a **separate job**, out of scope here. Note the migration SA token cannot read `ocp-connect-bootstrap`, so token handling can't be done from this migration's tooling. Still recommend the seed job be folded into `bootstrap_gitops.yaml` so a rebuild seeds all 4.
2. **ExternalSecrets can't span vaults.** An ES has one store → one vault.
   - **Quay `config-bundle-secret`** — RESOLVED (decision 5): all 3 items (`quay-user-rustfs-cold`, `quay-pg-credentials`, `quay-clair-pg-credentials`) live in `lab_openshift`; single store.
   - **pac-tenant chart** — STILL OPEN: emits 3 ES across `lab_forgejo`+`lab_container_registries`+`lab_redhat` from one `secretStore.name`. Needs a per-secret store override (chart change) or the 3 items co-located.
3. **Duplicate item titles already exist** (`lab_openshift/hub-cluster-read-only ×2`, `lab_redhat/rhsm ×2`). Connect resolves by title → duplicate breaks that title. Fix in Phase 0.
4. **rk8s DEFERRED (decision 7).** When taken up: rk8s loses `awx`+`ocp-pull` read, so `tailscale-oauth` (only in `ocp-pull`) must be copied to `lab_external_api_keys` first, and future `democratic-csi-*-config` secrets must go to `lab_rk8s` (rk8s has no `lab_truenas`).
5. **Field-name parity on copy** — non-obvious fields must be reproduced exactly: `ansible-ssh-ed25519` = `private key-openssh`; `acme-key` = `key.b64`; `awx-inventory-key`/github PAT = `credential` (not `password`); `romm`/`terraform`/`mktxp-exporter`/`routeros-backups-rustfs-cold` multi-field. A renamed field silently empties the credential.
6. **kubevirt token third move** — going straight to `lab_serviceaccounts`; supersede `igou-inventory#133`.
7. **Cross-cluster coupling unchanged** — rk8s ESO still depends on the OCP Connect route; new token doesn't decouple it.
8. **Benefit** — the openshift token's RW on `lab_serviceaccounts`/`ocp-push`/`claude` **fixes** the long-standing PushSecret 403 (previously masked by a live-only ArgoCD health-check). Verify pushes succeed post-cutover and retire the health-check hack.
9. **`vault` item still live** — the AAP `Vault` credential reads it; copy to `lab_aap` or the credential breaks even though inline `!vault` vars appear retired.
10. **Always keep the explicit `vault=` argument** on every Ansible lookup — never rely on Connect title resolution across an entity's multiple readable vaults.

See §8 for permission gaps (grant vs. actual code behavior).

---

## 7. Verification per phase

- 1Password: `op vault list` / `op item get <item> --vault <v>` under each entity token proves scope + field parity.
- OpenShift/rk8s: `oc get clustersecretstore` → all `Ready=True`; `oc get externalsecret -A` → `SecretSynced`; `oc get pushsecret -A` → `Synced`; ArgoCD apps `Synced/Healthy`.
- AAP: `onepassword_smoke_test` JT green per vault, then `aap_configure_all` (JT 41) `successful`, kubevirt inventory source syncs.
- devcontainer: `op read op://lab_*/…` resolves under the vscode token.

---

## 8. Permission gaps (grant in `~/.op-migration-PERMISSIONS` vs. what the code does)

Places where an entity's granted scope doesn't match its actual behavior. **G** = gap
that will fail; **O** = over-grant (works, but broader than needed — tighten later).

| # | Entity | Operation | Vault | Needs | Granted | Type | Resolution |
|---|---|---|---|---|---|---|---|
| 1 | **aap** | write `op://claude/<cluster>-kubeconfig` (`publish-kubeconfig-1password.yaml`, `install-k3s-cluster.yml`) | claude | **Write** | Read | **G** | Run the publish jobs under the **vscode** or **openshift** token (claude RW), or grant aap claude Write. Decide which entity owns kubeconfig publishing. |
| 2 | **aap** | write SA tokens (`sync_1pasword_secrets.yml` → today writes to `awx`) | lab_serviceaccounts | **Write** | Read | **G** | **Retire this write path** — OpenShift PushSecrets own SA-token writes to `lab_serviceaccounts`. aap only needs Read there (which it has). Do not repoint `sync_1pasword_secrets.yml` to lab_serviceaccounts; delete/disable it. |
| 3 | **rk8s** | any future PushSecret (SA token / generated secret) | lab_serviceaccounts | Write | Read | **G (latent)** | rk8s can only write `lab_rk8s`. Route any rk8s-originated write to `lab_rk8s`, never `lab_serviceaccounts`. |
| 4 | **rk8s** | resolve `tailscale-oauth` after cutover | lab_external_api_keys | item present | item only in `ocp-pull` today | **G (deferred)** | Copy `tailscale-oauth` → `lab_external_api_keys` before the rk8s store swap (Phase 2, deferred per decision 7). |
| 5 | **aap** | Read `claude/<cluster>-kubeconfig` (bootstrap-gitops kubeconfig lookup) | claude | Read | Read | OK | No gap — read side is fine; only the write (gap 1) is the problem. |
| 6 | **aap** | RW granted on `lab_forgejo`, `lab_rk8s`, `lab_s3`, `lab_aap` | those vaults | mostly Read (no in-repo writes found except lab_s3 backups, which write S3 not 1P) | Read/Write | **O** | Tighten to Read once confirmed no AAP job writes 1P items there. `lab_forgejo` RW may be intended for future CI item creation — leave if so. |
| 7 | **vscode** | broad RW across all `lab_*` + claude + ocp-push | all | interactive/dev reads; writes only during migration + item authoring | Read/Write | **O** | Acceptable for the human dev entity; it is also the entity that performs Phase 0 copies. Keep RW. |
| 8 | **openshift** | PushSecret writes | claude, ocp-push, lab_serviceaccounts | Write | RW | OK | No gap — this is what fixes the historical PushSecret 403. |
| 9 | **all** | read `ocp-connect-bootstrap` (where the 4 entity tokens live) | ocp-connect-bootstrap | n/a (bootstrap-only) | not granted to any entity (by design) | OK | Correct — bootstrap vault must stay outside the entity model. Seed job uses a dedicated bootstrap SA, not an entity token. |
| 10 | **aap/vscode** | transitional `awx` Read | awx | Read (until Phase 5) | Read | OK→remove | Remove the awx Read grant in Phase 5 once every awx item is migrated + verified. This grant existing is the only thing keeping un-migrated lookups alive — pulling it early fails jobs closed. |

**Net blocking gaps to resolve before/within their phase:** #1 (kubeconfig publish owner), #2 (retire AAP SA-token write path), #4 (tailscale copy, when un-deferred). #3 is latent (no rk8s writes today). The rest are over-grants to tighten opportunistically.
