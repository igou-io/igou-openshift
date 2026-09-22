# MeTube

MeTube is a trusted-LAN-only web UI for `yt-dlp`. The `metube` Argo CD
application deploys one replica at `https://metube.lan.igou.systems` through
the shared trusted-LAN Gateway.

MeTube has no built-in authentication. Do not expose it through the guest-DMZ
Gateway, a public Route, or an internet-facing ingress.

## Storage and import flow

```text
MeTube /downloads -> TrueNAS /mnt/cold/media/data/metube
                              |
                              +-- inbox/tv
                              +-- inbox/movies
                              +-- inbox/other
                                     |
                              Sonarr/Radarr manual import
                                     |
                              /data/media/{tv,movies}
                                     |
                                  Jellyfin
```

| Purpose | PVC | Source | Mount | Backup |
| --- | --- | --- | --- | --- |
| Queue, completion, and subscription state | `metube-config` | `freenas-nvmeof-ssd-csi`, 1Gi RWO | `/config` | Daily OADP |
| Download staging | `metube-downloads` | Static NFS `/mnt/cold/media/data/metube`, 8Ti RWX | `/downloads` | Excluded from OADP; containing TrueNAS dataset snapshots apply |

MeTube can write only to its staging subtree, not the canonical Jellyfin
libraries. Sonarr and Radarr mount the parent export at `/data`, so their
manual-import paths are `/data/metube/inbox/tv` and
`/data/metube/inbox/movies`. Keeping the inbox and libraries on the same NFS
filesystem permits hardlink imports when the Arr application accepts the
download and hardlinks are enabled.

## TrueNAS prerequisite

Before the first sync, create this directory tree on TrueNAS:

```text
/mnt/cold/media/data/metube
├── .tmp
└── inbox
    ├── movies
    ├── other
    └── tv
```

Set the tree owner to UID `1000`, group to media GID `3006`, and directory
mode to `2775`. `CREATE_CUSTOM_DIRS=false` intentionally limits the UI folder
selector to these pre-created destinations. The pod runs as `1000:1000` with
supplemental group `3006` and `UMASK=002`.

The static PV uses `Retain` and a unique storage class to preserve one-to-one
binding. Its `velero.io/exclude-from-backup` label keeps bulk, reproducible
downloads out of OADP while the small state PVC remains protected.

## Security and networking

- The `nonroot-v2` SCC admits the fixed non-root media identity.
- The service account token is not mounted and all Linux capabilities are
  dropped.
- Default-deny NetworkPolicies admit trusted-Gateway and kubelet health
  traffic, cluster DNS, and public internet egress only.
- MeTube's private-address access, free-form yt-dlp overrides, and directory
  indexing remain disabled.
- Browser cookies are not configured. Add them later through an
  ExternalSecret-mounted file if a source requires authentication.

## Verification after sync

1. Confirm `metube-config` and `metube-downloads` are `Bound` and the pod is
   admitted under `nonroot-v2`.
2. Open `https://metube.lan.igou.systems` and download a small test item into
   each staging directory.
3. Recreate the pod and verify queue/completed state and partial downloads
   persist.
4. Manually import one TV item through Sonarr and one movie through Radarr,
   verify ownership and link count, then confirm Jellyfin discovers them.
