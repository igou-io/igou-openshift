"""Give Omnigent's OpenShell launcher renewable OIDC service authentication.

The pinned upstream launcher only reads a CLI login token from disk. A server
Pod cannot safely depend on a human refresh token, so pass the supported SDK
ClientCredentialsAuth provider instead. Fail the image build if upstream code
changes and the patch no longer matches.
"""

from pathlib import Path


source = Path('/build/omnigent/onboarding/sandboxes/openshell.py')
old = '''        from openshell import SandboxClient, SandboxError

        try:
            self._client: SandboxClient = SandboxClient.from_active_cluster(cluster=cluster)
'''
new = '''        from openshell import ClientCredentialsAuth, SandboxClient, SandboxError

        client_id = os.environ.get("OMNIGENT_OPENSHELL_OIDC_CLIENT_ID")
        client_secret = os.environ.get("OMNIGENT_OPENSHELL_OIDC_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise click.ClickException("OpenShell service OIDC credentials are missing")
        auth = ClientCredentialsAuth(
            client_id=client_id,
            client_secret=lambda: os.environ["OMNIGENT_OPENSHELL_OIDC_CLIENT_SECRET"],
        )
        try:
            self._client: SandboxClient = SandboxClient.from_active_cluster(
                cluster=cluster, client_credentials=auth
            )
'''
text = source.read_text()
if text.count(old) != 1:
    raise SystemExit('Pinned Omnigent OpenShell launcher changed; review patch')
source.write_text(text.replace(old, new))
