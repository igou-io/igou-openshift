## Bootstrap OpenShift GitOps + 1Password Connect/ESO after a rebuild

Reusable runbook derived from the 2026-07-03 `ocp.igou.systems` cluster reinstall.
Every command, path, host, and gotcha below was executed or observed during that
recovery — nothing is aspirational.

### Purpose

After a full agent-based reinstall the control plane comes up with **no in-cluster
secret machinery**: OpenShift GitOps (ArgoCD), 1Password Connect, and External
Secrets Operator (ESO) are all gone, and every `op://` lookup that used to run
on-cluster (AAP, ESO) is dead. This runbook performs the **chicken-and-egg
bootstrap**: it seeds the two Secrets that Connect + ESO need, stands up ArgoCD with
the correct health-check / plugin configuration, and hands the cluster over to the
app-of-apps so ArgoCD can reconcile `clusters/ocp/` from git. It ends with the two
live-only ArgoCD tweaks that the rebuild proved are required for the wave march to
finish.

The seed is done **out-of-band** using a 1Password *service-account* token
(authenticating directly against 1Password SaaS, bypassing Connect — which is not up
yet), because Connect itself cannot supply its own credentials.

### When to use

- Immediately after `ClusterVersion` reports `Available` on a freshly reinstalled
  cluster (control plane MS-01 = `10.10.9.10`), before any application data restore.
- Any time OpenShift GitOps must be re-bootstrapped from zero and the on-cluster
  1Password lookups are unavailable.

Do **not** use this to "repair" a running GitOps — the playbook re-creates the ArgoCD CR
from its own committed spec, overwriting any live edit (see Step 5 / Gotchas).

### Prerequisites

- **API reachable** and the kubeconfig exported:
  `export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig`
  (this is the NEW kubeconfig minted by the agent installer; `oc get clusterversion`
  must succeed).
- **ocp-bootstrap 1Password service-account token** (a.k.a. the "dr" token), format
  `ops_...`. It needs read access to at least the `ocp-connect-bootstrap` vault. In
  the rebuild it was persisted at `~/.secrets/op-dr-sa-token` (mode 0600). This token
  authenticates the `community.general.onepassword*` lookups directly against
  1Password SaaS — Connect is not running, so it cannot be used.
- **Repos present** (local checkouts are STALE — always `git fetch origin main` and
  read with `git show origin/main:<path>`):
  - `/workspace/igou-ansible` — the bootstrap playbook
    (`playbooks/openshift/bootstrap_gitops.yaml`).
  - `/workspace/igou-openshift` — the GitOps repo (`github.com/igou-io/igou-openshift`),
    app-of-apps source at `clusters/ocp/`.
- **Tooling**: `ansible-navigator` (or `ansible-playbook`) with `community.general` +
  `kubernetes.core`; `oc`; `kustomize` + `helm` (the app-of-apps renders with
  `--enable-helm`).
- Data-restore inputs, needed only if you proceed to the staged app restore (Step 4), not
  to stand up GitOps:
  - **CNPG/Barman on RustFS** — `database-total-loss-recovery.md` (read the serverName
    map there; the READ side is *not* the cluster name).
  - **The nightly etcd snapshot** at `s3://etcd-backups/<z-stream>/<ts>/` on rustfs-cold —
    it cannot be restored into a reinstalled cluster, but mining it gives you the dead
    cluster's PV→zvol map and any Secret that never lived in 1Password. Procedure:
    `etcd-backup-restore.md`; the latest mined catalog is at
    `s3://etcd-backups/catalogs/pv-zvol-catalog-<date>.tsv`.
  - **Orphaned zvols on TrueNAS** — `restore-pvc-from-truenas.md`.

### Step-by-step

#### Step 0 — Environment + the kubeconfig CA-rotation fix

```bash
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig
oc get clusterversion            # must show Available (4.21.9 at the time of the rebuild;
                                 # 4.21.21 as of 2026-07-31)
```

**Kubeconfig CA-rotation gotcha (do this first, it bites early):** once the Machine
Config Operator settles after install, the **API serving cert rotates to a new CA**.
The `certificate-authority-data` embedded in the freshly generated kubeconfig then no
longer matches, and every `oc` call fails with `x509: certificate signed by unknown
authority`. Fix by **stripping `certificate-authority-data`** so `oc` falls back to
the host's system trust store (the serving cert is publicly trusted):

