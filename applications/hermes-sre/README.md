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
- Own data PVC and workspace PVC (`repos/` unused; `home/` subtrees start empty —
  coding-CLI OAuth state must be seeded per instance, see gaps).

Shared with `hermes-k8s` (owned there): the operator (ns `hermes-operator`) and the
`hermes-agent-root` SCC. The instance keeps the same image, security context and
session PodSpec shape; diffs are the env/mounts above, `max_concurrent_sessions: 2`,
agent-container resources, and quick commands (`contexts`, `whoami`).

Context the SRE gets on top of the credentials (all delivered from this
directory, nothing hand-seeded on the PVC):

- `context-configmap.yaml` — `SOUL.md` (environment brief: where it runs, which
  CLI to reach for, the estate, report format) mounted over `/opt/data/SOUL.md`,
  and the same brief as `/workspace/AGENTS.md` for coding CLIs inside sessions.
- `skill-alert-triage-configmap.yaml` — `openshift-alert-triage` skill mounted
  into `skills.external_dirs` (`/opt/data/agent-skills/homelab/`).
- `docs-sync-cronjob.yaml` — read-only mirror of `igou-io/igou-docs` refreshed
  every 30 min into the workspace PVC (`/workspace/igou-docs` in sessions) using
  a broker-minted `contents:read` token (`igou-docs` is in the broker policy and
  must be on the igou-hermes App installation).
- `max_concurrent_sessions: 4` (alert webhooks are rejected, not queued, at the
  limit), `session_reset: idle 120 min`, and no firecrawl plugin (lazy installs
  are disabled, so `web_extract` could never work; search stays on SearXNG).

Follow-ups: own 1Password item for dashboard auth/API key (uses `hermes` today);
alert ingestion (Alertmanager webhook → api_server) so this instance monitors rather
than only answers; a ClusterRole for `hermes.agent` CRs if it should inspect Hermes.
