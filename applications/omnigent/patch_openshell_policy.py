"""Supply creation-time policy and executable paths for the devenv host image."""

from pathlib import Path

source = Path('/build/omnigent/onboarding/sandboxes/openshell.py')
text = source.read_text()
changes = [
    (
        '        ws = self._workspace\n        ref = self._guard(\n            "OpenShell sandbox creation failed",',
        '''        from pathlib import Path
        import yaml
        from google.protobuf.json_format import ParseDict

        policy = yaml.safe_load(Path(os.environ["OMNIGENT_OPENSHELL_POLICY"]).read_text())
        policy["filesystem"] = policy.pop("filesystem_policy")
        ParseDict(policy, spec.policy)
        claim_name = os.environ["OMNIGENT_OPENSHELL_CODEX_AUTH_PVC"]
        spec.template.driver_config.update({
            "kubernetes": {
                "volumes": [{
                    "name": "codex-auth",
                    "persistent_volume_claim": {
                        "claim_name": claim_name,
                        "read_only": False,
                    },
                }],
                "containers": {
                    "agent": {
                        "volume_mounts": [{
                            "name": "codex-auth",
                            "mount_path": "/codex-auth",
                            "read_only": False,
                        }],
                    },
                },
            },
        })
        ws = self._workspace
        ref = self._guard(
            "OpenShell sandbox creation failed",''',
    ),
    (
        '        click.echo(f"  → created {sandbox_name}")\n        return sandbox_name',
        '''        click.echo(f"  → created {sandbox_name}")
        try:
            self.run(
                sandbox_name,
                "test -f /codex-auth/config.toml || "
                "printf '%s\\n' 'cli_auth_credentials_store = \\\"file\\\"' "
                "> /codex-auth/config.toml",
            )
        except Exception:
            self._openshell().delete_sandbox(sandbox_name)
            raise
        return sandbox_name''',
    ),
]
for old, new in changes:
    if text.count(old) != 1:
        raise SystemExit('Pinned OpenShell launcher changed; review policy patch')
    text = text.replace(old, new)
old = 'env={"HOME": _SANDBOX_HOME},'
if text.count(old) != 3:
    raise SystemExit('Pinned OpenShell exec environment changed; review PATH patch')
text = text.replace(old, '''env={"HOME": _SANDBOX_HOME,
                         "CODEX_HOME": "/codex-auth",
                         "PATH": "/home/igou/.opencode/bin:/home/igou/.local/bin:/usr/local/bin:/usr/bin:/bin"},''')
source.write_text(text)
