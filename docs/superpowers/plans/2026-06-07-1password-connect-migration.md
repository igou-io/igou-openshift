# 1Password SDK → Connect Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ESO (and external Ansible lookups) off the rate-limited `onepasswordSDK` provider onto a self-hosted in-cluster 1Password Connect server, via a big-bang cutover that leaves ExternalSecret bodies untouched.

**Architecture:** A new `onepassword-connect` component deploys the Connect server (Helm chart 2.4.1, server-only — no operator) into its own namespace, fronted by an edge Route on the cluster's `acme-apps` Let's Encrypt wildcard for external Ansible, and reachable in-cluster over plaintext HTTP gated by a NetworkPolicy. The 3 existing `onepassword-sdk-*` ClusterSecretStores are rewritten in place (same names) to the `onepassword` Connect provider. The chicken-egg seed (Connect credentials file + access token) is created imperatively, mirroring how the SDK token is seeded today.

**Tech Stack:** OpenShift/OKD, ArgoCD app-of-apps, kustomize + Helm (`--enable-helm`), External Secrets Operator, 1Password Connect, Ansible (`onepassword.connect` + `community.general.onepassword`), `op` CLI.

**Source spec:** `docs/superpowers/specs/2026-06-07-1password-connect-migration-design.md`

**Repos touched:** `igou-openshift` (this repo) and `igou-ansible` (bootstrap playbook). Task 8 is in `igou-ansible`.

**Commit convention:** commit directly to `main` (no branch/PR). Append this trailer to every commit message (omitted from the commands below for brevity):
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

**Validation note:** there is no unit-test framework — "verification" means `make validate-kustomize` (runs `kustomize build --enable-helm`), `make lint` (yamllint), and live `oc` checks. Run `make clean` if a build leaves a `charts/` dir behind.

---

### Task 1: One-time 1Password Connect server + token (manual, human-run)

This is a prerequisite done once by a human with `op` CLI authenticated to the account. It produces the two secrets every later task depends on. Nothing is committed.

**Files:** none (1Password + local filesystem only)

- [ ] **Step 1: Create the Connect server scoped to the three vaults**

Run:
```bash
op connect server create ocp-hub --vaults ocp-pull,ocp-push,claude
```
Expected: writes `1password-credentials.json` to the current directory and prints the server's details.

- [ ] **Step 2: Create an access token with per-vault scopes**

Run:
```bash
op connect token create eso --server ocp-hub \
  --vault ocp-pull:read --vault ocp-push:read_write --vault claude:read_write
```
Expected: prints the token (a JWT). Copy it.

- [ ] **Step 3: Create a dedicated bootstrap vault and store both Connect credentials there**

Create a SEPARATE privileged vault `ocp-connect-bootstrap` — NOT a vault Connect serves, and NOT in the Connect token scope from Step 2 — so the Connect server's own credentials never sit in a vault Connect distributes:
```bash
op vault create ocp-connect-bootstrap
op document create 1password-credentials.json --vault ocp-connect-bootstrap --title 1password-connect-credentials
op item create --category password --vault ocp-connect-bootstrap --title 1password-connect-token token=<PASTE_TOKEN_FROM_STEP_2>
```
Expected: vault created; two items in `ocp-connect-bootstrap`.

- [ ] **Step 3b: Create a read-only service account scoped to ONLY that vault**

On 1Password.com → Developer → service accounts, create an SA (e.g. `ocp-bootstrap`) granted **read on `ocp-connect-bootstrap` only** (no access to ocp-pull/ocp-push/claude). Save its token — this is the bootstrap root, supplied to the playbook as `OP_SERVICE_ACCOUNT_TOKEN`. It is the single service account retained for bootstrap/break-glass (Task 9).

- [ ] **Step 4: Shred the local credentials file**

Run: `shred -u 1password-credentials.json`
Expected: file removed.

---

### Task 2: Create the `onepassword-connect` component (server-only)

