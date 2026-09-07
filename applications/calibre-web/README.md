# Calibre-Web

Calibre-Web serves an ebook library stored on a deliberately static TrueNAS
NFS dataset. Application state and the library are kept on separate volumes.
The deployment uses the digest-pinned LinuxServer.io image.

## Storage

| Purpose | PVC | Source | Access |
| --- | --- | --- | --- |
| Settings and application database (`/config`) | `calibre-web-config` | `freenas-nvmeof-ssd-csi` | RWO, 5Gi |
| Ebook library (`/books`) | `calibre-web-books` | Static NFS PV, `10.10.9.213:/mnt/cold/ebooks` | RWX, 1Ti |

The library PV has a `Retain` reclaim policy and a dedicated storage class so
it cannot be replaced by dynamic provisioning. TrueNAS owns dataset, user,
NFS-share, quota, and snapshot lifecycle through `igou-ansible` and
`igou-inventory`.

The daily OADP application schedule protects the config PVC with CSI data
movement and the NFS-mounted library with Velero file-system backup. TrueNAS
also takes dataset-native daily and weekly snapshots.

## OpenShift security exception

LinuxServer.io's s6 init must start as root so it can apply `PUID=1000` and
`PGID=1000`, initialize `/config`, and then drop privileges for Calibre-Web.
The dedicated `calibre-web` service account is therefore granted the `anyuid`
SCC and the pod explicitly starts as UID 0. Privilege escalation remains
disabled and seccomp remains `RuntimeDefault`. Do not reuse this service
account for another workload.

## Secure first-run bootstrap

There is intentionally no Route in this initial deployment. Calibre-Web starts
with upstream default administrator credentials, so exposing it before setup
would be unsafe.

After the pod is healthy, forward the service locally and complete the setup at
`http://127.0.0.1:8083`: choose `/books` as the Calibre library location and
immediately replace the default administrator password.

```bash
oc -n calibre-web port-forward service/calibre-web-app 8083:80
```

Add the standard edge-terminated OpenShift ingress only after that bootstrap is
complete. Never record the replacement password in Git, command output, or PR
text.
