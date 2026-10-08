# Quay and Clair database backup boundary

`quay-pg` stores registry metadata and retains its nightly Barman backups,
continuous WAL archive, and 30-day recovery window. `clair-pg` stores disposable
advisory feeds and image scan results. It has no Barman plugin or backup schedule;
its inherited `velero.io/exclude-from-backup` label also excludes its volumes
from OADP.

Clair uses the existing `quay-clair-pg-credentials` Secret on the new instance.
The cluster is sync wave -1, the config bundle and QuayRegistry are wave 0, and
the old `clair` Database is wave 1 with `ensure: absent`. Keep that tombstone:
removing a Database resource with `databaseReclaimPolicy: retain` would keep the
old scanner data in every `quay-pg` backup.

The cutover rebuilds Clair rather than copying its old database. Invalidate
Quay's saved V4 scanner hashes once after Clair is healthy so existing images
are reindexed against the empty scanner database. Quay's registry metadata and
S3 image blobs remain in place. Historical combined database backups remain
until Barman's recovery window expires them.

The rollout, scan-cache reset, verification commands, and rebuild-on-loss
procedure are in `/workspace/igou-docs/openshift/Quay Registry Operations on
OpenShift.md` under "Clair rebuild-on-loss and backup separation".
