PYTHON ?= python3
SRC := src
export PYTHONPATH := $(CURDIR)/$(SRC)

.PHONY: test integration dist zipapp clean

test:
	$(PYTHON) -m unittest discover -s tests -t tests -v

# Run against the live system (root=/) into a throwaway store.
integration:
	@store=$$(mktemp -d); \
	$(PYTHON) -m apt_diff.cli --store $$store init && \
	$(PYTHON) -m apt_diff.cli --store $$store check && \
	$(PYTHON) -m apt_diff.cli --store $$store show latest && \
	$(PYTHON) -m apt_diff.cli --store $$store log; \
	rm -rf $$store

# Single-file zero-install executable (works over ssh/scp to any Pi/Debian).
zipapp:
	$(PYTHON) -m zipapp $(SRC) -o dist/apt-diff \
		-m "apt_diff.cli:main" -p "/usr/bin/env python3" --compress
	chmod +x dist/apt-diff
	@echo "Built dist/apt-diff — copy anywhere, run directly."

dist: zipapp

clean:
	rm -rf dist build src/*.egg-info .pytest_cache
