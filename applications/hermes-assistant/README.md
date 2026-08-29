# hermes-assistant — purpose-scoped Hermes for personal work

Successor of `hermes-k8s` for the **assistant** purpose: storescrape (grocery
flyers, sheets), sands-of-time (OSRS market), personal analysis, Slack Q&A. Takes
over the cron store, `agent-repos/storescrape`, `home/` CLI state, the shared Slack
app tokens and the `hermes-dashboard` hostname at cutover.

- Identity: Slack (after cutover), GCP `storescrape-sheets` SA, opencode-go key,
  ghbroker **read-only** (no repo writes from this instance). No Forgejo, no
  cluster credentials.
- Everything else mirrors `hermes-k8s` (Kata sessions, egress, sizes).

See `../hermes-sre/README.md` for the split and the sync-wave notes.
