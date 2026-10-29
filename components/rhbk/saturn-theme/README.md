# Saturn login theme

Extends the installed RHBK `keycloak.v2` login theme, retaining upstream forms, templates, password flows and CSRF handling. Only CSS, logos and favicon are added. The UI lockup embeds the unchanged designer-source blue Saturn planet and official Sega wordmark outlines; provenance: `../../saturn-branding/README.md`.

`BuildConfig/saturn-keycloak` uses the exact running RHBK 26.6.7 image digest, the theme ConfigMap as build context, and the existing Red Hat registry item through an ExternalSecret. This authenticated product-image build runs inside OpenShift because the public container CI has no Red Hat registry login. Output is the internal `saturn-keycloak:26.6.7` ImageStreamTag. The Dockerfile in the BuildConfig is authoritative.

Update its theme-content hash when assets change to trigger a new build. The image build enables PostgreSQL, health and metrics support. Build `saturn-keycloak-permissions-bvdrc` completed successfully with OpenShift-readable theme files; the runtime image is pinned to its output digest `sha256:87ff6b1824e22040d45922fcb1ed54410332bdbe7d50a290c06a797c10c737bf`. The build-only network policy allows internal registry TCP/5000 for pods carrying `openshift.io/build.name`. Select login theme `saturn` on the existing `igou` realm after the new image is Ready. `KeycloakRealmImport` does not update an existing realm. Restore the previous realm theme before removing the custom image during rollback.

Only login is themed. Account/admin/email themes remain upstream. Build resources alone do not change the SSO deployment. Operational rollout and verification belong in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
