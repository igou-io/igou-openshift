#!/usr/bin/env python3
"""Helm post-renderer: add hostUsers: false to the Deployment pod spec.

The ultraworkers chart has no passthrough for pod.spec.hostUsers (it is a
sibling of securityContext, not inside it), so we patch it in here.
"""
import sys
import yaml

docs = list(yaml.safe_load_all(sys.stdin))
for doc in docs:
    if doc and doc.get("kind") == "Deployment":
        doc["spec"]["template"]["spec"]["hostUsers"] = False
sys.stdout.write(yaml.safe_dump_all([d for d in docs if d is not None], default_flow_style=False))
