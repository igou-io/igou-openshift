---
name: propose-fix
description: Turn a confident infrastructure diagnosis into a small declarative pull request for human review.
version: 2.0.0
author: igou-io
platforms:
  - linux
metadata:
  igou:
    tags:
      - sre
      - git
      - pull-request
---

# Propose a fix

Use this only after diagnosing a concrete failure. The change must be small,
declarative and tied to evidence. If uncertain, report the diagnosis on the
existing incident issue instead. Live infrastructure remains read-only.

Hard rules: never merge, approve or close a PR; never update a default branch,
force-push, or combine unrelated concerns. A human reviews and merges.

## 1. Fetch and branch

Choose the exact repository, then fetch into this disposable workspace using
the existing SRE GitHub broker. Do not put a token in a clone URL or Git
remote. Record the base revision and create `sre/<short-slug>` from the
repository's default branch. `igou-kubernetes` uses `master`.

```bash
REPO=igou-io/igou-openshift
cd /home/omnigent
export GHAPP_BROKER_URL=http://ghbroker.hermes-sre.svc.cluster.local:8085
git clone "https://github.com/${REPO}.git" work
cd work
git rev-parse HEAD
git switch -c sre/<short-slug>
```

## 2. Implement with the configured OpenCode harness

Write the smallest change yourself in this session. Follow that repository's
`AGENTS.md`, use block-style YAML, and do not change controller-owned live
objects. Read `git diff` before validating. There is no Hermes process tool,
Cursor delegation, or subscription login in this runtime.

## 3. Validate

Run the repository's relevant tests, including `make test` for
`igou-openshift`; render changed Kustomize directories with `--enable-helm`.
If validation fails, fix the change before opening a PR. Keep secrets out of
the diff and output.

## 4. Push the proposal

Mint only the requested broker permissions. Keep the token in process memory,
never in the remote URL, command output, a file, or the PR body. Use a
temporary askpass helper that reads `GH_TOKEN` from the environment; remove
it after the push. Open a draft PR with the incident link, diagnosis,
verification and human-review request. Do not merge it.

```bash
export GH_TOKEN=$(ghapp token --repo "$REPO" --permission contents=write --permission pull_requests=write)
cat > /tmp/igou-sre-askpass <<'SH'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' x-access-token ;;
  *) printf '%s\n' "$GH_TOKEN" ;;
esac
SH
chmod 700 /tmp/igou-sre-askpass
GIT_ASKPASS=/tmp/igou-sre-askpass GIT_TERMINAL_PROMPT=0 git -c credential.helper= push origin HEAD
rm /tmp/igou-sre-askpass
unset GH_TOKEN
```

Mint a fresh PR-scoped token for `gh pr create`. Put only nonsecret evidence
in the PR. Link the PR on the existing incident issue when one exists and in
the final sweep report. State that no live infrastructure changes occurred.
