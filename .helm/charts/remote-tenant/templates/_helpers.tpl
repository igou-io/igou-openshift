{{/*
remote-tenant.merged — per-tenant config with defaults merged underneath.
Per-tenant values win. Usage:
  {{- $cfg := include "remote-tenant.merged" (dict "root" . "tenant" $tenant) | fromYaml -}}
*/}}
{{- define "remote-tenant.merged" -}}
{{- $defaults := deepCopy .root.Values.defaults -}}
{{- $merged := mergeOverwrite $defaults (deepCopy .tenant) -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
remote-tenant.namespace — namespacePrefix + tenant.name.
*/}}
{{- define "remote-tenant.namespace" -}}
{{- printf "%s%s" .root.Values.namespacePrefix .tenant.name -}}
{{- end -}}

{{/*
remote-tenant.labels — applied to every resource the chart produces.
*/}}
{{- define "remote-tenant.labels" -}}
app.kubernetes.io/managed-by: helm
app.kubernetes.io/part-of: remote-tenants
igou.systems/remote-tenant: {{ .tenant.name | quote }}
{{- end -}}