**Files:**
- Create: `components/onepassword-connect/onepassword-connect-namespace.yaml`
- Create: `components/onepassword-connect/kustomization.yaml`

- [ ] **Step 1: Create the namespace manifest**

`components/onepassword-connect/onepassword-connect-namespace.yaml`:
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: onepassword-connect
```

- [ ] **Step 2: Create the component kustomization (Helm chart, server-only)**

`components/onepassword-connect/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - onepassword-connect-namespace.yaml

helmCharts:
  - name: connect
    repo: https://1password.github.io/connect-helm-charts
    version: 2.4.1
    releaseName: onepassword-connect
    namespace: onepassword-connect
    valuesInline:
      operator:
        create: false                 # ESO is the consumer — no 1Password operator
      connect:
        create: true
        serviceType: ClusterIP
        credentialsName: op-credentials            # pre-seeded out-of-band (Task 5)
        credentialsKey: 1password-credentials.json
        tls:
          enabled: false                           # edge Route terminates TLS; pod serves HTTP :8080
        nodeSelector:
          node-role.kubernetes.io/control-plane: ""
        tolerations:
          - key: node-role.kubernetes.io/master
            operator: Exists
            effect: NoSchedule
          - key: node-role.kubernetes.io/control-plane
            operator: Exists
            effect: NoSchedule
```

- [ ] **Step 3: Verify it builds and the operator is NOT rendered**

Run:
```bash
kustomize build --enable-helm components/onepassword-connect | \
  grep -E "^kind:|operator|connect-api|onepassword-credentials|name: onepassword-connect"
```
Expected: a `Deployment`, `Service`, `ServiceAccount` named `onepassword-connect`; **no** `operator-deployment` / `OnePasswordItem` CRD objects. Note the Service port name for the API (`connect-api`) and the pod label (used in Tasks 4 & 6).

- [ ] **Step 4: Verify node placement applied (chart values are honored)**

Run:
```bash
kustomize build --enable-helm components/onepassword-connect | \
  grep -A4 "tolerations:"
```
Expected: the master/control-plane tolerations appear on the Deployment. If they do **not** appear (chart ignored the keys), add a strategic-merge patch on the `onepassword-connect` Deployment in the cluster wrap (Task 3) instead. Run `make clean` afterward.

- [ ] **Step 5: Commit**

```bash
git add components/onepassword-connect/
git commit -m "onepassword-connect: add Connect server component (chart 2.4.1, server-only)"
```

---

### Task 3: Create the cluster wrap (SCC, NetworkPolicy, Route)

**Files:**
- Create: `clusters/ocp/onepassword-connect/onepassword-connect-nonroot-v2-rolebinding.yaml`
- Create: `clusters/ocp/onepassword-connect/connect-allow-eso-and-router-networkpolicy.yaml`
- Create: `clusters/ocp/onepassword-connect/onepassword-connect-route.yaml`
- Create: `clusters/ocp/onepassword-connect/kustomization.yaml`

- [ ] **Step 1: SCC RoleBinding (lets the chart's hardcoded UID 999 run under a non-root SCC)**

The chart hardcodes `runAsUser/fsGroup: 999`, which `restricted-v2` rejects. `nonroot-v2` allows any non-root UID and any fsGroup, so the image's intended UID 999 works — which also sidesteps the `/home/opuser/.op` ownership crash ([#282](https://github.com/1Password/connect-helm-charts/issues/282)).

`clusters/ocp/onepassword-connect/onepassword-connect-nonroot-v2-rolebinding.yaml`:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: onepassword-connect-nonroot-v2
  namespace: onepassword-connect
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:nonroot-v2
subjects:
  - kind: ServiceAccount
    name: onepassword-connect        # confirm against Task 2 Step 3 output
    namespace: onepassword-connect
```

- [ ] **Step 2: NetworkPolicy (only ESO + the router may reach :8080)**

