# Windowed CBS No-Zone Study

This closed-batch experiment compares three policies over the same 640
batch-merged platter tasks and paired physical placements:

- `static_zone`: fixed two-level owner and reader; conflict-free by abstraction.
- `no_zone_coordinated`: global FIFO, nearest-idle shuttle, sequential route
  reservation.
- `no_zone_windowed_cbs`: the oldest small task window on each side is matched
  to shuttles by fetch completion, then planned with a constraint tree over
  continuous route segments. Reader selection minimizes estimated read
  completion.

The CBS variant is deliberately bounded. A constraint forbids one candidate
service from overlapping the conflicting continuous segment of another. This
is more conservative than standard CCBS unsafe-interval constraints and is not
an optimal CCBS implementation. If the node cap is reached, the window uses
sequential conflict-free reservation and records a fallback.

```bash
.venv/bin/python scripts/run_windowed_cbs_study.py \
  --config experiments/windowed-cbs/smoke.json
```

Full paired sweep:

```bash
.venv/bin/python scripts/run_windowed_cbs_study.py \
  --config experiments/windowed-cbs/full.json \
  --workers 4
```

The first question is whether joint small-window planning improves over the
existing Greedy No-Zone baseline without changing the batch work, physical
placement, reader/shuttle counts, or service-time model.
