# This contains disorganized manifests I used to make an old AMD GPU work with Openshift/Ollama. I did not have a good time.

based off https://github.com/robertrosenbusch/gfx803_rocm.git

oc run pytorch   --image=igou-registry-quay-quay-enterprise.apps.sno.igou.systems/gfx803/rocm6_gfx803_pytorch:latest   -n ollama   --labels=app=pytorch   --restart=Never   --limits=amd.com/gpu=1   --requests=amd.com/gpu=1   --stdin   --tty   --command   --overrides='{"spec":{ "imagePullSecrets":[{"name":"igou-quay-gfx803-robotaccount"}] }}'   -- /bin/bash

debugging stuff
