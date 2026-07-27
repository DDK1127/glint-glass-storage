.PHONY: test smoke-azure-preprocess smoke-rq1 smoke-static smoke-threshold smoke-stealing smoke-adaptive smoke-ownership smoke-ownership-threshold

PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s tests -v

smoke-azure-preprocess:
	$(PYTHON) -m glass_sim preprocess-azure-blob

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

smoke-ownership:
	$(PYTHON) -m glass_sim static-ownership-motivation

smoke-ownership-threshold:
	$(PYTHON) -m glass_sim static-ownership-threshold
