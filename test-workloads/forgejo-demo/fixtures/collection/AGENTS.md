# Demo collection contributor guide

- Keep changes small and scoped to the issue.
- For nginx changes run `PROVISIONER=docker make test` and `make lint`.
- Use FQCN modules, `nginx_`-prefixed inputs and argument specs; verify HTTP and actual worker identity.
- Add tests and update README when changing public behavior.
- Push a feature branch and open a PR against `main`, referencing the issue.
- Do not merge the PR or push directly to `main`.
