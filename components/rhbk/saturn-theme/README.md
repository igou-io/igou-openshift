# Saturn login theme

Extends the installed RHBK `keycloak.v2` login theme, retaining upstream forms, templates, password flows and CSRF handling. Only CSS, logos and favicon are added. The UI lockup embeds the unchanged designer-source blue Saturn mark; provenance: `../../saturn-branding/README.md`.

`BuildConfig/saturn-keycloak` uses the exact running RHBK 26.6.7 image digest, the theme ConfigMap as build context, and the existing Red Hat registry item through an ExternalSecret. This authenticated product-image build runs inside OpenShift because the public container CI has no Red Hat registry login. Output is the internal `saturn-keycloak:26.6.7` ImageStreamTag. The Dockerfile in the BuildConfig is authoritative.

Update its theme-content hash when assets change to trigger a new build. The image build enables PostgreSQL, health and metrics support. Runtime adoption requires a successful build, a digest-pinned `Keycloak.spec.image`, and selecting login theme `saturn` in the existing `igou` realm. `KeycloakRealmImport` does not update an existing realm. Restore the previous realm theme before removing the custom image during rollback.

Only login is themed. Account/admin/email themes remain upstream. Build resources alone do not change the SSO deployment. Operational rollout and verification belong in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
