.PHONY: test smoke-rq1 smoke-static smoke-threshold smoke-stealing smoke-adaptive

PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s tests -v

smoke-rq1:
	$(PYTHON) -m glass_sim rq1

smoke-static:
	$(PYTHON) -m glass_sim static-baseline

smoke-threshold:
	$(PYTHON) -m glass_sim skew-threshold

smoke-stealing:
	$(PYTHON) -m glass_sim work-stealing

smoke-adaptive:
	$(PYTHON) -m glass_sim adaptive-zone-upper-bound
