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
- Static checks: full repository `make test`, ShellCheck, fixture unit tests and
  Galaxy collection build passed.

A receiver Secret populated directly from `openssl rand -hex` output initially
contained a trailing newline while the API secret did not. The receiver runbook
strips that newline during Secret creation. Corrected delivery was verified before
completion.

The final reset leaves users/repos seeded, no issues or PRs, and the test receiver
connected. It logs events only; configure your real agent receiver before opening
`fixtures/issue.md`. Credentials stay in the deploying checkout's ignored `.state/`.
When moving to another checkout, securely move that state directory too; it holds the generated API tokens and webhook secret.
All four demo account passwords equal their usernames; seed restores these defaults.
No existing lab Forgejo resources were changed, and no ArgoCD application was added.

Password simplification: all four username/password logins passed against the live
instance after two seed runs. A fresh-container integration run also passed new-user
creation, repeated seed, password authentication, hooks, issues and an agent PR.

## Galaxy scaffold and issue-opened webhook check

Regenerated `demo.greetings` with `ansible-galaxy collection init demo.greetings`
using ansible-core 2.21.4. Kept the generated metadata/runtime templates and plugin
guide; filled in demo metadata and retained the greeting filter/tests as sample
content. The fixture and live repository now share that scaffold. Collection build
and all three unit tests passed, as did repository `make test` and ShellCheck.

`tests/issue-webhook.sh` opened real issues and correlated signed deliveries by
repository, issue number, event and action. The final run matched issue #3:

```json
{"event":"issues","action":"opened","repository":"demo-owner/ansible-collection-demo","issue":3,"delivery":"0809ea53-9d49-460d-a9b6-27cc0b915b2e","signature_verified":true}
```

The receiver returned HTTP 401 for a deliberately invalid signature. An initial
checker run missed its event because `oc logs --all-pods` prefixes log lines; the
checker now reads the single-replica deployment's JSON logs and passed on rerun.
Verification issues #1–#3 are closed and retained as evidence; the repository was
updated by a normal commit, with no reset or token rotation in this change.
