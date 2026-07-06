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

---

## 2. Authoritative item → target-vault map

Organized by target vault. **copy** = item not yet in the target vault (Phase 0);
**dupe** = duplicate title to resolve before wiring the store.

### `lab_openshift` (openshift RW · aap R)
casval_bmc, gotify-admin, gotify-bridge-token, guacamole-postgres, htpasswd,
minecraft-secrets, open-webui-secrets, quay-pg-credentials,
quay-clair-pg-credentials, rhdh-backend-secret, rhdh-postgres-credentials,
tekton-chains-signing, **truenas** (CSI driver config), **tailscale-oauth**,
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
quay-user-rustfs-cold, routeros-backups-rustfs-cold,
cnpg-s3-backup *(copy from ocp-pull — consumed by forgejo/quay/rhdh/temporalio)*.

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
OCP Connect route with the **rk8s-entity** token. Repoint the one ES
(`operator-oauth` → `…-lab-external-api-keys`).

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

**Phase 2 — rk8s** — swap store set, seed rk8s token, repoint tailscale ES. Small PR.

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

1. **New chicken-egg ×4.** Per-entity tokens still need out-of-band seeding into 4 sinks (OCP secret, rk8s secret, AAP cred 16, devcontainer host file). Decide where each token is durably stored (the `ocp-connect-bootstrap` vault is not in the model) and **fold the seeding into `bootstrap_gitops.yaml`**, or a rebuild multiplies today's pain by 4.
2. **ExternalSecrets can't span vaults.** An ES has one store → one vault. **Quay `config-bundle-secret`** reads 3 items across `lab_s3`+`lab_openshift`; the **pac-tenant chart** emits 3 ES across `lab_forgejo`+`lab_container_registries`+`lab_redhat` from one `secretStore.name`. Co-locate the items in one vault, or split into per-vault ES (chart change). Quay gates on it.
3. **Duplicate item titles already exist** (`lab_openshift/hub-cluster-read-only ×2`, `lab_redhat/rhsm ×2`). Connect resolves by title → duplicate breaks that title. Fix in Phase 0.
4. **rk8s loses `awx`+`ocp-pull` read.** Its one live secret `tailscale-oauth` is only in `ocp-pull` → copy to `lab_external_api_keys` or rk8s degrades at cutover. Future `democratic-csi-*-config` secrets must go to `lab_rk8s` (rk8s has no `lab_truenas`).
5. **Field-name parity on copy** — non-obvious fields must be reproduced exactly: `ansible-ssh-ed25519` = `private key-openssh`; `acme-key` = `key.b64`; `awx-inventory-key`/github PAT = `credential` (not `password`); `romm`/`terraform`/`mktxp-exporter`/`routeros-backups-rustfs-cold` multi-field. A renamed field silently empties the credential.
6. **kubevirt token third move** — going straight to `lab_serviceaccounts`; supersede `igou-inventory#133`.
7. **`pikvm` has no home** (BMC/KVM cred, `sno_iso_provision.yml`). Blocks "awx = nothing" until placed.
8. **`claude` write gap for AAP** — `publish-kubeconfig-1password.yaml` *writes* `op://claude/<cluster>-kubeconfig` but aap has claude Read only. Confirm it runs under openshift/vscode (claude RW) or grant.
9. **Cross-cluster coupling unchanged** — rk8s ESO still depends on the OCP Connect route; new token doesn't decouple it.
10. **Benefit** — the openshift token's RW on `lab_serviceaccounts`/`ocp-push`/`claude` **fixes** the long-standing PushSecret 403 (previously masked by a live-only ArgoCD health-check). Verify pushes succeed post-cutover and retire the health-check hack.
11. **`vault` item still live** — the AAP `Vault` credential reads it; copy to `lab_aap` or the credential breaks even though inline `!vault` vars appear retired.
12. **Always keep the explicit `vault=` argument** on every Ansible lookup — never rely on Connect title resolution across an entity's multiple readable vaults.

---

## 7. Verification per phase

- 1Password: `op vault list` / `op item get <item> --vault <v>` under each entity token proves scope + field parity.
- OpenShift/rk8s: `oc get clustersecretstore` → all `Ready=True`; `oc get externalsecret -A` → `SecretSynced`; `oc get pushsecret -A` → `Synced`; ArgoCD apps `Synced/Healthy`.
- AAP: `onepassword_smoke_test` JT green per vault, then `aap_configure_all` (JT 41) `successful`, kubevirt inventory source syncs.
- devcontainer: `op read op://lab_*/…` resolves under the vscode token.
