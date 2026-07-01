# AAP EDA Alertmanager to GitHub Issues Implementation Plan

> **For agentic workers:** This is a cross-repo plan. Implement one task at a
> time and verify after each meaningful unit. Do not overwrite existing dirty
> work in `igou-inventory` or `igou-ansible`.

**Goal:** Wire OpenShift Alertmanager alerts into AAP EDA so every selected
firing alert opens or updates a GitHub issue in `igou-io/igou-openshift`.

**Reviewed reference:** `/workspace/aap-aiops` implements the working pattern:
Alertmanager posts to an AAP EDA event stream; a rulebook activation matches
`status == "firing"`; EDA launches a controller job template; the playbook
deduplicates by alert identity and opens or comments on a GitHub issue.

**Target architecture:** Keep cluster alert routing in `igou-openshift`, keep
AAP object declarations in `igou-inventory`, and keep executable Ansible
content in `igou-ansible`. Use the existing platform Alertmanager config in
`components/alertmanager-config/alertmanager.yaml` rather than adding
per-namespace `AlertmanagerConfig` copies. Alertmanager fans out warning and
critical alerts to EDA with `continue: true`, so existing Gotify and Slack
receivers continue to work. EDA launches a controller job that files issues in
`igou-io/igou-openshift`.

**Important differences from `aap-aiops`:**

- `aap-aiops` is demo-first and mostly hand-applied. Here, OpenShift manifests
  should remain GitOps-managed in `igou-openshift`.
- `aap-aiops` stores AAP CaC in its own `casc/` tree. Here, AAP objects belong
  in `igou-inventory/group_vars/aap/` and are applied by
  `igou-ansible/playbooks/aap/configure-aap.yml`.
- `aap-aiops` routes through a namespace-scoped `AlertmanagerConfig`. Here,
  central `alertmanager-main` config is already owned in git, so that is the
  cleanest route for cluster-wide alert issue creation.
- `aap-aiops` uses manual Kubernetes Secrets. Here, use 1Password plus External
  Secrets for the Alertmanager event-stream token, and 1Password lookups for
  AAP credentials.

---

## Files Likely to Change

### `igou-ansible`

- Create `rulebooks/openshift_alertmanager_github_issue.yml`
- Create `playbooks/aap/open-github-issue-from-alert.yml`
- Optionally add docs under `docs/openshift-operations.md` or a new runbook if
  issue lifecycle needs operator guidance.

### `igou-inventory`

- Add `group_vars/aap/eda.yml`
- Modify `group_vars/aap/credential_types.yml`
- Modify `group_vars/aap/credentials.yml`
- Modify `group_vars/aap/projects.yml`
- Modify `group_vars/aap/job_templates.yml`
- Modify `group_vars/aap/labels.yml`

### `igou-openshift`

- Create `components/alertmanager-config/alertmanager-eda-event-stream-externalsecret.yaml`
- Modify `components/alertmanager-config/kustomization.yaml`
- Modify `components/alertmanager-config/alertmanager.yaml`
- Modify `components/user-workload-monitoring/cluster-monitoring-config-configmap.yaml`
- Modify `components/user-workload-monitoring/exporters/blackbox-exporter/blackbox-exporter-prometheusrule.yaml`
  only if the first rollout should be explicitly label-gated.
- Optionally update `docs/user-workload-monitoring.md` with the EDA incident
  routing convention.

---

## Design Decisions

1. **Route through platform Alertmanager.**
   `components/user-workload-monitoring/user-workload-monitoring-config-configmap.yaml`
   has UWM Alertmanager disabled, while
   `components/user-workload-monitoring/cluster-monitoring-config-configmap.yaml`
   enables user alert routing on `alertmanagerMain`. The existing
   `components/alertmanager-config/alertmanager.yaml` already owns Gotify and
   Slack routing, so add EDA there.

2. **Use fan-out, not replacement.**
   Add an EDA route before the severity routes with `continue: true`.
   Without `continue: true`, the first matching route would stop evaluation and
   existing Gotify/Slack delivery would be skipped.

3. **Start with warning and critical alerts, but allow a label gate if noise is
   too high.**
   The direct interpretation of "when an alert fires" is warning and critical
   alerts after current null routes and inhibition. If initial noise is too
   high, switch the EDA route matcher to `eda_github_issue = "true"` and add
   that label only to selected `PrometheusRule` objects.

4. **Deduplicate in the AAP playbook.**
   Alertmanager grouping and repeat intervals reduce volume, but the playbook
   must still be idempotent. Use one open issue per alert identity and comment
   on re-fires.

5. **Do not automate remediation in v1.**
   This mirrors the safe part of `aap-aiops`: collect context and create an
   incident record. Remediation can be added later through separate reviewed
   job templates or workflows.

---

## Task 1: Create the AAP Runtime Content in `igou-ansible`

**Files:**

- Create `rulebooks/openshift_alertmanager_github_issue.yml`
- Create `playbooks/aap/open-github-issue-from-alert.yml`

