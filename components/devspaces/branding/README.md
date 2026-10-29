# Dev Spaces dashboard artwork

Each generated branding Secret has one file. The running operator iterates Secret keys without stable ordering; a multi-file subpath Secret repeatedly reordered volume mounts and rolled the dashboard. Separate single-file Secrets keep the mount list stable.

Ship deterministic gzip siblings for the SVGs: the dashboard serves precompressed files to browsers that accept gzip. Without matching `.gz` replacements, requests can still receive the original Red Hat artwork. Regenerate with gzip mtime 0 when an SVG changes.

During migration, retire the old `devspaces-dashboard-customization` Secret before mounting the new set to avoid duplicate mount paths. It contains only public image data. Operational recovery and verification are recorded in `/workspace/igou-docs/openshift/Saturn Branding and Theme Controls.md`.
