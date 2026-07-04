# Component Health & Functionality Reviews — post-2026-07-03 rebuild

> Companion to [`2026-07-03-ocp-disaster-recovery.md`](./2026-07-03-ocp-disaster-recovery.md).
> One section per app-of-apps component, authored by a dedicated Opus 4.8 reviewer:
> a read-only health check of the live cluster plus a functionality review of the
> git config, focused on whether each component correctly recovered the rebuild.

## Contents
- [alertmanager-config](#alertmanager-config)
- [ansible-automation-platform](#ansible-automation-platform)
- [apiserver-certs](#apiserver-certs)
- [apiserver](#apiserver)
- [cert-manager-config](#cert-manager-config)
- [cloudnative-pg](#cloudnative-pg)
- [cluster-api-autoscaler](#cluster-api-autoscaler)
- [cluster-api-operator](#cluster-api-operator)
- [cluster-api](#cluster-api)
- [democratic-csi](#democratic-csi)
- [external-secrets-operator](#external-secrets-operator)
- [firecrawl](#firecrawl)
- [forgejo](#forgejo)
- [gateway-api](#gateway-api)
- [gitea-mirror](#gitea-mirror)
- [gotify](#gotify)
- [grafana](#grafana)
- [hermes-agent](#hermes-agent)
- [image-registry](#image-registry)
- [ingresscontroller-certs](#ingresscontroller-certs)
- [intel-device-plugins-operator](#intel-device-plugins-operator)
- [jellyfin](#jellyfin)
- [kubeletconfig](#kubeletconfig)
- [llmkube](#llmkube)
- [loki-operator](#loki-operator)
- [lvms-operator](#lvms-operator)
- [machineconfigs](#machineconfigs)
- [metallb](#metallb)
- [molecule](#molecule)
- [nmstate](#nmstate)
- [nvidia-gpu-operator](#nvidia-gpu-operator)
- [ocp-base-config](#ocp-base-config)
- [onepassword-connect](#onepassword-connect)
- [openshift-logging](#openshift-logging)
- [openshift-nfd](#openshift-nfd)
- [openshift-pipelines](#openshift-pipelines)
- [openshift-virt](#openshift-virt)
- [pac-tenants](#pac-tenants)
- [quay-operator](#quay-operator)
- [remote-tenants](#remote-tenants)
- [rhdh](#rhdh)
- [searxng](#searxng)
- [service-accounts](#service-accounts)
- [tailscale-operator](#tailscale-operator)
- [udn](#udn)
- [user-workload-monitoring](#user-workload-monitoring)

---

## alertmanager-config

**Status:** degraded

The component's own resources recovered cleanly from the rebuild (ArgoCD Synced/Healthy on origin/main HEAD `d81e454`, both ExternalSecrets synced, the `alertmanager-main` config Secret applied via `Replace=true`, and the running Alertmanager loaded a config byte-identical to git). However, **2 of the 3 notification sinks it fans out to are dead because their upstream dependencies were never restored post-disaster**, so alerts are actively failing to deliver.

### Scope

- Namespace: `openshift-monitoring`. Manages the platform `alertmanager-main` config Secret (`secretGenerator`, `disableNameSuffixHash`, `Replace=true`) plus two ExternalSecrets: `alertmanager-slack-bot-token` and `alertmanager-eda-event-stream` (ClusterSecretStore `onepassword-sdk-ocp-pull`).
- Pod `alertmanager-main-0` 6/6 Running on hpg5, 0 restarts, StatefulSet 1/1. Secret mounts (`alertmanager-eda-event-stream/{url,token}`, `alertmanager-slack-bot-token/password`) present and wired via `cluster-monitoring-config` `alertmanagerMain.secrets` (a separate component, verified present).

### Findings

- **[HIGH] Default `gotify` receiver + gotify leg of critical/warning receivers are broken — NXDOMAIN.** The config's catch-all `route.receiver: gotify` and the webhook in `gotify-and-slack-critical`/`gotify-and-slack-warning` all POST to `http://alertmanager-gotify-bridge.gotify.svc:8080/gotify_webhook`. The **`gotify` namespace/service does not exist**: DNS returns NXDOMAIN and Alertmanager logs are full of `notify retry canceled after 15/16 attempts ... lookup alertmanager-gotify-bridge.gotify.svc ... no such host`. Root cause: the **`gotify` ArgoCD Application was never created** — it is defined in git (`clusters/ocp/values.yaml:346`, path `applications/gotify`, sync-wave 20) but is absent from the 44 live apps, because `root-applications` is still `OutOfSync/Progressing` and hasn't reconciled it. Not this component's own defect, but it means all push notifications and any alert without a severity label (→ default receiver) are lost.
- **[HIGH] Critical/warning delivery degraded even to the healthy Slack sink (fanout coupling).** Because the gotify webhook and Slack live in the *same* receivers, the gotify NXDOMAIN failure makes the whole receiver fanout return error; Alertmanager retries the entire receiver (re-sending to Slack → duplicate Slack messages) and ultimately cancels the notification after ~15 attempts, so grouped critical/warning alerts are dropped. Slack is the only potentially-working sink but its reliability is dragged down by the dead gotify leg.
- **[HIGH] `eda-github-issue` receiver failing HTTP 503.** The receiver POSTs to `https://automation.apps.ocp.igou.systems` (from the `alertmanager-eda-event-stream` secret `url`); Alertmanager logs show 13+ `unexpected status code 503` with the OpenShift router "Application is not available" page — the backing AAP/EDA event-stream Route has no endpoints. There is **no `aap`/`eda`/`automation` ArgoCD app in this cluster**, so the EDA→GitHub-issue pipeline (per the EDA Alertmanager→GitHub memory) is down; no auto-issues are being filed for firing alerts.
- **[LOW] Transient ArgoCD ComparisonError on this app.** `alertmanager-config` shows a condition `ComparisonError: Failed to load target state ... context deadline exceeded` (repo-server manifest-gen timeout) even though it reports Synced/Healthy on the correct revision. Cosmetic/intermittent, likely repo-server load during the rebuild; monitor.
- **[INFO] The component itself is correctly configured and drift-free.** Synced revision == origin/main HEAD; the Alertmanager-loaded config exactly matches git (Watchdog/AlertmanagerReceiversNotConfigured null-routed, the `AlertmanagerFailedToSendAlerts integration=webhook` self-referential null-route present, inhibit rules and severity fan-out intact); ExternalSecrets both `SecretSynced/Ready=True`; the `Replace=true` strategy and Connect-empty-field `password`-only pull are working as designed. It recovered its own state correctly.

### Remediation

1. **Restore the `gotify` application (root cause of the HIGH gotify failures).** Investigate/repair `root-applications` (OutOfSync/Progressing) so the sync-wave-20 `gotify` Application is created; then confirm `alertmanager-gotify-bridge.gotify.svc:8080` resolves and the NXDOMAIN log spam stops. Owner: gotify application / app-of-apps, not this component.
2. **Restore the AAP/EDA event-stream endpoint** backing `https://automation.apps.ocp.igou.systems` so `eda-github-issue` stops returning 503 and the alert→GitHub-issue pipeline resumes. Confirm the Route/Service exists post-rebuild.
3. **(Hardening) Decouple Slack from gotify** in `alertmanager.yaml`: put the gotify webhook and Slack in separate receivers (or route `continue: true` legs) so a single sink outage can't retry-storm, duplicate Slack messages, or cancel delivery to the healthy sink.
4. **(Low)** If the `ComparisonError`/DeadlineExceeded recurs, raise the ArgoCD repo-server timeout or reconcile; currently non-blocking.

No change to the `alertmanager-config` component's own manifests is required to fix the two HIGH findings — they are unrestored-dependency gaps (gotify app, AAP/EDA), not misconfiguration or drift in this component.

---

## ansible-automation-platform

**Status: not-yet-deployed** (post-rebuild restoration in progress; queued at ArgoCD sync-wave 30, not yet reached)

Git source: `clusters/ocp/ansible-automation-platform/` (app-of-apps entry `clusters/ocp/values.yaml:393`, project `cluster-apps`, sync-wave 30).

### Health check (read-only, observed 2026-07-04 ~02:57–02:59 UTC)

- **The ArgoCD Application `ansible-automation-platform` does not exist** (`oc get applications.argoproj.io ansible-automation-platform -n openshift-gitops` → NotFound). It appears only as a child resource of the app-of-apps `root-applications`, listed **OutOfSync / health=Missing** (`nil->obj` — needs to be created).
- **Nothing AAP is deployed on the cluster**: no `ansible-automation-platform` namespace, no operator Subscription/CSV, no `AnsibleAutomationPlatform` CRD/CR, no pods, no PVCs, no route. The whole stack is absent.
- **Why it isn't there yet:** `root-applications` (automated, prune+selfHeal) is mid-reconciliation after the reinstall and is (re)creating a batch of pruned lower-wave child apps **wave-by-wave, gating on health**. During the observation window it visibly progressed: at 02:57 firecrawl/searxng/jellyfin/llmkube/gotify/gitea-mirror/AAP were all Missing; by 02:59 firecrawl/searxng/jellyfin/gotify/llmkube had been created (searxng/jellyfin/gotify `Progressing` = pods starting), with the operation message `waiting for healthy state of Application/gotify and 1 more`. The sync must clear wave 19→20→22→23 (gitea-mirror still Missing) before it reaches **wave 30, where the AAP Application gets created**. Only then does AAP install (namespace w0 → operator Sub w1 → admin-password ExternalSecret w3 → AAP CR w5).
- Dependencies for AAP are healthy/present: `external-secrets-operator`, `onepassword-connect`, `democratic-csi` apps Synced/Healthy; ClusterSecretStore `onepassword-sdk-ocp-pull` = **Ready/True**; StorageClass `freenas-nvmeof-ssd-csi` (provisioner `org.democratic-csi.nvmeof-ssd`) present. So once the wave is reached, AAP should install cleanly.

### Findings

- **[High] AAP deployment is transitively blocked behind unrelated lower-priority apps.** Because AAP is the highest sync-wave (30) among the currently-Missing child apps, the app-of-apps will only create it *after* firecrawl (w19), searxng/jellyfin/llmkube/gotify (w20), and gitea-mirror (w23) all reach Healthy. If any one of those wedges (image pull, crashloop, stuck Progressing), the app-of-apps sync stalls at that wave and **AAP never gets created**. AAP recovery is coupled to the health of apps it has no functional relationship to.
- **[Medium] app-of-apps not settling — persistent OutOfSync neighbors.** `root-applications` itself is OutOfSync with several always-OutOfSync/Healthy children (forgejo, openshift-pipelines, pac-tenants, quay-operator, rhdh). selfHeal keeps re-triggering; the create-and-gate cycle should still converge, but drift in those apps should be resolved so the app-of-apps can reach a clean synced state and reliably drive wave 30.
- **[Medium] No AAP database restore in the DR path.** The AAP CR uses the operator's *own managed PostgreSQL* (`database.postgres_storage_class: freenas-nvmeof-ssd-csi`, `postgres_data_volume_init: false`) — this is **not CloudNativePG** and was **not** part of the Barman/RustFS restore that recovered quay/rhdh/forgejo. When AAP finally deploys it comes up with a **fresh, empty controller DB**. Controller/EDA state (job templates, projects, inventories, credentials, rulebooks) must be repopulated by **AAP config-as-code** (from igou-inventory / aap-sync), which must be re-run post-deploy. Anything not captured in config-as-code (run history, manually-created objects, issued tokens) is permanently lost. Confirm config-as-code is the source of truth and re-runs; if any AAP DB state is expected to survive DR, a backup mechanism is missing.
- **[Medium] NVMe-oF PVCs exposed to the shared-hostnqn latent bug.** AAP's postgres (and redis) PVCs land on `freenas-nvmeof-ssd-csi`. The known cluster-wide defect (all 3 nodes share the same nvme `hostnqn`/`hostid`, nqn …466937ab…) causes intermittent NVMe-oF volume-attach failures — so AAP's first postgres attach (and any future node reschedule) is at risk of intermittent failure until the hostnqn uniqueness bug is fixed.
- **[Low] `installPlanApproval: Automatic` on channel `stable-2.7`.** Operator auto-upgrades within the channel unattended. Acceptable, but worth being aware of on a freshly reinstalled OCP 4.21.9.
- **[Low / verify] admin password secret key.** The AAP CR sets `admin_password_secret: aap-admin-password`; the ExternalSecret uses `dataFrom: extract` of the 1Password item `aap-admin-password`. The operator expects a `password` key — this worked pre-disaster and the secret store is Ready, so likely fine; verify the 1Password item exposes a `password` field once the ExternalSecret materializes.

### Config assessment (git)

The component definition itself is **correct and unchanged** — nothing in git needs fixing to get AAP running. `hub.disabled: true` / `eda.disabled: false` matches the known EDA-only design (Alertmanager→GitHub issue pipeline); Route + Edge TLS on `automation.apps.ocp.igou.systems`; admin password sourced from 1Password via ExternalSecret (DR-safe, re-hydrates automatically); correct intra-app sync-wave ordering (ns 0 → sub 1 → ES 3 → CR 5) with `SkipDryRunOnMissingResource=true` so the CR applies before its CRD exists. This is a *deployment-ordering / restoration-progress* gap, not a manifest defect.

### Remediation

1. **Let the app-of-apps converge, but watch the gating apps.** Monitor firecrawl (w19), searxng/jellyfin/llmkube/gotify (w20), gitea-mirror (w23) to Healthy; if any wedges, fix/prune it so the sync advances to wave 30. To unblock AAP immediately without waiting on those, an operator could manually sync/create just the AAP Application (out of band) — but the standing fix is to get the earlier waves healthy.
2. **Resolve the persistent OutOfSync neighbors** (forgejo, openshift-pipelines, pac-tenants, quay-operator, rhdh) so `root-applications` settles and reliably drives later waves.
3. **After AAP comes up, re-run AAP config-as-code** (aap-sync from igou-inventory) to repopulate the fresh controller/EDA DB, then verify job templates, EDA rulebook activations (Alertmanager→issue pipeline), and credentials are present. Confirm whether an AAP DB backup is expected as part of DR; if so, add one (it is not covered by the CNPG/Barman restore).
4. **Track the shared nvme hostnqn fix** — AAP postgres on NVMe-oF will be intermittently attach-flaky until nodes get unique hostnqn/hostid.
5. Re-verify AAP once deployed: operator CSV Succeeded, AAP CR `.status` Successful, postgres/redis PVCs Bound, pods Running, and the `automation.apps.ocp.igou.systems` route serving with a valid Edge cert.

---

## apiserver-certs

**Status: healthy**

Component that requests the external API serving certificate for `api.ocp.igou.systems` via cert-manager (ACME/Let's Encrypt). It fully recovered the 2026-07-03 rebuild: the certificate was automatically re-issued during reinstall and the live API endpoint is serving it.

### Scope
- Git source: `clusters/ocp/apiserver-certs/` — a single `cert-manager.io/v1` `Certificate` (`api-certificate`) in namespace `openshift-config`, wired into the app-of-apps at sync-wave 9 (`clusters/ocp/values.yaml`).
- Produces secret `acme-api` (`kubernetes.io/tls`), consumed by the sibling `apiserver` component (`clusters/ocp/apiserver/cluster-apiserver.yaml`) which patches `APIServer/cluster` `spec.servingCerts.namedCertificates` → `acme-api`.

### Health check (live)
- **ArgoCD app `apiserver-certs`: Synced / Healthy** (revision d81e454); single managed resource `Certificate/api-certificate` Synced+Healthy. Sibling app `apiserver` also Synced/Healthy.
- **Certificate `api-certificate`: Ready=True** — "Certificate is up to date and has not expired"; issued ~7h42m ago (during the rebuild), `notAfter 2026-10-01`, `renewalTime 2026-09-16`.
- **CertificateRequest `api-certificate-1`: Ready/Approved**; ACME **Order `api-certificate-1-...`: valid**. **ClusterIssuer `cluster-acme`: Ready=True** (ACME account registered).
- **Secret `acme-api`** present with `tls.crt`/`tls.key`; chain is a genuine Let's Encrypt cert (`O=Let's Encrypt, CN=YR2`).
- **Live functional proof:** `openssl s_client` to `api.ocp.igou.systems:6443` serves `CN=api.ocp.igou.systems`, Let's Encrypt issuer, `notBefore Jul 3 18:40:50 2026` — i.e. the freshly re-issued cert is actually on the wire, not just stored.
- **`kube-apiserver` ClusterOperator:** Degraded=False, Available=True, Progressing=False (revision 8). No crashloops/pending/PVC concerns (component owns no pods/workloads/PVCs/routes).

### Findings
- **[INFO] Disaster recovery complete, no manual restore needed.** Both the `Certificate` CR and its consumer `APIServer/cluster` patch are declarative in git, so GitOps recreated them and cert-manager re-ran the ACME flow automatically after reinstall. Nothing about this component required hand-restoration.
- **[LOW] Latent sync-wave ordering chicken-and-egg.** The consumer `apiserver` patch (references secret `acme-api`) is sync-wave 3, but `apiserver-certs` that creates `acme-api` is sync-wave 9. On a cold install the `APIServer/cluster` object names a serving cert whose secret does not yet exist. OpenShift tolerates this (falls back to the default serving cert until the secret appears), so it self-heals — and did here (cert is live) — but the ordering is inverted relative to the dependency.
- **[LOW/INFO] Issuance depends on the full ACME path staying healthy.** Recovery required a brand-new ACME order (new order observed, valid). Repeated reinstall loops could in principle hit Let's Encrypt rate limits or stall on the DNS/HTTP-01 solver; not observed this time. Renewal is unattended (renewBefore 15d) so no action needed, but this is the component's only real fragility.
- **[INFO] Cert hygiene is good; one superfluous usage.** RSA-4096, `rotationPolicy: Always`, 90d duration / 15d renewBefore. `usages` lists both `server auth` and `client auth`; only `server auth` is needed for an API serving cert — `client auth` is harmless but unnecessary.

### Remediation
- No corrective action required — component is healthy, functional, and correctly recovered.
- Optional hardening: consider raising the `apiserver-certs` sync-wave to precede the consumer `apiserver` component (or accept the documented self-healing behavior), and drop `client auth` from `usages` in `api-cert.yaml`. Both are cosmetic.

---

## apiserver

**Status:** healthy

The `apiserver` component (`clusters/ocp/apiserver`) manages a single cluster-scoped resource: the OpenShift `APIServer/cluster` config CR. Its job is to (a) select the etcd encryption provider and (b) wire a named ACME serving certificate onto the kube-apiserver for `api.ocp.igou.systems`. It fully recovered the rebuild and is verified functional end-to-end.

### Findings

- **[INFO] ArgoCD app Synced + Healthy, zero drift.** `apiserver` app is `Synced`/`Healthy` at revision `d81e454`, source `clusters/ocp/apiserver` (targetRevision HEAD). The live `APIServer/cluster` spec matches git byte-for-byte (`encryption.type: identity`; one `namedCertificate` for `api.ocp.igou.systems` → secret `acme-api`). Only field present live-but-not-in-git is `audit.profile: Default`, which is the API-server default injected by the apiserver-config operator — not real drift, and ArgoCD does not flag it.

- **[INFO] Named ACME serving cert is actually wired, not merely present (functional verification).** The live endpoint `api.ocp.igou.systems:6443` serves `CN=api.ocp.igou.systems` issued by **Let's Encrypt (O=Let's Encrypt, CN=YR2)**, `notBefore Jul 3 18:40:50 2026`, `notAfter Oct 1 18:40:49 2026`. This is the same cert stored in secret `openshift-config/acme-api` (`kubernetes.io/tls`, 2 keys) — confirming the `servingCerts.namedCertificates` override took effect on the running kube-apiserver, not just that the CR was applied. This is the meaningful "functional not just running" check and it passes.

- **[INFO] Post-disaster recovery confirmed.** The serving cert secret is ~7h old and the cert `notBefore` is `Jul 3 18:40`, i.e. re-issued *during* the rebuild window. The supporting `apiserver-certs` app is `Synced`/`Healthy`; its `Certificate openshift-config/api-certificate` (issuer `ClusterIssuer/cluster-acme`, secretName `acme-api`) reports `Ready=True — Certificate is up to date and has not expired`. So the cert-manager → ACME → named-cert chain re-established itself cleanly after the reinstall; no manual restore was needed for this component and none is outstanding.

- **[INFO] kube-apiserver operator fully rolled out.** `clusteroperator/kube-apiserver` = `Available=True, Progressing=False, Degraded=False` (v4.21.9, kube 1.34.6); `NodeInstallerProgressing=False`, single control-plane node at revision 8. The named-cert change is baked into the current rollout, not pending.

- **[LOW — security hardening] etcd encryption at rest is disabled (`encryption.type: identity`).** `identity` is a no-op provider: Secrets, ConfigMaps, ServiceAccount tokens, and OAuth tokens are stored **unencrypted** in etcd. This matches the OpenShift out-of-the-box default (it is *not* a rebuild regression and is exactly what git declares), but it is a deliberate, explicit choice here and leaves data-at-rest unprotected. Given the single-node control plane on MS-01, anyone with disk/etcd-snapshot/backup access to that node can read all cluster secrets in cleartext. Consider switching to `aescbc` (or `aesgcm`) if the threat model includes node-disk / backup exposure.

### Remediation

- No corrective action required for availability — component is healthy, in-sync, and functionally verified.
- (Optional hardening, non-urgent) To enable etcd encryption at rest, set `spec.encryption.type: aescbc` (or `aesgcm`) in `clusters/ocp/apiserver/cluster-apiserver.yaml` and let ArgoCD roll it out. Note this triggers a kube-apiserver + etcd re-encryption rollout and should be done in a maintenance window; verify a fresh etcd/Barman-adjacent backup exists first.
- (Watch item) The ACME serving cert expires `2026-10-01`. Renewal is automated via cert-manager (`api-certificate` Ready), but since the API endpoint's TLS depends on it, confirm cert-manager + the `cluster-acme` ClusterIssuer stay healthy ahead of that date — the same rebuild that just re-issued this cert proves the path works.

---

## cert-manager-config

**Status:** healthy

Declarative component (`clusters/ocp/cert-manager-config`) containing a single `ClusterIssuer` (`cluster-acme`) — a Let's Encrypt **production** ACME issuer using a Cloudflare **DNS-01** solver for the `igou.systems` / `ocp.igou.systems` zones. It fully recovered the rebuild with zero manual intervention and is proven functional end-to-end.

### Health check (live cluster)

- **ArgoCD app:** `cert-manager-config` — **Synced / Healthy**, project `cluster-config`. Synced revision `d81e454` **== origin/main HEAD** (no drift). `spec.source.path` = `clusters/ocp/cert-manager-config`.
- **ClusterIssuer `cluster-acme`:** `Ready=True`, reason `ACMEAccountRegistered` ("The ACME account was registered with the ACME server"), age 7h40m (registered fresh right after reinstall). Live spec matches git exactly (server, email, `dns-token/credential` solver ref, zones) — no manual drift.
- **cert-manager pods** (`cert-manager` ns): controller, cainjector, webhook all `1/1 Running` (a few restarts during the post-reinstall bring-up; stable now).
- **dns-token secret** (Cloudflare API token): present, delivered by an **ExternalSecret** (`onepassword-sdk-ocp-pull` ClusterSecretStore → 1Password), `SecretSynced / Ready=True`; contains the `credential` key that the ClusterIssuer references. (NB: this ExternalSecret is owned by the *cert-manager-operator* app, not this component.)
- **acme-private-key secret:** present (regenerated fresh on reinstall).
- **End-to-end issuance PROVEN — 3 real LE production certs issued via `cluster-acme` post-rebuild, all `Ready=True`:**
  - `openshift-config/api-certificate` → `api.ocp.igou.systems`
  - `openshift-ingress/apps-certificate` → `*.apps.ocp.igou.systems`
  - `openshift-ingress/gateway-guest-dmz-tls` → `*.dmz.igou.systems`
  - All Orders in `valid` state, no stuck Challenges; `notAfter 2026-10-01`, `renewalTime 2026-09-16` (proper LE 90-day + 2/3 renewal).
- **Controller logs:** no ACME rate-limit / DNS-solver / auth errors. Only benign optimistic-lock re-queues on unrelated CAPI self-signed certs.

### Findings

1. **[Low / advisory] No staging issuer — DR rate-limit exposure.** Only the LE **production** endpoint is defined (`acme-v02.api.letsencrypt.org`); there is no `letsencrypt-staging` ClusterIssuer. This incident's failure mode was a *reinstall loop*. Each agent-based reinstall re-registers a new ACME account and re-requests the same 3 certs. If a rebuild loop recurs (or multiple rebuilds land in one week), LE production limits — new-account, failed-validation, and 5 duplicate-certs/week — could throttle certificate issuance and leave the API/ingress on the default self-signed certs. It worked cleanly this time, but a staging issuer would de-risk future DR/testing.
2. **[Info / Low] Implicit cross-app dependency for the functional path.** The ClusterIssuer (this app, sync-wave 1) is only *registerable* on its own; actual issuance depends on `dns-token`, delivered by the **cert-manager-operator** app (sync-wave 2) via ESO + 1Password Connect. Since the DNS token is consumed only at challenge-solve time (not at account registration), the wave ordering is harmless and it recovered fine — but the end-to-end issuance path is gated on operator + ESO + 1Password Connect all being healthy. Worth documenting in the DR runbook so a future issuance failure isn't misattributed to this component.
3. **[Info] Redundant dnsZone entry.** `solvers[0].selector.dnsZones` lists both `igou.systems` and `ocp.igou.systems`; the latter is a subdomain of the former and cert-manager matches zones by subdomain, so it is redundant (harmless). `*.dmz.igou.systems` correctly matches via the `igou.systems` entry.
4. **[Info] ACME account key regenerated, not restored — by design.** `acme-private-key` was freshly generated on reinstall rather than restored from backup; correct behavior (ACME accounts are cheap/stateless). The prior LE account is orphaned but harmless — no restore was or is needed for this component.

### Remediation

- **(Low, optional)** Add a `letsencrypt-staging` ClusterIssuer to the component for DR/test issuance so rebuild loops don't consume LE production quota; use it to validate the DNS-01 path before switching to production.
- **(Info)** Document the issuance dependency chain (cert-manager-config → dns-token ExternalSecret from cert-manager-operator → ESO/1Password Connect) in the DR runbook.
- **(Info, cosmetic)** Drop the redundant `ocp.igou.systems` entry from `dnsZones` (no functional impact).
- **No corrective action required for recovery** — the component is fully declarative, self-healed on reinstall, and is verified functional end-to-end.

---

## cloudnative-pg

**Status: healthy**

The CloudNativePG operator and its Barman Cloud backup plugin (the two things this component actually ships) came back cleanly after the reinstall and are not merely running — they are actively performing the post-disaster PITR restores of the dependent databases. ArgoCD app `cloudnative-pg` is **Synced / Healthy**, last operation **Succeeded** (revision `d81e454`).

### What this component is
Git source `clusters/ocp/cloudnative-pg` = namespace `cloudnative-pg` + two remote-referenced components:
- `components/cloudnative-pg` — OperatorGroup (spec `{}` = AllNamespaces), Subscription (`certified-operators`, channel `stable-v1`, `installPlanApproval: Automatic`), a `cnpg-metrics` Service and a ServiceMonitor.
- `components/cloudnative-pg-barman-plugin` — the first-party `plugin-barman-cloud` v0.12.0 (the supported replacement for the deprecated in-tree `barmanObjectStore`), namespace-retargeted from upstream `cnpg-system` to `cloudnative-pg`, with the upstream `runAsUser/runAsGroup: 10001` stripped so OpenShift restricted-v2 SCC can inject a compliant UID.

The actual Postgres `Cluster` CRs live in the consuming components (`quay-enterprise/quay-pg`, `rhdh/rhdh-pg`, `forgejo/forgejo-pg`) — reviewed here only insofar as they prove the operator is functional.

### Live cluster state (read-only)
- **Operator**: CSV `cloudnative-pg.v1.30.0` = `Succeeded`; Subscription `AtLatestKnown`; `cnpg-controller-manager` Deployment 1/1 Running.
- **Barman plugin**: `barman-cloud` Deployment 1/1 Running (`plugin-barman-cloud:v0.12.0`); both cert-manager Certificates `barman-cloud-server` / `barman-cloud-client` = Ready (mTLS gRPC discovery intact after the namespace retarget).
- **Metrics wiring correct**: `cnpg-metrics` Service has a live endpoint (`10.128.0.41:8080`); controller pod carries `app.kubernetes.io/name=cloudnative-pg` and exposes a `metrics` port; ServiceMonitor selector matches.
- **Operator is doing real work**: `rhdh-pg` and `forgejo-pg` = "Cluster in healthy state", READY 1/1 (Barman restores already completed). `quay-pg` is mid-restore (`Setting up primary`) via the `quay-pg-1-full-recovery` job, actively replaying WAL from `s3://cnpg-backups/quay-pg` (LSN advancing ~240 MB / 10 s; sidecar logging continuous "Restored WAL file" — progressing, not stuck).
- No errors in current operator logs; no PVCs owned by this namespace (operator is stateless).

### Findings

- **[INFO] quay-pg restore still in progress (~1h WAL replay), not a component defect.** The operator + Barman plugin are functioning correctly; quay simply has a large WAL chain to replay to reach end-of-WAL. It is advancing steadily and should reach primary on its own. Belongs to the `quay` component's review; noted here as positive proof the plugin's WAL-restore path works. Monitor; do not intervene.
- **[LOW] Both operator pods restarted during the DR bootstrap window, now stable.** `cnpg-controller-manager` (7 restarts) and `barman-cloud` (3 restarts) each last terminated `exitCode 1 / Error` at ~2026-07-03T19:43:37Z — the reinstall/bootstrap churn while the API server / webhooks were still stabilizing. Both have been continuously Running for ~7h since. No action needed; expected DR noise.
- **[LOW] `installPlanApproval: Automatic` let the operator minor-bump to v1.30.0.** The barman-plugin kustomization header still documents "live: 1.29.1", and CNPG in fact auto-upgraded 1.29.x → 1.30.0 (unattended). Fine for a homelab, but an unpinned operator upgrade landing in the middle of a disaster recovery is a latent risk (a bad CSV could stall all three DBs at once). Consider `Manual` approval, or at least pin/track the channel, for change control.
- **[LOW/doc-drift] Stale version comment.** `components/cloudnative-pg-barman-plugin/kustomization.yaml` says "CNPG ... live: 1.29.1"; actual is 1.30.0. Cosmetic; update when convenient.
- **[SECURITY — OK] No gaps found.** OperatorGroup `{}` = AllNamespaces is intentional and required (operator must watch `quay-enterprise`/`rhdh`/`forgejo`). No secrets in git. The SCC-compliance patch (strip `runAsUser/runAsGroup`, keep `runAsNonRoot` + drop-ALL caps + `readOnlyRootFilesystem`) is the correct, minimal change. Backups target `s3://cnpg-backups/*` on RustFS with a 30d retention policy — credentials sourced out-of-band (ExternalSecret in the DB namespaces), not in this component.

### Cross-reference (not owned here)
The DR incident's latent **shared NVMe `hostnqn`/`hostid` across all 3 nodes** can cause intermittent `democratic-csi.nvmeof-ssd` volume-attach failures. CNPG DBs are the heaviest PVC consumers on that SC (quay-pg attached fine this cycle), so a future CNPG pod reschedule could surface the bug as a failed primary attach. Track under the storage/CSI remediation, not this component.

### Remediation
1. **No action required for the operator/plugin** — healthy and functional.
2. **Let `quay-pg` finish** its WAL replay; verify it transitions to `Cluster in healthy state` READY 1/1 and that Quay app reconnects. Only investigate if it plateaus (LSN stops advancing) or the recovery job errors.
3. **(Optional, low)** Switch the Subscription to `installPlanApproval: Manual` (or pin the CSV) to prevent unattended operator upgrades during future recoveries; refresh the stale "1.29.1" comment in the barman-plugin kustomization.
4. **(Track elsewhere)** Fix the shared-`hostnqn` NVMe uniqueness bug so CNPG PVC attaches stay reliable.

---

## cluster-api-autoscaler

**Status:** healthy (functional today; one MEDIUM latent drift risk from the rebuild)

Upstream `registry.k8s.io/autoscaling/cluster-autoscaler:v1.34.0` (digest-pinned) run standalone with `--cloud-provider=clusterapi`, deployed by GitOps (ArgoCD app `cluster-api-autoscaler`, sync-wave 12, project `cluster-config`). It auto-discovers the CAPI `casval-worker` MachineSet (min 0 / max 1) in `openshift-cluster-api` and drives scale-from-zero of the casval burst GPU node.

### Health check (read-only)

- **ArgoCD app:** `Synced` + `Healthy` (revision `d81e454`). No drift.
- **Namespace / workload:** `cluster-api-autoscaler-system` Active. Deployment `1/1` ready (`desired=1 ready=1 avail=1`), pod `Running`, **0 restarts**, up ~3.5h (since the rebuild), scheduled on the control-plane node `ocp.igou.systems` per its nodeSelector/tolerations. No PVCs (stateless — nothing to restore).
- **Leader election:** Lease `cluster-api-autoscaler` held in **kube-system** (holder = current pod, renewing). Note: despite `--leader-elect-resource-namespace=cluster-api-autoscaler-system`, this build parks the lease in kube-system; the RBAC comment already anticipated this and grants it, so it works. The namespace-local `leases` Role is effectively unused.
- **Runtime behavior (logs + status CM):** Node group `MachineSet/openshift-cluster-api/casval-worker (min 0, max 1, replicas 0)` discovered every loop; main loop runs (`No unschedulable pods` → `scale up not needed`, `no scale down candidates`). `cluster-autoscaler-status` ConfigMap in kube-system reports `autoscalerStatus: Running`, clusterWide health `Healthy` (3/3 nodes ready), node group `casval-worker` `Healthy` cloudProviderTarget 0 — proves the kube-system RBAC and write path work.
- **Benign noise (not defects):** `Failed to check cloud provider has instance for hpg5.igou.systems / ocp.igou.systems / truenas-w1: machine not found` — expected, those are agent-installed (non-CAPI) nodes. Also client-side API throttling delays + verbose `--v=4` make the loop ~6.4s and the log chatty.

### Functionality review (git vs live)

- **Recovered the rebuild cleanly.** Component is 100% declarative and holds no state, so GitOps redeployed it with no manual restore — the correct outcome. RBAC, SA, namespace, and the hardened deployment (`runAsNonRoot`, drop ALL caps, `readOnlyRootFilesystem`, seccomp RuntimeDefault, no privilege escalation, `system-cluster-critical`) are all intact and correct. Discovery works because the whole CAPI stack is internally self-consistent on the cluster name `ocp-hb42r`.

- **[MEDIUM] Post-disaster `infrastructureName` drift — documented invariant now violated; scale-up unverified since rebuild.** The reinstall regenerated the OpenShift infra name to **`ocp-m97rd`** (`oc get infrastructure cluster`), but the autoscaler's discovery arg `--node-group-auto-discovery=clusterapi:namespace=openshift-cluster-api,clusterName=ocp-hb42r` — and the whole CAPI stack it depends on (Cluster, MachineSet `cluster.x-k8s.io/cluster-name` label, `cluster-api-cluster-config` ConfigMap) — are still pinned to the **old `ocp-hb42r`**. The repo's own docs state clusterName "**must equal `infrastructure.status.infrastructureName`… Update on reprovision**"; this was not done. It does not break the autoscaler *today* (everything is self-consistent, so discovery + status all work), but: (a) the actual scale-up/provision path has **not been exercised since the disaster** — MachineSet is at 0 and BMH `casval` is `available`/offline; and (b) this is a cross-component coupling trap — the autoscaler hard-codes `ocp-hb42r` in its Deployment args, so if the `cluster-api` component is later corrected to `ocp-m97rd` without updating this arg in lockstep, discovery silently returns zero node groups. Root cause lives in the `cluster-api` component; this component carries a coupled copy.

- **[LOW] Scale-from-zero end-to-end unproven post-rebuild.** The CAPI `Cluster ocp-hb42r` is `Available=False` (`RemoteConnectionProbe` failed, `ControlPlaneAvailable=Unknown`) — the expected "phantom/externally-managed" state for this BYO pattern (control plane is agent-installed, not CAPI-managed; `InfrastructureReady=True`, `Paused=False`, so MachineSet reconciliation is not blocked). The BMH target survived and is `available`. However the MachineSet's own annotation warns of the known first-scale GPU limitation (kubernetes/autoscaler#5278): scale-*from*-zero for `nvidia.com/gpu` pods won't work until casval has been manually scaled to 1 once. Since casval has never come up since the reinstall, a one-shot bootstrap + a real burst-pod scale test is needed before treating autoscaling as operational.

- **[LOW] No metrics scrape.** Container exposes metrics on port 8085 but there is no `Service`/`ServiceMonitor` in the namespace, so Prometheus is not collecting autoscaler metrics — no alerting/visibility on scale events, failed scale-ups, or unschedulable-pod backlog.

### Remediation

1. **Reconcile the CAPI cluster name to the live infra name `ocp-m97rd` (repo-wide, atomic).** Update `clusters/ocp/cluster-api/cluster-config-configmap.yaml` (the single source of truth) **and** the autoscaler's `--node-group-auto-discovery=…clusterName=…` arg in `components/cluster-api-autoscaler/cluster-autoscaler-deployment.yaml` in the same change, then let ArgoCD resync. (Owner: coordinate with the `cluster-api` component review.) If instead a decision is made to keep `ocp-hb42r` permanently, update the comments/README so the "must equal infrastructureName" invariant is no longer misleading.
2. **Prove scale-from-zero once.** Manually scale `casval-worker` to 1 (bootstraps the GPU capacity per #5278), confirm the node joins with the burst taint/labels, then scale back and drive a real Pending burst pod to confirm the autoscaler scales up and back down. Read-only for this review — flag to the operator.
3. **(LOW) Add a `Service` + `ServiceMonitor`** (or PodMonitor) for port 8085 so scale activity and errors are observable in Prometheus.
4. **(Optional cleanup)** Lower `--v=4`→`--v=2` to cut log noise; the unused namespace-local `leases` Role can stay (harmless) since the lease actually lands in kube-system.

---

## cluster-api-operator

**Status: healthy** (operator + providers fully recovered; one Medium functional gap in the downstream CAPI machine-management path that is latent, not this component's file scope)

### Scope
`components/cluster-api-operator` installs the upstream (kubernetes-sigs) **cluster-api-operator** Helm chart (v0.27.0) plus three provider CRs, the SCC/PSA plumbing, and RBAC that OpenShift's built-in CAPI stack would normally supply. It is the *sole* CAPI implementation on this cluster — OpenShift's native `cluster-capi-operator` is not running (`openshift-cluster-api` has **no deployments**, only the csr-approver/node-cleanup cronjobs). The actual machine objects (BareMetalHost, `casval-worker` MachineSet, Metal3MachineTemplate, BMC ExternalSecret) live in the sibling **`cluster-api`** ArgoCD app (`clusters/ocp/cluster-api/`), which is also Synced/Healthy.

### Health check (read-only)
- **ArgoCD app** `cluster-api-operator`: **Synced / Healthy**, rev `d81e454`, `automated.selfHeal: true`.
- **Operator**: `capi-operator-system/capi-operator-cluster-api-operator` 1/1, 0 restarts, on control-plane (`ocp.igou.systems`), 3h30m.
- **Providers — all Ready=True, ProviderInstalled, PreflightChecksPassed:**
  - CoreProvider `cluster-api` **v1.12.7** → `capi-system/capi-controller-manager` 1/1
  - InfrastructureProvider `metal3` **v1.12.4** → `capm3-system/capm3-controller-manager` 1/1
  - IPAMProvider `metal3` **v1.12.4** → `capm3-system/ipam-controller-manager` 1/1
- **Namespaces** capi-operator-system / capi-system / capm3-system Active with `pod-security…/enforce: privileged` labels present; SCC `nonroot-v2` RoleBindings implicitly validated by the fact the UID-65532 controller pods are Running.
- **IPAM CRD SSA patch verified live**: `ipaddressclaims`/`ipaddresses.ipam.cluster.x-k8s.io` expose exactly `v1alpha1(served, not-stored)` + `v1beta1(served, stored)` — the OCP-4.21-payload shape the `providers.yaml` patch targets. No `v1beta2` storage version, so no CVO↔capi-operator SSA conflict. Working as designed.
- **No Warning events** in any of the three namespaces; **no CrashLoopBackOff / Pending**; no PVCs or Routes owned by this component (none expected).

### Findings

**[Medium] Downstream CAPI workload-cluster connection is broken — `ocp-hb42r-kubeconfig` secret missing post-reinstall.**
The `Cluster/ocp-hb42r` (in `openshift-cluster-api`) is `Available=False`:
- `RemoteConnectionProbe=False (ProbeFailed)`, `ControlPlaneAvailable=Unknown (InternalError)`.
- `capi-controller-manager` logs a hard failure every ~30s: `Connect failed … error getting kubeconfig secret: Secret "ocp-hb42r-kubeconfig" not found`.

Root cause: the cluster-cache kubeconfig Secret is normally minted by OpenShift's native `cluster-capi-operator` during bootstrap, but that operator is intentionally absent here, and no GitOps object recreates it. On reinstall the cluster infra-id regenerated (`ocp-hb42r`), so any previously-minted secret no longer matches. This component's own `capi-workload-cluster-access-rbac.yaml` grants the `default`/openshift-cluster-api SA node read/patch precisely so a token in that secret works — but the secret it depends on does not exist. Impact: `Metal3Cluster/ocp-hb42r` is Ready and `InfrastructureReady=True`, but if `casval-worker` (currently `replicas: 0`, the intended burst-GPU scale-from-zero path) is scaled up, the resulting Machine can provision the BareMetalHost yet fail to associate its `nodeRef`/reach `Running` because the CAPI cluster-cache cannot reach the workload apiserver, and autoscaler accounting would be off. No active workload is impaired today (0 replicas), so this is latent — but the scale-from-zero recovery path is unproven after the rebuild. Note: this may also have been a pre-existing cosmetic `Available=False` before the disaster; the missing secret is nonetheless real.

**[Low] IPAM CRD patch is version-pinned to the OCP 4.21 release payload and must be hand-regenerated on any CAPI-core bump.** The two RFC-6902 patches in `providers.yaml` embed byte-identical CRD schema bodies from the 4.21 release image so CVO and capi-operator get shared SSA ownership. Correct today (cluster is 4.21.9, CAPI v1.12.7), but this is fragile maintenance debt: bumping `CoreProvider.spec.version` without re-extracting the manifest would reintroduce the storage-version conflict. Documented in-file; flagging as an upgrade-time trap.

**[Info] No auto-prune on the ArgoCD app** (`syncPolicy.automated` has `selfHeal: true`, no `prune`). Drift is self-healed but resources removed from git are not garbage-collected. Consistent with the rest of the repo; not a defect.

**[Info] Recovery quality:** the operator layer itself recovered the rebuild cleanly and completely — chart version, all three provider versions, SCC/PSA/RBAC, and the IPAM CRD reconciliation are all in their intended state with no manual drift. Everything this component *directly* owns is GitOps-reproducible and healthy.

### Remediation
1. **(Medium)** Restore/create the `ocp-hb42r-kubeconfig` cluster-cache Secret in `openshift-cluster-api` (kubeconfig for the local apiserver, tokened by the `default` SA that `capi-workload-cluster-access-rbac.yaml` already authorizes) so `RemoteConnectionProbe`/`ControlPlaneAvailable` clear and Machine node-association works. Because the infra-id (`ocp-hb42r`) is installer-generated and changes on every reinstall, prefer a reproducible generator over a hand-created secret — e.g. add it to the `cluster-api` app (`clusters/ocp/cluster-api/`) rendered from the live infra-id, or a small post-install Ansible step — so this doesn't have to be rediscovered after the next rebuild. Validate by scaling `casval-worker` 0→1 and confirming the Machine reaches `Running` with a `nodeRef`.
2. **(Low)** Add a comment/checklist tying `CoreProvider.spec.version` bumps to re-extracting the IPAM CRD patch from the matching OCP release image (already partly noted in-file); consider a CI check that diffs the embedded schema against the payload.
3. **(Info)** Track that this cluster relies solely on the community capi-operator (native `cluster-capi-operator` disabled) — this is the reason the kubeconfig secret is not auto-minted and should be captured in the DR runbook.

---

## cluster-api

**Status: degraded** — ArgoCD `Synced`/`Healthy` and all operators/providers/CronJobs are running, but the burst-worker provisioning path did **not** recover from the 2026-07-03 reinstall. The cluster still carries the pre-disaster infrastructure name and the documented one-time bootstrap steps were never re-applied. Currently benign only because the MachineSet is at `replicas: 0` and the BMH is `online: false`; the first attempt to burst-scale `casval` will fail.

Git source: `clusters/ocp/cluster-api` (cluster-specific objects; the operator/providers live in `components/cluster-api-operator`).

### What is healthy
- ArgoCD app `cluster-api`: `Synced` + `Healthy` (rev d81e454, project cluster-config).
- Providers all `READY=True`: core-provider `v1.12.7` (capi-system), metal3 infra `v1.12.4` (capm3-system), metal3 ipam `v1.12.4`. Controllers `capi-controller-manager`, `capm3-controller-manager`, `ipam-controller-manager`, and `capi-operator-cluster-api-operator` all `1/1 Running`.
- `capi-csr-approver` and `capi-node-cleanup` CronJobs firing every minute; latest jobs `Complete`, pods scheduled on the control-plane node.
- `casval-bmc-secret` ExternalSecret `Ready=True` (SecretSynced, 3 keys) — 1Password path recovered fine.
- Dormant burst config intact and correct: BMH `casval` `available`/`online:false`, MachineSet `casval-worker` `replicas:0` with autoscaler 0→1 bounds and capacity/label hints. `Metal3Cluster` `Ready=true`.

### Findings

1. **[CRITICAL] Stale cluster name — post-disaster restore gap.** `cluster-config-configmap.yaml` still pins `clusterName: ocp-hb42r` (git and live agree, hence ArgoCD is "Synced"), but the reinstalled cluster's `infrastructure.status.infrastructureName` is now **`ocp-m97rd`**. The README and the ConfigMap comment state this value *must* equal `infrastructure.status.infrastructureName` and *must be updated on reprovision*. `git log` confirms the ConfigMap was untouched during recovery (last edit is the original creation commit). Every CAPI object (`Cluster`, `Metal3Cluster`, `MachineSet` cluster-name label/`spec.clusterName`, and the expected `<cluster-name>-kubeconfig` secret) is keyed to the wrong name. This is latent drift that ArgoCD cannot detect.

2. **[HIGH] `worker-user-data-managed` bootstrap secret missing.** README step 1 (one-time-per-cluster, not GitOps-automated) requires copying this secret from `openshift-machine-api` into `openshift-cluster-api`; CAPM3 consumes it for the Ignition bootstrap referenced by both the MachineSet and the Metal3MachineTemplate. It is **NotFound** in `openshift-cluster-api` (the source copy still exists in `openshift-machine-api`, 2 keys). Without it a burst worker cannot be provisioned.

3. **[HIGH] Workload kubeconfig secret missing + `ControlPlaneInitialized=False`.** README step 2 (create the `<cluster-name>-kubeconfig` secret carrying the `cluster.x-k8s.io/cluster-name` label, then patch `ControlPlaneInitialized=True` for the external-control-plane pattern) was not re-run. No kubeconfig/user-data secret exists in the namespace, and the `Cluster` shows `Available=False`, `ControlPlaneInitialized=False (NotInitialized — Waiting for the first control plane machine…)`, `RemoteConnectionProbe=False`. In this external-control-plane design the initialized condition must be patched manually; until then CAPI treats the control plane as uninitialized, which gates worker Machine provisioning and remote-cluster caching.

4. **[LOW/observation] Bootstrap remains manual and undocumented in recovery runbooks.** All three gaps above stem from steps the README itself flags as "not yet automated in GitOps." The disaster-recovery playbook did not include them, so they were silently skipped. Consider promoting them into the GitOps bootstrap Ansible (or at minimum the DR runbook) so a reinstall reconstitutes the burst path automatically.

### Remediation
1. Update `clusters/ocp/cluster-api/cluster-config-configmap.yaml` `clusterName` from `ocp-hb42r` to `ocp-m97rd`, commit, and let ArgoCD re-sync so the kustomize `replacements` propagate the new name into `Cluster`, `Metal3Cluster`, and the `MachineSet` (name/label/`spec.clusterName`). Verify against `oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'`.
2. Re-run README step 1: copy `worker-user-data-managed` from `openshift-machine-api` into `openshift-cluster-api`.
3. Re-run README step 2 against the corrected name `ocp-m97rd`: create the `ocp-m97rd-kubeconfig` secret (with the `cluster.x-k8s.io/cluster-name` label) and patch `ControlPlaneInitialized=True` on the `Cluster` status.
4. Validate the burst path end-to-end (scale MachineSet 0→1 or exercise the autoscaler once) before relying on it, then return to scale-to-zero.
5. Fold steps 1–3 into the GitOps/DR bootstrap automation so a future reinstall recovers the burst worker without manual intervention.

---

## democratic-csi

**Status: healthy** (fully recovered the rebuild and is the storage backbone of the DR restore) — **with one CRITICAL latent node-level risk (shared NVMe hostnqn) that threatens this component's default storage class.**

democratic-csi is the cluster's primary dynamic-provisioning CSI stack, fronting the TrueNAS box (`truenas.igou.systems`) over three transports (iSCSI, NFS, NVMe-oF) × three ZFS pools (fast, ssd, cold) = **9 driver releases**. `freenas-nvmeof-ssd-csi` is the **cluster-default StorageClass** and hosts essentially every restored stateful workload.

### Health check (read-only, cluster state)

- **ArgoCD app** `democratic-csi` (project `cluster-config`): **Synced / Healthy**, revision `d81e454`. 169 managed resources, **0 OutOfSync / 0 unhealthy**. No drift.
- **Controllers:** all 9 Deployments `…-config-controller` are `1/1` Available (6/6 containers each).
- **Node plugins:** all 9 DaemonSets `…-config-node` are `3/3` Ready across all three nodes (ocp/10.10.9.10, hpg5, truenas-w1).
- **StorageClasses:** all 9 `freenas-*-csi` present; **`freenas-nvmeof-ssd-csi` marked `(default)`**. **CSIDrivers:** all 9 `org.democratic-csi.*` registered. **VolumeSnapshotClasses:** 6 present (fast+ssd tiers; cold tiers intentionally have none).
- **ExternalSecrets:** all 9 `…-config` `SecretSynced / Ready=True` via ClusterSecretStore `onepassword-sdk-ocp-pull` (1Password item `truenas`). Decoded `nvmeof-ssd` config is fully templated (`host: truenas.igou.systems`, `apiKey` present, `datasetParentName: ssd/k8s/vols`) — secret plumbing survived the rebuild.
- **Functional proof (not merely running):** controller `Probe` → TrueNAS returns `ready:true` in steady state. **16 PVCs bound** on freenas SCs (14 on nvmeof-ssd, 2 on nvmeof-fast), **all VolumeAttachments `attached=True`**, **no unbound/Pending PVCs cluster-wide**, and **no `FailedAttachVolume` / `FailedMount` / Multi-Attach events**. The DR-restored stateful workloads are all live on this storage: `quay-pg-1-full-recovery` 2/2, `rhdh-pg-1` 2/2, `forgejo-pg-1` 2/2, and the `hermes` VM (30Gi root+state) 2/2 — plus the 6 CNV golden OS images and user-workload Prometheus/Thanos.

### Findings

- **[CRITICAL — latent, not-yet-firing] All 3 nodes share one NVMe `hostnqn` AND `hostid` (`466937ab-67bf-4315-971b-bc110d55ce28`).** Verified by SSH on all nodes. NVMe-oF requires a unique host identifier per initiator; the TrueNAS target gates namespace visibility / ANA / reservations by hostnqn, so three "identical" hosts against the same subsystems can cross-expose RWO namespaces or produce intermittent attach/reservation failures — exactly the incident's stated symptom. This is *the* default StorageClass and carries every restored database, so blast radius is maximal. **Not a fault in this component's git** (hostnqn is node/OS-level), but it is the single biggest threat to democratic-csi's correctness. It has not manifested as an outage yet (all attachments currently healthy), which is luck, not safety.
- **[MEDIUM] Controller pods flap under transient TrueNAS API latency.** Every controller shows 10–13 restarts; container `lastState` = `Error` (csi-driver exit 15, sidecars 255) correlated with `Liveness probe failed: grpc` warnings ~80–85 min ago and controller logs showing `TrueNAS api is unavailable: timeout of 5000ms exceeded` plus a `CreateVolume … timeout of 60000ms`. The 5s gRPC liveness probe restarts the driver whenever TrueNAS is briefly slow, cascading restarts across all 9 releases at once. Self-heals (all 6/6 now) but is disruptive during any real TrueNAS slowdown and masks genuine failures. Consider raising liveness `timeoutSeconds`/`failureThreshold`.
- **[LOW] Driver image pinned to the `next` development channel** (`ghcr.io/…/democratic-csi:next@sha256:0f308ae…`) rather than a tagged stable release. It is digest-pinned (reproducible) and tracked by a Renovate customManager, but `next` is democratic-csi's dev stream — acceptable as the price of NVMe-oF support, worth revisiting once NVMe-oF lands in a stable tag.
- **[INFO] No post-disaster restore was required for democratic-csi itself, and none is missing.** The component is effectively stateless: its config lives in 1Password (re-hydrated by ESO) and the actual volume data lives on TrueNAS ZFS (`ssd/k8s/vols`, etc.), which was never touched by the MS-01 wipe. GitOps re-sync + ESO fully reconstituted it; all volumes re-bound and re-attached against pre-existing ZFS zvols. Clean recovery.
- **[INFO — no gap] Security/RBAC is correctly scoped.** Privileged SCC is bound only to the per-release `…-node-sa` ServiceAccounts (node plugins legitimately need host mount + nvme/iscsi tooling); controllers use `hostNetwork: true` for target connectivity. TLS to TrueNAS is `allowInsecure: false`, apiVersion 2, via a scoped `csi` API key (per prior scoped-account work). No over-broad grants observed. iSCSI/NFS tiers are provisioned and running but currently carry 0 PVCs (idle tiering options).

### Remediation

1. **(Critical) Assign a unique `/etc/nvme/hostnqn` + `/etc/nvme/hostid` to each node** and reconnect NVMe-oF. Fix belongs in node provisioning (MachineConfig/ignition or the igou-ansible node role), not this component — generate with `nvme gen-hostnqn` / a fresh UUID per host so the three initiators are distinct on the TrueNAS target. Track/coordinate with the cluster-wide hostnqn remediation noted in the reinstall record. Until fixed, treat every nvmeof RWO attach as at risk of cross-node exposure.
2. **(Medium) Loosen the controller gRPC liveness probe** (higher `timeoutSeconds`/`failureThreshold`, or point liveness at the local socket rather than a path that round-trips to TrueNAS) via the helm `valuesInline`, so transient TrueNAS API latency stops restarting all 9 controllers. Optionally investigate the underlying TrueNAS API slowness (5s/60s timeouts) separately.
3. **(Low) Move off the `next` image channel to a stable digest** once democratic-csi ships NVMe-oF in a released tag; keep the Renovate customManager.
4. **(Verify)** No action needed on data restore — confirm ongoing health by watching that `quay/rhdh/forgejo` CNPG and the hermes PVCs stay `attached=True`; a sudden Multi-Attach event would be the first sign the shared-hostnqn risk has fired.

---

## external-secrets-operator

**Status:** degraded — operator fully recovered and the read/pull path is 100% functional, but the secret **write-back (PushSecret) path is broken** on two of three ClusterSecretStores.

Git source: `clusters/ocp/external-secrets-operator` (Helm chart `external-secrets` v2.6.0, app image pinned by digest `v2.2.0@sha256:876e627…`). Deployed via ArgoCD app `external-secrets-operator` (project `cluster-config`, sync-wave 0).

### Health check (read-only, live cluster)

- **ArgoCD app:** `Synced` + `Healthy`; `status.sync.revision` = `d81e454…` = current `origin/main` HEAD (no drift, no conditions/warnings).
- **Namespace:** `external-secrets-operator` Active (8h, matches post-rebuild age).
- **Deployments:** all 3 at `1/1` Ready — `external-secrets`, `external-secrets-cert-controller`, `external-secrets-webhook` (all pods Running, 0 restarts, 7h24m). This is a Helm-based install, not OLM (no Subscription/CSV — expected).
- **CRDs:** full ESO CRD set installed (externalsecrets, clustersecretstores, pushsecrets, clusterexternalsecrets, generators, etc.).
- **ClusterSecretStores (CRs owned by this component):** all 3 `Valid` / `Ready=True` / advertised `ReadWrite` — `onepassword-sdk-ocp-pull`, `onepassword-sdk-ocp-push`, `onepassword-sdk-claude`. All point at Connect `http://onepassword-connect.onepassword-connect.svc:8080` and auth via the shared `onepassword-connect-token` secret.
- **Consumers:** all ~28 `ExternalSecret`s cluster-wide are `SecretSynced=True` (cert-manager, democratic-csi, quay, rhdh, forgejo, tailscale, openshift-config htpasswd, monitoring, etc.) — the pull path that the rest of the rebuild depended on is fully working.
- **Bootstrap token:** `onepassword-connect-token` secret present in-ns.

### Findings

**[Medium] Secret write-back path is non-functional — Connect token lacks vault-update (403).**
All 6 `PushSecret`s in the `service-accounts` namespace are in `Errored` state, and the ESO controller is logging ~12 reconcile 403s per 10 min (ongoing, not a startup blip):
- `onepassword-sdk-ocp-push` → vault `dtd2bci…` (ocp-push): `403 Authorization: token does not have permission to perform update on vault`
- `onepassword-sdk-claude` → vault `iggugny…` (claude): same 403.

Root cause is the 1Password **Connect access token** (shared `onepassword-connect-token`) being scoped read-only on the `ocp-push` and `claude` vaults. Note ESO's store validation only probes reachability, so both stores still report `ReadWrite`/`Valid` while every actual write fails — the health signal is misleading. The PushSecret objects themselves live in the `service-accounts` component, but the broken capability is on stores this component owns. Read/pull is unaffected. Cannot definitively confirm whether this regressed during the rebuild or pre-existed, but it is broken *now*.

**[Low / DR-resilience] Bootstrap `onepassword-connect-token` is out-of-band, not in GitOps.**
The secret is created manually (`oc -n external-secrets-operator create secret generic onepassword-connect-token …`, managed-by `kubectl-client-side-apply`, no ArgoCD tracking-id, no ownerRefs, no labels) per `docs/superpowers/plans/2026-06-07-1password-connect-migration.md`. This is the intended ESO chicken-and-egg bootstrap and it *was* correctly re-applied during recovery, so ESO came back. But it is a single manual step with no GitOps safety net: if missed on a future rebuild, **every** ExternalSecret cluster-wide fails. It should be an explicit, checklisted DR-runbook step (which the migration doc provides).

**[Low / security] Single shared token spans read + write across all vaults.**
One `onepassword-connect-token` backs the pull, push, and claude stores. If the 403 is fixed by granting the shared token write on `ocp-push`/`claude`, the read-only `ocp-pull` store's token also becomes write-capable — a least-privilege gap. Prefer separate read-only vs write-scoped Connect tokens/secrets per store class.

**[Info] Benign startup transients (already self-resolved).** Webhook logged `invalid certs. retrying…` / `ca cert not yet ready` only at boot (7h ago); none in the last 15 min, the `externalsecret-validate` ValidatingWebhookConfiguration now has a populated caBundle, and the webhook is `1/1`. Normal cert-controller startup race — no action.

**[Info] Operator pinned to control-plane node only.** `valuesInline.global.nodeSelector: control-plane` + master/control-plane tolerations. Appropriate for this single-control-plane cluster, but means ESO shares fate with the MS-01 master (acceptable given the topology).

### Remediation

1. **Restore the push/write capability (Medium):** In 1Password, grant the Connect integration/token backing `onepassword-connect-token` **write (update)** access to the `ocp-push` (`dtd2bci…`) and `claude` (`iggugny…`) vaults, then re-apply the `onepassword-connect-token` secret in `external-secrets-operator`. The 6 `service-accounts` PushSecrets should flip to `SecretSynced` on next reconcile (or force with an annotation touch). Verify: `oc get pushsecret -A` shows no `Errored` and controller logs stop emitting `status 403`.
2. **Codify the bootstrap step (Low):** Ensure the manual `onepassword-connect-token` creation is a first-class step in the cluster DR runbook (it currently lives only in the migration plan doc), and consider whether it can be seeded from a break-glass source rather than hand-typed.
3. **Least-privilege tokens (Low):** Split into a read-only Connect token for `onepassword-sdk-ocp-pull` and a separate write-scoped token for the push/claude stores.
4. No action needed on the ArgoCD app, deployments, CRDs, webhook certs, or the pull path — all healthy and drift-free.

---

## firecrawl

**Status: not-yet-deployed** (correctly defined in git and registered in the app-of-apps, but blocked from being created by a stuck upstream app-of-apps sync — this is a rollout/ordering problem, not a firecrawl defect)

Firecrawl is an internal-only web scraping/crawling backend for the Hermes agent. It is a multi-workload `app-template` (bjw-s) Helm deployment: `api`, `worker`, `extract-worker`, `nuq-worker` (Node), plus support services `playwright`, `redis`, `rabbitmq`, and a persistent `nuq-postgres`. Source: `applications/firecrawl` (registered in `clusters/ocp/values.yaml` at sync-wave 19).

### Findings

- **[CRITICAL] The firecrawl ArgoCD Application does not exist; nothing is running.** `oc get applications.argoproj.io firecrawl -n openshift-gitops` → NotFound, and namespace `firecrawl` does not exist (no Deployments/PVCs/pods/secrets). In the `root-applications` app-of-apps resource tree, `Application/firecrawl` shows `OutOfSync / Missing`.

- **[CRITICAL] Root cause is an upstream app-of-apps deadlock, external to firecrawl.** `root-applications` is `OutOfSync / Progressing` with auto-sync (selfHeal+prune) enabled. An in-flight sync **operation has been Running/retrying since 01:42Z (~73 min, retryCount ≥4)** and is gated on child-app health (message cycles: "waiting for healthy state of Application/quay-operator", then "…/machineconfigs" — i.e. it restarts wave-walking each retry and never completes). Because the operation never reaches a clean finish, the newly-added wave-19 firecrawl Application is never created. The same stall is holding back six sibling apps (`ansible-automation-platform`, `gitea-mirror`, `gotify`, `jellyfin`, `llmkube`, `searxng` — all Missing).

- **[CRITICAL] The stuck operation is targeting a stale revision that predates firecrawl.** The running op's target is `056256c` (PR #386, "restore hermes-agent scaffolding") — but firecrawl was only added at HEAD `d81e454` (PR #389). So even if the current op eventually succeeds, it will not create firecrawl; a *fresh* sync to `d81e454` is required. The app's compare revision is already `d81e454` (hence the OutOfSync/Missing diff), but no new sync can start while the old operation is stuck. The actual health blocker is **quay-operator** (its CNPG `quay-pg` Cluster and `QuayRegistry/igou-registry` are Missing — the `quay-operator` namespace has no CNPG cluster and only the operator pod). This is a DR-restore-in-progress artifact (wave-3 apps were re-enabled incrementally in #386→#389).

- **[INFO/positive] The firecrawl git config is DR-safe and does not require any post-disaster restore.** Secrets come from a self-contained ESO `Password` generator (`firecrawl-secrets` → `firecrawl-secret`) — no 1Password/Barman dependency, so a fresh random secret is generated on deploy and shared consistently by redis/rabbitmq/nuq-postgres at first boot. The `passwords.generators.external-secrets.io` CRD is present and ESO is Synced/Healthy. `nuq-postgres` is only a transient queue DB, so the fresh 10Gi PVC (no backup/restore) is the correct design — no data-loss concern.

- **[LOW] Once created, PVC binding depends on democratic-csi NVMe-oF, which carries the cluster-wide latent bug.** `firecrawl-nuq-postgres` (RWO 10Gi) uses `freenas-nvmeof-ssd-csi` (present, default, democratic-csi Synced/Healthy). The shared-hostnqn/hostid defect noted in the incident could cause intermittent volume-attach failures for this PVC until fixed. No fsGroup is set on nuq-postgres; rely on OpenShift restricted SCC to assign one for the `/var/lib/postgresql/data` mount.

- **[LOW] Runtime search dependency is also down.** Config sets `SEARXNG_ENDPOINT=http://searxng.searxng.svc…`, but the `searxng` namespace/app is also not deployed (same stall). The core scrape/crawl path (api+worker+extract-worker+nuq-worker+playwright) does not need searxng, so this only degrades search-backed features once firecrawl comes up.

- **[INFO] Security posture is good.** `automountServiceAccountToken: false`, seccomp RuntimeDefault, `runAsNonRoot`, `allowPrivilegeEscalation: false`, `drop: [ALL]` on all containers; images pinned by digest; no Route (internal ClusterIP only); Hermes egress restricted to TCP 3002 via `hermes-agent` NetworkPolicy (hermes-agent app is Synced/Healthy). The upstream `nuq-prefetch-worker` is intentionally `enabled: false` (documented).

### Remediation (advisory — reviewer is read-only)

1. **Unblock the app-of-apps rollout** (this is the only thing preventing firecrawl from deploying). Terminate the wedged `root-applications` sync operation so a fresh sync against HEAD `d81e454` can start, and resolve the wave-22 `quay-operator` health gate (bring up its CNPG `quay-pg` Cluster + `QuayRegistry`). Firecrawl is wave 19, so a clean re-sync should create it before it re-reaches quay.
2. **Consider decoupling low-priority apps from the quay gate.** quay-operator being unhealthy is currently blocking unrelated apps (firecrawl, searxng, jellyfin, llmkube, gotify, gitea-mirror, AAP). Making these independently syncable (or ordering quay after them) would prevent one operator's slow restore from starving the rest.
3. **After firecrawl syncs, run the README smoke test** (`/v0/health/liveness` via `TEST_API_KEY`) and confirm the `firecrawl-nuq-postgres` PVC bound cleanly (watch for NVMe-oF attach flakiness tied to the shared-hostnqn bug). Bring up `searxng` to restore search-backed crawl features.

---

## forgejo

**Status: broken** — every pod is Running/Healthy and the CNPG database restore technically succeeded, but the live service is a **fresh empty instance**: the 356 restored repos are orphaned in the wrong database and the git repository filesystem was never restored. From a user/DR standpoint the component does not fulfil its function and there is active data-loss risk.

Source path: `applications/forgejo` · ArgoCD app `forgejo` (project `cluster-apps`, sync-wave 22) · namespace `forgejo` · route `https://forgejo.apps.ocp.igou.systems`.

### Health check (read-only, live cluster)
- **ArgoCD app**: `OutOfSync` / `Healthy`. The only OutOfSync resource is `Cluster/forgejo-pg` (itself Healthy). `operationState: Succeeded ("successfully synced")`; `automated.selfHeal: true`; no `ignoreDifferences` configured.
- **Pods**: `forgejo-6cc8b8565b-7lz8r` 1/1 Running (on `truenas-w1`), `forgejo-pg-1` 2/2 Running (pinned to control-plane per anti-multiattach affinity). No restarts, no crashloops, no Pending.
- **PVCs**: `forgejo-pg-1` (10Gi) and `forgejo-shared-storage` (100Gi) both Bound on `freenas-nvmeof-ssd-csi` (RWO).
- **CNPG cluster** `forgejo-pg`: 1/1 ready, "Cluster in healthy state"; conditions `Ready`, `ContinuousArchiving=Success`, `LastBackupSucceeded=True`. `ScheduledBackup forgejo-pg-daily` produced a completed Backup; WAL/backup archiving to the new `serverName forgejo-pg-r20260704` (correct post-DR timeline-collision avoidance).
- **ExternalSecrets**: `cnpg-s3-credentials` and `forgejo-secrets` both `SecretSynced` / Ready. Route (edge/Redirect) + services present.

### Findings

**[CRITICAL] Database restore landed in the wrong DB — forgejo is serving an empty instance.**
The recovery block in `forgejo-pg-cluster.yaml` specifies only `bootstrap.recovery.source: forgejo-pg` and omits `database`/`owner`. CNPG defaulted them to `app`/`app`, so on physical recovery it created a **new empty `app` database + `app` role** and generated the `forgejo-pg-app` secret pointing at `dbname=app, user=app`. The Forgejo Helm release consumes exactly that secret (`GITEA__database__{HOST,NAME,USER,PASSWD}` from `forgejo-pg-app`), so Forgejo connected to the empty `app` DB, ran its own migrations, and created a fresh admin.
- `app` DB: 128 tables, **users=1** (`igou_admin`, created post-disaster), **repos=0**, actions=0.
- `forgejo` DB (the real restored data, orphaned/unused): 128 tables, **users=6** (`igou_admin, starred, djdanielsson, Throckmortra, xvorenda, igou-io`), **repos=356**, last action `2026-07-02 21:20` (right before the disaster).
Pre-disaster the DB was named `forgejo`/`forgejo` (per the commented-out `initdb` block in the same file); the recovery block should have set `database: forgejo, owner: forgejo` so the `-app` secret pointed at the recovered DB.

**[CRITICAL] Git repository filesystem was NOT restored and has no backup mechanism.**
`forgejo-shared-storage` (100Gi) is a freshly provisioned empty volume: `/data/git/repositories` has **0 repos** and `df` shows **204K used of 98G**. Forgejo stores bare git repos (commits/blobs/refs) on this PVC — the CNPG Barman backups cover only Postgres metadata, **not** the on-disk git objects, and no Velero/CSI-snapshot/tar-to-S3 backup is configured for this PVC anywhere in the manifests. Consequence: even after fixing the DB pointer (Finding 1), all 356 repos would appear but be empty/broken. Unless the pre-disaster `forgejo-shared-storage` zvol still exists on TrueNAS (democratic-csi names zvols by PVC-UUID, so a name search is inconclusive — needs a lookup by the old PVC UUID) or the repos are mirrored elsewhere, this is unrecoverable data loss. The DR record mentions only the DB restore; the repo filesystem restore appears to have been missed.

**[HIGH] Empty Forgejo breaks Pipelines-as-Code tenants (downstream blast radius).**
`clusters/ocp/pac-tenants/values.yaml` registers PaC tenants against repos hosted in Forgejo (e.g. `https://forgejo.apps.ocp.igou.systems/igou-io/igou-ansible`). With an empty instance those repos 404, so tenant clones/webhooks/pipelines are broken until Forgejo data is recovered.

**[LOW→MED] Perpetual OutOfSync; recovery manifest not reverted.**
`bootstrap` is immutable, so the operator-defaulted `database: app`/`owner: app` will diff against git forever, and with no `ignoreDifferences` on `/spec/bootstrap` the app can never reach Synced (selfHeal churns cosmetically, masking real drift). The manifest also still has `bootstrap.recovery` active pointing at the OLD archive `serverName forgejo-pg` — its own comment instructs reverting to the `initdb`/normal running spec once recovery is verified; that revert is pending. If `forgejo-pg-1` is ever lost, it would recover from the stale pre-disaster archive rather than the current `forgejo-pg-r20260704` timeline.

**[INFO] Security posture is otherwise sound** — admin `passwordMode: initialOnlyRequireReset`, route edge TLS + redirect, `webhook.ALLOWED_HOST_LIST: private`, git memory caps, `nonroot-v2` SCC bound to the `forgejo` SA. No security gap found.

### Remediation (priority order)
1. **Repoint the DB (CRITICAL).** Bootstrap is immutable, so re-run recovery with `bootstrap.recovery: { source: forgejo-pg, database: forgejo, owner: forgejo }` — recreate the CNPG cluster from the same Barman backup so the operator-generated `forgejo-pg-app` secret points at the restored `forgejo` database (the current empty `app` DB is disposable). Verify `forgejo-pg-app.dbname=forgejo` and `users=6/repos=356` after.
2. **Recover the git repo filesystem (CRITICAL).** Before doing anything destructive, locate a source for the bare repos: (a) check TrueNAS for the orphaned pre-disaster `forgejo-shared-storage` zvol (by the old PVC UUID) and clone/restore it into the new PVC's zvol; (b) check the `gitea-mirror` app (wave 23) and any external GitHub mirrors as alternate sources; then rehydrate `/data/git/repositories`. If nothing is found, treat the 356 repos as lost and rebuild from upstream mirrors.
3. **Add a filesystem backup for `forgejo-shared-storage`** (Velero + CSI snapshot, or periodic tar-to-S3) so DB-only backups don't recur as a single point of loss.
4. **After verification, revert `forgejo-pg-cluster.yaml`** to the plain `initdb`/running spec per its own comment (or add `ignoreDifferences` on `/spec/bootstrap`) to clear the perpetual OutOfSync and prevent an accidental replay from the stale archive.
5. **Revalidate PaC tenants** (`igou-io/igou-ansible` etc.) once repos are back.

---

## gateway-api

**Status: healthy** (component fully recovered the rebuild) — but the guest-dmz tier is **not yet serving any application**: zero HTTPRoutes are attached because its documented consumer (jellyfin) was not restored. Root cause of that gap is outside this component.

Reviewed git revision: `origin/main` @ `d81e454` (git path `clusters/ocp/gateway-api`). ArgoCD app `gateway-api` is **Synced + Healthy**, synced to `d81e454` (targetRevision HEAD) — no drift.

### Scope
The component owns exactly three resources (per `kustomization.yaml`): `GatewayClass openshift-default`, `Gateway guest-dmz` (ns `openshift-ingress`), and cert-manager `Certificate gateway-guest-dmz-tls`. It does **not** own any HTTPRoute — apps onboard their own.

### Findings

**[OK] Full infrastructure recovery, verified live.**
- `GatewayClass openshift-default` → controller `openshift.io/gateway-controller/v1`, `Accepted=True` (7h40m).
- `Gateway guest-dmz` → `Programmed=True`, `Accepted=True`, address `10.10.152.3` (the contracted rb5009 VIP). Listener `https` conditions all clean (`ResolvedRefs=True`, `Conflicted=False`).
- Managed control plane + data plane both Running in `openshift-ingress`: `istiod-openshift-gateway` (restartCount 1, benign — no lastState, not a crashloop) and Envoy `guest-dmz-openshift-default-*` (1/1).
- LoadBalancer Service `guest-dmz-openshift-default` has `EXTERNAL-IP 10.10.152.3` (MetalLB honored the `spec.infrastructure.annotations` pin), ports 443 + 15021, `externalTrafficPolicy: Cluster` (as documented).
- `ingress` ClusterOperator: `Available=True, Progressing=False, Degraded=False`. The per-listener `DNSRecord guest-dmz-...-wildcard` exists and, as the README predicted for bare metal, stays unpublished without degrading the operator.

**[OK] TLS restored correctly — end-to-end verified.** `Certificate` READY, backing `Secret gateway-guest-dmz-tls` present. Live probe of `https://10.10.152.3:443` (SNI `*.dmz.igou.systems`) returns the **real production Let's Encrypt wildcard** `CN=*.dmz.igou.systems` (issuer LE, freshly reissued **notBefore Jul 3 2026**, notAfter Oct 1 2026, renewalTime Sep 16) and Envoy answers HTTP 404 (correct: no route attached). So TLS termination on the VIP is genuinely functional, not merely "pods Running." `cluster-acme` ClusterIssuer is READY. Cert was correctly regenerated during the rebuild — no stale/expired secret.

**[MEDIUM] The guest-dmz Gateway currently routes nothing — DMZ tier is not functional end-to-end.** Listener `attachedRoutes: 0`; **zero HTTPRoutes cluster-wide**; **zero namespaces** carry the `gateway-access/guest-dmz=true` label. The documented live consumer `jellyfin.dmz.igou.systems` (jellyfin-cutover memory) is down: the `jellyfin` namespace does not exist and the `jellyfin` ArgoCD Application is **missing from `openshift-gitops`**, even though it is declared in the app-of-apps (`clusters/ocp/values.yaml` → `applications.jellyfin`, project `cluster-apps`, sync-wave 20, path `applications/jellyfin`, which includes a valid `jellyfin-httproute.yaml` with correct `parentRefs` to `guest-dmz`). **This is a jellyfin / app-of-apps restore gap, not a gateway-api defect** — but it means the whole reason this Gateway exists is unserved. Flag for the jellyfin/app-of-apps owner.

**[INFO] Pre-flight constraints from README still hold post-rebuild.** Gateway API CRDs are the operator-managed bundle (`bundle-version v1.3.0`, `channel standard`) — not community CRDs, so no upgrade admin-gate. A `servicemeshoperator3` Subscription exists in `openshift-operators` (OSSM **v3**, stable) — this does **not** trigger `GatewayAPIOSSMConflict`, which fires only on OSSM **v2.x**; the managed `istiod-openshift-gateway` is healthy alongside it.

**[INFO / by-design] Shared-VIP exposure.** The wildcard cert + single VIP mean every VLAN admitted to the guest-dmz tier reaches anything routed here; per-app L4 isolation is impossible on this shared Gateway (documented tradeoff). No security regression from the rebuild — just noting the standing posture as more apps onboard.

### Remediation
1. **(Owner: jellyfin/app-of-apps, not gateway-api)** Restore the consumer app so the tier actually serves: investigate why the `jellyfin` ArgoCD Application isn't materializing from `clusters/ocp/values.yaml` (sync-wave 20 / project `cluster-apps`) — check the `applications` app-of-apps/ApplicationSet health and any pruned/failed generation, then let it sync (creates the `jellyfin` ns with the `gateway-access/guest-dmz=true` label + the HTTPRoute). After sync, confirm `Gateway guest-dmz` listener `attachedRoutes` becomes ≥1 and `curl https://jellyfin.dmz.igou.systems` returns 200 through the VIP.
2. **No action needed on gateway-api itself.** All three owned resources are correctly restored, Synced to HEAD, and live-verified. Optional post-restore smoke test once a route is attached: re-run the VIP curl expecting the app response instead of 404.
3. **Monitor** cert auto-renewal at ~Sep 16 (Envoy SDS hot-reload, no restart) — no action now.

---

## gitea-mirror

**Status:** not-yet-deployed (queued in the post-disaster app-of-apps restore; config in git is intact and valid, but the child Application has not been created yet, so there is no data-recovery step wired for it)

`gitea-mirror` is a GitHub→Forgejo repo-mirroring web app (image `ghcr.io/raylabshq/gitea-mirror:v3.15.6`, digest-pinned) deployed via the bjw-s `app-template` Helm chart. Source: `applications/gitea-mirror` (wired into `clusters/ocp/values.yaml:362`, project `cluster-apps`, sync-wave `23`).

### Health check (read-only, cluster = ocp)

- **ArgoCD Application `gitea-mirror` does not exist yet.** `oc get application gitea-mirror -n openshift-gitops` → NotFound. In `root-applications.status.resources` it shows `OutOfSync / Missing`.
- **Root cause = still queued, not failed.** `root-applications` (auto-sync, self-heal) is mid-DR-restore and re-running a wave-ordered sync (revision `d81e454`, started 02:56:21Z). The current syncResult has only reached the low waves (currently blocking on `democratic-csi`, hookPhase `Running`). A whole batch of higher-/file-wave apps is still `Missing`: `gitea-mirror`, `gotify`, `jellyfin`, `searxng`, `firecrawl`, `llmkube`, `ansible-automation-platform`. gitea-mirror is wave 23, so it is created near the end. No defect specific to gitea-mirror.
- **Nothing exists in-cluster:** no `gitea-mirror` namespace, no `gitea-mirror-config` PVC, no pods, no route. Nothing to be CrashLooping/Pending yet.
- **Downstream dependencies are ready**, so it should sync cleanly once reached: mirror target `forgejo` pod + `forgejo-pg` are Running and the route `forgejo.apps.ocp.igou.systems` is up; `ClusterSecretStore onepassword-sdk-ocp-pull` is `Ready=True`; default StorageClass `freenas-nvmeof-ssd-csi` present and `democratic-csi` app Synced/Healthy; `blackbox-exporter` svc exists (for the Probe CR).

### Functionality review (git config)

Config is correct and complete and was **never removed during DR** (only PR #250 ever touched the values.yaml block; the app dir is intact). Image is digest-pinned; securityContext is restricted-v2 compliant (`runAsNonRoot`, drop ALL, no privilege escalation, seccomp RuntimeDefault); `BETTER_AUTH_URL`/route host are consistent (`gitea-mirror.apps.ocp.igou.systems`); GitHub creds come from ExternalSecret `gitea-mirror-secrets` (envFrom). Findings:

- **[MEDIUM] No post-disaster restore for its state; it will come up empty and need manual first-run setup.** All app state — the better-auth admin account, GitHub/Forgejo connection, encrypted tokens, and mirror job history — lives in a **SQLite file DB** (`DATABASE_URL: file:/app/data/gitea-mirror.db`) on the 40Gi RWO PVC `gitea-mirror-config`. This is *not* a CloudNativePG database, so it was **not** part of the Barman/RustFS DB restore (quay/rhdh/forgejo) or the hermes tar restore. When the app finally deploys it gets a **fresh empty PVC** → boots into first-run setup with no admin user and no Forgejo target. It will **not** auto-resume mirroring. GITHUB_TOKEN/BETTER_AUTH_SECRET/ENCRYPTION_SECRET are injected from 1Password, and `AUTO_IMPORT_REPOS=true` + `SCHEDULE_ENABLED` are set, so once an admin logs in and re-pastes the Forgejo PAT (by design this PAT is UI-entered, not wired to k8s), it can re-import. But a human step is required — this is the real DR gap for this component.
- **[MEDIUM] Pre-disaster data likely survives as an orphaned zvol on TrueNAS (optional recovery path).** The default SC uses `org.democratic-csi.nvmeof-ssd` with `reclaimPolicy: Delete`. Because etcd was wiped rather than the PV gracefully deleted, the CSI driver never received a delete call, so the old `gitea-mirror-config` zvol was almost certainly **orphaned** on TrueNAS, not reclaimed. The old SQLite DB (with the working config) may still be recoverable via a manual static-PV import — otherwise GitOps will provision a fresh empty volume and the old one becomes dead storage. Low urgency since the data is re-derivable, but worth a look before accepting a clean-slate setup, and it adds to the cold/orphan cleanup backlog.
- **[HIGH — cross-cutting latent bug, affects this app's volume] Shared NVMe hostnqn/hostid across all 3 nodes.** gitea-mirror's PVC lands on the NVMe-oF default SC. The incident's known latent defect (all nodes share the same `hostnqn ...466937ab...`) causes intermittent volume-attach failures over NVMe-oF. Once gitea-mirror is scheduled, watch for stuck `ContainerCreating`/attach errors on `gitea-mirror-config`; this is not gitea-mirror's fault but will manifest on its RWO volume.
- **[LOW] Destructive cleanup is enabled against freshly-restored Forgejo.** `CLEANUP_DELETE_IF_NOT_IN_GITHUB: "true"`, `CLEANUP_ORPHANED_REPO_ACTION: archive`, `CLEANUP_DRY_RUN: "false"`. On the first scheduled run (`0 4 * * *`) it will archive Forgejo repos absent from GitHub. Archive (not delete) is relatively safe, but it runs automatically against the just-restored Forgejo — confirm the Forgejo DB restore matches GitHub before the first schedule fires, or start with `CLEANUP_DRY_RUN: "true"`.
- **[LOW] `resources: {}`** — no CPU/memory requests or limits → BestEffort QoS; first to be evicted under pressure on a recovering cluster. Add a small burstable request.
- **[LOW] Verify the 1Password item `gitea-mirror` is populated** (fields GITHUB_TOKEN, BETTER_AUTH_SECRET, ENCRYPTION_SECRET). The pod requires the `gitea-mirror-secrets` envFrom secret to start; couldn't confirm the item's contents here (op is Connect-mode). The store is Ready and it worked pre-disaster, so this is just a pre-flight check.
- **[COSMETIC] Probe CR is named `gitea-mirror-biscuit`** — stale "biscuit" host legacy; the target URL is correctly `...apps.ocp.igou.systems/api/health`, so it functions.

### Remediation

1. **None required to unblock it** — it is queued behind the wave-ordered DR sync. Let `root-applications` finish (it is currently blocked on `democratic-csi` reaching Healthy, then works up to wave 23). If it stalls, unblocking the earlier waves (democratic-csi / quay) lets it proceed. Do not hand-create the Application.
2. **After it deploys, do first-run setup** (expected, not a bug): open `https://gitea-mirror.apps.ocp.igou.systems`, create the admin account, re-paste the Forgejo PAT (stashed as 1Password item `gitea-mirror-forgejo-pat`), confirm the GitHub token connects, then trigger/allow the auto-import to re-mirror.
3. **Before the first 04:00 schedule**, verify the restored Forgejo repo set matches GitHub (or temporarily set `CLEANUP_DRY_RUN: "true"`) so the cleanup pass doesn't archive legitimately-restored repos.
4. **Optional data recovery:** check TrueNAS for the orphaned pre-disaster `gitea-mirror-config` zvol; if present and preferred over a clean setup, statically import it as the PV. Otherwise delete it as part of orphan cleanup.
5. **Watch the volume attach** on first schedule for the shared-hostnqn NVMe-oF issue; track under the cluster-wide hostnqn remediation.
6. **Nice-to-have:** add a small `resources.requests` block.

---

## gotify

**Status: broken** (defined in git, not re-deployed after the rebuild; causing a live alert-delivery outage)

Scope note: since the cluster reinstall, the Gotify *server* no longer runs on OCP — it lives on the public VPS `gotify.igou.io`. The only in-cluster piece is the `alertmanager-gotify-bridge` (druggeri/alertmanager_gotify_bridge v2.3.2), which receives Alertmanager webhooks and forwards them to `https://gotify.igou.io/message`. That bridge is currently **not deployed**.

### Findings

- **[CRITICAL] The `gotify` child Application was never (re)created — component is absent from the cluster.**
  - `oc get applications.argoproj.io gotify -n openshift-gitops` → `NotFound`.
  - In `root-applications` (the app-of-apps) the child shows `Application/gotify sync=OutOfSync health=Missing`.
  - Namespace `gotify` does not exist; no Deployment, Service, ServiceAccount, ExternalSecret, or Secret exist.

- **[CRITICAL] Alertmanager Gotify delivery is DOWN right now.** `alertmanager-main-0` is Running and `components/alertmanager-config/alertmanager.yaml` sets the **default** receiver to `gotify` plus `gotify-and-slack-critical` / `gotify-and-slack-warning`, all pointing at `http://alertmanager-gotify-bridge.gotify.svc:8080/gotify_webhook`. That Service does not exist, so every push notification to Gotify (including the Watchdog dead-man's-switch) is failing. Slack fan-out for critical/warning receivers is unaffected; info/Watchdog-to-Gotify visibility is lost.

- **[HIGH — root cause, external to gotify] The parent app-of-apps sync is stalled and never reached gotify.** `root-applications` is `OutOfSync | Progressing`, operation "waiting for healthy state of argoproj.io/Application/quay-operator", which is itself "waiting for healthy state of postgresql.cnpg.io/Cluster/quay-pg" (the Barman-restored Quay DB not yet Healthy). The same stall left a batch of workload apps Missing: firecrawl(19), gotify(20), jellyfin(20), llmkube(20), searxng(20), gitea-mirror(23), ansible-automation-platform(30). Note the ordering anomaly: gotify is sync-wave 20 yet quay-operator (wave 22) got created while gotify did not — so simply waiting on quay-pg may not auto-heal gotify; a targeted sync is likely required.

- **[INFO] gotify's own git config is correct and needs no data restore.** The bridge is stateless — the server/PVC/route/admin-secret were intentionally removed (comment in `applications/gotify/kustomization.yaml`), so there is **nothing to restore from backup** for this component; it should converge cleanly once synced. Config is sound: image digest-pinned (`...@sha256:2424...`), hardened securityContext (runAsNonRoot, drop ALL caps, `allowPrivilegeEscalation: false`, seccomp RuntimeDefault), and the documented `MESSAGE_ANNOTATION: summary` + `DISPATCH_ERRORS`/`EXTENDED_DETAILS` workarounds for the v2.3.2 HTTP-400 bug.

- **[INFO] Secret backing verified present.** ExternalSecret `gotify-bridge-token` uses ClusterSecretStore `onepassword-sdk-ocp-pull` (vault `ocp-pull`). The 1Password item `gotify-bridge-token` exists in that vault and has a `token` field, matching the Deployment's `secretKeyRef{name: gotify-bridge-token, key: token}`. So ESO resolution should succeed as soon as the app deploys.

- **[LOW] No resource requests/limits** on the bridge container (`resources: {}`). Minor; the bridge is lightweight.

### Remediation
1. Get the parent app-of-apps to converge: bring `quay-pg` CNPG cluster to Healthy so `root-applications` can finish, **or** don't block gotify on Quay — trigger a targeted `argocd app sync gotify` / sync `root-applications` (with the anomalous wave ordering, gotify likely needs an explicit sync rather than passively waiting on the quay-operator wave).
2. After it deploys, verify: `gotify` namespace + `alertmanager-gotify-bridge` Deployment Ready, Service `alertmanager-gotify-bridge.gotify.svc:8080` exists, ExternalSecret `gotify-bridge-token` → Secret `gotify-bridge-token` (key `token`) SecretSynced, and Alertmanager stops logging webhook failures (send a test alert / confirm the Watchdog reaches gotify.igou.io).
3. (Optional) add modest CPU/memory requests+limits to the bridge container.

---

## grafana

**Status:** healthy

Grafana instance for the `ocp` hub cluster, deployed via the community Grafana Operator (channel `v5`), fronted by an OpenShift OAuth-proxy sidecar, with the in-cluster Thanos Querier as the default (and only) datasource. It fully recovered the 2026-07-03 rebuild with no manual intervention.

### Health check (live cluster)

| Check | Result |
| ----- | ------ |
| ArgoCD app `grafana` (openshift-gitops) | **Synced + Healthy**; synced revision `d81e454` == `origin/main` HEAD (no drift/staleness) |
| Grafana Operator | `grafana-operator-controller-manager-v5` 1/1 Running on hpg5, 0 restarts |
| `Grafana` CR (`grafanas.grafana.integreatly.org/grafana`) | v13.0.1, stage `complete`/`success`, `GrafanaReady=True`; 11 dashboards + 1 datasource applied into the instance |
| Deployment `grafana-deployment` | 2/2 Running (grafana + oauth-proxy) on truenas-w1, **0 restarts** |
| PVC `grafana-pvc` | **Bound**, 1Gi, `freenas-nvmeof-ssd-csi` |
| Route `grafana-route` | **Admitted=True**, `grafana.apps.ocp.igou.systems`, reencrypt/Redirect |
| Secrets | `grafana-tls` (service serving cert), `grafana-oauth-cookie` (populated), `grafana-sa-token` (populated) all present |
| ExternalSecret `grafana-oauth-cookie` | `SecretSynced` / **Ready=True** |
| Datasource `thanos-querier` | `DatasourceSynchronized=True (ApplySuccessful)` |
| All 11 `GrafanaDashboard` CRs | `DashboardSynchronized=True (ApplySuccessful)` |

Note: `oc get grafana` returns "No resources found" because the short name `grafana` resolves to the **External Secrets** `Grafana` generator kind, not the grafana-operator CR — a harmless naming collision. The operator's `grafanas.grafana.integreatly.org` CR is present and Ready.

### Recovery assessment

This component is **stateless-by-config** and recovered the rebuild cleanly. Every dashboard and the datasource are GitOps-managed CRs that the operator re-pushes into the fresh instance, so no external/Barman/tar restore was required. The 1Gi PVC only backs Grafana's internal sqlite (annotations/prefs); the meaningful state is reconstructed from git. Good design — nothing to restore, and nothing was missed.

### Findings

- **MEDIUM — cross-cutting DR risk: PVC on NVMe-oF with the shared-hostnqn latent bug.** `grafana-pvc` rides `freenas-nvmeof-ssd-csi` (RWO) and the Deployment uses `strategy: Recreate` for a single replica. The cluster-wide latent defect (all 3 nodes share the same NVMe `hostnqn`/`hostid`, nqn `...466937ab...`) causes intermittent volume-attach failures. The volume is currently attached and mounted fine on truenas-w1, but any future reschedule of this pod could hang on attach. One transient readiness-probe timeout was observed ~5m before review (pod recovered, still 0 restarts) — plausibly storage-latency-related. Not grafana-specific, but grafana is exposed. Since this instance is stateless-by-config, it is also a candidate to drop off NVMe-oF entirely.

- **LOW — security (by design, worth restating):** `auth.proxy.enabled=true` + `users.auto_assign_org_role: Admin` means *any* OpenShift user who passes the OAuth-proxy SAR (`get services/grafana-service` in the `grafana` ns) is granted **Grafana Admin**. That SAR is a fairly low bar (namespace view). Documented as intentional (access control at the SAR layer) and acceptable for a homelab, but it is broad. `tlsSkipVerify: true` on the Thanos datasource is documented (internal service-CA cert) and acceptable.

- **LOW — documentation drift:** `README.md` describes the Route as `grafana.apps.hub.igou.systems` and calls this the "hub cluster," but the live config and admitted route are `grafana.apps.ocp.igou.systems`. Cosmetic; the manifests are correct.

- **INFO — self-healed bootstrap race:** At initial sync (~139m ago) the ExternalSecret `grafana-oauth-cookie` logged one `UpdateFailed: Password.generators.external-secrets.io "grafana-oauth-cookie" not found`. The ExternalSecret and its `Password` generator are both sync-wave `10`, so intra-wave ordering isn't guaranteed and the ExternalSecret reconciled first. It self-corrected and is now `SecretSynced=True`. Benign, but explains the stale Warning event.

### Remediation

- **Prioritize the cluster-wide shared-hostnqn/hostid fix** so this (and every other NVMe-oF) PVC re-attaches reliably on reschedule. Given grafana is stateless-by-config, also consider moving `grafana-pvc` to a simpler/non-NVMe-oF StorageClass (or dropping the PVC) to remove it from that failure domain.
- Update `README.md` Route/intro to `grafana.apps.ocp.igou.systems` (drop the "hub" wording) to match reality.
- Optional hardening of the sync-wave race: give the `grafana-oauth-cookie` ExternalSecret a later wave than its `Password` generator (e.g. generator wave 10, ExternalSecret wave 11) to eliminate the transient bootstrap error.
- Optional: reconsider `auto_assign_org_role: Admin` vs `Editor`/`Viewer` if finer-grained Grafana access is ever wanted; today all authz collapses to the single SAR.

---

## hermes-agent

**Status:** degraded — GitOps/platform scaffolding recovered clean and the VM is Running with state restored, but (a) the agent itself is not yet functional (convergence is operator-deferred, expected) and (b) one HIGH latent infra risk (shared NVMe hostnqn) already paused the VM once this session and remains unfixed.

Git source: `applications/hermes-agent` (repo `igou-io/igou-openshift`). ArgoCD app `hermes-agent` is **Synced + Healthy**, synced revision `d81e454` == current `origin/main` HEAD (no drift). Last change to the path: `59a2bc7` "allow igou.io and sandsoftime.igou.io in Hermes egress firewall (#379)".

### What GitOps manages vs. what Ansible manages
Argo owns only the *guardrails*: namespace, blank `hermes-state` DataVolume, `default` EgressFirewall, `hermes-deny-ingress` + `hermes-egress` NetworkPolicies, and the `hermes-vm-hardening` ValidatingAdmissionPolicy. The **VM itself and the `hermes-root` DataVolume are NOT in git** — they are provisioned by Ansible (`/workspace/igou-ansible/playbooks/hermes/provision-vm.yml`) and owned by the `VirtualMachine` object. This is the intended hybrid Argo+Ansible design, but it is a DR fact worth recording: after a cluster wipe the VM must be re-created out-of-band by re-running the playbook (which is what was done).

### Health check (live)
- **VM/VMI:** `virtualmachine/hermes` = Running/Ready; `vmi/hermes` phase Running, `AgentConnected=True`, guest = CentOS Stream 10 (kernel 6.12), IP 10.129.0.36 on **hpg5**. Networking = single `masquerade` interface on the pod network (passes the VAP).
- **PVCs:** `hermes-root` (30Gi) and `hermes-state` (30Gi) both **Bound** on `freenas-nvmeof-ssd-csi` (Block mode, RWO); both DataVolumes `Succeeded`.
- **Security controls all present and correct vs git:** EgressFirewall has 84 rules, is **locked** (terminal `Deny 0.0.0.0/0`, no allow-all debug rule live) and explicitly allows `igou.io` + `sandsoftime.igou.io`; `hermes-deny-ingress` permits only TCP/22 from the `ansible-automation-platform` namespace; `hermes-egress` restricts east-west to named llmkube model pods / searxng / firecrawl-api / quay only; VAP `hermes-vm-hardening` bound with `Deny`, `failurePolicy: Fail`, and the live VM satisfies all four invariants (masquerade-exclusive, no hostDevices, no GPUs). No leftover `temp-allow-ssh-restore` NetworkPolicy — cleanup confirmed. OVN ACL logging active.

### Findings

**[HIGH] Shared NVMe hostnqn/hostid across all 3 nodes — already paused this VM; auto-restart could re-trigger it.**
All nodes carry the identical `nqn.2014-08.org.nvmexpress:uuid:466937ab-…`, violating NVMe-oF uniqueness. Live evidence in the `hermes` namespace: at ~96m `FailedMapVolume … "unable to attach any nvme devices"` on the state volume, then at ~90m `IOerror — VM Paused due to IO error at the volume: state`. The VM recovered (currently Ready, no Paused condition), but because `runStrategy: Always`, **KubeVirt will auto-restart the VM on any crash/reschedule**, and the state (or root) nvmeof volume may again fail to attach — with a data-corruption risk from two hosts sharing one NVMe host identity. Hermes is acutely exposed (two nvmeof RWO volumes on a worker while the master may already hold a controller for that subsystem). This is the top risk. *Remediation:* apply a MachineConfig that regenerates unique `/etc/nvme/hostnqn` (`nvme gen-hostnqn`) + `/etc/nvme/hostid` per node and rolling-reboot; until then keep the human "do not stop/start the VM" guardrail.

**[MEDIUM] VM is not live-migratable and cannot survive a node drain gracefully.**
`vmi` condition `LiveMigratable=False (DisksNotLiveMigratable): PVC hermes-root is not shared (RWO, requires RWM)`. A recent (~92s) `Migrated` warning shows the cluster-default eviction strategy tried and could not migrate it. If hpg5 needs maintenance, hermes must be powered off — which collides with the hostnqn attach risk above. Consequence of RWO nvmeof storage; acceptable by design but a resilience gap to note. `evictionStrategy` is unset on the VM (inherits cluster default LiveMigrate).

**[INFO / not a bug — operator-deferred] Hermes is Running but not yet FUNCTIONAL.**
Guest-agent filesystem list shows **only `vda2` (root) mounted at `/`**; the state disk `vdb` is attached but **not mounted**, and there is no hermes user / gateway / dashboard process on this fresh guest. This means the guest is at Phase-2a only (cloud-init SSH-ready as `igou`, qemu-guest-agent up) and the convergence chain (`setup-os.yml` → `setup-hermes.yml` → `configure.yml`) has not run. Per the review instructions this convergence + go-live (telegram, enabling the systemd unit, re-locking egress) is **operator-deferred and explicitly NOT a defect** — recorded here only so no one mistakes "VM Running" for "agent operational."

**[INFO] State PV restore is done and correct.**
Per the reinstall record, the freshly-created blank `hermes-state` PVC (`pvc-46858de9`) was formatted xfs (UUID 431c7ecf) and ~1.4G of `.hermes` (auth.json / config.yaml / SOUL.md / agent-config / dashboard / cron / memory, uid 1001 preserved) was extracted from `/workspace/backups/hermes/hermes-state-20260703.tar.zst`, excluding the regenerable `./containers` podman store, then unmounted clean. `setup-os.yml` uses `mkfs … force: false`, so the already-formatted+populated disk will be re-mounted (not wiped) when convergence runs. This is consistent with the live observation (vdb present, unmounted). Non-`.hermes` `/home/hermes` content lived on the ephemeral root pre-disaster and is regenerable — not restored, by design.

**[LOW] Transient `ClaimMisbound` events on `hermes-state`** (CDI prime-PVC artifact during the blank import) — no current impact; PVC Bound and in use.

**[LOW] PSA `enforce` still not set** — namespace has `audit=restricted` + `warn=restricted` but no `enforce` (intentionally deferred pending a virt-launcher compatibility check). Minor hardening gap, documented in git.

### Remediation summary
1. **HIGH:** Fix the cluster-wide NVMe hostnqn/hostid collision (per-node MachineConfig + rolling reboot). This is the only finding that materially threatens hermes availability/integrity today. Do not stop/start the VM until it lands.
2. **MEDIUM:** Accept or address non-migratability (would need RWX storage for `hermes-root`); at minimum ensure node-maintenance runbooks account for a required power-off of hermes.
3. **When the operator chooses go-live:** run the deferred convergence (`setup-os` → `setup-hermes` → `configure`) to mount `vdb`, install the agent, and start the gateway/dashboard; then re-lock egress and enable the unit. Not a DR defect.

---

## image-registry

**Status: healthy** (running and recovered cleanly via GitOps; one MEDIUM durability/design caveat — ephemeral `emptyDir` storage)

Git source: `clusters/ocp/image-registry` (single `Config` CR, sync-wave 8). Manages the OpenShift internal image registry operator via `imageregistry.operator.openshift.io/v1 Config/cluster`.

### Health check (live cluster)

- **ArgoCD app** `image-registry` (project `cluster-config`): **Synced / Healthy**, revision `d81e454`.
- **ClusterOperator** `image-registry`: `AVAILABLE=True, PROGRESSING=False, DEGRADED=False`, version `4.21.9`, stable ~7h27m.
- **Config CR** `cluster`: `managementState: Managed`, `replicas: 1`, `rolloutStrategy: Recreate`, `storage: emptyDir {}`, condition `StorageExists=True` ("EmptyDir storage successfully created"), `Available=True`, `Degraded=False`. Created `2026-07-03T18:51:09Z`, storage ready `19:21:51Z` — i.e. reconstituted by GitOps during the reinstall, no manual restore required.
- **Pods** (ns `openshift-image-registry`): `image-registry-*` 1/1 Running on `ocp.igou.systems` (control plane); `cluster-image-registry-operator` 1/1 Running (3 restarts — reinstall churn, not live-flapping); `node-ca` DaemonSet 3/3 Running across all nodes; `image-pruner` CronJob last run **Completed**. No CrashLoopBackOff, no Pending.
- **PVCs**: none (expected — `emptyDir`). **Routes**: none (`defaultRoute` unset → registry not externally exposed). **Service**: `image-registry` ClusterIP `172.30.4.13:5000`.
- Pod `/healthz` returning 200 and serving Prometheus metrics; 64 ImageStreams present cluster-wide.

### Findings

- **[MEDIUM] Registry storage is ephemeral `emptyDir` — no durability.** All registry content lives on the control-plane node's ephemeral disk and is wiped on any pod restart, on the `Recreate` rollout of a config change, or on a control-plane (MS-01) reboot. This matters because the PaC/Pipelines-as-Code tenants actively depend on the in-cluster registry: `clusters/ocp/pac-tenants/values.yaml` adds an `allow-internal-registry` egress rule specifically so Buildah can pull FROM base images resolved through ImageStreams at `image-registry.openshift-image-registry.svc:5000`. After a registry pod restart the cached layers vanish and tenant builds will transiently fail until ImageStreams re-import. Impact is bounded (final build artifacts go to Quay, base images re-import from upstream — nothing is permanently lost), but it is a real availability gap and is exactly the kind of state a DR review should surface.
- **[LOW/INFO] No HA and pinned to the single control plane.** `replicas: 1` on `ocp.igou.systems`; combined with `emptyDir` + `Recreate`, a control-plane reboot means registry unavailability plus cache loss. Acceptable for a single-control-plane homelab, but worth stating explicitly.
- **[POSITIVE] Immune to the shared-hostnqn NVMe-oF bug.** Because this component uses `emptyDir` and no PVC, it was unaffected by the duplicate `hostnqn/hostid` volume-attach failures that hit PVC-backed components during recovery — it came back with zero manual intervention.
- **[LOW/INFO] Minimal attack surface / default trust config.** ClusterIP-only, no `defaultRoute` (not reachable off-cluster) — good. `images.config.openshift.io/cluster` `.spec` is empty `{}` (no `allowedRegistries`/`additionalTrustedCA` hardening) — this is stock OpenShift default, noted for completeness, not a regression.

### Remediation

1. **Decide and document the durability posture (MEDIUM).** If the internal registry is intentionally just a base-image/ImageStream cache with Quay as the real artifact store, add a comment in `cluster-config.yaml` stating `emptyDir` is deliberate and that a registry restart forces ImageStream re-import — so it isn't mistaken for an unfinished restore. Otherwise, back it with persistent storage: either a democratic-csi PVC (`storage.pvc`, RWO is fine given `replicas:1` + `Recreate`) or S3 object storage against the existing RustFS/MinIO used for the CNPG Barman backups (`storage.s3`) for durability across restarts and control-plane reboots.
2. **No immediate action required for health** — operator, pod, ClusterOperator, and ArgoCD are all green and the component self-recovered from the reinstall via GitOps.

---

## ingresscontroller-certs

**Status:** healthy

### Overview
Single-purpose GitOps component (`clusters/ocp/ingresscontroller-certs`) that declares one cert-manager `Certificate` — `apps-certificate` in namespace `openshift-ingress` — for the cluster ingress wildcard `*.apps.ocp.igou.systems`. It writes TLS material into secret `acme-apps`, issued by ClusterIssuer `cluster-acme` (Let's Encrypt/ACME). ArgoCD app in project `cluster-config`, sync-wave `2`.

### Health check (live cluster)
- **ArgoCD app `ingresscontroller-certs`:** Synced / Healthy, revision `d81e454`. Only managed resource is `Certificate/apps-certificate` (Synced/Healthy). No conditions/errors.
- **Certificate `apps-certificate`:** `Ready=True`, reason `Ready`, "Certificate is up to date and has not expired". `notAfter=2026-10-01T18:40:48Z`, `renewalTime=2026-09-16` (renewBefore 15d honored). Age ~7.7h — freshly re-issued after the 2026-07-03 reinstall.
- **Backing secret `acme-apps`:** present, type `kubernetes.io/tls`, 2 data keys. Leaf cert `CN=*.apps.ocp.igou.systems`, SAN `DNS:*.apps.ocp.igou.systems`, issuer `Let's Encrypt CN=YR2` (real public cert, not self-signed).
- **CertificateRequest `apps-certificate-1`:** Approved + Ready; no outstanding ACME `Challenges` (issuance fully completed, not stuck).
- **ClusterIssuer `cluster-acme`:** `Ready=True` (`ACMEAccountRegistered`).
- **End-to-end wiring:** `ingresscontroller/default.spec.defaultCertificate = {name: acme-apps}` — the cert is actually consumed by ingress. IngressController is `Admitted=True`, `Available=True`, `Degraded=False`, all router replicas available. Live TLS probe of `console-openshift-console.apps.ocp.igou.systems:443` served `CN=*.apps.ocp.igou.systems` (Let's Encrypt), confirming the cert is functionally in use, not merely present.

### Findings
- **[INFO] Disaster recovery: fully self-healed, no manual restore needed.** Because the cert is ACME-issued, cert-manager re-requested and re-issued it automatically post-reinstall (cert/secret/request ages ~7–7.7h match the rebuild timeline). No Barman/tar restore was required for this component; it recovered cleanly on its own.
- **[INFO] Correctly configured and functional.** 90d duration / 15d renewBefore matches Let's Encrypt's ~90d lifetime; RSA-4096, `rotationPolicy: Always` (key rotated on every renewal — good hygiene); usages server+client auth. No drift between git and cluster.
- **[LOW] `spec.subject.organizations: ["Igou"]` is a no-op with this issuer.** Public ACME CAs (Let's Encrypt) strip subject O/organization fields — the served leaf is `CN=*.apps.ocp.igou.systems` with no `O=Igou`. Cosmetic only; the field silently does nothing. Not a functional problem.
- **[LOW] Cross-component coupling not captured in this component.** The consumer wiring (`ingresscontroller/default.spec.defaultCertificate → acme-apps`) lives outside this git path. It is correctly set in the live cluster, but the two are maintained separately; if the IngressController config component drifted or were removed, this cert would exist but sit unused. Worth keeping the pairing documented.

### Remediation
- No action required — component is healthy, correctly configured, and end-to-end functional after the rebuild.
- Optional (cosmetic): drop `spec.subject.organizations` since Let's Encrypt ignores it, to avoid implying a subject O that never appears on the issued cert.
- Optional (hygiene): add a note/comment linking this Certificate to the IngressController `defaultCertificate` consumer so the secret-name coupling (`acme-apps`) is obvious to future maintainers.

---

## intel-device-plugins-operator

**Status: healthy**

Stateless operator that recovered the cluster rebuild cleanly from GitOps with no manual restore required. The ArgoCD app is `Synced`/`Healthy` (revision `d81e454`), the operator is running, and the GPU device plugin is not merely running but **verified functional** — it discovered real Intel iGPUs and is advertising them to the scheduler.

### Evidence of health / functionality
- **ArgoCD app** `intel-device-plugins-operator` (project `cluster-config`): `Synced` + `Healthy`; last sync "successfully synced (all tasks run)"; all 4 tracked resources (Namespace, OperatorGroup, Subscription, GpuDevicePlugin) Synced.
- **Operator**: Subscription `state=AtLatestKnown`, channel `stable`, `installPlanApproval: Automatic` (InstallPlan `install-7kfl7` approved). CSV `intel-device-plugins-operator.v0.36.0` = `Succeeded` (AllNamespaces install mode). `intel-deviceplugins-controller-manager` Deployment `1/1` Running on hpg5; no error/fail/panic lines in logs.
- **GpuDevicePlugin CR** `gpudeviceplugin`: DESIRED 3 / READY 3. DaemonSet `intel-gpu-plugin-gpudeviceplugin` `3/3` Ready.
- **Real device discovery (the key functional proof)**: both bare-metal nodes advertise `gpu.intel.com/i915: 10` + `gpu.intel.com/monitoring: 1` in node capacity/allocatable — `ocp.igou.systems` (MS-01 control-plane/worker) and `hpg5.igou.systems`. Plugin log on hpg5 confirms it probed a physical Intel iGPU at PCI `0000:00:02.0` (`/dev/dri/card0`, `/dev/dri/renderD128`) and registered 10 healthy `card0-N` shared slots with kubelet (`sharedDevNum: 10`).
- **No PVCs, no routes, no CRs with persistent state** → nothing to restore after the disaster. Component fully self-reconciled from git; recovery is complete and correct.
- No Warning events in the namespace.

### Findings

- **[INFO] Recovered fully with no restore needed.** This is a stateless device-plugin operator (no PVCs/DBs). Post-rebuild it reconciled entirely from GitOps and re-registered the physical GPUs. No disaster-recovery gap.
- **[LOW] GPU-plugin DaemonSet runs on the GPU-less VM worker.** `truenas-w1` (KubeVirt VM, no GPU passthrough) shows `gpu.intel.com/*` capacity `{}` yet still runs a plugin pod, because the DaemonSet nodeSelector in the CR is only `kubernetes.io/arch=amd64`. Harmless (the pod finds no `/dev/dri` device and advertises nothing) but wastes a pod slot and adds noise. Gating on an NFD/i915 label would keep it off nodes with no Intel GPU.
- **[LOW] No NFD-based gating; relies on the plugin's own probe.** The component does not deploy or depend on Node Feature Discovery labels — device presence is detected only at plugin runtime. Fine for a 3-node homelab, but combined with the finding above it means placement is arch-only, not capability-based.
- **[INFO] `spec.image` drift is benign (ServerSideApply).** The live GpuDevicePlugin CR carries `image: registry.connect.redhat.com/intel/intel-gpu-plugin@sha256:2569cfa0…` (a digest-pinned certified image) that is absent from git; this is the operator/CRD default. Because the app syncs with `ServerSideApply=true` (and `RespectIgnoreDifferences`), ArgoCD does not flag it OutOfSync. Acceptable — git intentionally lets the operator select the certified image. If a pinned, reviewable image is ever desired, add it to `gpu-device-plugin.yaml`.
- **[INFO] Capacity is available but currently unused.** No workload in the cluster requests `gpu.intel.com/i915` right now — 20 shared slots (10 on each of ocp + hpg5) sit idle. Not a defect; just note the plugin's value is latent until a consumer (e.g. media transcode / jellyfin, ML) requests the resource.
- **[INFO] `sharedDevNum: 10` = 10x oversubscription with no isolation.** Each physical iGPU is exposed as 10 schedulable units with no memory/compute isolation between co-scheduled containers. Expected homelab trade-off; consumers must tolerate GPU contention.

### Remediation

- No action required for health or recovery — component is healthy and correctly recovered.
- Optional hardening (both low priority):
  - Add a capability-based nodeSelector to the GpuDevicePlugin CR (e.g. an NFD label such as `intel.feature.node.kubernetes.io/gpu: "true"`) so the DaemonSet no longer schedules a pod on the GPU-less `truenas-w1` VM worker.
  - If a git-reviewable, pinned plugin image is desired for auditability, set `spec.image` explicitly in `components/intel-device-plugins-operator/gpu-device-plugin.yaml`; otherwise leave the operator default as-is.

---

## jellyfin

**Status: not-yet-deployed** (git-defined and re-enabled in `main`, but the ArgoCD child app has never been created — the app-of-apps rollout is stalled behind `quay-operator`).

Media server deployed via the vendored upstream Helm chart (`jellyfin-helm` 3.2.0, image `10.11.11`) with cluster overrides. Source: `applications/jellyfin`, sync-wave 20 in `clusters/ocp/values.yaml`.

### Health check (live cluster)

- **No `jellyfin` ArgoCD Application** in `openshift-gitops` (`applications.argoproj.io jellyfin` → NotFound). **No `jellyfin` namespace, PV, or PVC** exist. The workload is entirely absent.
- `root-applications` (app-of-apps) has synced to `d81e454` (PR #389, which re-enabled jellyfin), but its sync **operation is Running and gated**: `phase=Running, message="waiting for healthy state of argoproj.io/Application/quay-operator"`. In the root app's `status.resources`, `jellyfin` is listed `OutOfSync` (not yet applied), alongside the other wave-3 file apps also still missing: `firecrawl`, `searxng`, `llmkube`, `gotify`, `gitea-mirror`, `ansible-automation-platform`. Earlier wave-3 apps (`forgejo`, `rhdh`) reached Healthy; `quay-operator` is stuck `OutOfSync/Progressing` and is holding the whole ordered sync — so jellyfin is blocked purely by wave ordering, not by any defect of its own.
- Root app syncPolicy is `automated + selfHeal + prune`, so jellyfin will be created automatically **once `quay-operator` goes Healthy** — no manual jellyfin action is needed to unblock it.

### Findings

- **[HIGH] jellyfin not deployed — blocked behind `quay-operator` in the app-of-apps wave gate.** The rollout is parked waiting for `quay-operator` to become Healthy before proceeding to the wave-20 apps. Root cause is external to jellyfin (owned by the quay reviewer); jellyfin's own manifests are intact and its infra deps are ready.
- **[HIGH] `/config` restore gap — jellyfin will very likely come up as a FRESH install (data loss).** `jellyfin-config` PVC is *dynamically* provisioned from `freenas-nvmeof-ssd-csi` (democratic-csi, NVMe-oF) with **no `volumeName`/static bind** and the StorageClass reclaim policy is **Delete**. The DR restored hermes state and the CloudNativePG DBs, but there is **no evidence jellyfin's `/config` (library DB, users, watch/playback state, metadata, image cache) was backed up or restored**. When jellyfin finally schedules it will bind a brand-new empty 20Gi zvol, so the media server will "run" but present as an unconfigured first-boot instance — the definition of running-but-not-functional. (The media library itself is safe — see below — but all library state/user accounts/progress would be lost.)
- **[MEDIUM] NVMe-oF hostnqn collision risk on the config volume.** The config PVC rides NVMe-oF (`freenas-nvmeof-ssd-csi`). The cluster-wide latent bug (all 3 nodes share the same nvme `hostnqn`/`hostid`) causes intermittent volume-attach failures. jellyfin is single-replica, RWO, `Recreate`, pinned to the MS-01 — an attach flake would wedge the only pod with no fallback.
- **[LOW] Media library (`/media`) recovery is sound.** Static NFS PV `jellyfin-media-nfs` → `10.10.9.213:/mnt/cold/media/data/media`, `ReadOnlyMany`, `Retain`, with a pinned `claimRef` to `jellyfin/jellyfin-media`. It rebinds deterministically and is mounted read-only, so no data-loss exposure — only an external dependency on the TrueNAS cold pool.
- **[LOW] Deprecated MetalLB annotation.** The chart Service still uses `metallb.universe.tf/address-pool` (MetalLB logs it deprecated). Functional; already noted in the README as future cleanup.
- **[INFO / POSITIVE] All infra dependencies are healthy and ready to receive jellyfin the moment the gate clears:** `democratic-csi` Synced/Healthy and `freenas-nvmeof-ssd-csi` present (default SC); `gateway-api` Synced/Healthy; the shared `guest-dmz` Gateway is `PROGRAMMED=True` at `10.10.152.3`; MetalLB `guest-dmz` pool exists. Manifests are well-hardened: `Recreate` + single replica (RWO config + single iGPU), `nodeSelector` pinning to the MS-01 for i915 transcode, `externalTrafficPolicy: Local`, seccomp `RuntimeDefault`, `runAsNonRoot`, `drop: ALL`, supplementalGroup 797 for the iGPU, HTTPRoute with API-server defaults stated explicitly for SSA and `request: 0s` for streaming, and a blackbox Probe against the public `/health` path.

### Remediation

1. **Unblock the rollout:** clear `quay-operator` to Healthy (its reviewer's action). The app-of-apps is auto/selfHeal — jellyfin will then be created and synced with no jellyfin-specific step. Verify with `oc get applications.argoproj.io jellyfin -n openshift-gitops` and `oc -n jellyfin get pods,pvc`.
2. **Resolve the `/config` restore before/at first sync (do this deliberately, not by accident):** decide whether the pre-disaster jellyfin config is recoverable. Options: (a) if the old TrueNAS zvol still exists, statically pre-create the PV and pin the `jellyfin-config` PVC to it via `volumeName` so the sync adopts the existing data instead of provisioning empty; or (b) accept a fresh library and plan re-setup (users, libraries, transcode settings). Either way, add jellyfin `/config` to a backup routine — it is currently the only jellyfin state not covered by the DR restore plan.
3. **Confirm NVMe uniqueness before the config volume attaches:** ensure the shared-hostnqn/hostid fix is applied to the MS-01 (where jellyfin is pinned) so the RWO NVMe-oF config PVC attaches cleanly; otherwise the single pod risks an attach wedge.
4. **After it comes up**, verify functionality end-to-end (not just Running): pod on `ocp.igou.systems`, config + media volumes mounted, iGPU (`gpu.intel.com/i915`) allocated, `https://jellyfin.dmz.igou.systems/health` returns 2xx through the Gateway, and the direct VIP `10.10.152.1:8096` answers.

---

## kubeletconfig

**Status:** healthy

Declarative single-resource component: one `KubeletConfig` CR (`set-max-pods`) applied via the `machineconfiguration.openshift.io` API and rolled out by the Machine Config Operator. No namespace-owned workloads, no operator, no PVCs, no persistent state. It recovered the post-disaster rebuild cleanly and is verifiably functional (not merely synced).

### Health check (live cluster)

- **ArgoCD app** `kubeletconfig` (project `cluster-config`, sync-wave 3): `Synced` / `Healthy`; last sync operation `Succeeded` at 2026-07-03T18:56:41Z on revision `d81e454`. Single tracked resource `KubeletConfig/set-max-pods` is Synced.
- **KubeletConfig `set-max-pods`**: status condition `Success=True`, `observedGeneration: 1`. Age 7h53m (consistent with the 2026-07-03 reinstall).
- **MCO rollout**: MC `99-master-generated-kubelet` generated 7h53m ago; `master` MCP is `UPDATED=True, UPDATING=False, DEGRADED=False` (1/1 machines). No degraded/pending pool.
- **Effective on-node result (authoritative)**: master `ocp.igou.systems` reports `capacity.pods=1000` / `allocatable.pods=1000` — the config actually took effect on the kubelet. Master currently runs 201/1000 pods; node conditions `MemoryPressure=False, DiskPressure=False, PIDPressure=False, Ready=True`. Fully functional.
- No CrashLoopBackOff / Pending / OutOfSync / Missing anywhere for this component.

### Findings

- **[INFO] Config is master-MCP-scoped only; workers keep default 250 maxPods.** `machineConfigPoolSelector` matches `pools.operator.machineconfiguration.openshift.io/master`. Workers `hpg5` and `truenas-w1` remain at `capacity.pods=250`. This is almost certainly intentional — the control plane `ocp.igou.systems` carries the `worker` role (SNO-style schedulable master) and hosts the bulk of workloads, hence the 1000-pod headroom there. Flagged only so the asymmetry is a known choice, not drift.
- **[LOW] `maxPods: 1000` + `podsPerCore: 50` — effective limit is `min(maxPods, podsPerCore × cores)`.** Master has 20 CPU → podsPerCore yields exactly 1000, matching maxPods, so today they are consistent. If the control-plane were ever resized to fewer cores, `podsPerCore` would silently cap the limit below 1000 (e.g. 16 cores → 800). Not a current defect; note for any future CPU change.
- **[LOW/observation] 1000 pods on a single control-plane that also does worker duty is aggressive.** `autoSizingReserved: true` mitigates by auto-sizing system-reserved based on node capacity, and there is no pressure at 201 pods today. Worth watching PID/memory reserves as workload density grows; the number is real headroom, not a safe steady-state target.
- **[NONE] Security / DR:** No secrets, no ExternalSecrets, no persistent data — nothing to restore for this component. It was correctly re-materialized by GitOps on rebuild and the MCO re-derived + rolled the machineconfig automatically. No latent restore gap.

### Remediation

- No action required; component is correct, applied, and functional.
- Optional hygiene: if either dedicated worker is expected to host many pods, add a worker-scoped `KubeletConfig` rather than relying on the master-only override (currently they sit at the 250 default).
- If the control plane is ever rebuilt with a different core count, re-confirm `podsPerCore × cores ≥ maxPods` (or drop `podsPerCore`) so the intended 1000 limit still holds.

---

## llmkube

**Status: not-yet-deployed** (blocked behind the in-progress app-of-apps recovery sync; also carries one HIGH latent misconfiguration that will break a model the moment it does deploy)

LLMKube is the self-hosted LLM inference stack: the `defilantech/LLMKube` operator (Helm chart `0.8.8`) plus three `Model`/`InferenceService`/`Route` triplets in `llmkube-system` — `qwen3-35b-a3b` (2x RTX 4060 Ti on the casval burst node), `qwen35-2b` (Pascal P620 on p330), and `gemma-4-e2b` (CPU on hpg5).

### Health check (live cluster)

- **ArgoCD Application `llmkube` does not exist.** `oc get application llmkube -n openshift-gitops` → NotFound. The app-of-apps (`root-applications`) lists it as `OutOfSync | Missing`.
- **Nothing is deployed:** namespace `llmkube-system` absent, `inference.llmkube.dev` CRDs absent (`the server doesn't have a resource type "inferenceservices"/"models"`), no controller, no Model/InferenceService CRs, no pods, no model-cache PVC, no routes.
- **Why:** `root-applications` sync is `phase=Running` (started 2026-07-04T01:42Z) and repeatedly blocks "waiting for healthy state of" earlier-wave apps (observed cycling through `quay-operator`, `cert-manager-operator and 3 more`). The sync has not yet reached the point of creating the wave-19/20 apps. `llmkube` is one of **7 apps still `Missing`** for the same reason: `firecrawl` (w19), `gotify`/`jellyfin`/`searxng`/`llmkube` (w20), `gitea-mirror` (w23), `ansible-automation-platform` (w30). This is an **external app-of-apps ordering blocker, not a llmkube-specific defect.**
- **Runtime substrate llmkube depends on is healthy** (good news for when it deploys): `nvidia-gpu-operator` Synced/Healthy, `cluster-api` Synced/Healthy (casval `MachineSet` present, DESIRED=0 as expected for scale-from-zero), and all three democratic-csi NFS storage classes recovered — including `freenas-nfs-ssd-csi` which the RWX model-cache requires.

### Findings

- **[HIGH] `qwen35-2b` is pinned to a node that no longer exists — it will be permanently unschedulable.** `qwen35-2b-inferenceservice.yaml` sets `nodeSelector: kubernetes.io/hostname: p330.igou.systems`, but **p330 is dead/no-BMC and is not in the cluster** (`oc get node p330.igou.systems` → NotFound; nodes are only ocp, hpg5, truenas-w1). With `replicas: 1` in git, the instant llmkube syncs this pod goes Pending forever (no other Pascal GPU exists). This is stale-hardware config that survived into the rebuild.
- **[MEDIUM] Model-cache is empty post-disaster; first start re-downloads all GGUFs from HuggingFace.** The shared `llmkube-model-cache` RWX PVC was destroyed with the cluster and there is no restore step (it is a cache, so no data loss, but it is a functional cold-start cost + external dependency). On first sync the `Model` CRs will pull `Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf` (~25 GiB) plus the qwen3.5-2b and gemma-4-e2b weights over the internet onto `freenas-nfs-ssd-csi` before any endpoint is Ready. Expect a long "Downloading" phase; verify TrueNAS NFS-ssd headroom for ~30+ GiB.
- **[MEDIUM] Deployment is gated on an app-of-apps sync that is currently churning and not converging.** Until `root-applications` gets past the cert-manager/quay health waits, llmkube (and 6 peers) will never be created. Needs the upstream blocker cleared (out of llmkube's scope, but it is the reason for the not-yet-deployed status).
- **[LOW] `replicas: 1` on all three InferenceServices contradicts the README's "default replicas: 0".** So all three attempt to run immediately on first sync — including the doomed p330 one. If the intent is manual scale-up, git drifted from the documented default. (The `ignoreDifferences` on `/spec/replicas` is correctly present in both `values.yaml` and the README, so ArgoCD will not fight manual scaling — that part is fine.)
- **[LOW / INFO] `gemma-4-e2b` node pin is declarative-only.** The repo's own comment notes this controller build strips `nodeSelector` for CPU-accelerator models, so the `hpg5` pin is not enforced by the controller (hpg5 does exist and is Ready, so it is at least a valid target — unlike p330). Placement is not durable across reschedules.
- **[INFO / positive] Configuration is otherwise sound and disaster-aware.** Controller image is digest-pinned with an explicit rationale guarding against the `--default-fsgroup` CrashLoop on newer builds; `fsGroup: 1001030000` is pinned into the OpenShift restricted-v2 SCC range on every inference pod; model-cache is correctly `ReadWriteMany` on the NFS-ssd class (RWO block classes would Multi-Attach-deadlock across the burst + p330 pins); CUDA vs CPU llama.cpp images are per-model digest-pinned with correct Pascal/Ada reasoning. None of these are broken — they just have not run yet.

### Remediation

1. **Fix the p330 pin (HIGH).** Until p330 hardware is replaced, either remove/repoint `qwen35-2b-inferenceservice.yaml`'s `nodeSelector` to a live GPU node or set its `replicas: 0`, so it does not sit permanently Pending after deploy. (Note: no live change possible/permitted now — this is a git edit for the maintainer.)
2. **Clear the app-of-apps blocker (MEDIUM).** llmkube cannot deploy until `root-applications` finishes; drive `cert-manager-operator`/`quay-operator` (and the other early-wave gaters) to Healthy so the sync advances to wave 20. Then confirm the `llmkube` Application, `llmkube-system` namespace, CRDs, controller, and model-cache PVC appear.
3. **Plan for the cold model re-download (MEDIUM).** After deploy, watch `Model` CR `phase` (Downloading → Ready) and confirm `freenas-nfs-ssd-csi` has room for the GGUFs before expecting any InferenceService endpoint to answer.
4. **Reconcile `replicas` with intent (LOW).** Decide whether the checked-in default should be `0` (matching README) with manual scale-up, or keep `1`; either way ensure the p330 model is not the one left at `1`.
5. **Post-deploy functional verification (do NOT mark healthy on "pods Running").** For each intended model, curl `https://<route-host>/v1/models` and a small `/v1/chat/completions` to confirm the endpoint actually serves (the README's sanity-check block), since "running" here means weights must also load into VRAM/RAM and the llama.cpp server must pass warmup.

---

## loki-operator

**Status:** healthy (operator install fully recovered) — but functionally **idle**: no LokiStack instance exists anywhere, so no logs are actually aggregated.

Component source: `components/loki-operator` (kustomize: `openshift-operators-redhat` namespace + OperatorGroup + Subscription). ArgoCD app `loki-operator` (project `cluster-config`, sync-wave 10) is **Synced / Healthy**, last sync Succeeded 2026-07-04T01:38:06Z on the rebuilt cluster.

### Health check (cluster state)

- **Subscription** `loki-operator` (channel `stable-6.5`, source `redhat-operators`, `installPlanApproval: Automatic`) — state `AtLatestKnown`, currentCSV == installedCSV == `loki-operator.v6.5.1`.
- **CSV** `loki-operator.v6.5.1` — Phase **Succeeded** (replaced v6.5.0). InstallPlan `install-b5f8n` Automatic/approved.
- **OperatorGroup** `loki-operator` present; namespace `openshift-operators-redhat` created with `openshift.io/cluster-monitoring: "true"`.
- **Deployment** `loki-operator-controller-manager` **1/1 Available**; pod `...-9cw49` **Running, 0 restarts**, ~2.5h age, scheduled on `truenas-w1`. No errors/panics in recent controller logs.
- **CRDs installed:** `lokistacks`, `alertingrules`, `recordingrules`, `rulerconfigs` (loki.grafana.com), created 2026-07-04T00:25:07Z — consistent with a clean post-reinstall bootstrap.
- No OutOfSync / Degraded / Missing / Pending / CrashLoopBackOff for this component. The operator recovered the rebuild cleanly.

### Findings

1. **[Medium] No LokiStack instance — the operator is installed but does nothing.** `oc get lokistack -A` returns **No resources found**, and `git grep 'kind: LokiStack'` across `origin/main` (and full history via `-S`) returns nothing. The operator's sole job is to reconcile LokiStack CRs; with none declared, log aggregation/retention is not actually happening. The paired `openshift-logging` component (cluster-logging operator, also v6.5, Running) likewise ships **no LokiStack, no ClusterLogForwarder** (`oc get clusterlogforwarder -A` → none), so the end-to-end logging pipeline is non-functional. This is the current committed design (operators only), not a DR regression — but "running" here is not "functional."
2. **[Low] No object-storage backing prepared for a future LokiStack.** A LokiStack requires an S3-style object-storage secret; `openshift-logging` has no such secret. History shows a NooBaa/MCG `lokistack-backingstore.yaml` once lived under the old `config/sno/live/multicloudgateway/` path but was deleted ("remove mcg briefly", f8b82e2) and never re-added in the current `components/` structure. Any attempt to instantiate a LokiStack today would block on missing object storage — worth noting given the incident's separate NVMe/CSI attach fragility (shared hostnqn) that would also affect Loki PVCs.
3. **[Low] `installPlanApproval: Automatic`.** The operator silently rode the channel up to v6.5.1. Acceptable for a homelab, but on a single-control-plane cluster an unattended CSV bump is an uncontrolled change vector; consider `Manual` for the logging operators.
4. **[Info] No post-disaster restore was required for this component** — it is stateless (operator + CRDs only); state, if any, would live in a LokiStack's PVCs, which don't exist. Nothing to restore, nothing lost.

### Remediation

- Decide intent: if cluster log aggregation is desired, add a `LokiStack` CR (with an S3/object-storage `Secret` and a `ClusterLogForwarder`) to the `openshift-logging` component and wire it via values.yaml; otherwise document that `loki-operator` + `cluster-logging` are intentionally installed idle (e.g. as a dependency/placeholder) so future reviewers don't read the empty state as breakage.
- When a LokiStack is added, provision object storage first and confirm its PVCs bind cleanly given the known shared-hostnqn NVMe-oF attach bug.
- Consider switching `installPlanApproval` to `Manual` for loki-operator (and cluster-logging) to gate future version bumps on this single-node cluster.

_Scope note: findings 1–2 straddle the sibling `openshift-logging` component; the `loki-operator` component itself is correctly configured and healthy._

---

## lvms-operator

**Status:** healthy (running, Synced/Healthy, LVMCluster reconciled, thin-pool rebuilt post-disaster) — but functionally **idle/unproven** and carrying a couple of data-safety footguns.

Component provides node-local LVM/thin-pool storage via the LVM Storage operator (topolvm.io CSI). Git source: `clusters/ocp/lvms-operator` (cluster overlay: `lvmcluster.yml` + `lvms-lvm-local-storage-storageclass.yml`) which pulls in base `components/lvms-operator` (Namespace `openshift-storage` w0, OperatorGroup w1, Subscription w2). LVMCluster + StorageClass are sync-wave 5.

### Health check (live cluster)

| Object | State |
|---|---|
| ArgoCD app `lvms-operator` | **Synced / Healthy**, revision `d81e454`, no conditions/errors |
| Subscription `lvms` → CSV `lvms-operator.v4.21.0` | **Succeeded**; InstallPlan `install-hgm6m` Approved=true |
| Deployment `lvms-operator` | 1/1 Ready |
| DaemonSet `vg-manager` | 1/1 Ready (1 desired — pinned to master, see F2). 1 restart = normal thin-pool bootstrap restart (`reason: Completed`, exit 0 at init), **not** a crashloop |
| `LVMCluster/lvmcluster` | **Ready** — `ResourcesAvailable` + `VolumeGroupsReady` True; deviceClass `lvm-local-storage` on `ocp.igou.systems` Ready |
| StorageClasses | `lvms-lvm-local-storage` (WaitForFirstConsumer, operator-generated) + `lvms-lvm-local-storage-immediate` (git-managed, Immediate); VolumeSnapshotClass `lvms-lvm-local-storage` present |
| On-node (MS-01) | `/dev/nvme0n1p5` = 1.5T LVM2_member; VG `lvm-local-storage` present; thin-pool `lvm-local-storage-thin-pool` <1.38T, **0.00% data / 2.66% meta used** |
| No Warning events in `openshift-storage` | — |

**Disaster recovery: PASSED.** After the wipe/reinstall the operator + LVMCluster reconciled cleanly and `forceWipeDevicesAndDestroyAllData: true` re-created the VG/thin-pool on the master's `nvme0n1p5` with no manual intervention. Not affected by the shared-`hostnqn` NVMe-oF latent bug — LVMS is pure local LVM, so it is actually the one storage path independent of that fault (a resilience plus).

### Findings

- **[Low / informational] Zero consumers — running but functionally unproven.** 0 PVCs and 0 PVs exist on either topolvm StorageClass cluster-wide (thin-pool 0.00% used). Every live PVC uses democratic-csi (`freenas-nvmeof-ssd-csi` is the default). LVMS is healthy and idle; its data path has not been exercised since the rebuild. Intended consumers exist only in git (scaffold-vm skill default + `test-workloads/virtualmachine-devhosttest` DataVolume), none currently deployed. Recommend a quick provision smoke-test (PVC on `lvms-lvm-local-storage`, pod on master) to confirm end-to-end functionality rather than just "Ready".

- **[Medium / data-safety] `forceWipeDevicesAndDestroyAllData: true` left permanently enabled** (`lvmcluster.yml`). Needed to reclaim `nvme0n1p5` during the reinstall, but persisting it is a footgun — if the device selector ever resolves to a different/repurposed partition, LVMS silently destroys it. Especially pointed given the incident was itself an unattended destructive reinstall. Steady-state risk is low (device is already an lvms-owned LVM2_member), but best practice is to flip it back to `false` now that the VG exists.

- **[Low-Med / by-design SPOF] Master-only local storage.** LVMCluster `nodeSelector` pins the deviceClass to `node-role.kubernetes.io/master Exists` and tolerates the master taint (commit e43a7a2 — hpg5/truenas-w1 lack `/dev/nvme0n1p5`, and the webhook makes nodeSelector immutable). Consequence: topolvm volumes only provision on the single control-plane node (MS-01); no LVMS-backed local storage on either worker, and any consumer is hard-pinned to master. Acceptable as designed, but it is a single-node, non-HA storage path — do not use it for anything that must survive MS-01 loss.

- **[Low / latent misconfig] Immediate-binding SC is a scheduling footgun.** The hand-rolled `lvms-lvm-local-storage-immediate` (`volumeBindingMode: Immediate`) provisions a node-local LV on the master *before* a consumer is scheduled; topolvm PVs are node-local and cannot attach to a pod that lands on hpg5/truenas-w1. It works only because it's used for master-pinned KubeVirt DataVolumes. Any future workload using this SC without a master nodeSelector will hit attach failures. Prefer the WaitForFirstConsumer SC unless immediate binding is truly required.

### Remediation

1. (Optional, verification) Run a PVC+pod smoke test on `lvms-lvm-local-storage` scheduled to `ocp.igou.systems` to prove the CSI data path post-rebuild; delete after.
2. (Medium) After confirming the VG/thin-pool is stable, set `deviceSelector.forceWipeDevicesAndDestroyAllData: false` in `clusters/ocp/lvms-operator/lvmcluster.yml` and sync, to remove the standing data-destruction risk. (Note: the webhook makes some deviceClass fields immutable — validate whether this toggle requires an LVMCluster delete/recreate before attempting; do not act without operator sign-off.)
3. (Low) Document/accept the master-only SPOF and keep `-immediate` SC usage restricted to master-pinned workloads (as scaffold-vm already defaults). No change required unless HA local storage becomes a requirement.
4. No action needed on hostnqn — out of scope for LVMS.

---

## machineconfigs

**Status:** degraded (ArgoCD app Synced/Healthy and it recovered the rebuild, but there is a worker-coverage gap and the component does not remediate the critical shared-hostnqn latent bug that falls squarely in its domain)

Git source: `clusters/ocp/machineconfigs` (sync-wave 2, dest ns `openshift-machine-config-operator`). Contains exactly one resource: `MachineConfig 99-master-load-nvme-tcp` (kustomization + the MC YAML). It drops `/etc/modules-load.d/nvme-tcp.conf` = `nvme-tcp` (ignition 3.2.0) onto the **master** pool so the NVMe/TCP transport module loads at boot for democratic-csi NVMe-oF volumes.

### Health check (read-only)

- **ArgoCD app `machineconfigs`:** Synced / Healthy, last op Succeeded. Managed resource `MachineConfig/99-master-load-nvme-tcp` present and Synced.
- **ClusterOperator `machine-config`:** 4.21.9, Available=True, Progressing=False, Degraded=False (8h).
- **MachineConfigPools:** `master` Updated=True, Degraded=False (1/1); `worker` Updated=True, Degraded=False (2/2). No pending/updating pools.
- **MCO pods:** controller, operator, server, and all 3 daemons Running (2/2). Non-zero restart counts on the two worker daemons/rbac-proxy (23, 14) but currently stable — consistent with the post-reinstall worker re-join churn, not an active fault.
- **MC applied on cluster:** `99-master-load-nvme-tcp` created 2026-07-03T19:08 (during the rebuild recovery window) and is present in the master MCP rendered source list → **it did recover**.
- **Live verification (SSH):** on `ocp.igou.systems` (master) `/etc/modules-load.d/nvme-tcp.conf` exists and `nvme_tcp`/`nvme_fabrics` are loaded. On `hpg5` and `truenas-w1` (worker-only) the file is **absent**, yet `nvme_tcp` is loaded anyway (lazily modprobe'd by the democratic-csi node plugin at first volume attach).

### Findings

- **[CRITICAL] Shared NVMe hostnqn/hostid across all 3 nodes — not remediated by any component.** Confirmed live: all of `ocp`, `hpg5`, `truenas-w1` report the identical `nqn.2014-08.org.nvmexpress:uuid:466937ab-67bf-4315-971b-bc110d55ce28` and hostid `466937ab-...`. This violates NVMe-oF host-identity uniqueness and is the documented cause of intermittent volume-attach failures. The rebuild did NOT fix it, and no MachineConfig (or any git-managed resource) addresses it. This node-level Ignition concern belongs in this component's domain but is currently unowned.
- **[MEDIUM] nvme-tcp module persistence covers only the master pool; the actual worker attach-points are not covered.** The MC targets `machineconfiguration.openshift.io/role: master`. The nodes that actually run most workloads and attach democratic-csi NVMe-oF volumes are the dedicated workers `hpg5` and `truenas-w1`, which get NO persistent `modules-load.d` entry. It "works" today only because the CSI node driver modprobes `nvme_tcp` on demand — meaning a first NVMe-oF attach immediately after a worker reboot can race/fail before the module is up (retry then succeeds), which is precisely the failure mode a boot-time module-load is meant to prevent. There is no `99-worker-load-nvme-tcp` MC. (The single-node master is schedulable — roles master+worker — which is why only it was given the guarantee; the true workers were overlooked.)
- **[LOW/INFO] Component scope is minimal.** Only the nvme-tcp module is managed here; SSH keys and registries MCs on the cluster are MCO/agent-install generated, not GitOps-owned — expected, just noting the component does not manage them.

### Remediation

1. **Fix the shared hostnqn/hostid (critical).** Add a MachineConfig to this component (both `master` and `worker` roles) that installs a oneshot systemd unit regenerating a per-node identity, e.g. write `/etc/nvme/hostnqn` via `nvme gen-hostnqn` and `/etc/nvme/hostid` from a fresh UUID (or derive deterministically from `/etc/machine-id`), guarded so it only runs when the value still equals the shared `466937ab...` placeholder, followed by a one-time reboot/reconnect. Do NOT ship a static file (that would re-pin identical values). Validate uniqueness across all 3 nodes afterward. This is the highest-value change and directly clears the incident's latent bug.
2. **Extend nvme-tcp module load to the worker pool (medium).** Add `99-worker-load-nvme-tcp` (identical body, `role: worker`) or generalize to a shared MC per pool so `/etc/modules-load.d/nvme-tcp.conf` is present on `hpg5` and `truenas-w1`, removing the first-attach-after-reboot race. Confirm the resulting `worker` MCP rolls out cleanly (it will trigger one rolling reboot of the workers).
3. **No action needed on operator health** — MCO, MCPs, and the existing master MC are all healthy, in-sync, and recovered.

---

## metallb

**Status: healthy**

MetalLB (git sources `components/metallb-operator` + `clusters/ocp/metallb`) fully recovered from the 2026-07-03 cluster reinstall. Both ArgoCD apps are `Synced`/`Healthy` at `origin/main` (`d81e454`), the operator CSV is `Succeeded`, all BGP sessions are Established, and the one live LoadBalancer service (the guest-dmz ingress gateway) has its IP assigned and advertised end-to-end. MetalLB is stateless (no PVCs), so there was nothing to restore — GitOps reconciliation alone brought it back.

### Health check (live cluster)

- **ArgoCD apps**: `metallb-operator` = Synced/Healthy; `metallb` (pools/peers/advertisements) = Synced/Healthy. No drift vs `origin/main`.
- **Operator**: `metallb-operator.v4.21.0-202606240914` CSV `Succeeded`; Subscription `stable`/`redhat-operators`, InstallPlan Approved (Automatic). MetalLB CR `metallb` reports `Available=True`, `Degraded=False`, `Progressing=False`.
- **Pods** (all Running, all on schedule):
  - `controller` 2/2, `metallb-operator-webhook-server` 1/1 — 0 recent restarts.
  - `speaker` DaemonSet **3/3** across all three nodes (`ocp.igou.systems`, `hpg5`, `truenas-w1`) — confirms the `workload=burst` `speakerTolerations` in the MetalLB CR is doing its job so every node runs a speaker (needed for `externalTrafficPolicy: Local`).
- **CRs reconciled**: 3 IPAddressPools (`trusted-lan` 10.10.150.0/24, `iot` 10.10.151.0/24, `guest-dmz` 10.10.152.0/24, all `autoAssign:false` + `avoidBuggyIPs`), 3 BGPAdvertisements (aggregationLength /32 + per-tier community), 1 BGPPeer (`mikrotik` 10.10.9.1, myASN 64513 / peerASN 64512), 1 Community (`tier`).
- **BGP is actually up (functional, not just running)**: all 3 speakers show the `10.10.9.1` (64512) neighbor Established with multi-hour uptime (7h32m / 4h56m / 4h52m), each advertising `PfxSnt=1`.
- **End-to-end proof**: `guest-dmz-openshift-default` (openshift-ingress) has EXTERNAL-IP **10.10.152.3** from the `guest-dmz` pool; `show bgp ipv4 unicast` on the master speaker confirms `10.10.152.3/32` is the best path advertised to the router. The DMZ gateway path (jellyfin, etc.) is live through MetalLB.
- **PVCs**: none (component is stateless). No post-disaster data restore required — recovered by reconciliation only.

### Findings

- **[Info] Operator manager restarted 8× during bootstrap, now stable.** `metallb-operator-controller-manager` last terminated exitCode 1 at 2026-07-03T19:43:37 (during the initial post-reinstall install window, a CRD/webhook readiness race). No restarts in the last ~7h; currently 1/1 Running. Self-healed — no action needed, just noted so it isn't mistaken for an active crashloop.
- **[Low] BGPPeer has no MD5/authentication and no BFD profile.** `mikrotik-bgppeer.yaml` sets `holdTime: 180s`/`keepaliveTime: 60s` but no `password` and no `bfdProfile`. Consequence: (a) no session authentication, and (b) failover on node/link loss waits out the ~180s hold timer rather than sub-second BFD. Acceptable for a trusted homelab LAN, but sub-second failover would need a BFD profile added on both MetalLB and the RouterOS side.
- **[Low/expected] `metallb-system` namespace is PSA `privileged`** (`pod-security.kubernetes.io/enforce: privileged`, `podSecurityLabelSync:false`). This is required by the speaker (host networking / raw sockets for BGP+ARP) and is the standard MetalLB posture — flagged only for completeness.
- **[Info] `iot` and `trusted-lan` pools are provisioned but currently carry no LoadBalancer services** (only `guest-dmz` is in use, `PfxSnt=1` per speaker). Not a defect — capacity staged ahead of workloads; nothing to advertise yet.

### Remediation

- No corrective action required — component is healthy and functional post-rebuild.
- Optional hardening (both `clusters/ocp/metallb/mikrotik-bgppeer.yaml`): add a `bfdProfile` (+ matching BFD config on the rb5009) for fast failover, and consider an MD5 `password` (sourced via ExternalSecret) on the BGP session.
- No monitoring change needed; keep the operator-manager restart count in mind only if it climbs again (would indicate a webhook/CRD issue rather than the one-time bootstrap race seen here.)

---

## molecule

**Status: degraded** — the component itself (the namespace) is Synced/Healthy and recovered cleanly, but the end-to-end molecule test capability is **not functional** because the `ansible-molecule` service-account token was never re-published to 1Password after the reinstall (a cross-cutting PushSecret 403 in the sibling `service-accounts` component). The namespace has no persistent data, so there was nothing to restore.

### What the component is

`components/molecule` is intentionally tiny — a single scratch `Namespace` (`molecule`) used to run ad-hoc Ansible **molecule** test scenarios against the cluster. The git source is just:

- `kustomization.yaml` → `molecule-namespace.yaml`
- `molecule-namespace.yaml` — the namespace with `openshift.io/description: "This namespace is used to run ad-hoc molecule tests"`

The actual test-runner RBAC/credentials live in the separate `components/service-accounts` component:
- ServiceAccount `ansible-molecule` (in ns `service-accounts`)
- ClusterRole `molecule-kubernetes` (verbs on `kubevirt.io/virtualmachines`, core `services` [full CRUD], core `pods` [get/list]) bound into the `molecule` namespace via rolebinding `ansible-molecule-molecule-kubernetes`
- ClusterRoleBinding `ansible-molecule-node-reader` → `system:node-reader`
- **PushSecret `ansible-molecule-token-push`** → publishes the SA token to 1Password item `ocp-ansible-molecule` (property `token`) so external Ansible molecule runs can auth to the cluster

### Health check (cluster state)

- ArgoCD app `molecule` (project `cluster-config`, sync-wave 39): **Synced / Healthy**, last op Succeeded 2026-07-03T23:23:38Z.
- Namespace `molecule`: Active (created 2026-07-03T23:23:38Z, ~post-reinstall). Correct PSA labels (`restricted` warn/audit), Argo tracking-id present.
- No Deployments/StatefulSets/DaemonSets/pods/PVCs/routes/quotas — expected; it is a bare scratch namespace (nothing OutOfSync, Pending, or CrashLooping).
- RBAC in-cluster is correct: rolebinding `ansible-molecule-molecule-kubernetes` → ClusterRole `molecule-kubernetes`, subject = SA `ansible-molecule` in ns `service-accounts`. ClusterRole and SA both exist.

### Findings

- **[HIGH] Stale/undistributed molecule SA credential — test capability broken.** PushSecret `service-accounts/ansible-molecule-token-push` is `Ready=False / Errored`:
  `set secret failed: ... error updating 1Password Item: status 403: Authorization: token does not have permission to perform update on vault iggugnytc2y6nenftd65o4eyvi`.
  Because the reinstall minted a brand-new SA token (new cluster CA/signing keys), the token still sitting in 1Password item `ocp-ansible-molecule` is the **pre-disaster, now-invalid** one, and the fresh token cannot be pushed. Any external molecule run that pulls `ocp-ansible-molecule` from 1Password to authenticate will fail. So molecule is "running" (namespace + RBAC present) but not "functional".
- **[HIGH — root cause, cross-cutting, not molecule-specific] onepassword-sdk-claude lacks write grant.** This is not a molecule bug. **All 6** PushSecrets in `service-accounts` are Errored with the same 403 (`ansible-molecule-token-push`, `claude-edit-token-push`, `cluster-edit-token-push`, `cluster-read-only-token-push`, `ns-agent-token`, `virtualmachine-ops-token`). The `onepassword-sdk-claude` ClusterSecretStore itself validates (`Ready=True`), so the SDK service-account token has read but not **update/write** grant on vault `iggugnytc2y6nenftd65o4eyvi`. This matches the known pattern in memory ("Connect server edit grant was the final fix"; "queued writes drain on grant fix") — the vault write/edit grant for the SDK token was not re-applied after the DR rebuild.
- **[INFO] No data-restore gap for molecule.** The namespace holds no PVCs/stateful workloads, so no Barman/tar restore was required; the component recovered fully from GitOps. Sync-wave ordering is correct (molecule ns wave 39 precedes service-accounts RBAC wave 40).

### Remediation

1. **Fix the 1Password SDK write grant (fixes all 6 SAs, including molecule).** Grant the `onepassword-sdk-claude` service account **write/edit** permission on vault `iggugnytc2y6nenftd65o4eyvi` (the same edit-grant step from the prior 1Password Connect rollout). Then let External Secrets re-reconcile the PushSecrets — they should flip to `Ready=True` and overwrite the stale tokens.
2. **Verify the fresh molecule token lands in 1Password.** After the grant, confirm PushSecret `ansible-molecule-token-push` is `Ready=True` and that item `ocp-ansible-molecule.token` now matches the current in-cluster SA token, so external molecule runs can authenticate again. (Out of scope for this read-only review — no changes were made.)
3. **No change needed to `components/molecule` itself** — the component is correctly defined and healthy. Track the fix under the `service-accounts` / 1Password Connect grant workstream, not molecule.

---

## nmstate

**Status: healthy** — operator and all NNCPs recovered cleanly after the rebuild; the applied node network state matches git. One coverage gap and one dormant/stale policy noted below (both low severity, neither degrading).

Git source: `clusters/ocp/nmstate` (overlay) → `components/nmstate` (base). ArgoCD app `nmstate`: **Synced / Healthy**, revision `d81e45401b47`, last sync Succeeded 2026-07-03T19:16:40Z, all tracked resources Synced/Healthy.

### What is deployed and working
- **Operator**: `kubernetes-nmstate-operator.4.21.0-202606240914` (channel `stable`, Automatic approval) — CSV Phase Succeeded, version matches cluster 4.21. `NMState` instance `nmstate` = Available / SuccessfullyDeployed.
- **Workloads** (ns `openshift-nmstate`): deployments `nmstate-operator`, `nmstate-webhook`, `nmstate-metrics`, `nmstate-console-plugin` all 1/1; DaemonSet `nmstate-handler` 3/3 Ready (one handler per node). No crashloops/pending; the two single restarts on the hpg5 and truenas-w1 handlers (~4h58m ago) coincide with worker re-join reboots, not faults.
- **Recovery verified end-to-end**: post-reinstall the NNCPs re-applied on both intended nodes. NNCEs `ocp.igou.systems.mapping` and `hpg5.igou.systems.mapping-hpg5` = Available / SuccessfullyConfigured. Confirmed against live `NodeNetworkState`:
  - `ocp` (master): `br-secondary` OVS bridge present, `enp2s0f1.45` VLAN present, OVN bridge-mapping `br-secondary → trunk-network` present.
  - `hpg5`: `br-secondary` present, `enp2s0.45` VLAN present, `br-secondary → trunk-network` mapping present.
  - This restored the secondary/trunk localnet path that Multus/localnet secondary-network workloads depend on. nmstate did its job in the DR.

### Findings

- **[LOW / informational] truenas-w1 worker has no NNCP → no `br-secondary`/`trunk-network` localnet coverage.** The cluster now runs three nodes (ocp, hpg5, **truenas-w1**), but only `mapping` (master) and `mapping-hpg5` exist. `truenas-w1`'s NodeNetworkState shows only the default `br-ex → physnet` OVN mapping — no `br-secondary`, no `trunk-network`. This is architecturally expected: `truenas-w1` is a nested KubeVirt VM worker with a single virtio NIC (`ens3`) and no second physical/trunk port to bridge. Impact: any secondary-network (localnet `trunk-network`) or VLAN-45 workload scheduled onto `truenas-w1` will fail to attach — nmstate cannot and does not guard scheduling. Not a regression from the rebuild.

- **[LOW] `mapping-casval` NNCP is dormant (Ignored / NoMatchingNode) and carries stale storage config.** `casval` is the burst GPU node whose MachineSet is scaled to zero / deprovisioned, so the policy correctly reports `Ignored / NoMatchingNode` and — thanks to `argocd.argoproj.io/ignore-healthcheck: 'true'` — does not degrade the ArgoCD app. It re-applies automatically if the burst node returns, so keeping it is defensible. Note it also pins casval-specific storage networking (Mellanox CX4 `enp1s0f0np0` @ 9000 MTU, `10.199.0.2/24`, host route `10.10.9.213/32 → 10.199.0.1`); if the burst node or its NIC layout has changed, this is latent drift that would silently mis-apply on next scale-up.

- **[INFO] No nmstate-specific persistent state to restore.** nmstate is a declarative, git-sourced operator; there is no PVC/database. "Restore" = re-reconcile from git, which happened correctly. Nothing was missed in the DR for this component. No security gaps: no secrets, no routes, standard operator RBAC, webhook and metrics healthy.

- **[INFO] `maxUnavailable: 2` on all NNCPs.** Harmless on this 3-node cluster (the `mapping` policy selects the single master; worker policies select one node each), but worth remembering if the cluster grows — a rollout could reconfigure networking on 2 nodes simultaneously.

### Remediation

1. **Confirm intent for truenas-w1**: decide whether secondary/trunk-network workloads are ever meant to land there. If not (expected, given single-NIC VM), ensure such workloads carry node affinity/anti-affinity or a nodeSelector that keeps them off `truenas-w1` (a workload-side control, not nmstate). If they are meant to, `truenas-w1` needs a trunk NIC and a dedicated NNCP — currently impossible with one virtio interface.
2. **Validate `mapping-casval` before the next burst scale-up**: verify the CX4 interface name (`enp1s0f0np0`), the `10.199.0.0/24` storage addressing, and the `10.10.9.213/32` route still match reality; prune or update the policy if the burst node's hardware/topology changed. Otherwise leave as-is (correctly ignored).
3. No action required on the operator, handler DaemonSet, or the `mapping`/`mapping-hpg5` policies — all healthy and correctly recovered.

---

## nvidia-gpu-operator

**Status:** healthy (operator fully recovered; currently idle — no GPU nodes present in cluster)

The NVIDIA GPU Operator recovered cleanly from the 2026-07-03 cluster reinstall via GitOps. The ArgoCD app is `Synced / Healthy`, the operator CSV `gpu-operator-certified.v25.10.1` is `Succeeded`, the `gpu-cluster-policy` ClusterPolicy is `ready`, and the operator pod has 0 restarts. It is stateless (no PVCs/routes), so no post-disaster data restore was required — a redeploy from git was sufficient and complete.

The important caveat: the operator is doing its job but has **zero GPUs to manage right now**. Both `NVIDIADriver` CRs are `notReady`, and no node carries the `nvidia.com/gpu` label. This is the expected consequence of the current hardware state (p330 dead, casval scaled to 0), not an operator defect.

### Live state observed
- ArgoCD `nvidia-gpu-operator`: **Synced / Healthy**.
- Subscription `gpu-operator-certified` (channel `v25.10`, Automatic approval) → CSV `gpu-operator-certified.v25.10.1` **Succeeded**; InstallPlan `install-k8cql` approved.
- Deployment `gpu-operator` 1/1, pod on `truenas-w1`, 0 restarts, reconcile loop clean.
- ClusterPolicy `gpu-cluster-policy` state `ready`, condition `Ready=True` reason **`NoGPUNodes`** ("No GPU node found, watching for new nodes to join the cluster") — healthy idle state.
- `NVIDIADriver pascal-580`: **notReady** — `no nodes matching the given node selector for pascal-580` (targets `p330.igou.systems`).
- `NVIDIADriver burst-595`: **notReady** — `no nodes matching the given node selector for burst-595` (targets `casval.igou.systems`).
- NFD healthy (`nfd-instance`, 3 workers running) — feature detection is up and will label a GPU node when one appears.
- ServiceMonitors present (`gpu-operator`, `nvidia-dcgm-exporter`, `nvidia-node-status-exporter`); namespace has `openshift.io/cluster-monitoring: "true"`.
- No PVCs, no routes — nothing stateful to restore.

### Findings

**[INFO / expected] No live GPU capacity — both driver CRs notReady.**
`pascal-580` targets `p330.igou.systems`, which is dead (no BMC) per the incident record, and `burst-595` targets `casval.igou.systems`, whose CAPI MachineSet `casval-worker` is scaled to 0/0. With no matching nodes, neither driver DaemonSet can be created, so the cluster currently advertises no `nvidia.com/gpu` resource. This is correct behavior given the hardware, but it means GPU workloads (e.g. llmkube scaling) cannot schedule until casval bursts up or a Pascal node is restored. Not a regression from the rebuild.

**[MEDIUM] `time-slicing-config-configmap.yaml` is orphaned and non-functional.**
The file exists under `components/nvidia-gpu-operator/` but is **not listed in `kustomization.yaml`**, so ArgoCD never renders it — confirmed live: `configmaps "time-slicing-config" not found` in the namespace. Even if it were deployed, the ClusterPolicy's `devicePlugin` block does **not** reference it (no `devicePlugin.config.name`/`configMapName: time-slicing-config`), so the intended 4-replica GPU time-slicing is wired up nowhere. Net effect: the single Pascal/burst GPU could not be shared across pods as this config implies — the feature is silently inert. This is pre-existing incomplete config (not something the rebuild broke), but it is drift between apparent intent and actual behavior.

**[LOW] Subscription uses `installPlanApproval: Automatic`.**
Consistent with the other operators in this cluster, but it means the operator auto-upgraded to `v25.10.1` unattended. Acceptable for a homelab; worth being aware of since GPU driver-branch compatibility (Pascal 580 ceiling) is version-sensitive.

**[INFO] `ClusterPolicy.spec.driver.version: 580.105.08` is a dead default.**
Documented in-file as unused while `useNvidiaDriverCRD: true` (per-node versions come from the NVIDIADriver CRs). Correct and intentional — no action.

### Remediation
1. No action needed for the operator itself — it recovered fully and is correctly idle. When `casval` next bursts, confirm the node joins as `casval.igou.systems` (matching the `burst-595` selector) and that the driver DaemonSet lands and advertises `nvidia.com/gpu`; if the burst node name differs, update `nvidiadriver-burst-595.yaml`.
2. Resolve the orphaned time-slicing config: either (a) delete `time-slicing-config-configmap.yaml` from the component if time-slicing is not wanted, or (b) if it is wanted, add it to `kustomization.yaml` **and** wire it into the ClusterPolicy (`devicePlugin.config.name: time-slicing-config` with a default entry). As-is it is misleading dead config.
3. Track the p330 replacement/repair (dead, no BMC) — until then `pascal-580` will remain `notReady` by design; consider whether that CR should stay in git or be commented out to avoid a permanently-notReady resource.
4. (Optional) Consider pinning the Subscription to a specific CSV or Manual approval if GPU driver-branch stability matters, given the Pascal 580 compatibility ceiling.

---

## ocp-base-config

**Status: healthy**

ArgoCD app `ocp-base-config` (sync-wave 8) is **Synced / Healthy** (revision `d81e454`). It is a Helm chart (`.helm/charts/ocp-base-config`) rendered by kustomize `helmCharts`, cluster-scoped (no dedicated namespace). Given the ocp `values.yaml`, the only feature block that actually renders resources is **auth**; `monitoring`, `network.hostRouting`, and `timesync` are all `false`, and the `certManager` block renders nothing (see F1). All live auth resources are present and functional, and they recovered the rebuild automatically with no manual restore.

### What it manages (live verification)
- `OAuth/cluster` — HTPasswd IDP named `igou` → `htpasswd-secret`. **Synced.**
- `Group/global-admins` — `users: [igou]`. **Synced.**
- `ClusterRoleBinding/global-admins-binding` — `global-admins` group → `cluster-admin`. **Synced.**
- `ExternalSecret/htpasswd-secret` (openshift-config) — condition `SecretSynced` / "secret synced"; backing `Secret` present (keys: `htpasswd`, `notesPlain`, `password`), created `2026-07-03T19:25:53Z` (post-rebuild). **Synced/Healthy.**
- Generated `Secret/v4-0-config-user-idp-0-file-data` (openshift-authentication), created post-rebuild.
- `clusteroperator/authentication`: **Available=True, Degraded=False, Progressing=False** ("All is well").
- `ClusterSecretStore/onepassword-sdk-ocp-pull` (dependency): **Ready=True**.

**DR outcome: fully recovered, no manual intervention required.** The component is pure declarative config plus a 1Password-backed ExternalSecret, so it re-materialized the htpasswd secret and re-applied OAuth/group/RBAC on GitOps bootstrap. htpasswd login → `cluster-admin` for `igou` is working end-to-end.

### Findings

**F1 — LOW (misleading dead config): `certManager` block in `values.yaml` renders nothing.**
`clusters/ocp/ocp-base-config/values.yaml` carries a full `certManager:` block (`enabled: true`, `apiCert: true`, `defaultIngressCert: true`, ACME base, Cloudflare DNS-01 solvers, `dns-token` ExternalSecret). The chart `.helm/charts/ocp-base-config/templates/` has **no cert-manager templates** (only `auth/`, `monitoring/`, `networking/`, `timesync/`). So none of it is applied — a reader would wrongly believe this app provisions the API server cert and default ingress cert. Actual cert handling lives in the separate `cert-manager-config` (wave, `clusters/ocp/cert-manager-config`) and `apiserver-certs` (wave 9, `clusters/ocp/apiserver-certs`) apps. Not a functional break, but it is stale/duplicative config that invites drift and confusion during a DR (someone could "fix" certs here to no effect).

**F2 — LOW (durability): monitoring is disabled → ephemeral in-cluster metrics.**
`monitoring.enabled: false`, so no `cluster-monitoring-config` ConfigMap is rendered; Prometheus/Alertmanager fall back to `emptyDir`. Metrics and silences are lost on pod restart/reschedule. The chart already supports persistent PVCs (`storageClass: freenas-nvmeof-fast-csi`, 50Gi Prometheus / 10Gi Alertmanager). Likely intentional, but confirm this is desired given the cluster now has working democratic-csi storage.

**F3 — INFO (latent template inconsistency): OAuth hardcodes the secret name.**
`templates/auth/oauth-config.yaml` sets `htpasswd.fileData.name: htpasswd-secret` literally instead of `{{ .Values.auth.externalSecret.name }}`. Harmless today (value equals the literal), but if `auth.externalSecret.name` were ever changed, the OAuth would silently keep pointing at the old name and break login.

**F4 — INFO (secret hygiene): ExternalSecret extracts the whole 1Password item.**
`htpasswd-secret` is created via `dataFrom.extract`, so extra item fields (`notesPlain`, `password`) land in the openshift-config Secret alongside the needed `htpasswd` key. No exposure risk (restricted namespace, single field consumed), but a `data`-scoped `remoteRef` to just the `htpasswd` field would be cleaner.

### Remediation
1. **F1:** Remove the `certManager:` block from `clusters/ocp/ocp-base-config/values.yaml` (or re-add cert-manager templates to the chart if this app is meant to own certs — but do not, since `cert-manager-config`/`apiserver-certs` already do). Read-only review: no change applied.
2. **F2:** Decide explicitly on monitoring persistence; if wanted, set `monitoring.enabled: true` (PVCs already parameterized) — otherwise leave and document as intentional.
3. **F3:** Template the OAuth `fileData.name` from `.Values.auth.externalSecret.name` for consistency.
4. **F4:** Optional — switch the ExternalSecret to a field-scoped `data` ref for the `htpasswd` key only.

All remediation is config-quality / drift-reduction; none blocks current operation. Component is healthy and DR-recovered.

---

## onepassword-connect

**Status: degraded** — Connect itself is healthy and the READ path (its primary function, feeding External Secrets Operator) fully recovered post-disaster; but the WRITE path (all 6 `PushSecret` reverse-publish flows) is broken with HTTP 403 because the restored Connect credential lacks vault write grants.

Git source: `clusters/ocp/onepassword-connect` (Helm chart `connect` v2.4.1, images `1password/connect-{api,sync}:1.8.2`). ArgoCD app `onepassword-connect` (project `cluster-config`): **Synced / Healthy**, revision `d81e454`.

### Health check (live cluster)

| Aspect | State |
|---|---|
| ArgoCD app | Synced / Healthy, no conditions |
| Pod `onepassword-connect-759c7d68f4-c9r6f` | 2/2 Running, 0 restarts, 7h24m, on `ocp.igou.systems` (control-plane, as pinned by nodeSelector/tolerations) |
| Deployment/ReplicaSet/Service | 1/1 available; ClusterIP `172.30.169.214` :8080 (connect-api) + :8081 (connect-sync) |
| Route | `onepassword-connect-onepassword-connect.apps.ocp.igou.systems`, edge TLS + Redirect, default LE `acme-apps` cert |
| NetworkPolicy `connect-allow-eso-and-router` | present; ingress restricted to `external-secrets-operator` + `openshift-ingress` on 8080 (correct) |
| RoleBinding `onepassword-connect-nonroot-v2` | present; `default` SA → `nonroot-v2` SCC so UID/fsGroup 999 runs (avoids #282) |
| `op-credentials` secret | present, key `1password-credentials.json`, `managed-by: ansible` (age 8h — seeded BEFORE the pod) |
| connect-sync | clean startup, DB initialized, 21 vaults synced, **no sync-side errors** |
| connect-api | `/health` & `/heartbeat` 200; **5542× 200 (reads) but 1332× 403 (writes)** |

### Findings

**[HIGH] All 6 PushSecrets fail with 403 — Connect credential has no write grant on the `claude` and `ocp-push` vaults.**
Every `PushSecret` in namespace `service-accounts` is `Errored`:
- via `onepassword-sdk-claude` → vault `claude` (`iggugnytc2y6nenftd65o4eyvi`): `ansible-molecule-token-push`, `claude-edit-token-push`, `cluster-edit-token-push`, `cluster-read-only-token-push`
- via `onepassword-sdk-ocp-push` → vault `ocp-push` (`dtd2bcigxk7ud64ed4nvsb7hl4`): `ns-agent-token`, `virtualmachine-ops-token`

All report `status 403: Authorization: token does not have permission to perform update on vault …`, matching the 1332 `PUT … (403: Forbidden)` in connect-api. These flows publish generated k8s ServiceAccount tokens BACK into 1Password so downstream consumers (AAP/Ansible, molecule, ns-agent, virtualmachine-ops, Claude container) can read them. The root cause sits in this component: the Connect integration's per-vault access grant (embedded in the restored `1password-credentials.json` / its issued token) is **read-only** for these two vaults. Reads (ExternalSecrets) are unaffected. This is almost certainly a restore regression — the credential was re-seeded during the rebuild without carrying the prior read+write grants on `claude` and `ocp-push`.

**[MEDIUM] Bootstrap secrets live entirely outside GitOps (DR single point).**
`op-credentials` (this ns) and `onepassword-connect-token` (in `external-secrets-operator`) are both `managed-by: ansible`, pre-seeded out-of-band (documented as "Task 4" in the kustomization). Nothing in Git or ArgoCD can recreate them — Connect (and therefore ~all ExternalSecrets cluster-wide) cannot start without a correct manual seed. The read path was restored correctly, but the same seed step is exactly where the missing write grant (HIGH above) slipped through. This dependency must be captured in the DR runbook and, ideally, the seed automated/verified.

**[LOW] Misleading ClusterSecretStore naming.**
The stores are named `onepassword-sdk-*` but their provider is the **Connect** provider (`connectHost: http://onepassword-connect.onepassword-connect.svc:8080` + `connectTokenSecretRef`), not the 1Password SDK provider. Cosmetic, but can misdirect an operator during an incident.

**[INFO / positive — recovery confirmed] Read path is fully functional.**
All ExternalSecrets across the cluster are `SecretSynced=True` (zero exceptions); all 3 ClusterSecretStores validate `Ready=True` against Connect; 21 vaults synced; 5542 successful reads. In-cluster plaintext HTTP is acceptable (edge Route terminates TLS; NetworkPolicy limits ingress to ESO + router). Chart version, images, nodeSelector, tolerations, and SCC binding all match Git — no drift.

### Remediation

1. **Restore write access (fixes HIGH).** In the 1Password admin console, grant this Connect integration **read+write** on the `claude` and `ocp-push` vaults (currently read-only). Alternatively regenerate `1password-credentials.json` (and, if re-issued, the token) with those write grants, re-seed `op-credentials` + `onepassword-connect-token` via the Ansible playbook (`managed-by: ansible`), then `oc rollout restart deploy/onepassword-connect -n onepassword-connect` so connect-sync re-reads. The 6 PushSecrets will then reconcile. Verify with `oc get pushsecret -A`.
2. **Confirm the token↔server mapping:** ensure `onepassword-connect-token` (in `external-secrets-operator`) belongs to the same Connect server that now holds the write grants.
3. **Harden the DR runbook (fixes MEDIUM):** document and, where possible, automate/verify the out-of-band seed of `op-credentials` and `onepassword-connect-token` — including the required vault **read+write** grants — as an explicit post-reinstall step, since GitOps cannot reproduce them.
4. **(Optional, LOW):** rename the ClusterSecretStores to reflect that they are Connect-backed to reduce operator confusion.

---

## openshift-logging

**Status:** degraded — the cluster-logging **operator** recovered cleanly and is Healthy, but the logging **pipeline is non-functional**: no `LokiStack` (log store) and no `ClusterLogForwarder` (collector) exist anywhere in git or on the cluster, so zero logs are being collected, stored, or forwarded.

### Scope
`components/openshift-logging` deploys **operator-only** manifests: `namespace.yaml`, `operatorgroup.yaml` (`cluster-logging`, `upgradeStrategy: Default`), and `subscription.yaml` (`cluster-logging`, channel `stable-6.5`, `installPlanApproval: Automatic`, `redhat-operators`). A sibling `components/loki-operator` installs the Loki operator into `openshift-operators-redhat`. Both are sync-wave 10 in `clusters/ocp/values.yaml`.

### Health check (read-only)
- **ArgoCD app** `openshift-logging`: **Synced / Healthy**, revision `d81e454`, project `cluster-config`, selfHeal on. `loki-operator` app also Synced/Healthy.
- **Subscription/CSV**: `cluster-logging.v6.5.1` **Succeeded**; InstallPlan `install-229gv` approved. Loki `loki-operator.v6.5.1` Succeeded.
- **Deployment/Pods**: `cluster-logging-operator` 1/1 Available, pod Running on hpg5, **0 restarts**, 149m. `loki-operator-controller-manager` 1/1 Running. No crashloops/pending.
- **CRDs present**: `clusterlogforwarders.observability.openshift.io`, `logfilemetricexporters.logging.openshift.io`, plus Loki CRDs (`lokistacks`, `alertingrules`, `rulerconfigs`, etc.).
- **PVCs**: none (operator has no persistent state). **Routes/UIPlugin**: none. **Warning events**: none.
- Operator logs show the CLF controller started and is idle-watching for a `ClusterLogForwarder` — confirming none exists.

### Findings
1. **[HIGH — functional gap] No log collection/storage/forwarding is configured.** `oc get clusterlogforwarder -A`, `oc get lokistack -A` both return *No resources found*. In Logging 6.x the operators are inert until you create a `LokiStack` (store) and a `ClusterLogForwarder` (collector DaemonSet). Neither is committed in `components/openshift-logging` or `components/loki-operator`. Result: application/infra/audit logs are **not being aggregated at all** — the stack is "running but not functional."
2. **[INFO — not a DR regression] Nothing to restore.** This component is operator-only with no PVCs/persistent state, so the reinstall recovered it correctly and completely. The missing pipeline is a **pre-existing design gap**, not disaster-recovery drift (git never defined a LokiStack/CLF, and the live cluster matches git exactly — hence Synced/Healthy).
3. **[LOW — supply-chain/version pinning] `installPlanApproval: Automatic` on `stable-6.5`.** Combined with the incident's netboot/auto-reinstall theme, automatic operator upgrades mean a channel bump can roll the operator unattended. Acceptable for logging, but worth noting given the environment's sensitivity to unattended automation.
4. **[LOW — no visualization]** No logging `UIPlugin`/console log view and no route; even once a LokiStack exists, log viewing in the console would need the Cluster Observability Operator UIPlugin (not part of this component).

### Remediation
- To make logging actually functional, add (in git, GitOps-managed) a `LokiStack` CR referencing an object-storage secret (TrueNAS/RustFS S3 is already used for CNPG Barman backups and would be the natural bucket) plus a `ClusterLogForwarder` (`observability.openshift.io/v1`) selecting the desired log types → Loki. Wire storage-secret provisioning via ExternalSecret/1Password as done elsewhere.
- Optionally add a logging `UIPlugin` (Cluster Observability Operator) for in-console log viewing.
- Consider pinning to a specific CSV / `installPlanApproval: Manual` if unattended operator upgrades are a concern.
- No post-disaster restore action required for this component specifically — it is stateless and already reconciled to git.

---

## openshift-nfd

**Status:** healthy

Node Feature Discovery (Red Hat NFD operator) recovered cleanly from the 2026-07-03 cluster reinstall and is fully functional — it is producing node feature labels on all three nodes, not merely running. NFD is entirely stateless (no PVCs, no persistent data, no external secrets), so it required zero post-disaster restore: the operator re-derives all labels from live hardware on each `sleepInterval`.

### Evidence / health snapshot

- **ArgoCD app** `openshift-nfd`: `Synced` / `Healthy` at rev `d81e454`; app-of-apps sync-wave 5 (`clusters/ocp/values.yaml`), `IgnoreExtraneous` compare-option.
- **Operator**: CSV `nfd.4.21.0-202606240914` = `Succeeded`; Subscription `nfd` (channel `stable`, Automatic approval) = `AtLatestKnown`, installedCSV==currentCSV; InstallPlan approved. OperatorGroup `openshift-nfd` scoped to its own namespace (own-namespace mode) — correct.
- **Workloads**: `nfd-controller-manager` 1/1, `nfd-gc` 1/1, `nfd-master` 1/1, DaemonSet `nfd-worker` 3/3 — all Running, 0 restarts. No CrashLoopBackOff/Pending.
- **CR** `NodeFeatureDiscovery/nfd-instance`: `Available=True (AllInstanceComponentsAreDeployedSuccessfuly)`, `Degraded=False`, `Progressing=False`.
- **Functional proof**: `NodeFeature` objects exist for all 3 nodes; `feature.node.kubernetes.io/*` labels present (81 on ocp master, 60 on hpg5, 51 on truenas-w1). PCI whitelist is working — `pci-0200_*` (network, class 0200) and `pci-0300_*` (display, class 03) labels are populated per node, plus `network-sriov.capable`, `rdma.available`, CPU/kernel/OS-release feature labels.
- No PVCs, no Routes (expected — NFD is stateless and cluster-internal). No Warning events.

### Findings

1. **[Low–Medium] Operand image drift: pinned to v4.20 on a 4.21 cluster.**
   `nfd-instance-nodefeaturediscovery.yaml` hardcodes `spec.operand.image: registry.redhat.io/openshift4/ose-node-feature-discovery-rhel9:v4.20`, and the running master/worker/gc pods confirm the `:v4.20` tag — while the cluster is OpenShift 4.21.9 and the operator (controller-manager) is `ose-cluster-nfd-rhel9-operator` 4.21. Red Hat's guidance is that the operand image track the operator/cluster version. It is working today (NFD is version-tolerant and the labels are correct), but this is a real version skew that will diverge further on future upgrades and defeats the operator's own operand-image management. Note also the tag is mutable (`imagePullPolicy: Always` + floating `:v4.20`), so the exact operand digest is not pinned.

2. **[Info] Benign nfd-worker log noise.** Every discovery cycle logs `failed to detect Swap nodes ... open /host-proc/swaps: no such file or directory`. This is cosmetic on RHCOS (swap is disabled by design); discovery still completes (`feature discovery completed` each cycle). No action.

3. **[Info] PCI whitelist class `12` (processing accelerators) yields no labels.** The `workerConfig` whitelists device classes `0200`/`03`/`12`; only `0200` (network) and `03` (display) match hardware present today — no class-12 accelerator is installed, so no such label appears. Harmless; the whitelist is evidently intended to feed downstream GPU/accelerator consumers (nvidia-gpu-operator and intel-device-plugins-operator CSVs are both installed on this cluster).

### Remediation

- **Recommended:** Bump `spec.operand.image` to `...:v4.21` to match the 4.21 cluster/operator, or (preferred) drop the explicit `spec.operand.image` override entirely and let the operator select the version-matched operand from its CSV `relatedImages`. For reproducibility, prefer a digest (`@sha256:...`) over a floating tag. This is a single-line change in `components/openshift-nfd/nfd-instance-nodefeaturediscovery.yaml`; low risk, no data to migrate.
- No DR remediation needed — component is stateless and self-heals; nothing was lost in the reinstall.
- The Info items require no action.

---

## openshift-pipelines

**Status: broken** (operator never reinstalled after the 2026-07-03 DR rebuild; component is functionally down. The ArgoCD app misleadingly reports `Healthy`.)

### Summary
The OpenShift Pipelines (Tekton) operator failed to install during the post-disaster GitOps re-bootstrap and has been stuck ever since. The `openshift-pipelines` namespace does not exist, no CSV is installed, the `TektonConfig` CRD is absent, and no Tekton/Pipelines-as-Code controllers are running. ArgoCD has been retrying (attempt #19) to apply `TektonConfig` and failing with `no matches for kind "TektonConfig" ... ensure CRDs are installed first`. Root cause is an OLM shared-InstallPlan approval block, not a bad manifest — the git config itself is well-written.

### Findings

**[CRITICAL] Pipelines operator never installed — whole component non-functional.**
- Subscription `openshift-pipelines-operator` (ns `openshift-operators`) is stuck `state: UpgradePending`, `installedCSV: None`, `currentCSV: openshift-pipelines-operator-rh.v1.22.4`. Conditions: `InstallPlanPending=True (RequiresApproval)`, `BundleUnpacking=True`.
- No `openshift-pipelines` namespace, no CSV, `tektonconfig`/`pipelinesascode`/`tekton` API resources absent, zero pods/deployments/statefulsets.
- Subscription created `2026-07-03T23:21` (during the DR GitOps re-bootstrap) and has never progressed — a direct casualty of the reinstall.

**[CRITICAL — root cause] Automatic pipelines install is blocked behind a co-bundled Manual InstallPlan.**
- The pipelines Subscription is `installPlanApproval: Automatic`, but OLM bundled its install into InstallPlan `install-khg9h`, which contains **two** CSVs: `servicemeshoperator3.v3.3.5` **and** `openshift-pipelines-operator-rh.v1.22.4`.
- Because `servicemeshoperator3` uses `installPlanApproval: Manual` and is unapproved, the entire shared plan is `approval: Manual, approved: false, phase: RequiresApproval` — so the Automatic pipelines install cannot proceed. This is the classic shared-`openshift-operators`-OperatorGroup gotcha: one Manual operator in the namespace gates co-bundled Automatic operators.
- The servicemesh subscription is **out-of-band** (owned by the ingress operator for Gateway API — annotation `ingress.operator.openshift.io/owned`; pinned `startingCSV: servicemeshoperator3.v3.2.0`, channel `stable`). It is **not** in git or ArgoCD, so this blocker sits outside GitOps visibility.

**[HIGH] Downstream consumers are also down.**
- `TektonConfig config` and `ExternalSecret signing-secrets` show ArgoCD status `OutOfSync / Missing` (they can't apply — CRD and namespace don't exist).
- The `pac-tenants` ArgoCD app is `OutOfSync` (its Pipelines-as-Code `Repository` CRDs don't exist). Any PAC webhooks/CI PipelineRuns and Tekton Chains signing are non-functional cluster-wide.

**[LOW/INFO] ArgoCD app health is misleading.**
- `openshift-pipelines` app reports `SYNC=OutOfSync, HEALTH=Healthy`. The aggregate is `Healthy` only because the Subscription reports Healthy and the two blocked children have health `Missing` (which doesn't downgrade the app). `operationState.phase=Running` with a `SyncFailed` on `TektonConfig` is the real signal. Do not trust the top-line Healthy here.

**[POSITIVE] DR-restore design for signing state is sound; manifests are correct.**
- Tekton Chains signing key is restored declaratively via `ExternalSecret signing-secrets` from 1Password item `tekton-chains-signing` (ClusterSecretStore `onepassword-sdk-ocp-pull` is `Ready`), with `creationPolicy: Merge` + `deletionPolicy: Retain`. No manual DR step is needed — it will self-materialize once the namespace/operator exist. No separate backup/restore gap for this component.
- Config quality is good: pruner enabled (keep 20, daily), CI pod hardening (`runAsNonRoot`, `automountServiceAccountToken: false`, `tekton-ci-low` PriorityClass for preemptible PR runs), resolvers enabled, PAC wired to the console, Chains transparency/fulcio disabled (appropriate for homelab), and a well-documented note on why `seccompProfile` is deliberately omitted (avoids the OCP SCC `pipelines-scc` empty-seccompProfiles rejection). No misconfiguration found in the component manifests.

### Remediation
1. **Unblock the operator install (primary fix).** Approve the pending shared InstallPlan:
   `oc patch installplan install-khg9h -n openshift-operators --type merge -p '{"spec":{"approved":true}}'`
   **Caveat:** this ALSO upgrades OSSM `servicemeshoperator3` v3.2.0 → v3.3.5, which underpins Gateway API (jellyfin and other Gateways). Confirm that upgrade is acceptable first. If it is not, instead delete the pending plan (`oc delete installplan install-khg9h -n openshift-operators`) and let OLM regenerate; verify the regenerated pipelines plan is not re-bundled with servicemesh before it auto-approves.
2. **Let it converge.** Once the CSV reaches `Succeeded`, the operator creates the `openshift-pipelines` namespace and the `TektonConfig`/`TektonPipeline`/PAC CRDs; ArgoCD self-heal (automated + selfHeal) will then apply `TektonConfig` and the `signing-secrets` ExternalSecret. Verify: `oc get csv -n openshift-operators | grep pipelines`, `oc get tektonconfig config`, `oc get secret signing-secrets -n openshift-pipelines`, and the app returns to `Synced`.
3. **Recover downstream.** Refresh/sync `pac-tenants` and confirm PAC `Repository` objects and Chains signing are live after the operator is up.
4. **Preventive (MEDIUM).** Document/guard the shared-namespace gotcha: pipelines (Automatic) shares the global `openshift-operators` OperatorGroup with the Manual, ingress-operator-owned servicemesh subscription, so any future OSSM upgrade will re-block pipelines. Options: add a periodic pending-InstallPlan approval/alert for `openshift-operators`, or bring the servicemesh subscription under GitOps and set a deliberate approval policy so this drift is visible.

---

## openshift-virt

**Status:** degraded (running and Synced/Healthy, but a VM-storage reliability bug is actively hitting the workload and one placement guard is silently non-functional)

The component deploys OpenShift Virtualization (KubeVirt HyperConverged / CNV) into `openshift-cnv`: the `hco-operatorhub` Subscription (channel `stable`), OperatorGroup, the `HyperConverged` CR, and nine CDI `StorageProfile` overrides for the democratic-csi backends (nvmeof / iscsi / nfs × ssd/fast/cold).

### Health check (live cluster)

- **ArgoCD app `openshift-virt`:** `Synced` + `Healthy`, operationState `Succeeded`, synced to `d81e454` which is exactly `origin/main` HEAD — no git/tracked-revision drift.
- **Operator:** Subscription `AtLatestKnown`; CSV `kubevirt-hyperconverged-operator.v4.21.10` `Succeeded`; InstallPlan `install-xk76d` Complete. (Operator is 4.21.10 vs cluster 4.21.9 — expected, HCO tracks its own channel.)
- **HyperConverged:** `Available=True`, `Progressing=False`, `Degraded=False`, `Upgradeable=True`, `systemHealthStatus=healthy`. featureGates `deployTektonTaskResources` + `enableCommonBootImageImport` active as configured.
- **Pods:** all 36 in `openshift-cnv` Running; `virt-handler` DaemonSet 3/3 ready; virt-operator/virt-api/virt-controller healthy. The Warning events on `openshift-cnv` (FailedMount tls secrets, ssp-operator ComponentUnhealthy, SecretUpdateFailed) are all ~171m old from the post-reinstall operator bring-up and have cleared. `AdvancedFeatureUse` warnings are normal (HCO sets 2 infra replicas on a multi-node cluster).
- **StorageProfiles:** all 9 present; `.status.claimPropertySets` matches `.spec` on every one (block RWO for iscsi/nvmeof, RWX+RWO Filesystem for nfs, cloneStrategy snapshot) — correctly reconciled.
- **Golden images:** DataImportCrons for centos-stream9/10, fedora, rhel8/9/10 all `Ready=True`; boot-image PVCs Bound on `freenas-nvmeof-ssd-csi`. (rhel7 + all win* DataSources `Ready=False` is expected — no upstream/registry source is provided for those default templates; not a defect.)
- **Workload:** the restored `hermes` VM is `Running` / `Ready=True` on hpg5, DataVolumesReady, AgentConnected. **The rebuild recovered.**

### Findings

**[HIGH] NVMe-oF shared hostnqn/hostid bug is actively degrading VM storage.**
The default virt storage class is `freenas-nvmeof-ssd-csi` (RWO Block), and hermes' `hermes-root`/`hermes-state` PVCs both live there. During bring-up the `virt-launcher-hermes` pods logged `MapVolume.SetUpDevice failed ... unable to attach any nvme devices` (100–106m ago) and the VM was `Paused due to IO error at the volume: state` (~94m ago). This is the exact signature of the incident's known latent defect (all 3 nodes share one nvme `hostnqn`/`hostid`, violating NVMe-oF uniqueness). The VM has since stabilized (current launcher up 103m, no nvme errors in ~90m), but the uniqueness violation is unfixed and will recur on any reattach/reschedule/reboot. Root cause is node-level config (fix belongs in the ansible/node layer, not this component), but it manifests directly as openshift-virt VM attach/IO failures because nvmeof-ssd is the default VM disk backend.

**[MEDIUM] The "keep virt-handler/VMs off truenas-w1" guard is a silent no-op (misconfiguration introduced by PR #376, commit c36a124).**
`HyperConverged.spec.workloads.nodePlacement` excludes `kubernetes.io/hostname NotIn [truenas-w1.igou.systems]`, and that propagated to the virt-handler DaemonSet nodeAffinity as written. But the node's actual `kubernetes.io/hostname` label is `truenas-w1` (node name is alphanumeric, not the FQDN). The `NotIn` therefore never matches, the exclusion does nothing, and **virt-handler is running on truenas-w1** (DS desired=3, pod `virt-handler-mb2gj` on truenas-w1). The documented intent — keep VM scheduling off the nested-KVM worker that shares a failure domain with the cluster's CSI storage — is not in effect. Fix: change the affinity value from `truenas-w1.igou.systems` to `truenas-w1`.

**[LOW/MEDIUM] No explicit virt-default storage class; default VM disk is RWO Block → VMs are not live-migratable.**
No StorageClass carries `storageclass.kubevirt.io/is-default-virt-class`; VM disks fall back to the k8s default SC `freenas-nvmeof-ssd-csi` (RWO Block). Combined with the cluster-wide HCO default `evictionStrategy: LiveMigrate`, this makes VMs non-migratable: hermes' VMI reports `LiveMigratable=False` ("PVC hermes-root is not shared, live migration requires RWX"). On a node drain such VMs are force-stopped rather than migrated — and a cold restart re-exposes them to the NVMe attach bug above. Consider setting an explicit virt-default class and/or an RWX-capable tier (nfs) for migratable VMs, or intentionally documenting non-migratable as the accepted tradeoff.

### Remediation

1. **Fix NVMe uniqueness (owner: node/ansible layer, cross-cluster CRITICAL):** assign a unique `/etc/nvme/hostnqn` + `/etc/nvme/hostid` per node and re-detach/re-attach affected volumes. This is the single change that removes the "unable to attach any nvme devices" / IO-pause class of failures for all KubeVirt VMs.
2. **Correct the placement guard** in `components/openshift-virt/kubevirt-hyperconverged.yml`: set the `NotIn` value to `truenas-w1` (the real hostname label). After merge/sync, confirm virt-handler DS `desired` drops to 2 and no virt-handler pod lands on truenas-w1.
3. **Decide the migration story:** either add `storageclass.kubevirt.io/is-default-virt-class` on an RWX tier for migratable VMs, or explicitly document that nvmeof-ssd RWO Block VMs are pin-to-node / non-live-migratable so eviction/drain behavior is not a surprise.
4. No action needed on the rhel7/win DataSources (`Ready=False` is expected) or the aged post-reinstall operator Warning events (already cleared).

---

## pac-tenants

**Status: degraded** — all namespace scaffolding for the sole tenant (`igou-ansible`) was correctly restored and is healthy, but the tenant is **not functional**: the Pipelines-as-Code `Repository` CR cannot be created because the OpenShift Pipelines operator (and thus the `pipelinesascode.tekton.dev` CRDs) never installed after the rebuild. CI for the tenant is dead until the upstream operator is unblocked.

### What it is

ArgoCD app `pac-tenants` (project `cluster-config`, sync-wave 20, source `clusters/ocp/pac-tenants`) renders the local Helm chart `.helm/charts/pac-tenant` (`includeCRDs: false`). It provisions per-repo CI tenant namespaces for OpenShift Pipelines-as-Code (PaC). Currently one tenant: `igou-ansible` in namespace **`ci-igou-ansible`** (ansible-builder EE image builds → push to shared Quay).

### Health check (live)

- ArgoCD app: **SYNC=OutOfSync, HEALTH=Healthy**, `selfHeal: true`, retry limit `-1` — currently on **retry attempt #25**, failing every cycle.
- Sole failing/OutOfSync resource: **`Repository/igou-ansible` (pipelinesascode.tekton.dev/v1alpha1) — status Missing**. Sync error: `no matches for kind "Repository" in version "pipelinesascode.tekton.dev/v1alpha1" … ensure CRDs are installed first`.
- Everything else in the namespace is **Synced/Healthy and correctly restored**:
  - Namespace `ci-igou-ansible`, `ResourceQuota ci-quota` (pods 20, cpu 8/16, mem 16/32Gi, storage 50Gi, pvc 5), `LimitRange ci-limits`, ServiceAccount `pipeline`.
  - 3 ExternalSecrets all `SecretSynced/Ready=True` (backed by `onepassword-sdk-ocp-pull` ClusterSecretStore): `forgejo-webhook-config`, `quay-push-config` (image-pull), `rh-automationhub-credentials`. Verified the synced secrets carry the exact keys the manifests reference — `provider.token` + `webhook.secret` (forgejo) and `token` (automation hub) — so credential restore is complete.
  - ImageStream `ee-minimal-rhel9`; 6 NetworkPolicies (`default-deny-all`, `allow-dns`, `allow-external-egress`, `allow-internal-registry`, `allow-quay-push`, `allow-forgejo-clone`).
- No PVCs expected or present — the component is **stateless**, so there is no data-restore obligation here.

### Findings

- **[HIGH] Tenant CI is non-functional — `Repository` CR missing (root cause is upstream).** The PaC `Repository` is the object that binds the Forgejo webhook to a PipelineRun. Without it (and without the PaC controller), no `igou-ansible` CI runs. Direct cause: the `pipelinesascode.tekton.dev` and `operator.tekton.dev` (`TektonConfig`) CRDs are absent — the OpenShift Pipelines operator is not installed.
- **[HIGH] Post-disaster restore gap — OpenShift Pipelines operator blocked by an unapproved, co-bundled Manual InstallPlan (OLM gotcha).** The `openshift-pipelines` ArgoCD app (wave 10) is OutOfSync (`TektonConfig/config` + `signing-secrets` Missing). Its Subscription `openshift-pipelines-operator` is `installPlanApproval: Automatic` and `currentCSV: openshift-pipelines-operator-rh.v1.22.4`, but the Subscription is stuck `InstallPlanPending / RequiresApproval`. The referenced InstallPlan **`install-khg9h`** is `approval: Manual, approved: false` and bundles **two** CSVs: `["servicemeshoperator3.v3.3.5", "openshift-pipelines-operator-rh.v1.22.4"]`. Because OLM co-resolved the auto pipelines install into the same plan as a *manual* Service Mesh upgrade, the manual gate wins and the (otherwise automatic) pipelines operator is blocked. No pipelines CSV → no CRDs → `pac-tenants` cannot converge and thrashes retries.
- **[LOW] pac-tenants own config is correct; it will self-heal once the CRD exists.** The Repository template carries `SkipDryRunOnMissingResource=true` and the app has `selfHeal: true` + infinite retry, so no change to this component is required — it recovers automatically the moment the PaC CRD lands. This is purely a dependency-ordering victim, not a misconfiguration.
- **[INFO] Security posture is sound.** Namespace is default-deny with narrowly scoped egress (DNS, internal registry :5000, Forgejo/Quay via router IP 10.10.9.10:443 only). The `Repository` `settings.policy` (`pull_request` / `ok_to_test`) restricts who can trigger CI. Automation-hub token is delivered via `secret_ref` (not inlined).

### Remediation

1. **Unblock the Pipelines operator (owner: openshift-pipelines / servicemesh components — read-only here, do not execute in this review).** Preferred safe fix: delete the stuck shared InstallPlan so OLM regenerates a **pipelines-only, auto-approved** plan while preserving Service Mesh's intentional manual gate:
   `oc -n openshift-operators delete installplan install-khg9h`
   Alternative (couples the two): `oc -n openshift-operators patch installplan install-khg9h --type=merge -p '{"spec":{"approved":true}}'` — but this **also upgrades Service Mesh 3.2.0 → 3.3.5**, which was deliberately gated Manual; only do this if that upgrade is intended.
2. **Verify operator install:** CSV `openshift-pipelines-operator-rh.v1.22.4` reaches `Succeeded`; CRDs `repositories.pipelinesascode.tekton.dev` and `tektonconfigs.operator.tekton.dev` exist; `openshift-pipelines` app goes Synced/Healthy (TektonConfig applied, PaC controller running).
3. **Recover pac-tenants:** it should self-heal; if not, hard-refresh the app. Confirm `Repository/igou-ansible` becomes `Synced/Healthy` and the namespace shows `oc get repository -n ci-igou-ansible`.
4. **Functional validation (beyond "running"):** trigger the tenant's PaC path end-to-end — a Forgejo PR/`ok-to-test` on `igou-ansible` should spawn a PipelineRun in `ci-igou-ansible` that builds the EE and pushes to Quay via `quay-push-config`. Nothing has exercised this path since the rebuild.
5. **Hardening (prevent recurrence):** pin the pipelines operator (`startingCSV` / dedicated `spec.config` or a distinct sync grouping) so OLM does not co-bundle its auto-install into the Service Mesh manual InstallPlan; and/or add a CRD-presence/health dependency so `pac-tenants` doesn't burn infinite retries while the operator is absent.

---

## quay-operator

**Status: healthy** (recovered during this review; two follow-up items — a DR-cleanup footgun and a stalled clair rollout on the flaky NVMe-oF CSI)

Red Hat Quay `igou-registry` in `quay-enterprise`, operator in `quay-operator`. Postgres for both Quay and Clair is provided by an external CNPG cluster (`quay-pg`) restored from Barman; registry image blobs live on external RustFS S3.

### Timeline observed
When the review started the ArgoCD app was `OutOfSync / Progressing` with `operationState: waiting for healthy state of postgresql.cnpg.io/Cluster/quay-pg`. The CNPG cluster had been in `Setting up primary / Creating primary instance quay-pg-1` for ~60 min: a Barman **full-recovery** pod was replaying pre-disaster WAL (`0000000100...` through `...1BA00000027`+). The replay **completed successfully during the review** (`restore command execution completed without errors`), the primary came up `2/2`, the quay-app upgrade/migration job ran to `Completed`, and the operator brought every component up. This ~60-min "Progressing" window was expected DR behavior (Argo gates later sync-waves on the CNPG Cluster becoming healthy), not a defect — just slow WAL replay.

### Health check (end state)
- **ArgoCD app** `quay-operator`: `health=Healthy`, `operationState: successfully synced (all tasks run)`. Sync is `OutOfSync` but the **only** remaining OutOfSync resource is `Cluster/quay-pg` (CNPG SSA drift — see Finding 1). Earlier transient OutOfSync/Missing on Subscription/OperatorGroup/Namespace/PodMonitor/ServiceMonitor/QuayRegistry all resolved once the DB unblocked the sync.
- **Operator**: CSV `quay-operator.v3.17.3` `Succeeded`, Subscription `AtLatestKnown`, channel `stable-3.17`, `installPlanApproval: Automatic`. OperatorGroup is AllNamespaces (`spec: {}`) — correct per the in-file note (Quay operator does not support MultiNamespace).
- **QuayRegistry** `igou-registry`: `Available=True — All components reporting as healthy`. Managed: quay(1)/clair(1)/redis/mirror(1)/route/monitoring/tls. Unmanaged (external): postgres, clairpostgres, objectstorage, hpa.
- **Pods**: `quay-pg-1` 2/2; `quay-app` 1/1; `redis` 1/1; `mirror` 1/1; clair 1/1 on the old ReplicaSet (a second clair pod is stuck Pending — Finding 2).
- **PVCs**: `quay-pg-1` (40Gi) Bound; clair old `indexer-layer-storage` (20Gi) Bound; clair **new** `indexer-layer-storage` Pending.
- **Route/serving**: `quay.apps.ocp.igou.systems` admitted (edge/Redirect); `GET /health/instance` → **HTTP 200**. Registry is live and serving.
- **Backups**: ObjectStore `quay-pg-backup` → `s3://cnpg-backups/quay-pg` on `truenas.igou.systems:20292`; ScheduledBackup `quay-pg-daily` fired immediately (`quay-pg-daily-20260704025550`, phase `started`); WAL archiving to the new serverName is flowing.

### Findings

**1. [Medium] DR cleanup not done — git still pins `bootstrap.recovery`, a re-restore footgun.**
`components/quay-operator/quay-pg-cluster.yaml` on `origin/main` still declares `bootstrap.recovery.source: quay-pg` (the initdb block is commented out). The file's own comment says to revert to initdb "once the DB is recovered and verified." Consequences while it stays: (a) the live Cluster is permanently `OutOfSync` (CNPG mutates/strips the bootstrap stanza post-bootstrap), the last dirty spot on this Argo app; (b) **if the `quay-pg` Cluster CR is ever deleted and recreated by Argo, it will re-restore from the pre-disaster backup (`serverName: quay-pg`) and silently lose everything written since recovery.** The recovery↔archive serverName split is correct (recovery reads `quay-pg`, new WAL archives to `quay-pg-r20260704`), so the archive side is safe — the risk is purely the stale recovery bootstrap.
Remediation: verify quay data (push/pull a repo, confirm orgs/users), then revert `quay-pg-cluster.yaml` to the commented `bootstrap.initdb` block, commit, and sync; confirm `Cluster/quay-pg` goes Synced.

**2. [Medium] Clair rollout wedged — democratic-csi NVMe-oF provisioning failing.**
A clair rolling update spawned a new pod whose `indexer-layer-storage` PVC (20Gi RWO `freenas-nvmeof-ssd-csi`) will not provision: `ProvisioningFailed ... DeadlineExceeded / context deadline exceeded`, `Aborted: operation locked due to in progress operation(s)`, and `Internal: AxiosError: timeout of 60000ms exceeded` (democratic-csi → TrueNAS API on truenas-w1). Clair still serves via the old pod (`ComponentClairReady=True`), so this is not currently an outage, but the Deployment rollout cannot complete and a full clair restart while the CSI is unhealthy would take clair down. This is the storage-stack instability flagged in the incident (shared `hostnqn`/`hostid` across all 3 nodes + TrueNAS-API latency), surfacing through quay-operator's clair.
Remediation: stabilize democratic-csi/TrueNAS API + fix the duplicate NVMe hostnqn/hostid; once healthy the Pending PVC should provision and the rollout completes. Consider whether clair's indexer *layer cache* (scratch data) needs RWO NVMe-oF at all — every clair rollout mints a fresh 20Gi NVMe-oF volume, amplifying exposure to this flaky path.

**3. [Low] Timeline `.history` WAL archive fails repeatedly.**
The primary logs recurring `archive command failed ... wal-archive ... pg_wal/00000002.history` (exit status 1) while ordinary WAL segments archive fine (`00000002000001BA00000074` archived OK). Likely a benign CNPG/barman quirk on the timeline-switch history file, but if the history object never lands it can impair PITR *across* the 00000001→00000002 timeline switch. Watch after the initial backup completes; confirm the `.history` object appears under `quay-pg-r20260704`.

**4. [Low / security] Open self-registration on a public route + plaintext DB SSL.**
`config-bundle-secret` sets `FEATURE_USER_CREATION: true` with the registry exposed on a public edge route (`quay.apps.ocp.igou.systems`) — anyone who can reach the endpoint can self-register accounts (only `SUPER_USERS: [igou]` is privileged). Acceptable for a homelab but worth a conscious decision; set `FEATURE_USER_CREATION: false` if the registry is reachable beyond the LAN. Minor hardening: Clair connstrings use `sslmode=disable` and `DB_URI` sets no sslmode (in-cluster to `quay-pg-rw.svc`, so low risk).

**5. [Info / positive] Recovery genuinely succeeded — data, not just process.**
Registry image blobs are external/unmanaged on RustFS (`RHOCSStorage` → `truenas.igou.systems:20292`, bucket `quay`, `storage_path /datastorage/registry`) and survived the wipe; quay-app validates storage on boot and came up 1/1 with a 200 health check. The DB was restored via Barman WAL replay and the schema-migration job completed against the restored data. The `config-bundle-secret` is fully reconstructed from 1Password via ExternalSecret (DB_URI + clair connstrings + S3 creds). This component recovered the rebuild.

### Remediation summary (priority order)
1. Verify quay data, then revert `quay-pg-cluster.yaml` from `bootstrap.recovery` back to `bootstrap.initdb` and sync (Finding 1) — removes the re-restore footgun and the last OutOfSync diff.
2. Fix democratic-csi/TrueNAS NVMe-oF provisioning + duplicate hostnqn/hostid so the clair rollout completes (Finding 2).
3. Confirm the daily backup finishes and the `.history` object archives; keep an eye on WAL archiving (Finding 3).
4. Decide on `FEATURE_USER_CREATION` given the public route (Finding 4).

---

## remote-tenants

**Status: healthy** (guardrail scaffolding fully recovered; one latent, non-active onboarding prerequisite is missing — see MED-1)

Git source: `clusters/ocp/remote-tenants` (kustomize + local Helm chart `.helm/charts/remote-tenant`, `includeCRDs: false`). App-of-apps entry: `clusters/ocp/values.yaml` sync-wave 20, project `cluster-config`.

### What this component is
Per-user locked-down OpenShift namespaces reachable over the tailnet via the Tailscale API-server proxy. The cluster values file carries `tenants: []` (no tenants onboarded — onboarding was the only outstanding item pre-disaster). With an empty tenant list the chart renders **only its shared, once-rendered cluster-scoped guardrails**; all per-tenant objects (Namespace, ResourceQuota, LimitRange, NetworkPolicies, RoleBinding) are absent by design.

### Health check (live cluster)
- ArgoCD app `remote-tenants`: **Synced + Healthy**. Last sync `2026-07-03T23:23:20Z` at revision `d81e454` (= current `origin/main` HEAD). No conditions/errors.
- All 5 managed resources present and `Synced`, ~3h29m old (created during the reinstall recovery):
  - ClusterRole `remote-tenant-operator`
  - ValidatingAdmissionPolicy + Binding `remote-tenant-no-burst`
  - ValidatingAdmissionPolicy + Binding `remote-tenant-no-secondary-net`
- No tenant namespaces (`oc get ns -l igou.systems/tenant-type=remote-user` → none) — **expected**, `tenants: []`.
- No Deployments/StatefulSets/DaemonSets/PVCs/Routes/CRs owned by this component (it manages RBAC + admission policy only). Nothing to be Pending/CrashLooping.
- Functional dependency **Tailscale API-server proxy: enabled** — operator deploy env `APISERVER_PROXY=true` (git: `components/tailscale-operator/kustomization.yaml apiServerProxyConfig.mode: "true"`), operator pod Running 3h31m. This is the auth/impersonation path tenants use; it recovered.

### Findings

**MED-1 — Latent onboarding blocker: `node-role.kubernetes.io/tenant` label missing on all nodes post-reinstall.**
The chart default `defaults.nodeSelector: "node-role.kubernetes.io/tenant="` pins every tenant pod to that label and stamps it on each tenant Namespace as `openshift.io/node-selector`. That label is a **one-time out-of-band prerequisite** (`oc label node ... node-role.kubernetes.io/tenant=""`, per the chart README) — it is **not** managed by this GitOps component, nor by the Ansible repo (grep of both = only README docs). After the rebuild **no node carries it**: `hpg5` re-joined without it, `truenas-w1` never had it, and `p330` is dead/removed. Consequence: onboard a tenant today and all its pods are unschedulable (Pending forever) because the namespace node-selector matches no node. **No active impact right now** (zero tenants), but it is a silent trap for the next onboarding and will re-break on every future rebuild since nothing reconciles it. Recommend labeling `hpg5.igou.systems` and codifying the label so it survives rebuilds (Ansible node-label play or a MachineConfig/label-controller), and adding it to the DR runbook.

**LOW-2 — Stale `p330` references in default node pool.** Chart README prereqs and the "hpg5/p330 worker pool" wording still name `p330`, which is dead (no BMC). `hpg5` is the sole surviving tenant-pool worker. Doc/label drift; update the README prereq (drop the `p330` label line) so the next operator does not chase a dead node.

**INFO-3 — Recovery of this component is complete.** Because the component is guardrail-only with `tenants: []`, there was no persistent/per-tenant state to restore; the cluster-scoped ClusterRole + both VAPs/bindings re-applied cleanly via GitOps. Nothing DR-specific is outstanding for the component itself.

**INFO-4 — Burst-guard VAP literals are a maintenance coupling (not a defect).** `remote-tenant-no-burst` hardcodes `workload=burst` taint + `node-role.kubernetes.io/burst`, which must track `clusters/ocp/cluster-api/casval-worker-machineset.yaml`. The casval burst node is currently scaled to 0/deprovisioned, so the policy is dormant but correctly still denies future burst targeting. No action.

### Remediation
1. (MED-1) Label the tenant worker pool before any onboarding: `oc label node hpg5.igou.systems node-role.kubernetes.io/tenant=""` — and, to make it rebuild-durable, add the label to an Ansible node-labeling play (igou-ansible) or a label-managing MachineConfig/controller, plus a line in the reinstall runbook. Verify with `oc get nodes -L node-role.kubernetes.io/tenant`.
2. (LOW-2) Update `.helm/charts/remote-tenant/README.md` one-time prereqs to drop `p330` and reflect `hpg5` as the current tenant node.
3. No cluster changes required for the component to be considered recovered — it is Synced/Healthy and all guardrails are live. The above are pre-onboarding hardening, not outage fixes.

---

## rhdh

**Status: healthy** (fully functional and recovered the 2026-07-03 rebuild) — with one benign ArgoCD `OutOfSync` and one latent disaster-recovery correctness gap that will bite on a *future* recreate.

Red Hat Developer Hub (Backstage) in namespace `rhdh`, backed by a single-instance CloudNativePG cluster `rhdh-pg`, is serving live at `https://rhdh.apps.ocp.igou.systems` (route `/` → HTTP 200, `/healthcheck` → 200). `rhdh-operator.v1.10.1` CSV `Succeeded`; `backstage-rhdh-developer-hub` Deployment 1/1 Ready; `Backstage` CR condition `Deployed=True`; `rhdh-pg-1` 2/2 Running (postgres + injected barman-cloud sidecar). All 3 ExternalSecrets Healthy; both PVCs Bound (`freenas-nvmeof-ssd-csi`). The Backstage DB was restored from the Barman backup: the `backstage` database is present with **120 tables across 216 schemas** (per-plugin `schema` division), and the app connects with no DB errors in the logs.

### Findings

- **[INFO / recovered] DR restore succeeded end-to-end.** `rhdh-pg` bootstrapped via `bootstrap.recovery` from the RustFS Barman archive; `backstage` DB fully repopulated; UI + healthcheck return 200; DB connectivity clean. `ContinuousArchiving=True (ContinuousArchivingSuccess)`, `LastBackupSucceeded=True`, and a fresh `ScheduledBackup` (`rhdh-pg-daily-20260704015209`) completed at 01:52 with no error. New WAL/backups land under a fresh serverName (see below), confirmed by `ObjectStore.status.serverRecoveryWindow["rhdh-pg-r20260704"]` (firstRecoverabilityPoint/lastSuccessfulBackupTime = 2026-07-04T01:52:15Z). This component recovered the rebuild correctly.

- **[MEDIUM — latent DR gap] `bootstrap.recovery` in git still points at the STALE pre-disaster archive.** `components/rhdh/rhdh-pg-cluster.yaml` recovers from `externalClusters[0].serverName: rhdh-pg` (the pre-disaster base, ~2026-07-02), while the *live* cluster now archives all WAL + backups to a **different** serverName `rhdh-pg-r20260704`. Because CNPG `bootstrap` is immutable, the running cluster is fine and its data is safely backed up under `rhdh-pg-r20260704`. **But if `rhdh-pg` is ever deleted and recreated from git (i.e. the exact scenario this repo just lived through), CNPG will recover from the OLD `rhdh-pg` server and silently lose everything created since 2026-07-02.** The in-code comment ("Revert to the initdb block below once recovered and verified") is itself a footgun: reverting to `initdb` would make a future recreate come up **empty**. Correct fix is to repoint recovery at the current archive, not to initdb.

- **[LOW — cosmetic] ArgoCD app `rhdh` is `OutOfSync` (Healthy).** The only drifting resource is `Cluster/rhdh-pg`. Cause: CNPG's mutating webhook adds operator-defaulted fields the git manifest omits — on the immutable `bootstrap.recovery` block (`database: app`, `owner: app`) and on `externalClusters[0].plugin` (`enabled: true`, `isWALArchiver: false`). The app has `syncPolicy.automated.selfHeal=true` + `ServerSideApply=true`, but selfHeal cannot converge because `bootstrap` is immutable, so it stays permanently OutOfSync. No functional impact (cluster is Healthy). This is the kind of persistent noise that masks *real* drift on the app tile.

- **[LOW — resilience] Backstage pod rides an RWO NVMe-oF PVC on a worker, unpinned.** `dynamic-plugins-root` (RWO, `freenas-nvmeof-ssd-csi`) is attached to the backstage pod on worker `truenas-w1`, and the Deployment has no node pinning. Given the cluster-wide latent bug where all 3 nodes share the SAME NVMe hostnqn/hostid (per the reinstall record), a reschedule of this pod to another node while the volume is still attached is exactly the multi-attach failure mode. The CNPG cluster was deliberately pinned to the control-plane node to dodge this (good — and `rhdh-pg-1` is correctly on `ocp.igou.systems`), but the backstage workload was not. Lower blast radius (it's a plugin cache, repopulated on init) but still an availability risk until the shared-hostnqn bug is fixed cluster-wide.

- **[LOW — security/config] No identity provider configured.** `app-config-rhdh` defines only `auth.externalAccess` (legacy service-to-service token) and no user sign-in provider / `signInPage`. The hub UI is reachable at a public-ish route with edge TLS (redirect) but effectively has no user authentication in front of it. Acceptable for a homelab, but worth an explicit decision. (Secrets themselves are handled well: backend + postgres creds via ExternalSecrets from 1Password, `deletionPolicy: Retain`.)

- **[LOW — noise] Backstage catalog "Policy check failed" / "metadata.name is not valid" warnings.** Repeated `catalog warn` for RHDH marketplace `extensions-package-provider` entities whose package names exceed 63 chars or carry an extra `author` property. These are upstream RHDH marketplace metadata issues, cosmetic only — no functional impact on the hub.

### Remediation

1. **(MEDIUM) Close the DR recreate gap.** After confirming the current data is good, update `components/rhdh/rhdh-pg-cluster.yaml` so a from-git recreate restores the *current* data: point `bootstrap.recovery.externalClusters[0].parameters.serverName` at `rhdh-pg-r20260704` (the live archive), matching the WAL archiver's serverName. Do **not** switch to the `initdb` block (that would recreate empty). Verify the `rhdh-pg-backup` ObjectStore has a valid `serverRecoveryWindow` for `rhdh-pg-r20260704` first (it does, as of 2026-07-04T01:52:15Z).
2. **(LOW) Silence the benign OutOfSync.** Add an ArgoCD `ignoreDifferences` for `Cluster/rhdh-pg` on `spec.bootstrap` (and, if needed, `spec.externalClusters` plugin defaults), or declare the operator-defaulted values (`database: app`, `owner: app`, `enabled`/`isWALArchiver`) in git so SSA matches. This restores a clean `Synced` tile so genuine drift is visible.
3. **(LOW) Pin backstage or fix the root cause.** Either add a control-plane nodeSelector to the Backstage Deployment (as done for CNPG) to avoid the shared-hostnqn NVMe-oF multi-attach trap, or — preferably — fix the cluster-wide duplicate `hostnqn`/`hostid` so RWO NVMe-oF PVCs reschedule safely for all workloads.
4. **(LOW) Decide on auth.** If the hub should be more than open/guest, add a real sign-in provider to `app-config-rhdh`; otherwise document that guest/legacy-only access is intentional.

---

## searxng

**Status: not-yet-deployed** (git config is sound; the component never came back after the rebuild because the parent app-of-apps sync is wedged)

SearXNG is the in-cluster, internet-facing metasearch backend consumed east-west by `hermes-agent` (Hermes web search) and `firecrawl` (`SEARXNG_ENDPOINT`). Git source: `applications/searxng` (bjw-s `app-template` 4.6.2, stateless Deployment). Added in a single recent commit (`dfd7c72 feat(searxng): add internal search service`).

### Findings

- **[CRITICAL] Component is entirely absent from the cluster — did NOT recover from the rebuild.** There is no `searxng` ArgoCD Application, no `searxng` namespace, and no workloads/service/secret. `oc get applications.argoproj.io searxng -n openshift-gitops` → NotFound; `oc get ns searxng` → NotFound.

- **[CRITICAL] Root cause: the `root-applications` app-of-apps sync is wedged, blocking creation of searxng.** `root-applications` is OutOfSync/Progressing with an in-flight sync operation stuck `Running … waiting for healthy state of argoproj.io/Application/quay-operator` (startedAt 01:42Z, still running >1h, retryCount 4). `quay-operator` (wave 22) never reaches Healthy (its `QuayRegistry igou-registry` is Missing and the `quay-pg` CNPG cluster is Progressing). Because a sync operation is perpetually in-flight, ArgoCD's selfHeal cannot create the child Applications that are currently `Missing`: **searxng**, `firecrawl`, `jellyfin`, `llmkube`, `gotify`, `gitea-mirror`, `ansible-automation-platform`. searxng is collateral damage of the stuck quay-operator wave — nothing is wrong with searxng itself.

- **[HIGH] Downstream capability loss.** `firecrawl` (also Missing) and `hermes-agent`'s web-search path have no SearXNG backend. `hermes-agent` is Synced/Healthy but its in-cluster web search is non-functional until searxng is up.

- **[MEDIUM] NetworkPolicy will block firecrawl even once both deploy.** `searxng-networkpolicy.yaml` ingress permits port 8080 only from `namespaceSelector kubernetes.io/metadata.name: hermes`. But `firecrawl` runs in namespace `firecrawl` and is configured with `SEARXNG_ENDPOINT: http://searxng.searxng.svc.cluster.local:8080`. With default-deny ingress, firecrawl→searxng will be dropped. The ingress rule omits the `firecrawl` namespace. (hermes ns exists and is correctly labeled, so the hermes path is fine.)

- **[LOW] Runtime secret dependency unverified.** `SEARXNG_SECRET` env pulls key `secret_key` from Secret `searxng-secrets`, populated by an ExternalSecret using `dataFrom.extract` on 1Password item `searxng-secrets` (ClusterSecretStore `onepassword-sdk-ocp-pull` is Ready/Valid). The 1P item must contain a `secret_key` field or the pod won't start; could not confirm item contents read-only.

- **[POSITIVE] Config is well-formed and secure; nothing to restore.** Image pinned by digest (`searxng/searxng:2026.6.24…@sha256:77b6ec…`); hardened securityContext (runAsNonRoot, drop ALL caps, `allowPrivilegeEscalation: false`, seccomp RuntimeDefault, `automountServiceAccountToken: false`); liveness/readiness/startup probes on `/healthz:8080`; `search.formats` includes `json` (required by firecrawl/API consumers); `limiter: false` is acceptable (no Redis, internal-only); settings mounted read-only from a ConfigMap. Stateless (no PVC) so there is **no post-disaster data to restore**. No Route/HTTPRoute — internal-only, matching the netpol; egress allows DNS + public internet while denying RFC1918 (good lateral-movement containment for upstream search-engine access).

### Remediation

1. **Unblock the parent app-of-apps** (the real fix): get `quay-operator` to Healthy (its `quay-pg` CNPG cluster and `QuayRegistry igou-registry` — see the quay/CNPG review) OR terminate the stuck `root-applications` sync operation so selfHeal can proceed and create the Missing child Applications. Once unblocked, searxng should be created and sync automatically (config requires no changes to deploy).
2. **As an immediate unblock for searxng specifically** (independent of quay): create/sync just this app, e.g. `argocd app sync searxng` after the Application exists, or apply the `searxng` entry directly. Verify: namespace created, ExternalSecret `searxng-secrets` becomes Ready with a `secret_key` key, pod reaches Ready on `/healthz`, and `curl http://searxng.searxng.svc:8080/search?q=test&format=json` returns JSON.
3. **Fix the NetworkPolicy before relying on firecrawl→searxng**: add the `firecrawl` namespace to `searxng-networkpolicy.yaml` ingress (`namespaceSelector kubernetes.io/metadata.name: firecrawl`, port 8080), or firecrawl's SearXNG integration will silently fail.
4. **Confirm the 1Password `searxng-secrets` item contains a `secret_key` field** before/at first sync to avoid a CreateContainerConfigError.

---

## service-accounts

**Status:** degraded

The in-cluster half of this component (ServiceAccounts + RBAC) recovered cleanly and is functionally verified. The disaster-recovery-critical half — republishing the freshly-minted post-rebuild SA tokens back into 1Password via ExternalSecrets `PushSecret`s — is **broken and has never succeeded since the rebuild**, leaving 6 downstream automation consumers reading stale (pre-disaster / invalid) tokens from 1Password. ArgoCD reports Synced/Healthy, which masks the real functional failure.

### What it is
Git source `clusters/ocp/service-accounts` → Helm chart `service-account-access` (via `components/service-accounts`, `.helm/charts`). It provisions namespace `service-accounts`, 9 managed ServiceAccounts (+ long-lived `-token` secrets, `automountServiceAccountToken: false`), 4 ClusterRoles (`molecule-kubernetes`, `virtualmachine-reader/-deployer/-ops`), assorted RoleBindings/ClusterRoleBindings, and 6 `PushSecret`s that publish each SA's token into 1Password (vault `claude` and vault `ocp-push`) for off-cluster consumers (Claude, ansible-molecule CI, ns-agent, vm-ops automation, devhost cluster-read-only access).

### Findings

**[HIGH] All 6 PushSecrets are `Errored` — SA tokens are NOT being published to 1Password (403 write-denied).**
`oc get pushsecret -n service-accounts` shows all six `Errored`, `lastPushTime=<none>`, `Ready=False` since `2026-07-03T19:25:38Z` (the rebuild) — never a single successful push in 7.5h. ESO controller logs and PushSecret status give the exact cause:
`status 403: Authorization: token does not have permission to perform update on vault iggugnytc2y6nenftd65o4eyvi` (vault `claude`) and `...vault dtd2bcigxk7ud64ed4nvsb7hl4` (vault `ocp-push`).
Root cause: the 1Password **Connect token** backing `onepassword-connect-token` (ns `external-secrets-operator`), used by ClusterSecretStores `onepassword-sdk-claude` and `onepassword-sdk-ocp-push`, has **read** access to those vaults but no **write/update (edit)** grant. This is an out-of-band 1Password integration grant that did not recover with the rebuild — the exact failure mode recorded in memory `onepassword-kubeconfig-publish` ("Connect server edit grant was the final fix; queued writes drain on grant fix").
Impact: because the cluster was fully reinstalled (new SA signing key), every token stored in 1Password is now stale/invalid. The 6 consumers reading these items authenticate with dead credentials:
- vault `claude`: `ocp-cluster-read-only`, `ocp-cluster-edit`, `ocp-claude-edit`, `ocp-ansible-molecule`
- vault `ocp-push`: `ns-agent`, `ocp-virtualmachine-ops`

**[LOW] ArgoCD health masks the failure.** `applications.argoproj.io/service-accounts` = Synced + Healthy, and it lists the PushSecrets as "Healthy", yet their actual `Ready=False`. Health checks here should not be trusted as a functional signal for this app.

**[INFO / not a regression] Misleading store status.** Both ClusterSecretStores report `Valid / ReadWrite / Ready=True` ("store validated") because validation only exercises a read; the write grant gap is invisible until a push is attempted.

**[GOOD] In-cluster RBAC recovered and is functionally correct** (verified with `oc auth can-i --as=system:serviceaccount:...`):
- `cluster-read-only`: get nodes = yes, delete pods = no ✓
- `cluster-edit`: create deployments in `default` = yes, in `kube-system` = no ✓
- `claude-edit`: create pods = no (matches intentional empty roleBindings) ✓
- `virtualmachine-reader`: list VMs = yes ✓; `virtualmachine-deployer`: create VMs = yes ✓; `virtualmachine-ops`: create datavolumes = yes ✓
- `ns-agent`: no perms (no bindings defined — token published for use elsewhere) ✓
- Security posture is sound: `automountServiceAccountToken: false`, VM roles are scoped, cluster-edit is namespace-scoped to `default`.

### Remediation
1. **Grant the 1Password Connect integration write/edit access to vaults `claude` and `ocp-push`** (1Password admin console → the Connect server/integration used by `onepassword-connect-token`). This is the fix; it is out-of-band and not represented in git.
2. After the grant, force the queued pushes to drain (ESO retries automatically, or annotate/refresh the PushSecrets / restart the ESO controller). Confirm `lastPushTime` populates and `Ready=True` on all 6.
3. **Verify downstream tokens** actually rotated in 1Password (compare item `updatedAt`) and that consumers work: `ocp-cluster-read-only` (devhost access), `ocp-claude-edit`, `ocp-ansible-molecule` (molecule CI), `ns-agent`, `ocp-virtualmachine-ops`. Until step 1 lands, treat all six 1Password token items as invalid.
4. Consider a lightweight post-DR checklist item / alert on `PushSecret Ready=False`, since ArgoCD Healthy does not catch this and it silently strands automation credentials.

---

## tailscale-operator

**Status: healthy** — fully recovered from the 2026-07-03 rebuild, ArgoCD Synced/Healthy, and end-to-end egress functionality verified live (not merely running).

### Scope
- Git source: `components/tailscale-operator` (Helm chart `tailscale-operator` v1.98.4 from pkgs.tailscale.com, `includeCRDs: true`) plus overlay manifests.
- Namespace: `tailscale` (created 3h31m ago during recovery, sync-wave `-100`).
- Wired into app-of-apps at `clusters/ocp/values.yaml:270` (sync-wave 10, `ignoreDifferences` on the egress Service `externalName`).
- Purpose here: (a) tailnet-joined operator with the k8s API-server auth-proxy enabled, (b) a single cluster-egress proxy that DNATs to `node_exporter` on the igou.io VPS so UWM Prometheus can scrape it.

### Health check (read-only)
- **ArgoCD app** `tailscale-operator`: `Synced` / `Healthy`, last op `Succeeded`, no conditions. All 27 tracked resources Synced (CRDs, operator Deployment, ExternalSecret, ServiceMonitor, RBAC, IngressClass).
- **Pods**: `operator-…-8svkp` 1/1 Running, `ts-igou-io-node-exporter-8jftz-0` 1/1 Running — both **0 restarts**, ~3h31m, scheduled on `truenas-w1`. No CrashLoop/Pending.
- **Workloads**: `deployment/operator` 1/1, `statefulset/ts-igou-io-node-exporter-8jftz` 1/1. No DaemonSets.
- **ExternalSecret** `operator-oauth`: `SecretSynced` / Ready=True from ClusterSecretStore `onepassword-sdk-ocp-pull` (item `tailscale-oauth`); target Secret `operator-oauth` (5 keys) present. OAuth creds **auto-restored** post-disaster with no manual step.
- **CRDs**: all 7 tailscale.com CRDs installed & Healthy. No Connectors/ProxyGroups/ProxyClasses/DNSConfigs/Recorders defined (expected — this deployment only uses an ExternalName egress Service).
- **PVCs**: none. Proxy state lives in a k8s Secret (`ts-…-0`), so this component has **no storage dependency** and was immune to the shared-hostnqn NVMe attach bug — it restored purely from Helm + ExternalSecret.

### Functionality review (is it actually working?)
- **Operator**: authenticated to the tailnet, actively reconciling (logs show clean service-reconciler loops; the `[unexpected] no ProxyGroup annotation` lines on `quay-pg-*` services are benign — those are CNPG services not meant for tailscale).
- **Egress proxy — VERIFIED FUNCTIONAL**: `tailscale status` inside the proxy shows the VPS device `racknerd-49580b0` **active, direct** (192.129.238.44:41641, tx 502K/rx 6.4M). Curling the proxy pod IP `:9100` and the `igou-io-node-exporter-metrics` ClusterIP from the operator pod both return real VPS metrics (`node_exporter_build_info … version="1.11.1"`). DNAT egress path works end-to-end.
- **Scrape plumbing**: UWM enabled (`enableUserWorkload: true`); selector Service `igou-io-node-exporter-metrics` targets the proxy pod via stable `tailscale.com/*` labels; `ServiceMonitor` relabels `instance=igou.io`. Wiring is correct and complete.
- **Anti-drift engineering (working)**: the config deliberately writes API-defaulted fields explicitly (ExternalSecret `conversionStrategy/decodingStrategy/…`, ServiceMonitor relabel `action: replace`) and the app-of-apps `ignoreDifferences` defers the operator-rewritten `externalName` — the app is genuinely Synced, not force-synced.
- **Rebuild recovery**: complete. Git history (`#309`, `#314`, API-server-proxy enablement) matches live state; no post-disaster restore is outstanding for this component.

### Findings
- **[Medium — security surface]** `apiServerProxyConfig.mode: "true"` exposes the Kubernetes API server over the tailnet with **identity impersonation** (`tailscale-auth-proxy` ClusterRole holds `impersonate` on `users`/`groups`). This is intentional (remote-tenant access design) but is a broad control-plane exposure — its blast radius is entirely defined by the Tailscale ACL grants, which live outside this repo and are not verifiable here. Audit the tailnet ACL to confirm only intended tags/identities can reach `tag:k8s-operator` and that granted k8s groups are least-privilege.
- **[Low — security]** ClusterRoleBindings grant `system:openshift:scc:privileged` to the `proxies` SA and `anyuid` to the `operator` SA. Required for the proxy's NET_ADMIN/iptables DNAT, but these are broad SCC grants; they are correctly scoped to the two service accounts.
- **[Low — availability]** The VPS egress runs as a **single replica** (statefulset 1/1) and currently sits on `truenas-w1` (a KubeVirt-VM worker). If that node is unavailable, VPS `node_exporter` scraping gaps until reschedule. No HA/anti-affinity (a ProxyGroup would be the HA path).
- **[Info]** Operator `logging: "debug"` — verbose (steady `/localapi/v0/debug` chatter in proxy logs); fine operationally, consider `info` to cut log volume.
- **[Info]** `valuesInline.oauth: {}` is empty by design — the chart consumes the ExternalSecret-provisioned `operator-oauth` Secret by convention; confirmed working.

### Remediation
- No corrective action required for health — component is fully operational.
- **Verify the Tailscale ACL** (out-of-repo) for the API-server proxy grants and the `tag:openshift → tag:vps tcp/9100` egress grant; document/version them alongside this component so the auth surface is auditable and reproducible after a rebuild.
- Optional hardening/resilience: lower operator log level to `info`; consider migrating the VPS egress to a `ProxyGroup` (or add replicas/anti-affinity) to remove the single-node SPOF for VPS metrics.

---

## udn

**Status: healthy**

Component source: `clusters/ocp/udn` (ArgoCD app `udn`, project `cluster-config`, sync-wave 6). It deploys a single cluster-scoped resource: the `ClusterUserDefinedNetwork/vlan9-no-ipam` — a **Secondary Localnet** OVN network that tags workload traffic onto VLAN 9 of the hub trunk (`physicalNetworkName: trunk-network`, IPAM disabled). No namespaces, operators, Deployments, PVCs, or routes are owned by this component; it is effectively a stateless network-definition CRD.

### Health check (live cluster)

- **ArgoCD app `udn`**: `Synced` + `Healthy`. Last sync 2026-07-03 18:56:41Z (immediately after the reinstall), self-heal on, retry limit -1, ServerSideApply. Reconciled cleanly, no OutOfSync/degraded history.
- **CUDN `vlan9-no-ipam`**: present (created 2026-07-03 18:56:41Z), `generation: 1`, finalizer `k8s.ovn.org/user-defined-network-protection` set. Status condition `NetworkCreated=True`, reason `NetworkAttachmentDefinitionCreated`.
- **Underlay dependency satisfied on master + hpg5**: the `trunk-network` → `br-secondary` OVS localnet bridge-mapping (nmstate) that this CUDN relies on is `Available / SuccessfullyConfigured` via NNCPs `mapping` (master `ocp.igou.systems`) and `mapping-hpg5`. `mapping-casval` is `Ignored (NoMatchingNode)` — expected, that burst node is absent.
- No crashloops/pending pods, no PVCs — none exist for this component. Recovery from the rebuild was clean.

### Findings

1. **[INFO] No consumers currently — NAD generated in 0 namespaces (expected).** The CUDN condition message is `NetworkAttachmentDefinition has been created in following namespaces: []`; no namespace carries the `network.igou.systems/vlan9: "true"` label, so no NAD is materialized anywhere. The only repo consumers of `vlan9-no-ipam` are `test-workloads/vlan9-vm-multinode/*` and `test-workloads/virtualmachine-devhosttest` — ephemeral test workloads that are **not** part of the app-of-apps and are not deployed (namespaces `vlan9-vm-multinode` / `devhosttest` absent). There is **no persistent state to restore** for a network CRD, so nothing was lost in the disaster. The network sits idle and ready by design.

2. **[LOW/MEDIUM] `truenas-w1` worker has no `trunk-network` bridge mapping.** NNCPs cover master and hpg5 only (`mapping-casval` targets the absent `casval` host). The `truenas-w1` KubeVirt-VM worker is `Ready` but is not covered by any nmstate localnet mapping, so a pod/VM scheduled there and attached to `vlan9-no-ipam` would have no OVS underlay path to VLAN 9. Impact is limited today: per prior ops notes KubeVirt is fenced off `truenas-w1`, and `truenas-w1`'s VLAN-9 trunk is handled at the TrueNAS host/bridge level (br9) rather than by OpenShift nmstate. Still a latent gap if this network is ever consumed by a plain pod scheduled on that node.

3. **[INFO] Config is correct and consistent.** `physicalNetworkName: trunk-network` matches the live `ovn.bridge-mappings` (`localnet: trunk-network` → `br-secondary`); VLAN access id 9, role Secondary, `ipam.mode: Disabled`. IPAM-disabled is intentional (README documents that consumers must supply addressing via DHCP/cloud-init/static). README also correctly flags CUDN immutability (delete+recreate to change VLAN/IPAM). No drift between git (`d81e454`) and cluster; no security gaps for a Secondary localnet definition.

### Remediation

- **No action required for DR recovery** — the component is fully restored and healthy; being a stateless CRD, it needed no data restore and reconciled correctly post-reinstall.
- **Optional (finding 2):** if `vlan9-no-ipam` should ever be usable from workloads on `truenas-w1`, add a matching nmstate NNCP (`trunk-network` → `br-secondary`) for that node, or explicitly document that `truenas-w1` is intentionally excluded from this localnet. Read-only review — no change applied.
- **Optional (finding 1):** none needed; if a real workload is meant to consume this network, label its namespace `network.igou.systems/vlan9: "true"` and verify the NAD appears.

---

## user-workload-monitoring

**Status: healthy** — fully recovered the rebuild and functional end-to-end. The only firing alerts are *true positives* about **other** components (Quay mid-recovery, AAP/automation absent), which actually proves the probing + alerting path works.

### Scope
Git path `components/user-workload-monitoring` (ArgoCD app `user-workload-monitoring`, sync-wave 6). Enables OpenShift UWM and layers on: platform/UWM monitoring config, a blackbox-exporter (HTTP/TLS probes), a MikroTik `mktxp` exporter, in-cluster wiring for the off-cluster `upsmonitor` Pi exporters, and 4 ServiceMonitor/PodMonitor bundles (argocd, cert-manager, external-secrets, grafana-operator).

### Health check (live)
- **ArgoCD app:** `Synced` + `Healthy`.
- **UWM core** (`openshift-user-workload-monitoring`): `prometheus-operator` 2/2, `prometheus-user-workload-0` 6/6, `thanos-ruler-user-workload-0` 4/4 — all Running (~136m, i.e. post-reinstall). Both PVCs **Bound** on `freenas-nvmeof-fast-csi` (prometheus 20Gi, thanos-ruler 10Gi).
- **Config matches git:** `cluster-monitoring-config` has `enableUserWorkload: true` + `enableUserAlertmanagerConfig: true` with the `alertmanager-eda-event-stream` / `alertmanager-slack-bot-token` secrets; UWM Alertmanager is intentionally `enabled: false` so user alerts route through platform `alertmanager-main` (correct, matches manifests).
- **Exporters:**
  - *blackbox-exporter*: Deployment 1/1 Running; all 5 Probe CRDs present; **probe_success = 12/14 up** (2 legit failures, below).
  - *mktxp*: Deployment 1/1 Running; ExternalSecret `mktxp-secret` = `SecretSynced/Ready=True` (1Password-backed config re-synced cleanly post-disaster); all **3 routers reporting** (RB5009, CRS328, CRS317).
  - *upsmonitor*: no in-cluster pods (correct — exporters live on the Pi); selectorless Service + Endpoints (`10.10.9.32:9100/:9199`) + 2 ServiceMonitors + PrometheusRule all present; **both UPSes reporting** (apc1500 + cyberpower1500 at 100% charge), node_exporter up.
- **Scrape health:** 33/33 UWM active targets **UP**. The 2 argocd ServiceMonitors are correctly scraped by the **platform** Prometheus (namespace `openshift-gitops` carries `openshift.io/cluster-monitoring: true`, and UWM excludes `openshift-*`) — both `up`. cert-manager (3), external-secrets (3 pods), grafana-operator all `up`.
- **Rules:** `blackbox.*` and `ups.*` PrometheusRules loaded and evaluating in-Prometheus (`leaf-prometheus` scope, correct).

### Findings

1. **[Info — not a UWM defect] Two blackbox probes firing are TRUE POSITIVES.**
   - `https://quay.apps.ocp.igou.systems` (tier=critical) → `BlackboxProbeFailed` + `BlackboxProbeFailedCritical`. Quay is still mid-recovery (app `quay-operator` OutOfSync/Progressing; only the `quay-pg-1-full-recovery` pod is up; no Quay route yet). This alert self-clears once Quay finishes restoring.
   - `https://automation.apps.ocp.igou.systems` (tier=standard) → `BlackboxProbeFailed`. There is **no `automation` route on this cluster** and no AAP/EDA app in the app-of-apps. Either AAP is not yet restored, or this is now a **stale probe target** that will fire forever.
   These demonstrate the monitoring works; the failures belong to other components.

2. **[Medium — latent] UWM state volumes sit on the shared-hostnqn NVMe-oF path.** Both `prometheus-user-workload-0` and `thanos-ruler-user-workload-0` PVCs use CSI driver `org.democratic-csi.nvmeof-fast`, and both pods run on `truenas-w1`. The cluster-wide latent bug (all 3 nodes share nqn `…466937ab…`) can cause intermittent NVMe-oF attach failures. Currently Bound/Running so no impact, but any reschedule of these StatefulSet pods risks the attach race and blinds monitoring. Exposure only — fix is at the cluster/node level.

3. **[Low] blackbox-exporter `serviceMonitor.enabled: true` is dead config.** No ServiceMonitor is rendered anywhere (chart v11.13.0 only emits one when `serviceMonitor.targets` is set; here Probe CRDs are used instead). Consequence: the exporter's **own self-metrics** (`blackbox_exporter_build_info`, config-reload success, module errors) are scraped by nothing. Probe results are unaffected. Either drop the block or add a real self-metrics ServiceMonitor selecting the `blackbox-exporter` service on `:9115`.

4. **[Info] Post-disaster restore: nothing to restore, and it recovered cleanly.** UWM TSDB is ephemeral (15d retention) and repopulating on freshly-provisioned PVCs; the mktxp 1Password secret re-synced automatically via ESO. No Barman/tar restore applies to this component.

5. **[Nit] `saas-https` Probe has an empty target list (`static: []`)** — a harmless placeholder producing no series.

### Remediation
- **Prune or fix the `automation.apps.ocp.igou.systems` probe target** in `exporters/blackbox-exporter/probes/infra-https-probe.yaml` if AAP will not live on this cluster — otherwise `BlackboxProbeFailed` fires indefinitely and adds noise to the EDA/Slack pipeline. (The Quay alert needs no action; it clears when `quay-operator` finishes recovery.)
- **Track the NVMe-oF shared-hostnqn fix at the node level**; until fixed, avoid unnecessary reschedules of the UWM prometheus/thanos-ruler pods.
- **Optional cleanup:** remove the ineffective `serviceMonitor` block in `exporters/blackbox-exporter/kustomization.yaml`, or replace it with an explicit ServiceMonitor for the exporter's self-metrics.
