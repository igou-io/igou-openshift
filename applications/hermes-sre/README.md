# hermes-sre — purpose-scoped Hermes for infrastructure inspection

Second `HermesInstance` (namespace `hermes-sre`), split from `hermes-k8s` per the
purpose-scoped plan (assistant / developer / sre). This one **monitors and
inspects**; it cannot change anything:

- Every Kata session pod carries the igou-devenv **`read-only` bundle**
  (ADR-0006): OCP + rk8s `cluster-read-only` SAs, RouterOS `mktxp` (`read,api`),
  TrueNAS `agent-ro` (`READONLY_ADMIN`). The bundle is an ExternalSecret rendered in
  the `envs/*.env` format into `/etc/agent/envs`; `AGENT_PROFILE=read-only` makes
  the baked `~/.bashrc.d/05-agent-profile.sh` activate it in every shell
  (`kubectl config get-contexts` → `ocp-cluster-reader`, `rk8s-cluster-reader`).
- GitHub via its own `ghbroker`, policy `contents:read` + `issues:write` only.
- Own Slack app "Hermes SRE" (tokens on `lab_agents/hermes-sre`), confined to
  `#igoucloud-hermes-sre` (`SLACK_ALLOWED_CHANNELS`) and DMs; no slash commands
  (Slack routes a command name to the most recently installed app workspace-wide, so
  only the assistant app registers them). Alertmanager investigations are delivered
  to that channel (`deliver: slack`). No Forgejo token, no GCP service accounts.
- Egress: the hermes-k8s allow-list plus the infra targets on their read-only ports
  (rk8s/OCP API 6443, RouterOS 8729, TrueNAS 443, *.apps routes 443).
- Own data PVC and workspace PVC (`repos/` is the shared `/workspace`; `home/`
  subtrees start empty —
  coding-CLI OAuth state is seeded or refreshed per instance with the
  scale-to-zero `auth-login` Deployment below).

## Refresh coding-CLI authentication

The `auth-login` Deployment uses the same `igou-devenv` image as terminal
sessions and mounts this instance's persistent workspace `home/` subtree as
its `HOME`. It normally has zero replicas. To refresh Cursor or Codex:

```bash
namespace=hermes-sre
oc -n "$namespace" scale deployment/auth-login --replicas=1
oc -n "$namespace" rollout status deployment/auth-login --timeout=5m
oc -n "$namespace" exec -it deployment/auth-login -- bash
```

Inside the shell, confirm the image and run the required device login:

```bash
command -v cursor-agent codex
NO_OPEN_BROWSER=1 cursor-agent login
cursor-agent status
codex login --device-auth
codex login status
exit
```

Only run the provider login that needs refreshing. The displayed URL/code is
completed in a browser on the operator's workstation. Always return the helper
to zero replicas afterward:

```bash
oc -n hermes-sre scale deployment/auth-login --replicas=0
```

Credentials persist on `hermes-workspace` and are immediately visible to new
terminal sessions. Codex is also shared with Hermes through `/opt/data/.codex`;
the `codex-auth-sync` sidecar keeps later single-use refresh-token rotations in
sync.

Shared with `hermes-k8s` (owned there): the operator (ns `hermes-operator`) and the
`hermes-agent-root` SCC. The instance keeps the same image, security context and
session PodSpec shape; diffs are the env/mounts above, `max_concurrent_sessions: 2`,
agent-container resources, and quick commands (`contexts`, `whoami`).

Context the SRE gets on top of the credentials (all delivered from this
directory, nothing hand-seeded on the PVC):

- `context-configmap.yaml` — `SOUL.md` (environment brief: where it runs, which
  CLI to reach for, the estate, report format) mounted over `/opt/data/SOUL.md`,
  and the same brief as `/workspace/AGENTS.md` for coding CLIs inside sessions.
