# Signed webhook receiver for OpenShift smoke tests

This optional test endpoint verifies HMAC signatures and logs JSON correlation metadata (event, action, repository, issue, delivery ID).
It does not launch an agent. Deploy the Forgejo demo and seed it first. From the
`forgejo-demo` directory, with cluster credentials active:

```bash
oc whoami --show-server
oc whoami
# Avoid a trailing newline in the Secret (command substitution strips it from
# WEBHOOK_SECRET, so both sides must receive the same bytes).
oc -n forgejo-demo create secret generic demo-receiver \
  --from-file=secret=<(tr -d '\n' < .state/webhook-secret) \
  --dry-run=client -o yaml | oc -n forgejo-demo apply -f -
kustomize build tests/receiver | oc -n forgejo-demo apply -f -
oc -n forgejo-demo rollout status deploy/demo-receiver --timeout=180s

export FORGEJO_URL=https://forgejo-demo.apps.ocp.igou.systems
export FORGEJO_TOKEN="$(cat .state/admin-token)"
export AGENT_TOKEN="$(cat .state/agent-token)"
export WEBHOOK_SECRET="$(cat .state/webhook-secret)"
export WEBHOOK_TEST_URL=http://demo-receiver.forgejo-demo.svc:39991/events
./tests/integration.sh --existing
oc -n forgejo-demo logs deploy/demo-receiver
```

Create `.state/webhook-secret` with `openssl rand -hex 32` first if needed, as in
README. Run the integration test on a fresh seed: it creates an issue and PR and
expects no preexisting ones. Look for JSON records with `event: issues` / `action: opened` and
`event: pull_request` / `action: opened` in receiver logs; an unsigned or incorrectly signed request returns HTTP 401.
After changing the Secret, restart the receiver deployment to reload its env.

For an automatic issue-opened check on an already seeded instance (no reset needed):

```bash
./tests/issue-webhook.sh
```

This configures the test receiver hook, opens a real issue, and waits up to 60 seconds
for a signature-verified event matching that exact repository and issue number, with
`event=issues`, `action=opened`, and a nonempty delivery ID. It prints the matching
record and closes the test issue on success; a failed check leaves the issue open
for investigation. It preserves other webhook destinations. It requires the same
`FORGEJO_URL`, `FORGEJO_TOKEN`, and `WEBHOOK_SECRET` exports shown above.

To test reset with integration restoration, export `WEBHOOK_URL=$WEBHOOK_TEST_URL`
and run `scripts/demo.sh reset --confirm-forgejo-demo`, then reload the token files.
Verify issues/PRs are empty, only `main` remains, the hook exists, the PVC UID changed,
and old tokens return HTTP 401. The receiver remains deployed across reset.

Cleanup after testing: delete the hook pointing to this receiver in the Forgejo UI,
then run `kustomize build tests/receiver | oc -n forgejo-demo delete -f -` and
`oc -n forgejo-demo delete secret demo-receiver`. This leaves Forgejo itself running.
