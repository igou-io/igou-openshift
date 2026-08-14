# aap-portal — AAP 2.7 Ansible automation portal (POC)

Self-service automation portal for AAP 2.7: a dedicated RHDH/Backstage
instance (separate from `components/rhdh`) that fronts the AAP gateway with a
curated job-template catalog, a visual execution-environment builder, and
Git-based collection discovery. Deployed from the certified
[`redhat-rhaap-portal`](https://charts.openshift.io) Helm chart via the
kustomize `helmCharts` field — render with
`kustomize build --enable-helm`.

- URL: <https://portal.apps.ocp.igou.systems>
- Sign-in: AAP gateway OAuth (authorization-code). Users must be able to log
  in to AAP (org `igou` is the synced catalog org); portal admins default to
  the AAP `admin` user.
- Install contract follows the AAP 2.7 "Install automation portal on
  OpenShift Container Platform" docs: secret `secrets-rhaap-portal`
  (aap-host-url / oauth-client-id / oauth-client-secret / aap-token) and
  `<release>-dynamic-plugins-registry-auth` (skopeo `auth.json` for
  registry.redhat.io — the plug-in initContainer does NOT use kubelet pull
  secrets). Both are ESO-rendered; sources: 1P `lab_aap/aap-portal` and
  `lab_container_registries/redhat-registry`.
- AAP-side objects (OAuth app `automation-portal`, gateway setting
  `ALLOW_OAUTH2_FOR_EXTERNAL_USERS=true`) are declared in
  igou-inventory `group_vars/aap/` (infra.aap_configuration). The OAuth
  client secret and the write-scope API token are only issued at creation
  time; rotate by deleting the app/token in AAP, re-creating, and updating
  the 1P item.
- The chart pins plug-in artifacts with `imageTagInfo` (must exist as a tag
  on `registry.redhat.io/ansible-automation-platform/automation-portal`);
  bump it together with the chart version.
- Postgres is chart-managed (1Gi PVC on the default StorageClass) — POC
  footing, not in OADP scope yet.

Not configured yet (follow-ups): `secrets-scm` GitHub token for EE-builder
push / content discovery, ServiceMonitor for the 9464 metrics port, dev1 /
sandbox org exposure.