- `skill-*-configmap.yaml` — the homelab skills mounted into
  `skills.external_dirs` (`/opt/data/agent-skills/homelab/`):
  `openshift-alert-triage`, `propose-fix`, `sre-sweeps` (the scheduled
  sweep procedures), `triage-domains` (storage/network/rk8s/change-correlation
  deep-dives, one skill with reference files to keep the skill index small)
  and `incident-reporting` (postmortem comments + runbook-gap issues on
  `igou-io/igou-docs` — issues survive that repo's `contents: read` cap).
  These operational skills are immutable and GitOps-owned. Agent-created skills
  live separately in the writable, PVC-backed `/opt/data/skills` directory.
- `docs-sync-cronjob.yaml` — read-only mirror of `igou-io/igou-docs` refreshed
  every 30 min into the workspace PVC (`/workspace/igou-docs` in sessions) using
  a broker-minted `contents:read` token (`igou-docs` is in the broker policy and
  must be on the igou-hermes App installation).
- `max_concurrent_sessions: 4` (alert webhooks are rejected, not queued, at the
  limit), `session_reset: idle 120 min`, and no Firecrawl configuration. Lazy
  installs remain disabled and search stays on SearXNG; issue #859 tracks baking
  the plugin into the pinned image before restoring `web_extract`.

Alert-path hardening (2026-08-30, second pass):

- `am-relay` requires the `hermes-sre-am-relay` bearer token on every POST
  (item `lab_rk8s/hermes-sre-am-relay`; mounted into alertmanager-main via
  cluster-monitoring-config `alertmanagerMain.secrets`) and answers **503**
  while Hermes is at `max_concurrent_sessions` — Alertmanager retries 5xx, so
  alerts queue upstream instead of being rejected. It reads the authoritative
  `active_agents` count that the gateway persists to its PVC-backed state file
  at every turn boundary; it does not rely on cross-container PID visibility.
- `am-relay-route.yaml` exposes the relay for the **rk8s** Alertmanager
  (igou-kubernetes `components/alertmanager-config`); `/healthz` is probed by
  the blackbox-exporter (`BlackboxProbeFailed` = watcher for the watcher).
- `heartbeat-cronjob.yaml` fires a synthetic `SREHeartbeat` through the full
  chain every Monday 09:00 America/New_York; no Slack report = the chain is
  broken.
- Incident memory: the agent reads/comments the EDA-filed issue in
  `igou-io/igou-inventory` per alert (skill step 0) and answers repeat
  firings from it; the OCP route also batches with `group_interval: 30m`,
  `repeat_interval: 12h`.

Propose-fix (2026-08-31): the broker ceiling is now `contents: write` +
`pull_requests: write` so the SRE can PROPOSE fixes as PRs (`propose-fix`
skill: clone, branch, delegate implementation to
`cursor-agent -p --force --trust --sandbox disabled --model cursor-grok-4.5-medium`
(Grok 4.5 medium, not fast), validate,
push, PR, link on the incident issue). Never merges — by contract (SOUL +
skill) AND by ruleset: every writable repo's `protect-default-branch`
ruleset carries a restrict-updates rule whose bypass list is repo-admin +
igou-dev + renovate, so GitHub refuses a default-branch update (= a merge)
by the igou-hermes App even though its token holds `contents: write`
(verified 2026-08-31; note `bypass_actors` reads as null without an
`administration`-scoped token). `default_permissions` stays
`contents: read`; write tokens exist only when a mint explicitly requests
them.

Scheduled sweeps (native Hermes cron): four jobs run in fresh isolated agent
sessions with the `sre-sweeps` skill, `/workspace` workdir, pinned
`openai-codex/gpt-5.6-luna` model at `high` reasoning, and direct delivery to
the SRE Slack channel. `cron.max_parallel_jobs: 1` serializes them. Manage them
with `hermes cron`; never patch `/opt/data/cron/jobs.json`. Issue #860 tracks a
future operator API for declarative reconciliation.

- `sre-sweep-daily-health` (07:00 America/New_York daily) — OADP/CNPG backup
  verification, ArgoCD drift, cert/CSR state, rk8s nodes. Watches for the
  failures that never fire an alert.
- `sre-sweep-hygiene` (Mon 09:30 America/New_York, after the heartbeat) — long-firing
  alerts, silences due a decision, the week's flappiest rules, and
  incident-memory grooming (proposes closure comments; EDA/human close).
- `sre-sweep-capacity` (Tue 09:00 America/New_York) — TrueNAS pools, fullest PVCs, node
  pressure, pending OLM updates.
- `sre-sweep-pr-followup` (Mon+Thu 10:30 America/New_York) — CI state of its own open
  PRs, review nudges, stale-proposal flags. Needs the broker's
  `checks`/`statuses: read` ceiling (policy change: roll the ghbroker
  Deployment — it reads policy at startup only).

The separate Kubernetes heartbeat still resolves through the skill
(`SREHeartbeat` section, per-hop OK/FAIL) because its purpose is testing the
external Alertmanager/relay path rather than merely scheduling agent work.

Follow-ups: own 1Password item for dashboard auth/API key (uses `hermes` today);
alert ingestion (Alertmanager webhook → api_server) so this instance monitors rather
than only answers; a ClusterRole for `hermes.agent` CRs if it should inspect Hermes.
