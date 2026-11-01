# hermes-assistant — purpose-scoped Hermes for personal work

Successor of `hermes-k8s` for the **assistant** purpose: storescrape (grocery
flyers, sheets), sands-of-time (OSRS market), personal analysis, Slack Q&A. Takes
over the cron store, `agent-repos/storescrape`, `home/` CLI state, the shared Slack
app tokens and the `hermes-dashboard` hostname at cutover.

- Identity: Slack (after cutover), Google Drive through the private MCP service, opencode-go key,
  ghbroker **read-only** (no repo writes from this instance). No Forgejo, no
  cluster credentials.
- External HTTP/HTTPS from the Hermes agent and its generated sessions uses the
  shared cluster-local Squid proxy. `NO_PROXY` keeps the Kubernetes services,
  model endpoints, broker and other internal dependencies on direct paths.
  NetworkPolicy denies generic direct Internet access, so HTTP-aware clients
  must honor the proxy environment.
- Everything else mirrors `hermes-k8s` (regular Kubernetes sessions, egress, sizes).

See `../hermes-sre/README.md` for the split and the sync-wave notes.

## Google Drive

The main assistant connects to Piotr Agier's Google Drive MCP server at
`http://google-drive-mcp.hermes-assistant.svc.cluster.local:3100/mcp` through
`spec.config.raw.mcp_servers.gdrive`. The server runs as its own Deployment;
NetworkPolicy admits only the main assistant pod and sends external traffic
through Squid. No public Route is created.

External Secrets reads the `igou-gdrive-automation.json` document from
`lab_external_api_keys/igou-gdrive-automation`. The key is mounted only into
the MCP pod. It is not exposed to Hermes or its terminal session pods.

Google sharing grants the service account Editor access to the `hermes` folder
(`1d-peZiX5um4ivyx9XZ3eF73ffLtMP6s0`) and its descendants. There is no server-side
folder allowlist: the account can access anything subsequently shared with it.
The assistant can edit existing spreadsheets, including `hermes/test_sheet`.
The user creates files in My Drive because service accounts cannot own them.

The storescrape procedure in `storescrape/SKILL.md` is delivered by a generated
ConfigMap as a read-only skill under
`/opt/data/agent-skills/homelab/storescrape`. Scheduled grocery and chicken-thigh
scans use `gdrive` MCP tools to update `hermes/meat-prices-23236`
(`1cM4iq_iJyNS9peZvMSK9-kWqssUfupBEW-ERukle7Ss`) before delivery. Writes preserve
historical rows and upsert by scan date, category, cut and merchant, with readback
verification. The retired key-based helper and terminal credential mount are
removed; the only Google credential belongs to the MCP pod.

`storescrape/cron-jobs.json` holds the two meat-scan jobs' prompts and explicit
toolsets. Apply these payloads to the existing native cron store with
`cron.jobs.update_job`; retain IDs, schedules, enabled states, and delivery
settings. The paused generic daily job and soda report retain their behavior.
