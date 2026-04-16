---
name: troubleshoot
description: Diagnose issues in a Kubernetes namespace by inspecting pods, events, operator CSVs, InstallPlans, CRDs, and common failure modes. Extends /inspect with root-cause analysis.
argument-hint: <namespace>
allowed-tools: Read, Bash(oc *), Bash(kubectl *), mcp__kubernetes__pods_list, mcp__kubernetes__pods_list_in_namespace, mcp__kubernetes__pods_get, mcp__kubernetes__pods_log, mcp__kubernetes__pods_top, mcp__kubernetes__events_list, mcp__kubernetes__resources_list, mcp__kubernetes__resources_get, mcp__kubernetes__namespaces_list, mcp__kubernetes__nodes_top
---

# Troubleshoot a namespace

Perform a comprehensive diagnostic of the namespace **$ARGUMENTS** to identify issues and suggest fixes.

If `$ARGUMENTS` is empty, ask the user for the namespace.

## Diagnostic steps

Run these checks in order. Use MCP tools as the primary method; fall back to `oc` CLI when MCP doesn't cover the operation.

### 1. Namespace existence and basics

Verify the namespace exists:
```bash
oc get namespace <namespace> -o yaml
```

If the namespace doesn't exist, report that immediately and stop.

### 2. Pod health

Use `mcp__kubernetes__pods_list_in_namespace` to list all pods.

For each pod, check:
- Phase (Running, Pending, Failed, CrashLoopBackOff, etc.)
- Container readiness and restart counts
- Container state details (waiting reason, terminated reason, exit codes)

For any unhealthy pod, use `mcp__kubernetes__pods_get` for full details and `mcp__kubernetes__pods_log` for recent logs (check both current and previous container if restarts > 0).

### 3. Events

Use `mcp__kubernetes__events_list` filtered to the namespace.

Look for:
- Warning events (FailedScheduling, FailedMount, ImagePullBackOff, etc.)
- Recent error patterns
- Repeated events indicating a loop

### 4. Operator health (if this is an operator namespace)

Check for ClusterServiceVersions:
```bash
oc get csv -n <namespace> -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,REASON:.status.reason
```

Check for pending InstallPlans:
```bash
oc get installplan -n <namespace> -o custom-columns=NAME:.metadata.name,APPROVED:.spec.approved,PHASE:.status.phase
```

Check Subscription status:
```bash
oc get subscription -n <namespace> -o yaml
```

Look for:
- CSVs not in `Succeeded` phase
- InstallPlans not approved (if installPlanApproval is Manual)
- Subscription conditions indicating errors
- Missing CatalogSource references

### 5. Resource issues

Check resource quotas and limits:
```bash
oc get resourcequota -n <namespace>
oc get limitrange -n <namespace>
```

Check PVC status:
```bash
oc get pvc -n <namespace> -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,CAPACITY:.status.capacity.storage,STORAGECLASS:.spec.storageClassName
```

Look for:
- PVCs stuck in Pending
- Resource quota exhaustion

### 6. Network resources

Check for NetworkAttachmentDefinitions:
```bash
oc get net-attach-def -n <namespace>
```

Check Services and endpoints:
```bash
oc get svc -n <namespace>
oc get endpoints -n <namespace>
```

Look for:
- Services with no endpoints (selector mismatch)
- NADs referencing non-existent interfaces

### 7. Node health (if scheduling issues detected)

If pods are stuck in Pending with scheduling errors:
```bash
oc get nodes -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status,TAINTS:.spec.taints[*].key
```

Use `mcp__kubernetes__nodes_top` to check resource pressure.

## Analysis and report

After gathering data, produce a structured report:

### Status summary
- Overall health: Healthy / Degraded / Unhealthy
- Pod status breakdown (X running, Y pending, Z failed)
- Operator status (if applicable)

### Issues found
For each issue, provide:
1. **What**: Clear description of the problem
2. **Evidence**: The specific data that indicates the issue (event message, pod status, log line)
3. **Root cause**: Most likely underlying cause
4. **Fix**: Specific remediation steps

### Common issue patterns to check for

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| Pod `ImagePullBackOff` | Wrong image ref or missing pull secret | Check image URL, check `imagePullSecrets` |
| Pod `Pending` no events | No nodes match scheduling constraints | Check tolerations, nodeSelector, affinity |
| Pod `Pending` FailedScheduling | Insufficient resources or taint | Check node resources, taints |
| Pod `CrashLoopBackOff` | App crash, wrong config | Check logs (current + previous) |
| CSV `InstallReady` not `Succeeded` | Dependency issue or webhook failure | Check CSV conditions, related CSVs |
| InstallPlan not approved | Manual approval required | Check Subscription `installPlanApproval` |
| PVC `Pending` | No matching PV or StorageClass issue | Check StorageClass, PV availability |
| Service no endpoints | Label selector mismatch | Compare svc selector with pod labels |
| ExternalSecret not syncing | SecretStore misconfigured or 1Password key wrong | Check ExternalSecret status conditions |

### Healthy namespace

If no issues are found, confirm the namespace is healthy and provide a brief status summary (pod count, resource usage, operator status).