`clusters/ocp/onepassword-connect/connect-allow-eso-and-router-networkpolicy.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: connect-allow-eso-and-router
  namespace: onepassword-connect
spec:
  podSelector:
    matchLabels:
      app: onepassword-connect        # confirm against Task 2 Step 3 pod label
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: external-secrets-operator
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-ingress
      ports:
        - protocol: TCP
          port: 8080
```

- [ ] **Step 3: Edge Route (inherits the acme-apps Let's Encrypt wildcard)**

`clusters/ocp/onepassword-connect/onepassword-connect-route.yaml`:
```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: onepassword-connect
  namespace: onepassword-connect
spec:
  to:
    kind: Service
    name: onepassword-connect
  port:
    targetPort: connect-api          # HTTP :8080
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
  # no spec.host / no spec.tls.certificate → default hostname under
  # *.apps.ocp.igou.systems, served with the acme-apps cert
```

- [ ] **Step 4: Cluster wrap kustomization**

`clusters/ocp/onepassword-connect/kustomization.yaml`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../../components/onepassword-connect
  - onepassword-connect-nonroot-v2-rolebinding.yaml
  - connect-allow-eso-and-router-networkpolicy.yaml
  - onepassword-connect-route.yaml
```

- [ ] **Step 5: Verify build + lint**

Run: `kustomize build --enable-helm clusters/ocp/onepassword-connect >/dev/null && echo OK`
Expected: `OK`. Then `make lint` → no errors for the new files. Run `make clean`.

- [ ] **Step 6: Commit**

```bash
git add clusters/ocp/onepassword-connect/
git commit -m "onepassword-connect: cluster wrap — nonroot-v2 SCC, NetworkPolicy, edge Route"
```

---

### Task 4: Seed the Connect credentials + access token on the running cluster

ArgoCD will not start Connect until the `op-credentials` Secret exists, and ESO can't authenticate without the token Secret. On an already-running cluster these are created imperatively now (Task 8 makes future bootstraps do this automatically). Requires `op` CLI + `oc` logged in.

**Files:** none (live cluster only)

- [ ] **Step 1: Ensure the namespace exists**

Run: `oc create namespace onepassword-connect --dry-run=client -o yaml | oc apply -f -`
Expected: `namespace/onepassword-connect created` (or `configured`).

- [ ] **Step 2: Seed the Connect server credentials Secret**

Run:
```bash
op document get 1password-connect-credentials --vault ocp-connect-bootstrap --out-file /tmp/1password-credentials.json
oc -n onepassword-connect create secret generic op-credentials \
  --from-file=1password-credentials.json=/tmp/1password-credentials.json
shred -u /tmp/1password-credentials.json
```
Expected: `secret/op-credentials created`.

- [ ] **Step 3: Seed the Connect access token Secret for ESO**

Run:
```bash
oc -n external-secrets-operator create secret generic onepassword-connect-token \
  --from-literal=token="$(op item get 1password-connect-token --vault ocp-connect-bootstrap --fields label=token --reveal)"
```
Expected: `secret/onepassword-connect-token created`.

- [ ] **Step 4: Verify both secrets exist and are non-empty**

Run:
```bash
oc -n onepassword-connect get secret op-credentials -o jsonpath='{.data.1password-credentials\.json}' | wc -c
oc -n external-secrets-operator get secret onepassword-connect-token -o jsonpath='{.data.token}' | wc -c
```
Expected: both print a number > 0.

---

### Task 5: Wire `onepassword-connect` into the app-of-apps and deploy

**Files:**
- Modify: `clusters/ocp/values.yaml` (add an entry next to `external-secrets-operator`)

- [ ] **Step 1: Add the application entry at sync-wave 0**

In `clusters/ocp/values.yaml`, immediately after the `external-secrets-operator:` block (which ends before `lvms-operator:`), insert:
```yaml
  onepassword-connect:
    annotations:
      argocd.argoproj.io/compare-options: IgnoreExtraneous
      argocd.argoproj.io/sync-wave: '0'
    destination:
      namespace: onepassword-connect
    source:
      path: clusters/ocp/onepassword-connect
```

- [ ] **Step 2: Verify the app-of-apps still builds**

Run: `kustomize build --enable-helm clusters/ocp >/dev/null && echo OK` (then `make clean`)
Expected: `OK`.

- [ ] **Step 3: Commit (this triggers the deploy)**

```bash
git add clusters/ocp/values.yaml
git commit -m "onepassword-connect: register in ocp app-of-apps (sync-wave 0)"
git push
```

- [ ] **Step 4: Sync and verify the Connect server is Running**

Run:
```bash
argocd app sync onepassword-connect 2>/dev/null || true
oc -n onepassword-connect rollout status deploy/onepassword-connect --timeout=120s
oc -n onepassword-connect get pods
```
Expected: rollout succeeds; the `onepassword-connect` pod is `Running` with both containers ready (connect-api + connect-sync). If it `CrashLoopBackOff`s on a `/home/opuser/.op` ownership error, the SCC binding (Task 3 Step 1) isn't taking — confirm the pod's SA and that the RoleBinding subject name matches.

- [ ] **Step 5: Verify the Route serves the Let's Encrypt cert (no custom CA)**

Run:
```bash
HOST=$(oc -n onepassword-connect get route onepassword-connect -o jsonpath='{.spec.host}')
curl -sS -o /dev/null -w "%{http_code}\n" "https://${HOST}/heartbeat"
```
Expected: an HTTP status (e.g. `200`) with **no** TLS error — confirming the public LE cert validates against the system trust store.

---

### Task 6: Smoke-test Connect with a throwaway ExternalSecret (de-risk the big-bang)

Prove the Connect server + token actually resolve a secret before flipping the real stores. Uses a temporary store/ExternalSecret that is deleted at the end. Pick any existing item in the `ocp-pull` vault for `<KNOWN_ITEM>` (e.g. an item you know has a `password` field).

**Files:** none (applied imperatively, then deleted)

- [ ] **Step 1: Apply a throwaway Connect ClusterSecretStore**

Run:
```bash
cat <<'EOF' | oc apply -f -
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-connect-smoke
spec:
  provider:
    onepassword:
      connectHost: http://onepassword-connect.onepassword-connect.svc:8080
      vaults:
        ocp-pull: 1
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            key: token
            namespace: external-secrets-operator
EOF
```

- [ ] **Step 2: Verify the store reports Ready**

Run: `oc get clustersecretstore onepassword-connect-smoke -o jsonpath='{.status.conditions[0].type}={.status.conditions[0].status}{"\n"}'`
Expected: `Ready=True`. If `False`, read the message — it surfaces token/connectHost problems.

- [ ] **Step 3: Apply a throwaway ExternalSecret and verify it syncs**

Run:
```bash
cat <<'EOF' | oc apply -f -
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: connect-smoke
  namespace: external-secrets-operator
spec:
  secretStoreRef: { kind: ClusterSecretStore, name: onepassword-connect-smoke }
  target: { name: connect-smoke }
  dataFrom:
    - extract: { key: <KNOWN_ITEM> }
EOF
sleep 5
oc -n external-secrets-operator get externalsecret connect-smoke -o jsonpath='{.status.conditions[0].reason}{"\n"}'
```
Expected: `SecretSynced`.

- [ ] **Step 4: Tear down the smoke test**

Run:
```bash
oc -n external-secrets-operator delete externalsecret connect-smoke
oc -n external-secrets-operator delete secret connect-smoke
oc delete clustersecretstore onepassword-connect-smoke
```
Expected: all deleted. **Do not proceed to Task 7 unless Step 2 and Step 3 passed.**

---

### Task 7: Cutover — rewrite the 3 ClusterSecretStores in place

**Files:**
- Modify: `clusters/ocp/external-secrets-operator/onepassword-sdk-ocp-pull-clustersecretstore.yaml`
- Modify: `clusters/ocp/external-secrets-operator/onepassword-sdk-ocp-push-clustersecretstore.yaml`
- Modify: `clusters/ocp/external-secrets-operator/onepassword-sdk-claude-container-clustersecretstore.yaml`

- [ ] **Step 1: Rewrite the `ocp-pull` store (keep the name)**

Replace the full contents of `clusters/ocp/external-secrets-operator/onepassword-sdk-ocp-pull-clustersecretstore.yaml` with:
```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-sdk-ocp-pull
spec:
  refreshInterval: 3600
  provider:
    onepassword:
      connectHost: http://onepassword-connect.onepassword-connect.svc:8080
      vaults:
        ocp-pull: 1
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            key: token
            namespace: external-secrets-operator
```

- [ ] **Step 2: Rewrite the `ocp-push` store**

Replace the full contents of `clusters/ocp/external-secrets-operator/onepassword-sdk-ocp-push-clustersecretstore.yaml` with:
```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-sdk-ocp-push
spec:
  refreshInterval: 3600
  provider:
    onepassword:
      connectHost: http://onepassword-connect.onepassword-connect.svc:8080
      vaults:
        ocp-push: 1
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            key: token
            namespace: external-secrets-operator
```

- [ ] **Step 3: Rewrite the `claude` store**

Replace the full contents of `clusters/ocp/external-secrets-operator/onepassword-sdk-claude-container-clustersecretstore.yaml` with:
```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: onepassword-sdk-claude
spec:
  refreshInterval: 3600
  provider:
    onepassword:
      connectHost: http://onepassword-connect.onepassword-connect.svc:8080
      vaults:
        claude: 1
      auth:
        secretRef:
          connectTokenSecretRef:
            name: onepassword-connect-token
            key: token
            namespace: external-secrets-operator
```

- [ ] **Step 4: Verify build + lint**

Run: `kustomize build clusters/ocp/external-secrets-operator >/dev/null && echo OK && make lint`
Expected: `OK` and no lint errors. (`validate-schemas` skips `ClusterSecretStore`, so the build check is the gate.)

- [ ] **Step 5: Commit and push the cutover**

```bash
git add clusters/ocp/external-secrets-operator/onepassword-sdk-*.yaml
git commit -m "external-secrets: cut over the 3 ClusterSecretStores to the Connect provider"
git push
```

- [ ] **Step 6: Sync and verify all stores Ready against Connect**

Run:
```bash
argocd app sync external-secrets-operator 2>/dev/null || true
oc get clustersecretstore -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status
```
Expected: `onepassword-sdk-ocp-pull`, `-ocp-push`, `onepassword-sdk-claude` all `True`.

- [ ] **Step 7: Verify all ExternalSecrets re-synced from Connect**

Run: `oc get externalsecrets -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,REASON:.status.conditions[0].reason | grep -v SecretSynced`
Expected: only the header line (every ExternalSecret is `SecretSynced`).

- [ ] **Step 8: Verify the write path (PushSecret) still works**

Run: `oc get pushsecret -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,STATUS:.status.conditions[0].reason`
Expected: PushSecrets report a synced/`Pushed` reason. Spot-check in 1Password that a pushed item updated. **If any check fails, roll back by `git revert`ing the Task 7 commit** (the SDK stores resolve again immediately; the seed token Secret is harmless to leave).

---

### Task 8: Update the Ansible bootstrap (`igou-ansible`)

Makes a future from-scratch bootstrap seed Connect instead of the SDK token. This repo is `igou-ansible`, not `igou-openshift`.

**Files:**
- Modify: `igou-ansible/playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`

- [ ] **Step 1: Replace the SDK token seed task**

Find the task `- name: Create 1password-token secrets` (the one looping over `onepassword_tokens` and writing `stringData: { token: ... }` into `external-secrets-operator`). Replace that single task with:
```yaml
- name: Create onepassword-connect namespace
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: onepassword-connect

- name: Fetch Connect credentials file (document)
  ansible.builtin.command: op document get 1password-connect-credentials --vault ocp-connect-bootstrap
  register: op_creds
  no_log: true
  changed_when: false

- name: Fetch Connect access token
  ansible.builtin.set_fact:
    op_connect_token: "{{ lookup('community.general.onepassword',
                          '1password-connect-token', field='token', vault='ocp-connect-bootstrap') }}"
  no_log: true

