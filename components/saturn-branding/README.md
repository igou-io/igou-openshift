# Saturn console identity

ConfigMap-backed light/dark masthead and favicon assets use the supported Console logos API. This changes identity; it does not inject a global console stylesheet. The partial Console resource preserves existing plug-ins and customizations.

Initial adoption requires removing the live empty `customLogoFile` atomically with adding `logos`: SSA alone does not remove that legacy field owned by another manager. Follow the migration and rollback procedure in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.

The blue planet is the pixel-exact alpha crop from original designer [Ken Loh's portfolio](https://kenloh.com/logos), with 336×212 useful pixels. The SVGs embed that unchanged raster and outlined new UI typography; they are not vector redraws. Detailed source evidence remains in `/workspace/scratch/saturn-assets/theme-design/audit/blue-mark-quality.md`.
