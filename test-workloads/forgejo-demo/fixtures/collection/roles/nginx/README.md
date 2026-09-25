# demo.greetings.nginx

Installs the distribution nginx package and enables/starts its service. The baseline
uses the package's configuration and nginx worker account; runtime UID is not yet
configurable. Scaffolded with `ansible-creator add resource role nginx`.

Requirements: Rocky Linux 9 (EL9), ansible-core >=2.16, package repository access,
a service manager, and root privileges. No firewall or TLS configuration is included.

| Variable | Default | Purpose |
| --- | --- | --- |
| `nginx_service_enabled` | `true` | Enable the service at boot; it is always started. |

```yaml
---
- name: Install nginx
  hosts: webservers
  become: true
  roles:
    - role: demo.greetings.nginx
```

Repeated convergence is idempotent. Check mode works for an existing installation;
on a fresh host the service task may fail because package installation is simulated.
Rollback/uninstall is outside this role's scope. License: MIT. Author: Demo Maintainer.
