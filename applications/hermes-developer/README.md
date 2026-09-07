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

## Refresh coding-CLI authentication

The `auth-login` Deployment uses the same `igou-devenv` image as terminal
sessions and mounts this instance's persistent workspace `home/` subtree as
its `HOME`. It normally has zero replicas. To refresh Cursor or Codex:

```bash
namespace=hermes-developer
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
oc -n hermes-developer scale deployment/auth-login --replicas=0
```

Credentials persist on `hermes-workspace` and are immediately visible to new
terminal sessions. Codex is also shared with Hermes through `/opt/data/.codex`;
the `codex-auth-sync` sidecar keeps later single-use refresh-token rotations in
sync.
