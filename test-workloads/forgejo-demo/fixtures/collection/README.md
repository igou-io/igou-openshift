# Ansible Collection - demo.greetings

Scaffolded with ansible-core 2.21.4 using the standard Galaxy CLI:

```bash
ansible-galaxy collection init demo.greetings
```

The generated metadata, runtime template, plugin guide, and docs directory are
retained. Metadata is filled in for this private demo. The collection's nginx role
was added with `ansible-creator` as the starting point for the UID feature request.
The collection name remains `demo.greetings` because that is the Galaxy-generated
name already seeded into the live repository.

Requires ansible-core 2.16 or later.

```bash
ansible-galaxy collection build
ansible-galaxy collection install demo-greetings-1.0.0.tar.gz
```

## nginx role

`demo.greetings.nginx` installs, enables, and starts nginx on Rocky Linux 9 using
the package-provided worker account. See [role documentation](roles/nginx/README.md).
The demo feature request asks an agent to add a configurable worker UID.