**Implementation notes:**

- Rulebook source should use `ansible.eda.webhook` as a placeholder, just like
  `aap-aiops/rulebooks/aiops_alertmanager.yml`; the rulebook activation will
  swap it to the EDA event stream.
- Rule condition: `event.payload.status == "firing"`.
- Rule action: `run_job_template` with `alert_payload: "{{ event.payload }}"`.
- The playbook should:
  - assert `alert_payload` exists;
  - process only `alert_payload.alerts` whose status is `firing`;
  - derive a stable issue title from `alertname` plus best available target
    labels: `namespace`, `pod`, `instance`, `job`, or `persistentvolumeclaim`;
  - list open GitHub issues with fixed labels such as
    `eda-alert` and `incident`;
  - match an existing issue by exact title;
  - create a new issue in `igou-io/igou-openshift` when none exists;
  - comment on the open issue when the alert re-fires;
  - publish `set_stats` artifacts containing issue URLs.
- Use a custom controller credential to inject `GITHUB_TOKEN` as an environment
  variable. Do not pass the token through extra vars.
- Include useful alert fields in the issue body: labels, annotations,
  `startsAt`, `generatorURL`, Alertmanager external URL, and AAP job ID.

**Verification:**

```bash
cd /workspace/igou-ansible
yamllint rulebooks/openshift_alertmanager_github_issue.yml playbooks/aap/open-github-issue-from-alert.yml
ansible-playbook --syntax-check playbooks/aap/open-github-issue-from-alert.yml
```

If the playbook uses modules or filters not available locally, run the syntax
check inside the same EE used by AAP.

---

## Task 2: Add AAP Objects in `igou-inventory`

**Files:**

- Add `group_vars/aap/eda.yml`
- Modify `group_vars/aap/credential_types.yml`
- Modify `group_vars/aap/credentials.yml`
- Modify `group_vars/aap/projects.yml`
- Modify `group_vars/aap/job_templates.yml`
- Modify `group_vars/aap/labels.yml`

**Objects to declare:**

- Controller label: `eda-alert`
- Controller credential type: `GitHub Token`
  - input: secret `token`
  - injector: `GITHUB_TOKEN`
- Controller credential: `igou-openshift-issues-github`
  - use a dedicated 1Password item with Issues read/write on
    `igou-io/igou-openshift`
- Controller job template: `openshift_alert_to_github_issue`
  - project: `igou_ansible`
  - playbook: `playbooks/aap/open-github-issue-from-alert.yml`
  - inventory: `igou_inventory`
  - execution environment: prefer `igou-aap-ee-rhel9`
  - credentials: `igou-openshift-issues-github`
  - `ask_variables_on_launch: true`
  - extra vars: `github_repo: igou-io/igou-openshift`
- EDA source control credential for `igou-ansible`
  - EDA has a separate credential store, so do not assume the controller
    `github` SCM credential is reusable.
- EDA AAP API credential for `run_job_template`
  - host must end with `/api/controller/`, matching the working `aap-aiops`
    pattern.
- EDA decision environment
  - use the supported RHEL decision environment image for the installed AAP
    version. Verify the correct image tag before committing; `aap-aiops` uses
    `registry.redhat.io/ansible-automation-platform-27/de-supported-rhel9:latest`.
- EDA event stream: `alertmanager`
  - token credential backed by the same value Alertmanager sends.
- EDA rulebook activation: `openshift-alertmanager-github-issue`
  - project: EDA `igou_ansible`
  - rulebook: `openshift_alertmanager_github_issue.yml`
  - `swap_single_source: true`
  - map source `alertmanager` to event stream `alertmanager`
  - credential: EDA AAP API credential
  - `enabled: true`
  - `restart_policy: on-failure`

**Secret handling:**

- Create a 1Password item for the event-stream token. Use the same item from:
  - AAP CaC, via `community.general.onepassword` lookup in `igou-inventory`;
  - ExternalSecret in `igou-openshift`, consumed by Alertmanager.
- Create or reuse a GitHub PAT item with only the permissions needed to create
  and comment on issues in `igou-io/igou-openshift`.

**Verification:**

```bash
cd /workspace/igou-inventory
yamllint group_vars/aap
ansible-inventory -i inventory.yaml --list >/dev/null

cd /workspace/igou-ansible
ansible-playbook -i /workspace/igou-inventory/inventory.yaml playbooks/aap/configure-aap.yml --check
```

Then apply for real from the normal AAP configuration workflow:

```bash
cd /workspace/igou-ansible
ansible-playbook -i /workspace/igou-inventory/inventory.yaml playbooks/aap/configure-aap.yml
```

After applying, retrieve the EDA event stream URL from the AAP EDA API and
store it in the same 1Password item as the event-stream token under property
`url`. Alertmanager reads that value through `url_file`, so the
server-generated UUID does not need to be committed to git.

---

