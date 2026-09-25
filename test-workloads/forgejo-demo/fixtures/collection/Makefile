export MOLECULE_GLOB := extensions/molecule/*/molecule.yml

.PHONY: test lint
test:
	molecule test --all

lint:
	ansible-lint roles/nginx extensions/molecule/nginx/*.yml
