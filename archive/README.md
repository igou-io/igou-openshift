# Archived examples

`misc/examples/` preserves the former standalone affinity demo manifests from
the repository's `misc/examples/` directory. Their content and internal paths
are unchanged. They have no app-of-apps registration or external caller.

Archived content is excluded from `make test` and Renovate. Before reusing an
example, review it against current APIs, move it outside `archive/`, repair its
references, and run the repository validation gate. Active Kustomizations and
Applications must not reference this directory.

Reusable dormant applications and components belong in `inactive/`, where
validation and dependency updates continue.
