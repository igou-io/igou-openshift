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
{{- if or (and $s.imagePullSecrets (gt (len $s.imagePullSecrets) 0)) (and $s.workspaceSecrets (gt (len $s.workspaceSecrets) 0)) (and $s.serviceAccountSecrets (gt (len $s.serviceAccountSecrets) 0)) -}}
true
{{- end -}}
{{- end -}}

{{/*
pac-tenant.secretStoreRef — renders the spec.secretStoreRef block for an
ExternalSecret. Each secret may point at its own store via an optional
per-secret `secretStore.{kind,name}` override; unset fields fall back to the
chart-level secretStore.{kind,name} default. This lets ExternalSecrets whose
items live in different context vaults each reference the matching per-vault
ClusterSecretStore.
Usage:
  spec:
    secretStoreRef:
      {{- include "pac-tenant.secretStoreRef" (dict "root" $ "store" $secret.secretStore) | nindent 6 }}
*/}}
{{- define "pac-tenant.secretStoreRef" -}}
{{- $root := .root -}}
{{- $store := .store | default dict -}}
kind: {{ $store.kind | default $root.Values.secretStore.kind | quote }}
name: {{ $store.name | default $root.Values.secretStore.name | quote }}
{{- end -}}

{{/*
pac-tenant.dataFromExtract — renders a dataFrom[].extract block from a
remoteRef dict ({key, property?, version?}). Bakes in the four CRD
default fields so rendered ExternalSecrets match the post-defaulted live
state (avoids permanent OutOfSync drift).
Usage:
  dataFrom:
    {{- include "pac-tenant.dataFromExtract" $remoteRef | nindent 4 }}
*/}}
{{- define "pac-tenant.dataFromExtract" -}}
- extract:
    key: {{ .key | quote }}
    {{- with .property }}
    property: {{ . | quote }}
    {{- end }}
    {{- with .version }}
    version: {{ . | quote }}
    {{- end }}
    conversionStrategy: Default
    decodingStrategy: None
    metadataPolicy: None
    nullBytePolicy: Ignore
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
