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
