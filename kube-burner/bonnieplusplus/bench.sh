#!/bin/bash

kubectl delete jobs,pvc -n bonnieplusplus -l name=bonnieplusplus --ignore-not-found
kube-burner init -c bonnieplusplus.yml --skip-log-file
