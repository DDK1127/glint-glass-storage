.PHONY: test smoke-azure-preprocess extract-azure-batch smoke-azure-static smoke-azure-capacity smoke-lun-address smoke-rq1 smoke-static smoke-threshold smoke-stealing smoke-adaptive smoke-ownership smoke-ownership-threshold smoke-capacity

PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s tests -v

smoke-azure-preprocess:
	$(PYTHON) -m glass_sim preprocess-azure-blob

extract-azure-batch:
	$(PYTHON) -m glass_sim extract-azure-batch

smoke-azure-static:
	$(PYTHON) -m glass_sim azure-static-zone-pilot

smoke-azure-capacity:
	$(PYTHON) -m glass_sim azure-capacity-scalability

smoke-lun-address:
	$(PYTHON) -m glass_sim lun-address-static-zone

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

smoke-capacity:
	$(PYTHON) -m glass_sim capacity-scalability
