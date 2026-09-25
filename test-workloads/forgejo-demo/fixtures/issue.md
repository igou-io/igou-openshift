Add an optional `prefix` argument to the `demo.greetings.greeting` filter.

Acceptance criteria:

- `greeting("Ada")` still returns `Hello, Ada!`.
- `greeting("Ada", prefix="Welcome")` returns `Welcome, Ada!`.
- Leading/trailing whitespace is trimmed from both name and prefix.
- Existing tests pass and new tests cover a custom prefix and whitespace.
- README documents the optional argument with an Ansible/Jinja example.
- Open a pull request against `main` with `Closes #<this issue number>` in its body.

Run `python3 -m unittest discover -s tests/unit -v` from the collection root.
Do not merge the PR. No remote hosts or deployment are required for this task.
