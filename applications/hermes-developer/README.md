# hermes-developer — purpose-scoped Hermes for features and fixes

Successor of `hermes-k8s` for the **developer** purpose: changes to the igou-*
infrastructure repos and personal projects, delivered as PRs.

- Identity: ghbroker with the full write policy (13 repos, contents/issues/PRs),
  Forgejo token (mirrors), coding-CLI OAuth state on its own workspace `home/`
  subtree (seeded from hermes-k8s at cutover), opencode-go key, own Slack app "Hermes Developer" confined to
  `#igoucloud-hermes-developer` (no slash commands, see hermes-sre). No GCP, no cluster credentials — verification of infra changes goes through CI,
  ArgoCD and the read-only `hermes-sre` instance.
- No cron store; `agent-repos` is the full checkout set copied from hermes-k8s.

See `../hermes-sre/README.md` for the split and the sync-wave notes.
