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
        ws = self._workspace
        ref = self._guard(
            "OpenShell sandbox creation failed",''',
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
                         "PATH": "/home/igou/.opencode/bin:/home/igou/.local/bin:/usr/local/bin:/usr/bin:/bin"},''')
source.write_text(text)
