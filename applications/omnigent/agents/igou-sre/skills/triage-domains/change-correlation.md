# Change correlation: what merged recently?

First question for any regression. Map the symptom to its ArgoCD app,
then to recent commits on its source path.

```bash
oc get applications.argoproj.io -n openshift-gitops -o json | jq -r '.items[]
  | select(.spec.destination.namespace=="NS")
  | "\(.metadata.name) path=\(.spec.source.path) rev=\(.status.sync.revision[:8]) synced=\(.status.operationState.finishedAt)"'
export GH_TOKEN=$(ghapp token --repo igou-io/igou-openshift --permission contents=read)
gh api "repos/igou-io/igou-openshift/commits?path=<path>&per_page=5" \
  --jq '.[] | "\(.sha[:8]) \(.commit.committer.date[:16]) \(.commit.message | split("\n")[0])"'
```

- Compare the app's synced revision with those commits: a commit newer
  than `finishedAt` has NOT rolled out yet — do not blame it.
- For rk8s substitute igou-io/igou-kubernetes; for host/router/TrueNAS
  symptoms the change stream is igou-io/igou-ansible + igou-io/igou-inventory
  (AAP job history is not visible read-only — say so rather than guess).
- Renovate merges land in waves (Sunday schedule, automerge-on-green);
  a digest-only image bump timing-matching the regression is the usual
  suspect. Name the PR in the report.
