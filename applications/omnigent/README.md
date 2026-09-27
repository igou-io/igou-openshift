# Omnigent SRE runners

Omnigent at <https://omnigent.apps.ocp.igou.systems> hosts the GitOps-owned
`igou-sre` agent. New managed SRE sessions use the direct `kubernetes` provider:
Omnigent creates one Job in `omnigent-sandboxes` per session. The server image
is the upstream Kubernetes build at the digest in `omnigent-deployment.yaml`;
the Job uses the pinned `igou-devenv` image in
`omnigent-sandbox-config-configmap.yaml`. The server keeps its one replica,
CNPG history, artifact PVC, account authentication and Route.

The five operational skills and four triage reference files live in
`agents/igou-sre/`. Kustomize generates `omnigent-sre-bundle`; the server
projects it at `/etc/omnigent/igou-sre` and seeds the built-in agent. The
pinned Omnigent `materialize_bundle` path packages those skills into the
runner session. `executor` pins OpenCode, `opencode-go`, and
`glm-5.3-flash`. The four sweep prompts live in `sweeps/` and the shared
finite client in `scripts/sweep_client.py`.

The devenv image contains Omnigent 0.15.0 and OpenCode 1.18.31. The runner
passes an explicit `PATH` to reach the real OpenCode binary and read-only
helper CLIs. Omnigent fixes its Job UID/GID at `1000660000`, which has no
passwd entry in this image; Git author, committer and login names are
supplied as nonsecret environment values so proposal commits work.

## Credentials and boundaries

ESO reads existing 1Password items into `omnigent-sandboxes` Secrets. The
runner mounts OCP and rk8s kubeconfigs, RouterOS and TrueNAS read-only
profiles as read-only Secret volumes under `/mnt/credentials`. Its
ServiceAccount token is not mounted. OCP's API uses a publicly trusted
certificate; the rk8s kubeconfig embeds the verified `k3s-server-ca` from
the cluster's `kube-root-ca.crt`. The endpoints and context names are pinned
in the ExternalSecret templates. The OpenCode Go key comes from the existing
`omnigent-creds` Secret as environment data.

ESO refreshes the Kubernetes Secret from 1Password hourly. Mounted files
update eventually and each use must reread them; the mount uses no
`subPath`. Environment credentials update only when a new Pod starts. ESO
does not renew the source service-account token in 1Password; retain the
existing publisher and verify its renewal separately. The sweep client gets
only its Omnigent OAuth secret and the existing SRE Slack bot token in
`omnigent`, not estate kubeconfigs. Machine tokens last 300 seconds; the
client mints a fresh token before expiry.

The SRE GitHub broker remains in `hermes-sre`. Its ingress policy admits only
`igou-sre` runner Pods from `omnigent-sandboxes`; no GitHub private key is
mounted. Runner/client NetworkPolicies deny inbound traffic and allow only
DNS, the required internal endpoints, and Squid for public HTTP/HTTPS.
The existing read-only service-account roles are the infrastructure authority
boundary. Logs and readable objects may still contain sensitive data; keep
investigation output bounded and never print mounted credential files.

The Kubernetes provider's `secret_mounts` setting applies to every Job it
launches. This Omnigent deployment should be treated as an SRE-only runner
until upstream provides agent-scoped mounts; do not offer generic or
untrusted agents on this backend. The old `opencode-go-test` and
`codex-chatgpt` bundles are no longer seeded. Historical conversations remain
in the database. Do not register generic or untrusted agents on this backend
while mounts are provider-wide.

## Schedules and reporting

All four new CronJobs start **suspended**. They use `America/New_York`,
`concurrencyPolicy: Forbid`, a 900-second starting deadline, a 3600-second
client deadline, no Job retries, and bounded history. The shared Lease
`omnigent-sre-sweeps` serializes different CronJobs and manual launches.
An expired Lease never lets a second run start until cleanup verifies the
old session and host.

