REPO_ROOT := $(shell git rev-parse --show-toplevel)

.PHONY: validate
validate: ## Validate all kustomization.yaml files build successfully
	@find $(REPO_ROOT) -name kustomization.yaml -print0 | \
		xargs -0 -I{} sh -c 'dir=$$(dirname "{}"); reldir=$${dir#$(REPO_ROOT)/}; \
		if kustomize build --enable-helm "$$dir" > /dev/null 2>&1; then \
			echo "✅ $$reldir"; \
		else \
			echo "❌ $$reldir"; \
			kustomize build --enable-helm "$$dir" 2>&1 | tail -5; \
			exit 1; \
		fi'

.PHONY: clean
clean: ## Remove charts/ directories left behind by kustomize build (excludes .helm/charts)
	@find $(REPO_ROOT) -type d -name charts -not -path '*/.helm/*' -print -exec rm -rf {} + 2>/dev/null || true

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