## Task 3: Route Alertmanager to EDA in `igou-openshift`

**Files:**

- Create `components/alertmanager-config/alertmanager-eda-event-stream-externalsecret.yaml`
- Modify `components/alertmanager-config/kustomization.yaml`
- Modify `components/alertmanager-config/alertmanager.yaml`
- Modify `components/user-workload-monitoring/cluster-monitoring-config-configmap.yaml`

**ExternalSecret shape:**

- Namespace: `openshift-monitoring`
- Store: `onepassword-sdk-ocp-pull`
- Target secret: `alertmanager-eda-event-stream`
- Secret keys: `token` and `url`
- Remote item: the same 1Password event-stream token item used by AAP CaC.

**Kustomization change:**

- Add the new ExternalSecret resource.

**Cluster monitoring config change:**

- Add `alertmanager-eda-event-stream` to
  `components/user-workload-monitoring/cluster-monitoring-config-configmap.yaml`
  under `alertmanagerMain.secrets`, next to `alertmanager-slack-bot-token`.
  This mounts the token for Alertmanager as
  `/etc/alertmanager/secrets/alertmanager-eda-event-stream/token`, and the URL
  as `/etc/alertmanager/secrets/alertmanager-eda-event-stream/url`.

**Alertmanager config change:**

- Add a receiver named `eda-github-issue`.
- Add a route before the severity routes:

```yaml
    - matchers:
        - severity =~ "critical|warning"
      receiver: eda-github-issue
      continue: true
```

- Add the receiver:

```yaml
  - name: eda-github-issue
    webhook_configs:
      - url_file: /etc/alertmanager/secrets/alertmanager-eda-event-stream/url
        send_resolved: false
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/alertmanager-eda-event-stream/token
```

**Optional label-gated variant:**

If the first rollout should be quieter, use this route instead:

```yaml
    - matchers:
        - eda_github_issue = "true"
      receiver: eda-github-issue
      continue: true
```

Then add `eda_github_issue: "true"` to selected rules, starting with the
blackbox exporter rules in
`components/user-workload-monitoring/exporters/blackbox-exporter/blackbox-exporter-prometheusrule.yaml`.

**Verification:**

```bash
cd /workspace/igou-openshift
yamllint components/alertmanager-config components/user-workload-monitoring
make validate-kustomize
make validate-schemas
```

After Argo sync:

```bash
oc -n openshift-monitoring get secret alertmanager-eda-event-stream
oc -n openshift-monitoring get secret alertmanager-main -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | rg 'eda-github-issue|continue: true'
```

---

## Task 4: End-to-End Test

**Synthetic event-stream test first:**

1. Read the event stream URL from AAP EDA.
2. Read the event-stream token from 1Password or the OpenShift Secret.
3. POST a realistic Alertmanager v4 payload directly to the event stream.
4. Confirm the activation launches `openshift_alert_to_github_issue`.
5. Confirm a GitHub issue appears in `igou-io/igou-openshift`.
6. Re-post the same payload and confirm the existing issue gets a comment
   instead of opening a duplicate.

**Real alert test second:**

- Trigger a safe alert source, preferably a blackbox target or a temporary test
  `PrometheusRule`.
- Confirm Alertmanager still sends Gotify/Slack notifications.
- Confirm EDA receives the alert and opens or updates the issue.
- Confirm resolved notifications do not open issues in v1.

**Operational checks:**

```bash
# Activation is running
curl -sk -u "$AAP_USER:$AAP_PASS" "https://automation.apps.ocp.igou.systems/api/eda/v1/activations/" | jq

# Newest issue job status
curl -sk -u "$AAP_USER:$AAP_PASS" "https://automation.apps.ocp.igou.systems/api/controller/v2/jobs/?name__startswith=openshift_alert_to_github_issue&order_by=-id&page_size=1" | jq

# Alertmanager delivery failures
oc -n openshift-monitoring logs -l alertmanager=main -c alertmanager --since=30m | rg -i 'eda|webhook|failed|error'
```

---

## Rollback Plan

1. Remove or comment out the `eda-github-issue` route in
   `components/alertmanager-config/alertmanager.yaml`.
2. Let Argo sync Alertmanager config.
3. Disable the EDA activation in AAP if job launches continue from queued
   events.
4. Keep the job template and event stream objects in place for debugging unless
   the token is suspected compromised.

---

## Follow-Up Enhancements

- Add automatic close-or-comment behavior for resolved alerts after the firing
  path is stable.
- Add runbook URL mapping: if an alert has a known runbook in
  `docs/runbooks/`, include it prominently in the issue body.
- Add optional diagnostics collection for Kubernetes alerts with `namespace`
  and `pod` labels, using a read-only Kubernetes credential.
- Replace the PAT with a GitHub App token flow if long-lived PAT management
  becomes the weak point.
- Add a small test payload fixture in `igou-ansible` so syntax and idempotency
  can be tested without live Alertmanager.
