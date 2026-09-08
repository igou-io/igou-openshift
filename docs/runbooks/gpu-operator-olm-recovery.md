# GPU Operator OLM recovery

Use this runbook when the `nvidia-gpu-operator` ArgoCD application is
Degraded and the GPU Operator CSV is stuck in `Replacing`, especially when
OLM reports that the replacement CSV does not exist.

## Confirm the failure

```bash
oc get application/nvidia-gpu-operator -n openshift-gitops
oc get subscription/gpu-operator-certified -n nvidia-gpu-operator -o yaml
oc get csv -n nvidia-gpu-operator
oc get installplan -n nvidia-gpu-operator
oc logs -n openshift-operator-lifecycle-manager deploy/olm-operator --since=15m
```

Preserve the current GPU workload state before recovery. The operator can be
stuck while the existing driver, device plugin, and `ClusterPolicy` remain
healthy.

## Recover the Subscription

The GitOps manifest is the source of truth. For this component it currently
selects channel `v26.7` and deliberately does not set `startingCSV`.

If the Application has an out-of-band reconcile pause, remove it and wait for
ArgoCD to reconcile the current Git revision:

```bash
oc annotate application/nvidia-gpu-operator -n openshift-gitops \
  argocd.argoproj.io/skip-reconcile-
```

If the live Subscription still carries an old `startingCSV` after its channel
has been corrected, delete only the Subscription. ArgoCD will recreate it from
Git without the stale pin:

```bash
oc delete subscription/gpu-operator-certified -n nvidia-gpu-operator
```

Wait for the recreated Subscription to show the desired channel with no
`startingCSV`. Do not add `startingCSV: gpu-operator-certified.v26.3.3`; that
pins the deprecated 26.3 release and prevents the intended upgrade path.

## Remove an orphaned CSV only when required

If the old CSV is the only CSV in the namespace, remains `Replacing`, and no
InstallPlan is created after the clean Subscription is recreated, remove that
specific orphaned CSV:

```bash
oc delete csv/gpu-operator-certified.v26.3.3 -n nvidia-gpu-operator
```

Immediately watch for the replacement:

```bash
watch -n 5 'oc get subscription,csv,installplan -n nvidia-gpu-operator'
```

## Verify recovery

The recovery is complete only when all of these are true:

```bash
oc get application/nvidia-gpu-operator -n openshift-gitops
oc get subscription/gpu-operator-certified -n nvidia-gpu-operator
oc get csv -n nvidia-gpu-operator
oc get installplan -n nvidia-gpu-operator
oc get clusterpolicy,nvidiadriver -n nvidia-gpu-operator
oc get pods -n nvidia-gpu-operator
oc get node p330.igou.systems -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\\.com/gpu
```

Expected results are an ArgoCD `Healthy/Synced` application, a completed
InstallPlan, a `Succeeded` `gpu-operator-certified.v26.7.0` CSV, ready driver
resources, healthy GPU pods, and GPU capacity still advertised on `p330`.
