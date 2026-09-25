# Live validation — 2026-09-25

Tested on `https://api.ocp.igou.systems:6443` in the dedicated `forgejo-demo`
namespace, with the pinned Forgejo 16.0.5 image and default NVMe-oF SSD storage.

- Deployment: namespace, SCC binding, service, PVC and HTTPS Route applied;
  deployment became Ready and bootstrap admin/token creation succeeded.
- Seed: repeated runs kept four users (including admin), two repositories, the
  collection baseline, and agent/reviewer write permissions.
- Agent: scoped token could clone over HTTPS, push a feature branch, create a
  commit through the API, and open a PR as `demo-agent`.
- Webhooks: repeated configuration left one hook; receiver verified raw-body
  HMAC-SHA256 signatures and logged `issues opened`, `pull_request opened`,
  `create`, and `push`. This checks Forgejo delivery, not an external agent service.
- Reset: the old PVC was deleted and a new UID provisioned; all test issues, PRs
  and feature branches disappeared; only `main` remained; webhook configuration
  was restored. Tokens rotated and the old agent token returned HTTP 401.
- Static checks at initial validation: full repository `make test`, ShellCheck,
  and Galaxy collection build passed.

The test receiver and its hook were removed after validation at the user's request.
Configure your real agent receiver before opening a feature request. Credentials stay in the deploying checkout's ignored `.state/`.
When moving to another checkout, securely move that state directory too; it holds the generated API tokens and webhook secret.
All four demo account passwords equal their usernames; seed restores these defaults.
No existing lab Forgejo resources were changed, and no ArgoCD application was added.

Password simplification: all four username/password logins passed against the live
instance after two seed runs. A fresh-container integration run also passed new-user
creation, repeated seed, password authentication, hooks, issues and an agent PR.

## Galaxy scaffold and past webhook validation

Regenerated `demo.greetings` with `ansible-galaxy collection init demo.greetings`
using ansible-core 2.21.4. Collection build passed.

Before removing the optional test receiver, issues #1–#3 produced signed
`issues/opened` deliveries matching their repository and issue numbers. The
receiver rejected a deliberately invalid signature with HTTP 401. These issues
are closed; the test hook and receiver are no longer deployed.

## nginx role and UID feature request

Added `demo.greetings.nginx`, scaffolded with ansible-creator. During development,
the role passed package/service convergence, second-run idempotence, HTTP 200,
worker identity, and cleanup checks in a Rocky Linux 9 container. The disposable
test harness was subsequently removed from the demo collection. Ansible lint and
the collection build passed.

On a separate disposable Forgejo, seeding included the role and
`scripts/create-nginx-uid-issue.sh` created the expected feature request, including
custom UID 1500, migration to 1501, conflict handling and functional acceptance
criteria. This feature request was not opened on the live demo; run the script when
the real agent webhook is ready. The role is updated in the live collection; UID
configuration remains the task for the agent.
