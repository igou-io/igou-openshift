# Keycloak login theme

Extends the installed RHBK `keycloak.v2` login theme, retaining upstream forms, templates, password flows and CSRF handling. Only CSS, logos and favicon are added. The planet is 420×265 pixels on desktop and shrinks proportionally on narrow screens. Provenance: `../../console-theme/README.md`.

`ConfigMap/keycloak-theme-assets` supplies the build context. `BuildConfig/keycloak-theme` uses the pinned RHBK 26.6.7 base image and `Secret/keycloak-theme-registry`, reconciled by its ExternalSecret from the existing registry item. It writes `ImageStreamTag/keycloak-theme:26.6.7`. The Dockerfile is authoritative and its `org.igou.theme-sha256` label hashes the exact ConfigMap input files.

The existing realm login theme ID remains `saturn`; it is an application compatibility setting, not a Kubernetes object name. The image continues to install resources below `/opt/keycloak/themes/saturn/login`, so existing realms require no authentication configuration changes. `theme.properties` now loads `theme.css` and that CSS references `planet-dark.png` and `planet-light.png`.

The runtime still uses the previously verified immutable image `image-registry.openshift-image-registry.svc:5000/keycloak/saturn-keycloak@sha256:8f8774627c4a0db9284d79bd65f6a5b702235be8ec35a0b77e3ecd62deb2d477`. Retain that legacy ImageStream while it is in use. Build the renamed resources, verify file readability under the restricted UID, and promote a real output digest from the new `keycloak-theme` repository in a follow-up change. Do not rename the current image URI to a repository that has not published that digest.

Only login is themed; account/admin/email themes remain upstream. A KeycloakRealmImport does not modify existing realms. Build resources alone do not change the running SSO image. Operational migration, cleanup and verification belong in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
