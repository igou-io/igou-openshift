{{/*
pac-tenant.merged — returns the per-tenant config with defaults merged underneath.
Per-tenant values take precedence. Use:
  {{- $cfg := include "pac-tenant.merged" (dict "root" . "tenant" $tenant) | fromYaml -}}
*/}}
{{- define "pac-tenant.merged" -}}
{{- $defaults := deepCopy .root.Values.defaults -}}
{{- $tenant := .tenant -}}
{{- $merged := mergeOverwrite $defaults (deepCopy $tenant) -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
pac-tenant.namespace — derives the namespace name from tenant.name + namespacePrefix.
*/}}
{{- define "pac-tenant.namespace" -}}
{{- printf "%s%s" .root.Values.namespacePrefix .tenant.name -}}
{{- end -}}

{{/*
pac-tenant.hasSecrets — returns "true" if the tenant declares any secrets, "" otherwise.
*/}}
{{- define "pac-tenant.hasSecrets" -}}
{{- $s := .tenant.secrets | default dict -}}
{{- if or (and $s.imagePullSecrets (gt (len $s.imagePullSecrets) 0)) (and $s.workspaceSecrets (gt (len $s.workspaceSecrets) 0)) (and $s.pushSecrets (gt (len $s.pushSecrets) 0)) -}}
true
{{- end -}}
{{- end -}}

{{/*
pac-tenant.okToTest — returns the effective ok-to-test list for a tenant.
If the tenant has any secrets, this collapses to the pullRequest list (no widening allowed).
Otherwise returns the configured okToTest (default merged).
*/}}
{{- define "pac-tenant.okToTest" -}}
{{- $cfg := include "pac-tenant.merged" (dict "root" .root "tenant" .tenant) | fromYaml -}}
{{- if include "pac-tenant.hasSecrets" (dict "tenant" .tenant) -}}
{{- toYaml $cfg.policy.pullRequest -}}
{{- else -}}
{{- toYaml $cfg.policy.okToTest -}}
{{- end -}}
{{- end -}}

{{/*
pac-tenant.labels — labels applied to every resource the chart produces.
*/}}
{{- define "pac-tenant.labels" -}}
app.kubernetes.io/managed-by: helm
app.kubernetes.io/part-of: pac-tenants
igou.systems/pac-tenant: {{ .tenant.name | quote }}
{{- end -}}
