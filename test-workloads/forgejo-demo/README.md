# Forgejo issue-to-PR demo

A disposable OpenShift Forgejo 16.0.5 instance, SQLite and Git repositories on one
5 GiB PVC, with Bash automation (curl, jq, git, tar, openssl). Deployment/reset also
need `oc` and `kustomize`. No operator, PostgreSQL, Ansible runtime, or CI runner.
The image is pinned by digest. HTTP Git is served through an HTTPS Route; SSH and
Actions are disabled. Self-registration is disabled.

## Deploy and seed

The default target is `https://api.ocp.igou.systems:6443`, namespace `forgejo-demo`,
URL `https://forgejo-demo.apps.ocp.igou.systems`. Activate your usual OCP credentials
first. Deployment needs permission to create a namespace and grant this service
account use of `nonroot-v2` (the rootless image runs as UID 1000).

```bash
cd /workspace/igou-openshift/test-workloads/forgejo-demo
./scripts/demo.sh deploy
./scripts/demo.sh seed
```

By default, `fixtures/collection` supplies `demo.greetings`, generated with
`ansible-galaxy collection init` (ansible-core 2.21.4). Its `nginx` role installs
and starts nginx on Rocky Linux 9. The UID request in `fixtures/nginx-uid-issue.md`
is the agent task. No external checkout is required.

To use a real collection, export `COLLECTION_SOURCE=/path/to/collection-checkout`.
Choose a collection with no tracked secrets. For a remote collection, clone
it locally first using that host's normal authentication. The snapshot excludes Git
history and untracked files, but includes all tracked files. The source checkout is
never modified. Seed preserves populated repositories and restores each demo password to its username.
Use reset when you need to remove demo changes and reproduce the baseline. Keep the
source checkout at the same commit for repeatable resets.

`seed.json` declares users, repository names and write collaborators. The default is:

- `demo-owner`: maintainer, owns `ansible-collection-demo` and `demo-notes`.
- `demo-agent`: write collaborator on the collection, able to push branches and open PRs.
- `demo-reviewer`: write collaborator on both repositories.
- `demo-admin`: separate bootstrap administrator.

Each repository may have a `source` pointing to a local Git checkout. The default
collection uses `COLLECTION_SOURCE`; other repos without a source get a README.
The default lifecycle token and webhook commands assume these default user/repo names.
If changing them, adjust those commands too.

For this private demo, every password equals the username: `demo-admin`,
`demo-owner`, `demo-agent`, and `demo-reviewer`. Deploy/seed restores these defaults.
No password files or password environment variables are needed.

Generated API credentials are stored in ignored, private `.state/` files:
`admin-token` and `agent-token`. Give the agent only `agent-token`, the instance URL, and
`demo-owner/ansible-collection-demo`. Its scopes are `write:repository`, `write:issue`,
and `read:user`, constrained by the user's collaborator permissions. These are
standalone demo identities, not lab identities.

For another OpenShift cluster, edit the Route host and deployment `ROOT_URL`, and
export matching `FORGEJO_URL` and `EXPECTED_SERVER`. PVC uses the default storage
class. For vanilla Kubernetes, omit the Route and SCC Role/RoleBinding, supply your
own ingress, and use an allowed UID/GID and storage configuration.

## Configure the integration, then open the issue

Use a receiver reachable **from the Forgejo pod**. `localhost` on your laptop is
not reachable as the pod's localhost. Private network destinations are allowed;
add a specific hostname to `FORGEJO__webhook__ALLOWED_HOST_LIST` if needed.

```bash
export FORGEJO_URL=https://forgejo-demo.apps.ocp.igou.systems
export FORGEJO_TOKEN="$(cat .state/admin-token)"
export WEBHOOK_URL=https://your-agent-receiver.example/events
# Generate once; configure the same secret in the receiver.
(umask 077; openssl rand -hex 32 > .state/webhook-secret)
export WEBHOOK_SECRET="$(cat .state/webhook-secret)"
./scripts/webhook.sh demo-owner/ansible-collection-demo "$WEBHOOK_URL"

./scripts/create-nginx-uid-issue.sh
```

The webhook subscribes to every repository event supported by the pinned Forgejo
version: pushes, branches/tags, forks, all issue and PR events (including reviews),
wiki, repository, releases, packages and Actions outcomes. Actions outcomes require
Actions to be enabled separately. Forgejo's API has no wildcard. The event list
should be reviewed on a version upgrade.

Running `webhook.sh` again replaces hooks with the **same URL**, preserving other
integrations. It creates the replacement first; if deleting an old hook fails,
rerun to remove duplicates. Briefly overlapping hooks are possible during replacement.
A different URL adds an integration; remove a retired destination in the UI.

