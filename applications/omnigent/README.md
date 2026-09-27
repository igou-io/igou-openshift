# Omnigent SRE and first-party Slack integration

Issue [#1040](https://github.com/igou-io/igou-openshift/issues/1040) stages the
`igou-sre` agent, its four sweep prompts, and Omnigent v0.15.0's upstream
interactive Slack bot. No live cluster resources or Hermes schedules were
changed during implementation. The live
`omnigent` ArgoCD Application has automated sync: merging this PR can deploy
server, Secret, PVC, bot and NetworkPolicy changes. Before merging with
auto-sync active, complete the dedicated Slack app and 1Password item setup,
inventory and obtain approval to drain legacy sessions, then authorize GitOps
reconciliation. Otherwise establish and verify a deployment hold. Hermes keeps
its four production schedules, Slack app, alert relay, EDA and `SREHeartbeat` until a separately
approved cutover.

## Platform and credentials

The server keeps accounts authentication, `/opt/venv/bin` first on PATH, and
the direct `agent_sandbox` provider. Managed sessions use the pinned
`igou-devenv` host image, `opencode-go`, and the native idle/reaper lifecycle.
The `igou-sre` bundle has five skills and four domain references. ESO mounts
read-only OCP/rk8s, RouterOS and TrueNAS credentials into managed hosts, not
the Slack bot. The runner ServiceAccount token is disabled. The existing SRE
`ghbroker`, Squid and namespace-wide default-deny restrict classified and
unclassified runner Pods. The server-to-host and host-to-runner environment
allowlists preserve the proxy, broker and Git identity settings.

The separate `omnigent-slack` Deployment runs `omni integration slack` in the
foreground, one replica with `Recreate` strategy. It has no Kubernetes API
token, infrastructure credentials, public Route or inbound listener. Its only
network paths are DNS, Squid for Slack HTTPS/WebSocket traffic, and the
existing Omnigent HTTPS Route at `10.10.9.10:443`. The pinned bot image adds
the unmodified v0.15.0 upstream Slack package to the pinned server image; the
server image itself lacks that
optional package. A 1 Gi RWO PVC holds the upstream SQLite store and encrypted
per-user delegated tokens. Preserve the PVC and encryption key across restarts.
The bot's `OMNIGENT_SERVER_URL` uses the browser-accessible HTTPS Route for
both API calls and conversation links. The exact Route hostname bypasses
Squid through `NO_PROXY`/`no_proxy`; the bot's NetworkPolicy permits only
the verified router VIP on TCP 443 for that path. TLS verification stays on.
`OMNIGENT_DEVICE_GRANT_ENABLED=1` is set on the accounts
server, and both server and bot read the same device-client secret through
separate ESO targets. Slack bot/app tokens and the encryption key are consumed
only by the bot Pod. No Slack credential is mounted into a runner.

Before any deployment, create a **dedicated Omnigent Slack app** from upstream
[`slack-app-manifest.yaml`](https://github.com/omnigent-ai/omnigent/blob/v0.15.0/integrations/slack/deploy/slack-app-manifest.yaml).
It enables Socket Mode, interactivity, `/omnigent`, DMs and channel events.
Generate a `connections:write` app token, install the app and obtain its bot
token. Check `/omnigent` command ownership first; do not reuse the live Hermes
app or its Socket Mode tokens. Store the new tokens in the `lab_agents` item
`omnigent-slack` as `app-token` and `bot-token`; add a stable Fernet
`encryption-key` and a random `device-client-secret`. The item did not exist at
the 2026-09-27 read-only check; the ESO resources cannot become Ready until
these operator prerequisites are complete. Never put their values in Git,
commands, logs or PR text. The `onepassword-lab-agents` ClusterSecretStore uses
1Password Connect, and both ESO targets extract only their named fields.
Retire the old runner-namespace `omnigent-sre-slack` ExternalSecret from
desired state. Neither it nor its generated Secret existed at the 2026-09-27
read-only check. Reconfirm before any separately approved cleanup; leave the
Hermes backing item intact.

The bot package is built from the upstream v0.15.0 source archive pinned by
SHA-256 in `igou-containers/apps/omnigent-slack/Containerfile`. The
`igou-containers` workflow builds both supported architectures and publishes
the image to GHCR. Reproduce the build from that repository's root with:

```bash
podman build -t localhost/omnigent-slack:v0.15.0 apps/omnigent-slack
```

The Deployment pins the published GHCR multi-architecture manifest digest as
`ghcr.io/igou-io/omnigent-slack:latest@sha256:<digest>`. The `latest` tag lets
Renovate track digest updates while the digest fixes the deployed content.
The image is publicly pullable, so the bot does not need the Quay pull secret;
the Omnigent server still uses that secret for its own Quay image.

## Interactive setup

After approved deployment, invite the new Omnigent bot to the intended SRE
channel. In a DM or channel `@mention`, follow **Set up Omnigent** or run
`/omnigent`: authenticate with your own Omnigent account through the browser,
select `igou-sre`, and choose **Managed sandbox (agent_sandbox)**. The pinned
bot reads server managed-host support from `/v1/info`, so no permanent host is
needed. Each thread belongs to its initiating user. In a channel, `@mention`
the bot for both a new request and every follow-up in the thread. In a DM,
reply in the existing thread to continue its session; a new top-level DM
starts a separate session. Channel history scopes do not enable plain
unmentioned channel replies. The bot streams replies and supports
approval cards and multiple-choice questions; free-form questions open in the
web UI. `/omnigent logout` revokes delegated auth and clears setup. Account
permissions and Slack app/channel membership constrain participation; this
release has no dedicated bot allowlist to configure.

The bot is for interactive conversations only. It does **not** forward native
Automation results to Slack. Sweep findings remain in Omnigent conversations
and run history, and the agent must not recreate the removed Slack sender via
shell. Preserve Hermes reporting while its schedules remain active.

## Native sweep schedules

The Markdown files in `sweeps/` are prompt references. They are not
Kubernetes resources and ArgoCD/Omnigent does not import them. Under the
intended Omnigent user, use the native **Automations UI** to create and edit
the four tasks with agent `igou-sre`, `managed_sandbox` execution target and
`America/New_York` timezone:

| Task | Schedule | RRULE | Hermes predecessor |
| --- | --- | --- | --- |
| `SRESweepDailyHealth` | Daily 07:00 | `FREQ=DAILY;BYHOUR=7;BYMINUTE=0` | `sre-sweep-daily-health` |
| `SRESweepHygiene` | Monday 09:30 | `FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30` | `sre-sweep-hygiene` |
| `SRESweepCapacity` | Tuesday 09:00 | `FREQ=WEEKLY;BYDAY=TU;BYHOUR=9;BYMINUTE=0` | `sre-sweep-capacity` |
| `SRESweepPRFollowup` | Monday and Thursday 10:30 | `FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=10;BYMINUTE=30` | `sre-sweep-pr-followup` |

The v0.15.0 scheduled-task create API creates tasks **active by default**.
Do not create these schedules until the approved cutover unless the native UI
can create them paused and their stored `paused` state is verified. Do not use
a parking date or a custom registration helper. Native tasks live in the
Omnigent database, are user-owned and are managed manually in this phase.
Scheduled results stay in Omnigent; losing automatic Slack digests after a
future Omnigent-only cutover is an explicit limitation to accept separately.
The native scheduler does not replay missed fires and skips overlapping runs.

## Controlled validation and rollback

After approved deployment, confirm the active cluster and identity before
read-only inspection:

```bash
use ocp-cluster-reader
oc whoami --show-server
oc whoami
oc -n omnigent get deployment,externalsecret,pvc,networkpolicy
oc -n omnigent-sandboxes get sandbox,pod,externalsecret,networkpolicy
oc -n squid-proxy get networkpolicy
```

The 2026-09-27 read-only check found three running legacy `opencode-go-test`
Job Pods in `omnigent-sandboxes` and no NetworkPolicy there. Reconfirm before
acting; the new default deny would remove their network access. Inspect the
full effective policy set because allow policies are additive. Verify ESO
readiness, SCC admission, bot startup, Socket Mode connection, writable state
and state persistence across restart without plaintext delegated tokens.
Check that the upstream Slack SDK sends both HTTPS and WebSocket traffic via
Squid, and that the bot reaches the HTTPS Omnigent Route with valid TLS and
browser conversation links. Exercise `/omnigent` enrollment, login,
logout/re-enrollment, an `igou-sre` DM and
channel mention, thread continuation, streaming and approval/question cards.
Confirm the bot creates a real authenticated managed Sandbox and that runner
Pods have no Slack credentials.

Run each sweep manually in Omnigent and confirm a readable final conversation
with no Slack-tool call. Validate read-only infrastructure access, denied
mutations and proxy bypass, broker use, classified and unclassified runner
network behavior, busy-run continuity, idle Pod suspension, stale Sandbox
cleanup, credential refresh and server restart/misfire handling. Keep the
Hermes alerting and schedules unchanged during this validation. Only after
separate cutover approval should the four Hermes schedules be disabled and
Omnigent Automations created or activated; do not let both own the same
schedule. For rollback, pause Omnigent tasks, inspect active runs, then
restore only those four Hermes schedules. Retain historical conversations
and existing storage.

## Repository checks

```bash
make test
make validate-manifest-files
kustomize build --enable-helm applications/omnigent
kustomize build --enable-helm applications/squid-proxy
```
