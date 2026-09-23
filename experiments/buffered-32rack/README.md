# Fixed 32-Rack Feeder-Buffer Study

This pilot fixes 32 racks at 16 m, 32 rack-side shuttles, and 8 readers. Each
reader has four demand-driven input staging slots. Rack centerlines are 1 m
apart, exceeding the 0.65 m shuttle clearance. Reader-side loading is a
fixed station mechanism represented by serialized load/read/unload time.

[Architecture diagram](../../docs/diagrams/buffered-32rack-architecture.svg)

Policies:

- `static_8zone_end_to_end`: 8 shuttles, each owning four racks and carrying
  each platter through the complete reader cycle without feeder buffers.
- `rack_local_zone`: one shuttle remains on each rack.
- `shared_no_zone`: all rack shuttles share work; direct routes wait behind
  prior space-time reservations.

This is an architecture comparison: Static uses 8 end-to-end shuttles, while
the two buffered designs use 32 rack shuttles plus 8 fixed reader-side loaders.

```bash
.venv/bin/python scripts/run_buffered_32rack_study.py \
  --config experiments/buffered-32rack/full.json \
  --workers 4
```
