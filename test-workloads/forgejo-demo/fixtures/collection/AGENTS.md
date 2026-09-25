# Demo collection contributor guide

- Keep changes small and scoped to the issue.
- Run `python3 -m unittest discover -s tests/unit -v` from the collection root.
- Preserve existing filter behavior unless the issue explicitly changes it.
- Add tests and update README when changing public behavior.
- Push a feature branch and open a PR against `main`, referencing the issue.
- Do not merge the PR or push directly to `main`.
