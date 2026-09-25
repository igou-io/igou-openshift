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
When moving to another checkout, securely move that state directory too; do not
regenerate password files for existing users (seed intentionally preserves passwords).
No existing lab Forgejo resources were changed, and no ArgoCD application was added.
