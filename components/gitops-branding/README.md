# Saturn GitOps adapter

Mounts CSS and the derived GitOps logo under `/shared/app/custom` through the ArgoCD operator's server volumes. `ui.cssurl` loads `./custom/saturn.css` from the same origin. No external asset host is required.

The sidebar banner pairs the planet with OpenShift GitOps. The login uses the planet-only image at 200×126 pixels, approximately 3.5 times the previous planet's visible size; the sidebar and login images have separate keys in the asset ConfigMap.

The partial ArgoCD object declares only the new branding fields. It preserves the bootstrapped instance's authentication, RBAC, health checks and repo configuration; server-side dry run verified that merge. The bootstrap playbook continues to own its existing fields.

The adapter uses graphite panels and lavender primary controls. Semantic status icons and destructive controls retain their meaning. Check selectors against the running version after GitOps upgrades. This component targets the main `openshift-gitops` instance; the VPS-management instance is separate.

Logo provenance is in `../saturn-branding/README.md`. Operational adoption and rollback belong in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