- name: Seed the Connect server credentials Secret
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Secret
      metadata: { name: op-credentials, namespace: onepassword-connect }
      type: Opaque
      stringData:
        1password-credentials.json: "{{ op_creds.stdout }}"
  no_log: true

- name: Seed the Connect access token Secret (for ESO)
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Secret
      metadata: { name: onepassword-connect-token, namespace: external-secrets-operator }
      type: Opaque
      stringData:
        token: "{{ op_connect_token }}"
  no_log: true
```

- [ ] **Step 2: Remove the SDK rate-limit ArgoCD health-check override**

In the same file, inside the `ArgoCD` object's `resourceHealthChecks`, delete the two blocks between the comment markers `# WORKAROUND: 1Password SDK rate limiting …` and `# END WORKAROUND: ESO rate-limit health overrides` (the `external-secrets.io / ClusterSecretStore` and `external-secrets.io / ExternalSecret` checks). Leave the cert-manager/Route/Subscription/InstallPlan checks intact.

- [ ] **Step 3: Lint the playbook**

Run (in `igou-ansible`): `ansible-lint playbooks/openshift/hub-cluster/bootstrap_gitops.yaml`
Expected: no new errors (pre-existing warnings unchanged).

- [ ] **Step 4: Commit (in igou-ansible)**

