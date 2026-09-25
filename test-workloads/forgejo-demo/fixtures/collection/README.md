# demo.greetings

A minimal Ansible collection with a `demo.greetings.greeting` filter.

In a Jinja expression, `{{ 'Ada' | demo.greetings.greeting }}` produces `Hello, Ada!`.
Requires ansible-core 2.16 or later for Ansible use. The filter implementation and
unit tests use only the Python standard library.

```bash
python3 -m unittest discover -s tests/unit -v
ansible-galaxy collection build
ansible-galaxy collection install demo-greetings-1.0.0.tar.gz
```