```bash
cp "$KUBECONFIG" "${KUBECONFIG%/*}/kubeconfig_self_signed"   # backup FIRST
# remove the certificate-authority-data line(s) from the cluster stanza
# result: `grep -c certificate-authority-data "$KUBECONFIG"` must return 0
```

Verified end state: `kubeconfig` has 0 `certificate-authority-data` lines; the
original is preserved at `.../auth/kubeconfig_self_signed`.

#### Step 1 — Provide the service-account token to the lookups

The playbook reads the token **only from the `OP_SERVICE_ACCOUNT_TOKEN` environment
variable** and asserts it is non-empty as its first task. There is no `vars_prompt` — it was
deliberately removed because it returns empty under ansible-navigator/AAP (no interactive TTY
wired to the lookup), which makes the lookup fall through to an interactive sign-in and fail
with `Missing required parameters`. Because the `community.general.onepassword*` lookups will
otherwise try to reach a (dead) Connect server, make sure no Connect env vars are set and the
SA token is exported:

```bash
unset OP_CONNECT_HOST OP_CONNECT_TOKEN
export OP_SERVICE_ACCOUNT_TOKEN=$(cat ~/.secrets/op-dr-sa-token)   # ops_... token
```

#### Step 2 — Run the bootstrap playbook

The **only** bootstrap playbook is `playbooks/openshift/bootstrap_gitops.yaml` in
`igou-ansible`. The `hub-cluster/` subdirectory and the drifted
`bootstrap_openshift_gitops.yaml` were both **deleted** from the repo — if a doc, memory, or
AAP template still names either path, it is stale.

```bash
cd /workspace/igou-ansible
git fetch origin main
ansible-navigator run playbooks/openshift/bootstrap_gitops.yaml \
  -e target_cluster=ocp \
  -e kubeconfig="$KUBECONFIG"
# OP_SERVICE_ACCOUNT_TOKEN must already be exported (Step 1) — there is no prompt.
```

`-e target_cluster=<cluster>` is required: it is the play's `hosts:` value (defaults to
`all`), so omitting it fans the bootstrap out across the whole inventory.

What the play creates, in order:
1. `openshift-gitops-operator` namespace + OperatorGroup + Subscription (channel
   `latest`, `redhat-operators`).
2. `external-secrets-operator` namespace.
3. `onepassword-connect` namespace.
4. **Seed Secret `op-credentials`** (ns `onepassword-connect`) — the Connect server's
   `1password-credentials.json`.
5. **Seed Secret `onepassword-connect-token`** (ns `external-secrets-operator`, key
   `token`) — the Connect access JWT that ESO's ClusterSecretStores use.
6. `gitops-cluster-admin` ClusterRoleBinding (argocd application-controller SA →
   cluster-admin).
7. The `ArgoCD` CR `openshift-gitops` (health checks, CMP setenv plugin, RBAC, repo
   sidecar).
8. `setenv-cmp-plugin` ConfigMap + `environment-variables` ConfigMap (derives
   `CLUSTER_BASE_DOMAIN` / `PLATFORM_BASE_DOMAIN` from the `Ingress` config).
9. `root-applications` Application → `clusters/ocp` (the app-of-apps root).

**The two seed-Secret fixes (already merged into the playbook via igou-ansible#312 —
do not regress them):**

- **FIX 1 — the Connect JWT is in the `credential` field, not `token`.** The
  `onepassword-connect-token` Secret pulls from the `ocp-connect-token` item using
  `field='credential'`. The item's `token` field is an unrelated **83-char stub**; the
  real Connect JWT (with `aud=com.1password.connect`, ~1762 chars) lives in
  `credential`. Using `token` yields a Connect server that never authenticates.

  ```yaml
  token: "{{ lookup('community.general.onepassword', 'ocp-connect-token',
             field='credential', vault='ocp-connect-bootstrap',
             service_account_token=op_bootstrap_sa_token) }}"
  ```

- **FIX 2 — `onepassword_doc` returns bytes → use `data:` + `| b64encode`, not
  `stringData`.** `community.general.onepassword_doc` returns raw bytes, which
  ansible-core ≥ 2.19 refuses to serialize into module args. Put the value under
  `data:` (base64) instead of `stringData:`:

  ```yaml
  data:
    1password-credentials.json: "{{ lookup('community.general.onepassword_doc',
      'ocp-connect-credentials', vault='ocp-connect-bootstrap',
      service_account_token=op_bootstrap_sa_token) | b64encode }}"
  ```

