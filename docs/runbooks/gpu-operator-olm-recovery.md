# GPU Operator OLM recovery

Use this runbook when the `nvidia-gpu-operator` ArgoCD application is
Degraded, the Subscription cannot resolve, or a GPU Operator CSV is stuck in
`Replacing`.

## Desired GitOps contract

The intended long-term state for the Pascal GPU node is deliberately pinned:

- channel: `v26.3`
- starting CSV: `gpu-operator-certified.v26.3.3`
- InstallPlan approval: `Manual`

`startingCSV` is intentional and must remain in Git. It is not merely a
bootstrap hint, and this component must not automatically advance beyond the
known-good `v26.3.3` operator state. Every InstallPlan requires inspection and
explicit approval.

## Inspect the failure

Run these commands before changing anything:

```bash
oc get application/nvidia-gpu-operator -n openshift-gitops
oc get subscription/gpu-operator-certified -n nvidia-gpu-operator -o yaml
oc get csv -n nvidia-gpu-operator \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,REPLACES:.spec.replaces
oc get installplan -n nvidia-gpu-operator \
  -o custom-columns=NAME:.metadata.name,CSV:.spec.clusterServiceVersionNames,APPROVED:.spec.approved,PHASE:.status.phase
oc logs -n openshift-operator-lifecycle-manager deploy/olm-operator --since=15m
```

Confirm that the Subscription declares `v26.3`,
`gpu-operator-certified.v26.3.3`, and `Manual`. Preserve a healthy
`gpu-operator-certified.v26.3.3` CSV; the fact that `startingCSV` references
it does not make it stale.

## Handle stale v26.7 state

The previous incident left an unwanted/orphaned
`gpu-operator-certified.v26.7.0` CSV. It is not the recovery target.
Delete it only after confirming that it is not the current or installed CSV
and that the Subscription is being restored from the desired GitOps manifest:

```bash
oc get csv/gpu-operator-certified.v26.7.0 -n nvidia-gpu-operator
oc delete csv/gpu-operator-certified.v26.7.0 -n nvidia-gpu-operator
```

Do not delete `gpu-operator-certified.v26.3.3` when it is the desired or
installed CSV. Do not remove `startingCSV` from the Subscription. If the live
Subscription itself is stale, reconcile it from Git; delete and recreate the
Subscription only when necessary to remove stale live fields, and recreate it
with the exact desired contract above.

## Inspect and manually approve the expected InstallPlan

After the desired Subscription exists, identify only the InstallPlan that
contains the expected CSV:

```bash
EXPECTED_CSV=gpu-operator-certified.v26.3.3
mapfile -t INSTALL_PLANS < <(oc get installplan -n nvidia-gpu-operator -o json \
  | jq -r --arg csv "$EXPECTED_CSV" \
    '.items[] | select(.spec.clusterServiceVersionNames | index($csv)) | .metadata.name')

test "${#INSTALL_PLANS[@]}" -eq 1
INSTALL_PLAN="${INSTALL_PLANS[0]}"
oc get installplan "$INSTALL_PLAN" -n nvidia-gpu-operator -o yaml
oc get installplan "$INSTALL_PLAN" -n nvidia-gpu-operator \
  -o custom-columns=NAME:.metadata.name,CSV:.spec.clusterServiceVersionNames,APPROVED:.spec.approved,PHASE:.status.phase
```

Inspect the full plan and confirm that its CSV list contains
`gpu-operator-certified.v26.3.3` before approving it. Approve only that exact
plan:

```bash
oc patch installplan "$INSTALL_PLAN" -n nvidia-gpu-operator \
  --type merge -p '{"spec":{"approved":true}}'
```

Never approve every InstallPlan in the namespace, and never approve a plan
whose CSV list does not contain the expected `v26.3.3` CSV.

## Verify recovery

The recovery is complete only when the approved InstallPlan completes and the
desired CSV reaches `Succeeded`:

```bash
oc get installplan "$INSTALL_PLAN" -n nvidia-gpu-operator \
  -o custom-columns=NAME:.metadata.name,CSV:.spec.clusterServiceVersionNames,APPROVED:.spec.approved,PHASE:.status.phase
oc get subscription/gpu-operator-certified -n nvidia-gpu-operator \
  -o custom-columns=CHANNEL:.spec.channel,STARTING:.spec.startingCSV,APPROVAL:.spec.installPlanApproval,CURRENT:.status.currentCSV,INSTALLED:.status.installedCSV
oc get csv/gpu-operator-certified.v26.3.3 -n nvidia-gpu-operator \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,REASON:.status.reason
oc get clusterpolicy,nvidiadriver -n nvidia-gpu-operator
oc get pods -n nvidia-gpu-operator
oc get node p330.igou.systems \
  -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\\.com/gpu
```

Expected results are a completed, approved InstallPlan; Subscription fields
of `v26.3`, `gpu-operator-certified.v26.3.3`, and `Manual`; a
`Succeeded` `gpu-operator-certified.v26.3.3` CSV; ready driver resources and
GPU operands; and GPU capacity advertised on `p330`.
