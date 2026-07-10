# sands-of-time

OSRS Grand Exchange price DB + boss-drop EV analytics API
([david-igou/sands-of-time](https://github.com/david-igou/sands-of-time)).
Agent-facing: `/api/brief`, `/api/playbook`, `/api/screener`, `/api/movers`.

- **UI/API**: <https://sands-of-time.apps.ocp.igou.systems>
- **Production** stays on the VPS (`sandsoftime.igou.io`); this is the
  in-cluster instance.
- Single replica on a RWO PVC (SQLite) with `Recreate` strategy — never
  scale above 1.
- The serve process keeps itself current (daily bulk update, startup
  repair); there is no CronJob.

## Bootstrap (once, after first sync)

The GHCR package is private. The pull secret is created out-of-band so no
credential lands in git (source: the same GHCR login the VPS uses):

```bash
oc create secret generic ghcr-pull -n sands-of-time \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson=<auth.json with a ghcr.io read:packages login>
```

TODO: move this to an ExternalSecret once a GHCR item exists in the
`lab_container_registries` 1Password vault (or make the GHCR package public
and drop `imagePullSecrets`).

Then hydrate the database (~80 min, resumable, throttled to 1 req/s against
the Weird Gloop bulk API):

```bash
oc apply -f applications/sands-of-time/sands-of-time-bootstrap-job.yaml
```

## Admin API (optional)

`/api/admin` stays disabled (503) until the token Secret exists:

```bash
oc create secret generic sands-of-time-admin -n sands-of-time \
  --from-literal=token="$(openssl rand -hex 32)"
```