Both Secrets are annotated `managed-by: ansible` and set `no_log: true`.

#### Step 3 — Let the app-of-apps take over

`root-applications` renders `clusters/ocp/` (Helm values → `Application`s; 48 at the time of
the rebuild, 61 as of 2026-07-31) and orders them by `argocd.argoproj.io/sync-wave`.
Foundation is **wave 0**: `external-secrets-operator` + `onepassword-connect`. The wave
ladder observed during the 2026-07-03 rebuild — indicative, not current; read
`clusters/ocp/values.yaml` for today's list:

```
 0  external-secrets-operator, onepassword-connect
 1  lvms-operator
 2  machineconfigs        3  kubeletconfig
 5  nmstate, openshift-nfd
 6  metallb, udn, cert-manager-config, nvidia-gpu-operator, user-workload-monitoring
 7  democratic-csi        8  image-registry, ocp-base-config
 9  apiserver(+certs), ingresscontroller-certs
10  cluster-api-operator, gateway-api, grafana, loki-operator, openshift-logging,
    openshift-pipelines, tailscale-operator, intel-device-plugins-operator
11  cluster-api           12  cluster-api-autoscaler
19  firecrawl
20  cloudnative-pg, hermes-agent, jellyfin, llmkube, searxng, gotify,
    pac-tenants, remote-tenants
22  forgejo, quay-operator, rhdh          23  gitea-mirror
25  alertmanager-config   30  ansible-automation-platform   39  molecule
40  service-accounts      50  openshift-virt
```

