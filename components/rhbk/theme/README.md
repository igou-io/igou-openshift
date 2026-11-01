# Keycloak login theme

Extends the installed RHBK `keycloak.v2` login theme, retaining upstream forms, templates, password flows and CSRF handling. Only CSS, logos and favicon are added. The planet is 420×265 pixels on desktop and shrinks proportionally on narrow screens. Provenance: `../../console-theme/README.md`.

`ConfigMap/keycloak-theme-assets` supplies the build context. `BuildConfig/keycloak-theme` uses the pinned RHBK 26.6.7 base image and `Secret/keycloak-theme-registry` to pull from Red Hat. It pushes directly to `quay.apps.ocp.igou.systems/igou-io/keycloak-theme:26.6.7`, using `Secret/keycloak-theme-quay`. Both credentials are reconciled by ExternalSecrets from existing registry items. The Dockerfile is authoritative and its `org.igou.theme-sha256` label hashes the exact ConfigMap input files.

The existing realm login theme ID remains `saturn`; it is an application compatibility setting, not a Kubernetes object name. The image continues to install resources below `/opt/keycloak/themes/saturn/login`, so existing realms require no authentication configuration changes. `theme.properties` now loads `theme.css` and that CSS references `planet-dark.png` and `planet-light.png`.

`Keycloak.spec.image` pins the verified Quay digest and `spec.imagePullSecrets` references the same Quay credential. After a rebuild, verify the published manifest and theme-file readability as a non-owner UID in group 0 before promoting its actual digest. A mutable build tag does not update the running SSO image. Keep the previous Quay digest available for rollback.

Only login is themed; account/admin/email themes remain upstream. A KeycloakRealmImport does not modify existing realms. Build resources alone do not change the running SSO image. Operational migration, cleanup and verification belong in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
