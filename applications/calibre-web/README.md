# Calibre-Web

Calibre-Web serves ebook files stored on a deliberately static TrueNAS NFS
dataset. Application state and the Calibre metadata database are kept on a
separate CSI-backed volume. The deployment uses the digest-pinned
LinuxServer.io image.

## Migration rollback state

Calibre-Web Automated is now the authoritative Calibre library manager. This
stock Deployment is retained for rollback with `replicas: 0`; do not restart
it against its old SQLite databases without an explicit rollback procedure.

## Storage

| Purpose | PVC | Source | Access |
| --- | --- | --- | --- |
| Application state and Calibre database (`/config`) | `calibre-web-config` | `freenas-nvmeof-ssd-csi` | RWO, 5Gi, read-write |
| Ebook files (`/books`) | `calibre-web-books` | Static NFS PV, `10.10.9.213:/mnt/cold/media/data/media/books` | RWX, 1Ti, read-write |

The library PV has a `Retain` reclaim policy and a dedicated storage class so
it cannot be replaced by dynamic provisioning. It reuses the existing TrueNAS
`media` NFS export also mounted by Jellyfin; Calibre-Web is restricted to its
`books` subdirectory.

The Calibre library database is stored at `/config/calibre-db/metadata.db` on
the CSI-backed ext4 PVC. Initialize this directory and seed a valid Calibre
`metadata.db` with a separate one-shot task after the deployment rolls out.
That task should leave an existing database untouched, install new files
atomically, and set ownership and permissions for UID 1000 and GID 3006. It
must operate on `/config` only and must not modify `/books`; a persistent
bootstrap Job is intentionally not part of this GitOps application.

Calibre-Web must use split-library mode:

- Database location: `/config/calibre-db`
- Separate Book Files from Library: enabled
- Book files location: `/books`

This keeps SQLite off NFS while preserving the shared NFS book tree for
Calibre-Web and Shelfmark. Do not configure the database location as `/books`
or depend on `/books/metadata.db`.

The daily OADP application schedule protects the config PVC with CSI data
movement and the NFS-mounted library with Velero file-system backup. The
existing recursive weekly snapshot of `cold/media` also covers the books.

## OpenShift security exception

LinuxServer.io's s6 init must start as root so it can apply `PUID=1000` and
`PGID=3006`, initialize `/config`, and then drop privileges for Calibre-Web.
GID `3006` is the shared media group that grants the application write access
to the NFS-backed book tree.

The pod does not use `supplementalGroups` for this workload. LinuxServer's
`s6-setuidgid abc` rebuilds supplementary groups from the image's account
database when launching Calibre-Web, so a Kubernetes-only supplemental group
would not be present in the actual Python process. Setting `PGID=3006` makes
the LinuxServer `abc` primary group match the NFS permission model.

Keeping `metadata.db` on the CSI-backed `/config` volume is also intentional:
SQLite databases depend on filesystem locking and atomic-write behavior that
network filesystems, including NFS, do not reliably provide.
The dedicated `calibre-web` service account is therefore granted the `anyuid`
SCC and the pod explicitly starts as UID 0. Privilege escalation remains
disabled and seccomp remains `RuntimeDefault`. Do not reuse this service
account for another workload.

## Secure first-run bootstrap

There is intentionally no Route in this initial deployment. Calibre-Web starts
with upstream default administrator credentials, so exposing it before setup
would be unsafe.

After the pod is healthy, forward the service locally and complete the setup at
`http://127.0.0.1:8083`. In Admin > Edit Calibre Database Configuration, set
the database location to `/config/calibre-db`, enable `Separate Book Files from
Library`, and set the separate book files location to `/books`. Immediately
replace the default administrator password. The one-shot database
initialization task does not rewrite the existing Calibre-Web `app.db`, so this
UI step is required after the first deployment if it still points at `/books`.

```bash
oc -n calibre-web port-forward service/calibre-web-app 8083:80
```

Add the standard edge-terminated OpenShift ingress only after that bootstrap is
complete. Never record the replacement password in Git, command output, or PR
text.

Shelfmark mounts the same TrueNAS-backed `/books` volume read-write. Downloads
and library changes made by Shelfmark are therefore visible to Calibre-Web
immediately; do not treat the Shelfmark Route as an isolation boundary.
