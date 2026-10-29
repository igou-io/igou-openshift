# Saturn console identity

ConfigMap-backed light/dark masthead and favicon assets use the supported Console logos API. This changes identity; it does not inject a global console stylesheet. The partial Console resource preserves existing plug-ins and customizations.

Initial adoption requires removing the live empty `customLogoFile` atomically with adding `logos`: SSA alone does not remove that legacy field owned by another manager. Omit `customLogoFile` from the steady-state resource: after its removal, the API rejects an explicit null under server-side apply. Follow the migration and rollback procedure in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.

The blue planet is the pixel-exact alpha crop from original designer [Ken Loh's portfolio](https://kenloh.com/logos), with 336×212 useful pixels. The active banner SVGs embed that unchanged raster beside the platform name in outlined UI type. Login screens use the planet alone. Light/dark banner variants keep platform names readable on their corresponding surfaces.

[sources/blue-planet.png](sources/blue-planet.png) is the original transparent planet crop; [planet provenance](sources/blue-planet-provenance.json) records its source and checksum. The archived official wordmark files document the previous design and are not used by the active theme. Local regeneration and pixel-fidelity evidence remain in `/workspace/scratch/saturn-assets/theme-design/planet-platform/`.

Public product names and browser titles use `<product> - igou.systems`. Saturn names identify the visual theme and internal resources.
