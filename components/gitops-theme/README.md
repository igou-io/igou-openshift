# GitOps theme

`Application/gitops-theme` deploys `ConfigMap/gitops-theme-assets` and the branding fields of the existing `ArgoCD/openshift-gitops`. The operator mounts the assets at `/shared/app/custom`; `ui.cssurl` loads `./custom/theme.css` from the same origin. The volume is named `gitops-theme`.

`assets/masthead-dark.png` pairs the planet with OpenShift GitOps. `assets/planet.png` supplies the planet-only login at 420×265 pixels, shrinking proportionally on narrow screens. The login adapter expands the upstream logo container, centers the sign-in panel and hides the decorative Argo illustration. Authentication controls and the version footer remain available.

The adapter uses graphite panels and lavender primary controls. Semantic status icons and destructive controls retain their meaning. Check selectors against the installed version after upgrades. This component targets the main GitOps instance; the VPS-management instance is separate. It does not enforce a user's native dark-mode preference.

Logo provenance is in `../console-theme/README.md`. The partial ArgoCD object preserves authentication, RBAC, health checks and repository configuration. Operational adoption, rollback and the non-cascading retirement of the old `gitops-branding` Application are documented in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