Note: `kustomizeBuildOptions` / `--enable-helm` come from the **ArgoCD CR the playbook
created** (and the setenv CMP plugin's `kustomize build ... --enable-helm`). If you
change plugin/build options live, the **repo-server must be restarted** to pick them up.

#### Step 4 — Staged restore via sync-waves (DR only)

In a full rebuild you do **not** enable all apps at once — a data-less app that lands
before its PV/DB is restored goes Degraded and (because of the wave gate, below) wedges
every higher wave. The rebuild deferred apps by **commenting them out in
`clusters/ocp/values.yaml`** and uncommenting per wave (ArgoCD ignores comment
indentation, so block-commenting an app entry is a clean defer).

- Rebuild-from-original technique: `git show <defer-commit>^:clusters/ocp/values.yaml`
  to recover the full list, then re-comment only the still-deferred apps. Scratchpad
  helpers used: `recomment.py` + `values-original.yaml`.
- Order actually used (each a merged PR): essential/stateless first
  (igou-openshift#383/#384 — operators, CAPI, CNV-operator, tenants, pipelines,
  tailscale) → observability (#385 — loki/logging/grafana/alertmanager) → stateful
  wave 3 (#386 hermes-agent; #387/#388 the CNPG DBs quay/rhdh/forgejo restored from
  Barman) → everything enabled (#389, values.yaml back to full).

**Wave-gate behavior (the recurring trap):** the app-of-apps gates wave *N+1* on wave
*N* being **Synced AND Healthy**. A single Degraded app in a low wave blocks all higher
waves. Transient operator-install degrades (`service-accounts`, `grafana`,
`cluster-api`) each stall the march — nudge by manually applying the operator's
`ns + OperatorGroup + Subscription` from its component, wait for the CSV to Succeed,
then hard-refresh.

#### Step 5 — ArgoCD CR tuning (now codified — verify, don't re-apply)

> ✅ **Resolved since this runbook was written.** The repo-server tuning below is committed
> in `playbooks/openshift/bootstrap_gitops.yaml` (`spec.repo.env` +
> `spec.repo.resources`), so a bootstrap re-run no longer reverts it — nothing to hand-patch.
> The PushSecret health-check override was never needed in the end: the Connect token was
> widened, all seven `service-accounts` PushSecrets are `Synced`, and the app is
> Synced/Healthy. Both subsections are retained as **diagnosis aids** for if the symptom
> returns; treat them as history, not as steps.

**Patch A (historical — no longer applied) — lenient PushSecret health check.**
`service-accounts` (wave 40) went Degraded because 6 PushSecrets returned 403 — the
Connect token is **read-only** on the `claude` + `ocp-push` vaults, and the operator
chose to leave outbound 1P publishing broken rather than widen the token. That Degraded
wave-40 app gated `openshift-virt` (wave 50) and every wave > 40. The durable fix that
honors "leave publishing broken" is a health-check override that reports PushSecrets
Healthy:

```bash
# add an external-secrets.io/PushSecret entry to spec.resourceHealthChecks
oc -n openshift-gitops patch argocd openshift-gitops --type=merge \
  --patch-file /path/to/argocd-patch.json     # full resourceHealthChecks array
# the change only takes effect after a controller restart + hard refresh:
oc -n openshift-gitops rollout restart statefulset openshift-gitops-application-controller
```

The health-check body to embed in the ArgoCD CR `spec.resourceHealthChecks`:

```yaml
- group: external-secrets.io
  kind: PushSecret
  check: |
    hs = {}
    hs.status = "Healthy"
    hs.message = "PushSecret present; outbound 1P publish may fail (read-only Connect token) but is non-blocking for GitOps"
    return hs
```

(Manually force-creating a gated wave > 40 Application instead does NOT work —
`root-applications` has `prune: true` and treats a not-yet-due app as extraneous, so it
gets pruned. Open the gate with the health check; do not force-create.)

**Patch B (codified in the playbook — do not re-apply) — repo-server performance.**
Heavy Helm render of `clusters/ocp/` (app-of-apps with `--enable-helm`) exceeded the
default 90s exec timeout on 1 CPU, producing recurring `Unknown` / `DeadlineExceeded`
states that stalled the wave march. Fix:

```bash
oc -n openshift-gitops patch argocd openshift-gitops --type=merge -p \
'{"spec":{"repo":{"resources":{"limits":{"cpu":"2","memory":"2Gi"}},
"env":[{"name":"ARGOCD_EXEC_TIMEOUT","value":"3m"}]}}}'
```

The committed playbook now carries this under `spec.repo` — the live values to expect are
`cpu: "2"` / `memory: 1Gi` and `ARGOCD_EXEC_TIMEOUT=3m` (the memory limit was left at 1Gi;
only the CPU limit and the timeout mattered):

```yaml
repo:
  env:
    - name: KUSTOMIZE_PLUGIN_HOME
      value: /etc/kustomize/plugin
    - name: ARGOCD_EXEC_TIMEOUT
      value: 3m
  resources:
    limits:
      cpu: "2"
      memory: 1Gi
    requests:
      cpu: 500m
      memory: 256Mi
```

### Verification

```bash
# 1) Seed Secrets present, annotated by ansible
oc -n onepassword-connect get secret op-credentials \
  -o jsonpath='{.metadata.annotations.managed-by}{"\n"}'          # -> ansible
oc -n external-secrets-operator get secret onepassword-connect-token \
  -o jsonpath='{.metadata.annotations.managed-by}{"\n"}'          # -> ansible

# 2) ESO ClusterSecretStores Valid + Ready (Connect JWT is good)
oc get clustersecretstore
#   onepassword-sdk-claude / -ocp-pull / -ocp-push  =>  Valid  ReadWrite  True

# 3) App-of-apps converging (a few OutOfSync/Progressing during the march is normal)
oc -n openshift-gitops get applications \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
#   observed at hand-off: 42 Synced / 43 Healthy of 48

# 4) Repo-server tuning came through from the playbook (no hand-patching needed)
oc -n openshift-gitops get argocd openshift-gitops \
  -o jsonpath='{.spec.repo.resources.limits}{"  "}{.spec.repo.env[*].name}={.spec.repo.env[*].value}{"\n"}'
#   {"cpu":"2","memory":"1Gi"}  KUSTOMIZE_PLUGIN_HOME ARGOCD_EXEC_TIMEOUT=/etc/kustomize/plugin 3m
# There is deliberately NO external-secrets.io/PushSecret health check (Step 5). Instead:
oc -n service-accounts get pushsecrets       # all Synced

# 5) Kubeconfig CA stripped
grep -c certificate-authority-data "$KUBECONFIG"                  # -> 0
```

Connect pod `Running` in `onepassword-connect` and the `onepassword-sdk-*` stores
`Valid` are the true green light: from here ExternalSecrets resolve and the wave march
proceeds.

### Rollback

This is an additive bootstrap onto an empty cluster; git is the source of truth, so
"rollback" means tearing the bootstrap down and re-running — with care not to delete
namespaces that hold restored data.

- **Re-bootstrap cleanly:** delete `root-applications`
  (`oc -n openshift-gitops delete application root-applications`; if it hangs on the
  `resources-finalizer.argocd.argoproj.io` finalizer, remove the finalizer), then
  re-run the Step 2 playbook.
- **A playbook re-run no longer loses the repo-server tuning** — `cpu: "2"` and
  `ARGOCD_EXEC_TIMEOUT=3m` are committed in `bootstrap_gitops.yaml` (Step 5). Re-running
  still overwrites *live* edits you made outside git, so if you hand-tuned the ArgoCD CR,
  fold the change into the playbook instead.
- A gated (wave > 40) app that keeps disappearing was **pruned** by `root-applications`,
  not failed — do not re-create it by hand; open its wave gate instead.

### Gotchas & pitfalls (from this incident)

1. **Right playbook.** `playbooks/openshift/bootstrap_gitops.yaml` with
   `-e target_cluster=<cluster>`. The old `hub-cluster/bootstrap_gitops.yaml` and
   `bootstrap_openshift_gitops.yaml` paths no longer exist — both were deleted.
2. **Connect JWT field.** The real Connect JWT is in the item's `credential` field; the
   `token` field is an 83-char stub. Wrong field = Connect never authenticates.
3. **`onepassword_doc` bytes.** Returns bytes → `data:` + `| b64encode`, never
   `stringData:` (ansible-core ≥ 2.19 refuses to serialize bytes to module args).
4. **Kubeconfig CA rotation.** After the MCO settles, the API serving cert's CA rotates;
   strip `certificate-authority-data` (back up to `kubeconfig_self_signed`) so `oc`
   uses system trust. Symptom: sudden `x509: unknown authority` on a kubeconfig that
   worked minutes earlier.
5. **SA token bypasses Connect (chicken-and-egg).** `unset OP_CONNECT_HOST
   OP_CONNECT_TOKEN` and set `OP_SERVICE_ACCOUNT_TOKEN` so the lookups hit 1Password
   SaaS, not the not-yet-running Connect.
6. **Wave gate.** app-of-apps gates wave N+1 on wave N being Synced **and** Healthy. One
   Degraded low-wave app blocks everything above it.
7. **PushSecret 403 wedge.** Read-only Connect token → 6 PushSecrets 403 →
   `service-accounts` (wave 40) Degraded → blocks `openshift-virt` (wave 50) and all
   wave > 40. Fix with the lenient PushSecret health check + controller restart +
   hard-refresh.
8. **repo-server perf.** Default 90s / 1 CPU is too small for the Helm app-of-apps
   render → `Unknown` / `DeadlineExceeded` stalls. Bump `cpu: 2 / memory: 2Gi` and
   `ARGOCD_EXEC_TIMEOUT=3m`.
9. **The ArgoCD CR is playbook-managed, not GitOps-managed.** Any live edit is lost on the
   next run, so tuning must land in `bootstrap_gitops.yaml`. The 2026-07 repo-server tuning
   has been folded in; the PushSecret health check was dropped as unnecessary (Step 5).
10. **Stale local checkouts.** `/workspace/igou-openshift` (and `igou-ansible`) local
    HEAD lags origin by 100+ commits. `oc kustomize` / `kustomize build` from a stale
    checkout renders OLD manifests (e.g. CNPG `initdb` instead of `recovery`). Always
    `git fetch origin main` and apply with `git show origin/main:<path>`.
11. **`--enable-helm` origin.** It comes from the ArgoCD CR / setenv CMP plugin — change
    it live and you must restart the repo-server.
12. **Operator-CRD ordering during the march.** Some wave apps need their CRDs to exist
    before ArgoCD's dry-run: apply `ns + OperatorGroup + Subscription` from the
    component, wait for the CSV to Succeed, then sync the app (CNV needs
    `SkipDryRunOnMissingResource=true` — StorageProfiles depend on the `cdi.kubevirt.io`
    CRD that only appears after the HyperConverged CR). Not part of GitOps bootstrap
    proper, but it recurs on every wave that installs an operator.
