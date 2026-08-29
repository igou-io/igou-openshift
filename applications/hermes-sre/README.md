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
- No Slack socket (the shared Slack app stays on the interactive instance; reports
  go out via webhook), no Forgejo token, no GCP service accounts.
- Egress: the hermes-k8s allow-list plus the infra targets on their read-only ports
  (rk8s/OCP API 6443, RouterOS 8729, TrueNAS 443, *.apps routes 443).
- Own data PVC and workspace PVC (`repos/` unused; `home/` subtrees start empty —
  coding-CLI OAuth state must be seeded per instance, see gaps).

Shared with `hermes-k8s` (owned there): the operator (ns `hermes-operator`) and the
`hermes-agent-root` SCC. The instance keeps the same image, security context and
session PodSpec shape; diffs are the env/mounts above, `max_concurrent_sessions: 2`,
agent-container resources, and quick commands (`contexts`, `whoami`).

Follow-ups: own 1Password item for dashboard auth/API key (uses `hermes` today);
alert ingestion (Alertmanager webhook → api_server) so this instance monitors rather
than only answers; a ClusterRole for `hermes.agent` CRs if it should inspect Hermes.
