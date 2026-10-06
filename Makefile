REPO_ROOT := $(shell git rev-parse --show-toplevel)
PYTHON ?= python3

.PHONY: lint
lint: clean ## Lint all YAML files with yamllint
	yamllint -c .yamllint .

.PHONY: validate-manifest-files
validate-manifest-files: ## Validate one-object-per-file and manifest filenames
	$(PYTHON) scripts/validate_manifest_files.py

.PHONY: validate-kustomize
validate-kustomize: ## Validate all kustomization.yaml files build successfully
	$(PYTHON) scripts/validate_kustomize.py --lifecycle

# Kinds skipped because the datreeio CRDs-catalog schema is stale vs the live CRD:
#  - CoreProvider/InfrastructureProvider/IPAMProvider: catalog ships the deprecated
#    `manifestPatches` field but not the newer `patches` field that v1alpha2 supports.
#  - NVIDIADriver: catalog's nvidiadriver_v1alpha1.json lacks the `kernelModuleType`
#    field the operator added (used by the 580/595 side-by-side drivers; valid on the
#    live CRD), so `-strict` rejects it as an additional property.
# All verified against the live CRDs on cluster. Re-enable each when datreeio catches up.
KUBECONFORM_FLAGS := -strict -ignore-missing-schemas \
	-skip ClusterSecretStore,MachineSet,CoreProvider,InfrastructureProvider,IPAMProvider,NVIDIADriver \
	-schema-location default \
	-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
	-summary

.PHONY: validate-schemas
validate-schemas: ## Validate rendered manifests against K8s/OpenShift schemas
	$(PYTHON) scripts/validate_kustomize.py --lifecycle --schemas $(KUBECONFORM_FLAGS)

.PHONY: lint-helm
lint-helm: ## Lint all Helm charts under .helm/charts/
	@for chart in $(REPO_ROOT)/.helm/charts/*/; do \
		echo "--- $$chart ---"; \
		helm lint "$$chart" || exit 1; \
	done

.PHONY: validate-hermes-proxy
validate-hermes-proxy: ## Ensure Hermes bypasses Squid for the in-cluster API service
	@find $(REPO_ROOT)/applications/hermes-* -name '*.yaml' -type f -exec \
		awk '/- name: (NO_PROXY|no_proxy)$$/ { \
			if ((getline value) <= 0 || value !~ /(^|,)172[.]30[.]0[.]1(,|$$)/) { \
				printf "❌ %s:%d: Kubernetes API service IP missing from proxy bypass\n", FILENAME, FNR - 1; \
				failed = 1; \
			} \
		} END { exit failed }' {} +

.PHONY: test
test: lint lint-helm validate-manifest-files validate-hermes-proxy test-validation validate-schemas ## Run all standard validation checks (one render per Kustomization)

.PHONY: test-validation
test-validation: ## Run validation regression tests
	$(PYTHON) -m unittest discover -s tests -v

.PHONY: clean
clean: ## Remove charts/ directories left behind by kustomize build (excludes .helm/charts)
	@find $(REPO_ROOT) -type d -name charts -not -path '*/.helm/*' -print -exec rm -rf {} + 2>/dev/null || true

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
