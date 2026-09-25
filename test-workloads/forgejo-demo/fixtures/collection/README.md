# Ansible Collection - demo.greetings

Scaffolded with ansible-core 2.21.4 using the standard Galaxy CLI:

```bash
ansible-galaxy collection init demo.greetings
```

The generated metadata, runtime template, plugin guide, and docs/roles directories
are retained. Metadata is filled in for this private demo; empty directories have
`.gitkeep` files so Git preserves them. A small `demo.greetings.greeting` filter
and unit tests are added as the starting point for the issue-to-PR task.

In a Jinja expression, `{{ 'Ada' | demo.greetings.greeting }}` produces `Hello, Ada!`.
Requires ansible-core 2.16 or later for Ansible use. The filter implementation and
unit tests use only the Python standard library.

```bash
python3 -m unittest discover -s tests/unit -v
ansible-galaxy collection build
ansible-galaxy collection install demo-greetings-1.0.0.tar.gz
```

## nginx role

`demo.greetings.nginx` installs, enables, and starts nginx on Rocky Linux 9 using
the package-provided worker account. See [role documentation](roles/nginx/README.md).
The demo feature request asks an agent to add a configurable worker UID.

Test with `PROVISIONER=docker make test` (Molecule, ansible-core, Docker, and
controller Python package `docker` required). The dependency step installs the
pinned `david_igou.molecule_provisioners` collection. The test container needs
privileged/systemd support and a writable cgroup mount.

Run `make lint` for the role and scenario lint checks.