The receiver should verify the `X-Forgejo-Signature` HMAC-SHA256 over the raw body,
filter `X-Forgejo-Event: issues` with action `opened`, and deduplicate deliveries.
Ignore the agent's subsequent push/PR/comment events as task triggers to avoid loops.
The agent service itself is external to this bundle. OAuth, SMTP and CI runners are
not configured. Inspect webhook delivery history under repository Settings → Webhooks.

Setting `WEBHOOK_URL` and `WEBHOOK_SECRET` during seed/reset restores that integration
automatically. Issue creation is deliberately separate and creates a new issue on each
invocation, so a reset does not launch the agent before you are ready.

## Reset

Stop any external agent run before reset. This command deletes the **demo PVC**,
recreates Forgejo, and seeds the users/repos again:

```bash
export WEBHOOK_SECRET="$(cat .state/webhook-secret)"
# Keep WEBHOOK_URL exported to restore the integration.
./scripts/demo.sh reset --confirm-forgejo-demo
export FORGEJO_TOKEN="$(cat .state/admin-token)"
```

All demo repositories, issues, PRs, users, tokens, hooks and app configuration are
recreated. Passwords return to the usernames; admin and agent tokens rotate.
Update the external agent's token after reset. The webhook secret stays the same.
This touches only `forgejo-demo`, not the lab's `forgejo` namespace. The script checks
cluster URL and the demo namespace label before deleting anything. A storage class
with `Retain` reclaim policy can leave old PVs behind; reset is not secure erasure.
Do not register this disposable deployment with auto-sync unless its reset behavior
is coordinated with that controller.

## Using the scripts with another Forgejo

`seed.sh`, `webhook.sh` and `issue.sh` use `FORGEJO_URL` and `FORGEJO_TOKEN` directly.
Seed needs an admin token; `COLLECTION_SOURCE` is optional. The lifecycle
wrapper is the only part that invokes `oc`. User/repo seed is additive, not full
configuration reconciliation. All failures return nonzero without printing API
response bodies or credentials. Don't run these scripts with shell tracing.

## Verification

```bash
(cd scripts && shellcheck -x *.sh ../tests/*.sh)
kustomize build manifests | kubeconform -strict -summary -skip Route
```

`tests/integration.sh CONTAINER_NAME` targets a fresh disposable Docker Forgejo
container with the same image and install-lock/SQLite settings. Set `FORGEJO_URL`
to its local HTTP endpoint and optionally `COLLECTION_SOURCE` to a real collection checkout (defaults to the fixture).
It creates an admin, seeds twice, checks users/repos/permissions, creates an issue,
then uses the agent's scoped token to commit and open a PR.
It intentionally creates demo state; never point it at a real instance.

Verified locally with Forgejo 16.0.5: repeated seed and scoped agent PR.
The nginx role passed its Molecule scenario and the collection build passed.

Live OpenShift deployment, HTTPS Route, storage, signed webhook delivery, agent Git
push/PR permissions, and PVC reset were verified on 2026-09-25. See [VALIDATION.md](VALIDATION.md).
For repeatable API tests, use `tests/integration.sh --existing` against a freshly
seeded demo. Connect your agent endpoint with `scripts/webhook.sh` when ready.

Keep the deploying checkout's `.state/` when moving this bundle to another checkout:
it holds the generated API tokens and webhook secret.

References: [Forgejo Docker installation](https://forgejo.org/docs/v16.0/admin/installation/docker/),
[API schema](https://code.forgejo.org/swagger.v1.json),
[pinned webhook implementation](https://code.forgejo.org/forgejo/forgejo/src/tag/v16.0.5/routers/api/v1/utils/hook.go).

## nginx UID feature-request demo

The seeded collection contains `demo.greetings.nginx`, a Rocky Linux 9 role
that installs and starts nginx with its package-provided worker account. Its
Molecule scenario checks HTTP 200, worker ownership, and idempotence.

After configuring your agent webhook, open the UID feature request with:

```bash
./scripts/create-nginx-uid-issue.sh
```

The script defaults to the demo URL and reads `.state/admin-token` unless
`FORGEJO_URL`/`FORGEJO_TOKEN` are exported. Optionally pass another `owner/repo`.
Each invocation creates a new issue, so it can trigger the connected agent. The
request in `fixtures/nginx-uid-issue.md` covers default behavior, custom UID, UID
changes/conflicts, writable paths, worker identity, HTTP availability and tests.
UID configuration is intentionally left for the agent to implement.
