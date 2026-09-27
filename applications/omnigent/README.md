# Omnigent SRE Automations

Issue [#1040](https://github.com/igou-io/igou-openshift/issues/1040) stages the
`igou-sre` agent and four native Omnigent Automations. No live change has been
made during implementation. The live `omnigent` ArgoCD Application has
automated sync enabled: merging this PR can immediately
reconcile its server, Secrets and NetworkPolicies even while the four native
Automations remain paused. Before merge, choose an approved path: inventory
and drain legacy sessions, then authorize GitOps reconciliation; or establish
and verify a deployment hold. Hermes retains all four production schedules,
alert relay, EDA, and `SREHeartbeat` until a separately approved cutover.

## Runner and credentials

The server uses the pinned Omnigent Kubernetes image and direct
`agent_sandbox` provider. The existing Agent Sandbox Operator serves
`agents.x-k8s.io/v1beta1`; its controller was Ready at the read-only
pre-change check. The provider creates a Sandbox in `omnigent-sandboxes`
using the pinned `igou-devenv` runner image. The existing nonroot SCC permits
the runner UID. The server has namespaced Sandbox create/get/patch/delete
rights. The runner ServiceAccount token remains disabled.
The server container keeps `/opt/venv/bin` first on PATH for its Python
entrypoint. The runner image uses its own `omnigent` launcher and OpenCode
binary; its login-shell startup resolves those paths separately.

Kustomize projects `agents/igou-sre/` into the server. Its five skills, four
triage references, and fixed-destination Slack tool travel in the agent
bundle. OpenCode uses `opencode-go` and `glm-5.3-flash`; the agent has an
80-iteration cap. ESO mounts the OCP/rk8s kubeconfigs, RouterOS/TrueNAS
read-only profiles, and the existing SRE Slack bot token as read-only files.
The provider's Secret mounts apply to every managed agent on this server,
so only trusted SRE agents may be seeded. No GitHub private key or runner
ServiceAccount token is mounted. The existing SRE `ghbroker`, Squid, and
NetworkPolicies constrain external access. A namespace-wide default-deny
covers classified and unclassified runner Pods; the `igou-sre` policy adds
only its needed destinations. The server passes selected proxy, broker and
Git identity variable names to the host, which forwards them to the runner
through `OMNIGENT_RUNNER_ENV_PASSTHROUGH`. ESO refreshes Secrets hourly;
mounted files update eventually, while the source OCP token still needs its
existing renewal publisher.

A native Automation produces a conversation and run record in Omnigent. The
model calls `post_sre_sweep_digest` once with a digest of at most 20 lines;
that tool sends only to `#igoucloud-hermes-sre` (`C0BTMS7AV34`). The tool
returns Slack's timestamp on confirmed delivery. If the agent fails before
calling the tool, Omnigent records a failed run but Slack has no independent
failure notification. An ambiguous Slack transport failure is not retried.
The digest may be a single line beginning `SRESweepName — all green:` or a
multiline report with the sweep name alone on its first line.

## Schedules and registration

`automations.yaml` and `sweeps/*.md` are the Git source for the four tasks.
Omnigent stores the registered tasks in its backed-up database as user-owned
records, not Kubernetes resources. The idempotent registration script uses a
human account login and always leaves tasks paused. It creates new tasks with
a recurrence starting in 2099, pauses them, then installs their real schedule;
this avoids an active initial fire. Never put that account password or session
token into a Kubernetes Secret, repository file, or command line.

| Task | America/New_York schedule | Hermes predecessor |
| --- | --- | --- |
| `SRESweepDailyHealth` | daily 07:00 | `sre-sweep-daily-health` |
| `SRESweepHygiene` | Monday 09:30 | `sre-sweep-hygiene` |
| `SRESweepCapacity` | Tuesday 09:00 | `sre-sweep-capacity` |
| `SRESweepPRFollowup` | Monday and Thursday 10:30 | `sre-sweep-pr-followup` |

After approved deployment, run from the `applications/omnigent` directory:

```bash
python3 scripts/register_automations.py
python3 scripts/register_automations.py --apply --user igou
```

The second command prompts for the human account password. It prints task IDs
and confirms `paused`. If registration stops mid-run, rerun it; existing tasks
are paused before any other update. A machine OAuth client cannot use the
scheduled-task API in this Omnigent version. Reconcile the definitions after
a Git edit; registration does not activate any schedule.

## Lifecycle and acceptance

`sandbox.keep_warm_s: 300` sets the runner idle timeout. The provider extends
its Sandbox shutdown deadline while work is active. After an idle runner
stops, the Agent Sandbox controller suspends the Pod; the Sandbox resource is
retained. The native reaper checks hourly and terminates offline managed hosts
older than seven days. No per-sandbox persistent HOME is configured;
conversation history stays in Omnigent while workspace files disappear on
Pod removal. These are expected upstream behaviors pending live validation.
They are not a hard timeout for an agent that remains busy. Native scheduling
also has a 30-second misfire grace, no replay after prolonged server downtime,
and overlap control only within each task.

After separately approved deployment, check the cluster and identity before
read-only inspection:

```bash
use ocp-cluster-reader
oc whoami --show-server
oc whoami
oc -n omnigent get deployment,externalsecret
oc -n omnigent-sandboxes get sandbox,pod,externalsecret
oc -n omnigent-sandboxes get networkpolicy
```

Before deploying the default deny, reconfirm the current legacy sessions and
drain them under the approved rollout plan. The read-only check on 2026-09-27
found three running `opencode-go-test` Job Pods in `omnigent-sandboxes`; they
will lose network access under the new policy. Existing network policies are
additive, so inspect the namespace's complete effective set. An unclassified
forked runner should have no ingress or egress while a classified SRE runner
receives only the listed allowances.

Verify ESO readiness, the v1beta1 CRD and operator, SCC admission, and the
real authenticated runner callback. With the tasks still paused, use each
task's **Run now** action in Omnigent. A 202 means accepted, not completed:
check the task's run history, linked conversation, final digest and Slack
timestamp. Confirm allowed read-only queries and denied mutations, proxy
and broker access from the actual runner, Slack delivery from the tool
subprocess, proxy bypass resistance, mounted credential refresh, server
restart behavior and missed-fire behavior. Observe a busy run remain active,
then an idle Pod
suspend after the warm period; verify retained Sandbox cleanup later and
conversation readability. No test may relax server authentication.

At an approved cutover, first disable only the four Hermes sweep schedules
and confirm they are inactive. Then activate the corresponding Omnigent
Automations in the UI or authenticated task API. Do not run both schedulers.
For rollback, pause the four Omnigent tasks, inspect in-flight runs, then
restore only the four Hermes schedules. Leave the alert/EDA/heartbeat path,
legacy PVCs and historical conversations intact.

## Repository checks

Run from the repository root. The image smoke check needs Podman and the
pinned images; it does not contact the cluster.

```bash
make test
make validate-manifest-files
kustomize build --enable-helm applications/omnigent
python3 -m unittest discover -s applications/omnigent/tests -v
python3 applications/omnigent/tests/smoke_runtime_images.py
python3 applications/omnigent/scripts/register_automations.py
```