| Hermes name | Omnigent CronJob | Local schedule | Procedure |
| --- | --- | --- | --- |
| `sre-sweep-daily-health` | `omnigent-sre-sweep-daily-health` | daily 07:00 | `SRESweepDailyHealth` |
| `sre-sweep-hygiene` | `omnigent-sre-sweep-hygiene` | Monday 09:30 | `SRESweepHygiene` |
| `sre-sweep-capacity` | `omnigent-sre-sweep-capacity` | Tuesday 09:00 | `SRESweepCapacity` |
| `sre-sweep-pr-followup` | `omnigent-sre-sweep-pr-followup` | Monday and Thursday 10:30 | `SRESweepPRFollowup` |

The client creates a run-keyed session, waits for runner readiness, submits
one named prompt, and waits for a committed final assistant item and idle
status. It reports exceptions only to the existing SRE channel
`#igoucloud-hermes-sre` (`C0BTMS7AV34`) with the existing bot. An empty
response, 403 that prevents a check, blocked approval, model error, or
missing credential cannot become an all-green result. It records delivery
state and Slack message timestamp on the session before archiving the
conversation. An ambiguous Slack failure is reported without an automatic
repost.

The cleanup-only CronJob runs every five minutes. It reads only the
machine-owned, run-keyed session recorded in the Lease, archives an expired
run, checks the retained transcript, then deletes only the matching host Job
and its launch-token Secret. A separate ServiceAccount has those narrowly
scoped deletion rights. The client releases the Lease after cleanup
acknowledges. If the client dies, the 120-second Lease expiry plus the
five-minute cleanup cadence target recovery within 30 minutes of the run
deadline. The upstream seven-day Job limit remains a last-resort backstop.
A failure of cleanup leaves the Lease held and the next sweep fails closed.

## Run now and inspect

Before running a sweep, verify the cluster and identity. A manual run uses
the existing CronJob template while its schedule remains suspended:

```bash
use ocp
oc whoami --show-server
oc whoami
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
oc -n omnigent create job --from=cronjob/omnigent-sre-sweep-daily-health \
  "omnigent-sre-sweep-daily-health-manual-${run_id,,}" \
  --dry-run=client -o json |
  jq --arg id "$run_id" '.spec.template.spec.containers[0].command += ["--manual-id", $id]' |
  oc -n omnigent apply -f -
oc -n omnigent get jobs,pods -l app=omnigent-sre-sweep-client
oc -n omnigent-sandboxes get jobs,pods -l omnigent.ai/agent=igou-sre
```

The manual ID keeps an out-of-band run distinct from a scheduled occurrence.
Check client
Job logs for a session ID and Slack timestamp, then open that session from
the human `igou` account under **Shared with me / Archived**. A successful
HTTP 202 or runner connection alone is not completion. For a failed Job,
read its bounded logs, the session status/items, the cleanup Job, and the
Lease; never delete a host Job by label alone. The cleanup job may need a
manual rerun through its CronJob template after the cause is repaired.

## Cutover and rollback

The draft PR does not authorize deployment, production activation or Hermes
teardown. Before merging, inventory and drain old OpenShell sessions and
their credential PVCs. Removing old OpenShell manifests from Kustomize does
not delete live resources because automatic pruning is disabled; any later
retirement is a separate, narrowly scoped operation. Shared OpenShell and
all legacy PVCs remain untouched.

After approved deployment, verify ESO Ready, SCC admission for both Job
containers, credential reads, blocked writes and network paths. Test one
manual run of each sweep and its Slack report and transcript. Check native
Hermes cron metadata read-only to confirm schedules and destination. At an
approved cutover, disable only the four Hermes-native jobs through its CLI
or API and record their IDs; then change these four CronJobs to
`suspend: false` in Git. Never run both schedulers concurrently.

To roll back, suspend the four Omnigent schedules first, stop and verify
their in-flight managed runs, then re-enable the four original Hermes jobs.
Leave Omnigent transcripts, all legacy PVCs, Hermes alert relay, heartbeat,
operator and other personas intact. `SREHeartbeat` continues to test the
separate Hermes alert path throughout this migration.

## Validation

```bash
make test
make validate-manifest-files
kustomize build --enable-helm applications/omnigent
.venv/bin/python -m unittest discover -s applications/omnigent/tests -v
```
