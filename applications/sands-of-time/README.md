# sands-of-time

Internal application, deployed from a private image.

- **URL**: <https://sands-of-time.apps.ocp.igou.systems>
- Single replica on a RWO PVC (SQLite) with `Recreate` strategy — never
  scale above 1.
- The serve process keeps its data current on its own; there is no CronJob.

## Bootstrap (once, after first sync)

The image registry package is private. The pull secret is created
out-of-band so no credential lands in git:

```bash
oc create secret generic ghcr-pull -n sands-of-time \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson=<auth.json with a ghcr.io read login>
```

TODO: move this to an ExternalSecret once a registry item exists in the
appropriate 1Password vault.

Then seed the database (long-running, resumable, rate-limited):

```bash
oc apply -f applications/sands-of-time/sands-of-time-bootstrap-job.yaml
```

## Admin API (optional)

`/api/admin` stays disabled (503) until the token Secret exists:

```bash
oc create secret generic sands-of-time-admin -n sands-of-time \
  --from-literal=token="$(openssl rand -hex 32)"
```
