REPO_ROOT := $(shell git rev-parse --show-toplevel)

.PHONY: lint
lint: clean ## Lint all YAML files with yamllint
	yamllint -c .yamllint .

.PHONY: validate-kustomize
validate-kustomize: ## Validate all kustomization.yaml files build successfully
	@find $(REPO_ROOT) -name kustomization.yaml -print0 | \
		xargs -0 -I{} sh -c 'dir=$$(dirname "{}"); reldir=$${dir#$(REPO_ROOT)/}; \
		if kustomize build --enable-helm "$$dir" > /dev/null 2>&1; then \
			echo "✅ $$reldir"; \
		else \
			echo "❌ $$reldir"; \
			kustomize build --enable-helm "$$dir" 2>&1 | tail -5; \
			exit 1; \
		fi'

# CoreProvider/InfrastructureProvider/IPAMProvider skipped: the
# datreeio catalog ships the deprecated `manifestPatches` field but
# not the newer `patches` field that v1alpha2 actually supports
# (verified against the live CRD on cluster). Re-enable when
# datreeio/CRDs-catalog catches up.
KUBECONFORM_FLAGS := -strict -ignore-missing-schemas \
	-skip ClusterSecretStore,MachineSet,CoreProvider,InfrastructureProvider,IPAMProvider \
	-schema-location default \
	-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
	-summary

.PHONY: validate-schemas
validate-schemas: ## Validate rendered manifests against K8s/OpenShift schemas
	@find $(REPO_ROOT) -name kustomization.yaml -print0 | \
		xargs -0 -I{} sh -c 'dir=$$(dirname "{}"); reldir=$${dir#$(REPO_ROOT)/}; \
		echo "--- $$reldir ---"; \
		kustomize build --enable-helm "$$dir" 2>/dev/null | \
		kubeconform $(KUBECONFORM_FLAGS) || exit 1'

.PHONY: lint-helm
lint-helm: ## Lint all Helm charts under .helm/charts/
	@for chart in $(REPO_ROOT)/.helm/charts/*/; do \
		echo "--- $$chart ---"; \
		helm lint "$$chart" || exit 1; \
	done

.PHONY: test
test: lint lint-helm validate-kustomize validate-schemas ## Run all tests (lint, lint-helm, validate-kustomize, validate-schemas)

.PHONY: clean
clean: ## Remove charts/ directories left behind by kustomize build (excludes .helm/charts)
	@find $(REPO_ROOT) -type d -name charts -not -path '*/.helm/*' -print -exec rm -rf {} + 2>/dev/null || true

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
