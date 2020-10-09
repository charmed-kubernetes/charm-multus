CHANNEL ?= unpublished
CHARM_BUILD_DIR ?= .
CHARM := multus

setup-env:
	@bash script/bootstrap

charm: setup-env
	@env CHARM=$(CHARM) CHARM_BUILD_DIR=$(CHARM_BUILD_DIR) bash script/build

upload: setup-env
ifndef NAMESPACE
	$(error NAMESPACE is not set)
endif

	@env CHARM=$(CHARM) NAMESPACE=$(NAMESPACE) CHANNEL=$(CHANNEL) CHARM_BUILD_DIR=$(CHARM_BUILD_DIR) bash script/upload

.phony: charm upload setup-env
all: charm
