# Console theme

ConfigMap-backed masthead and favicon assets use the supported Console logos API. `Application/console-theme` deploys `ConfigMap/console-theme` and the existing `Console/cluster` customization. The light and dark variants preserve platform-name contrast; the native console controls its own appearance.

Object names, asset keys and component paths describe the theme's role. The artwork remains the original blue Saturn planet paired with the platform name. `sources/blue-planet.png` preserves the original 336×212 pixels and transparency; its provenance JSON records the source and checksum. Archived official wordmark files are historical evidence and are not used by active assets.

The existing `customLogoFile` migration and the rename/ownership-transfer procedure are documented in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`. Renaming an Application does not retire its old instance or resources: the parent and child pruning policies differ, and old tracking metadata can remain. Retire the old `saturn-branding` Application without cascading deletion before the new Application adopts `Console/cluster`.

Public product names and browser titles use `<product> - igou.systems`. Asset provenance can name Saturn; Kubernetes object and component names use `theme`.
