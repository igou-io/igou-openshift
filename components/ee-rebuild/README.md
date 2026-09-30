# Weekly RHEL 9 execution environment rebuild

`ee-rebuild` runs Sunday at 03:00 America/New_York in `ci-igou-ansible`.
It clones `igou-ansible/main`, renders the RHEL 9 EE artifacts with
ansible-builder, and builds and pushes
`quay.apps.ocp.igou.systems/igou-io/igou-aap-ee-rhel9:latest`.
The final RHACS check is advisory.

Tekton does not provide a recurring-run resource in the installed OpenShift
Pipelines 1.23.2 APIs. Upstream [TEP-0128: Scheduled Runs](https://github.com/tektoncd/community/blob/main/teps/0128-scheduled-runs.md)
describes CronJobs creating PipelineRuns or calling EventListeners as the
existing scheduling patterns; its `ScheduledTemplate` is a proposal.
For this single weekly build, the CronJob creates the PipelineRun directly.
`TektonScheduler` configures Kueue resource scheduling, not calendar schedules.

The CronJob waits for the PipelineRun to finish. Build failures fail the Job,
and `concurrencyPolicy: Forbid` covers the whole build. There is no automatic
Job retry that would submit a duplicate PipelineRun.

## Dependencies

The `pac-tenants` ArgoCD application creates the namespace, mirrored
`ee-minimal-rhel9:latest` base ImageStream, `pipeline` ServiceAccount, Quay
push credentials, Automation Hub token ExternalSecret, and network policies.
Its namespace annotations configure the Tekton operator's daily pruner to
retain three PipelineRuns, below the namespace's five-workspace-PVC quota.
Deleting a completed PipelineRun garbage-collects its workspace PVC and tasks.

Keep `ansible-builder-task.yaml` and `buildah-galaxy-task.yaml` byte-identical
to the corresponding files in `igou-ansible/.tekton/tasks/`. The build task
reads `rh-automationhub-credentials/token` through `secretKeyRef` and passes
the token build arguments by name. Never put credentials in TaskRun results,
PipelineRun parameters, or verbose build arguments.

The ArgoCD Application uses server-side diff with mutation webhooks so Tekton's
admission defaults are included in comparisons. Avoid `ignoreDifferences` paths
inside task or parameter arrays with `RespectIgnoreDifferences=true`: ArgoCD
can preserve the entire old array during sync, preventing new task definitions
from deploying.

## Trigger and verify

Verify the target cluster and identity before any cluster command:

```bash
oc whoami --show-server
oc whoami
oc create job --from=cronjob/ee-rebuild ee-rebuild-manual-$(date +%s) -n ci-igou-ansible
oc get jobs,pipelineruns,pvc -n ci-igou-ansible
oc logs -n ci-igou-ansible job/<job-name>
```

The Job log identifies the PipelineRun. Verify its `Succeeded` condition and
the build TaskRun's `IMAGE_DIGEST` result, then inspect that digest in Quay.
AAP's registered EE uses this image with `pull: always`.

`components/user-workload-monitoring/rules/ee-rebuild-alerts-prometheusrule.yaml`
alerts on the latest Job failing or no successful scheduled rebuild for eight
days. It runs in platform Prometheus because the Job/CronJob metrics come
from platform kube-state-metrics.

If a run never creates tasks, check the PVC quota before investigating task
resolution. Prune only completed PipelineRuns in this namespace; active runs
must retain their workspaces.