```bash
git -C ../igou-ansible add playbooks/openshift/hub-cluster/bootstrap_gitops.yaml
git -C ../igou-ansible commit -m "bootstrap_gitops: seed 1Password Connect creds/token; drop SDK token seed + SDK rate-limit health override"
git -C ../igou-ansible push
```
(Adjust the relative path if `igou-ansible` is not a sibling of `igou-openshift`.)

---

### Task 9: Decommission SDK artifacts and tune

**Files:**
- Modify: `clusters/ocp/external-secrets-operator/onepassword-sdk-*-clustersecretstore.yaml` (lower refreshInterval — already free of `cache` after Task 7's rewrite)

- [ ] **Step 1: Measure the propagation floor (undocumented sync interval)**

Run:
```bash
op item create --category password --vault ocp-pull --title connect-latency-probe token=probe-$(date +%s)
HOST=$(oc -n onepassword-connect get route onepassword-connect -o jsonpath='{.spec.host}')
TOKEN=$(oc -n external-secrets-operator get secret onepassword-connect-token -o jsonpath='{.data.token}' | base64 -d)
# poll until the probe shows up via the Connect API; note the elapsed time
time until curl -sf -H "Authorization: Bearer $TOKEN" "https://$HOST/v1/vaults" \
  | grep -q ocp-pull; do sleep 5; done
op item delete connect-latency-probe --vault ocp-pull
```
Expected: records how long Connect takes to surface a change. Use it to choose `refreshInterval` in Step 2.

- [ ] **Step 2: Lower `refreshInterval` on the 3 stores**

In each `onepassword-sdk-*-clustersecretstore.yaml`, change `refreshInterval: 3600` to a value appropriate to the measured floor (e.g. `300`). Verify: `kustomize build clusters/ocp/external-secrets-operator >/dev/null && echo OK`.

- [ ] **Step 3: Commit**

```bash
git add clusters/ocp/external-secrets-operator/onepassword-sdk-*.yaml
git commit -m "external-secrets: lower Connect store refreshInterval now that reads are local"
git push
```

- [ ] **Step 4: Delete the leftover SDK token Secrets**

Run:
```bash
oc -n external-secrets-operator get secret -o name | grep -E "onepassword-sdk-.*-token"
# for each that is NOT onepassword-connect-token and no longer referenced:
oc -n external-secrets-operator delete secret <sdk-token-secret-name>
```
Expected: the old `onepassword-sdk-*-token` Secrets removed; `onepassword-connect-token` retained.

- [ ] **Step 5: Retire surplus service accounts (keep one)**

In 1Password, revoke all but one service account; keep **only** the `ocp-bootstrap` SA (read-only on `ocp-connect-bootstrap`, from Task 1 Step 3b) for the bootstrap seed + break-glass. Verify ESO is unaffected: `oc get clustersecretstore -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status` → all still `True`.

---

### Task 10: Ansible steady-state client (`onepassword.connect`)

**Files:** none in this repo (control-node setup + optional future playbook edits)

- [ ] **Step 1: Install the collection on control nodes**

Run: `ansible-galaxy collection install onepassword.connect`
Expected: installs `onepassword.connect` (v2.4.0+). No extra PyPI deps; no `op` binary needed. No custom CA needed (the Route uses the public LE cert).

- [ ] **Step 2: Verify a read against Connect**

Create `/tmp/connect-check.yml`:
```yaml
- hosts: localhost
  gather_facts: false
  environment:
    OP_CONNECT_HOST: "https://onepassword-connect.apps.ocp.igou.systems"
    OP_CONNECT_TOKEN: "{{ op_connect_token }}"
  tasks:
    - name: Read a known field from Connect
      onepassword.connect.field_info:
        item: "<KNOWN_ITEM>"
        vault: "ocp-pull"
        field: "password"
      register: probe
      no_log: true
    - debug: { msg: "got {{ (probe.field.value | length) }} chars" }
```
Run: `OP_CONNECT_HOST=... OP_CONNECT_TOKEN=... ansible-playbook /tmp/connect-check.yml -e op_connect_token=$OP_CONNECT_TOKEN`
Expected: prints a non-zero char count — confirms REST auth + TLS work end to end.

- [ ] **Step 3 (optional): Migrate `sync_1pasword_secrets.yml` writes**

If desired, replace its `op item create/delete` shell tasks with `onepassword.connect.generic_item` (state present/absent). Otherwise it keeps using the `op` CLI — acceptable, since the kept service account still works. No action required to complete the migration.

---

## Self-Review

- **Spec coverage:** server-only deploy (T2, `operator.create:false`); SCC/#282 (T3 nonroot-v2); edge Route + LE (T3); NetworkPolicy (T3); plaintext-HTTP `connectHost` (T6/T7); big-bang 3-store rewrite keeping names (T7); PushSecret write-path verified (T7 S8); chicken-egg imperative seed (T4) + bootstrap edit (T8); remove SDK health-check override (T8); phased Ansible — op CLI seed (T4/T8) + `onepassword.connect` steady-state (T10); decommission + tune + measure (T9). All spec sections map to a task.
- **Placeholders:** `<PASTE_TOKEN…>` and `<KNOWN_ITEM>` are deliberate human inputs (a secret value and an operator-chosen vault item), not unfilled design gaps. No TODO/TBD.
- **Type/name consistency:** store names unchanged (`onepassword-sdk-ocp-pull`/`-ocp-push`/`onepassword-sdk-claude`); token Secret `onepassword-connect-token` (key `token`, ns `external-secrets-operator`) and credentials Secret `op-credentials` (key `1password-credentials.json`, ns `onepassword-connect`) referenced identically across T2/T4/T6/T7; `connectHost` identical in T6/T7.
- **Risk gates:** T6 smoke test must pass before T7; T7 S8 gives an explicit `git revert` rollback.
