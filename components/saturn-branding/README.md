# Saturn console identity

ConfigMap-backed light/dark masthead and favicon assets use the supported Console logos API. This changes identity; it does not inject a global console stylesheet. The partial Console resource preserves existing plug-ins and customizations.

Initial adoption requires removing the live empty `customLogoFile` atomically with adding `logos`: SSA alone does not remove that legacy field owned by another manager. Omit `customLogoFile` from the steady-state resource: after its removal, the API rejects an explicit null under server-side apply. Follow the migration and rollback procedure in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.

The blue planet is the pixel-exact alpha crop from original designer [Ken Loh's portfolio](https://kenloh.com/logos), with 336×212 useful pixels. The SVGs embed that unchanged raster beside the original SEGA SATURN wordmark outlines extracted from page 2 of [Sega’s Saturn papercraft PDF](https://sns.sega.jp/sp/dl/segasaturn_fb.pdf). Only the lettering is extracted; the PDF planet is excluded. Dark/light lettering and a red S accent adapt the original geometry for the UI. Only the small application subtitle uses a UI font.

[sources/official-wordmark-paths.svg](sources/official-wordmark-paths.svg) retains the original lettering geometry; [source evidence](sources/official-wordmark-provenance.json) records the PDF checksum, page, bounds and path checksum. Local regeneration and pixel-fidelity evidence remain in `/workspace/scratch/saturn-assets/theme-design/`.
