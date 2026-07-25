.PHONY: test smoke-rq1 smoke-static smoke-stealing

PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s tests -v

smoke-rq1:
	$(PYTHON) -m glass_sim rq1

smoke-static:
	$(PYTHON) -m glass_sim static-baseline

smoke-stealing:
	$(PYTHON) -m glass_sim work-stealing
