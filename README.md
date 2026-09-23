# GLINT Glass Storage

GLINT is trace-driven research code for studying capacity scalability, shuttle
movement, and static ownership in a Project Silica-style glass storage
library.

## Current Research Status

The current research is organized around two primary studies and supporting
static-ownership evidence:

| Study | Question | Current status |
| --- | --- | --- |
| Capacity scalability | What happens when passive capacity grows while readers and shuttles remain fixed? | Controlled sweeps isolate movement amplification and reader-time dilution. |
| Azure capacity scalability | Does the mechanism remain under trace-derived object sizes and reuse? | A paired head-100k Azure batch confirms the same capacity trend under controlled platter packing. |
| Static ownership | When do non-overlapping owners strand otherwise available resources? | Motivation and threshold studies quantify owner-level imbalance after request merge. |
| Trace placement checks | How sensitive are observed zones to address and object placement? | LUN-address and Azure pilots document the mapping assumptions separately from source traces. |
| Zone vs. No-Zone scheduling | Does shared shuttle mobility recover stranded capacity without losing locality? | Natural-arrival and paired closed-batch studies show the current greedy No-Zone policy lowers idle capacity but raises tail latency. |
| Bounded coordination | Can a small-window conflict solver improve the greedy shared-mobility baseline? | Windowed CBS and a collision-free virtual upper bound quantify routing headroom. |
| Feeder-buffer architecture | Can rack-local transport keep fixed readers supplied? | A fixed 32-rack pilot compares end-to-end static ownership, rack-local feeder transport, and shared No-Zone movement. |

Earlier adaptive-zone, work-stealing, and skew studies remain available as
supporting evidence. Superseded implementations live under `archive/` and are
not part of the active import path.

## Repository Layout

```text
glass_sim/       active simulator and experiment implementations
experiments/     full and smoke configurations for current studies
scripts/         explicit experiment runners and trace inspection tool
tests/           tests for the active model
docs/            current research notes, diagrams, and local paper references
results/         retained reports, summaries, and paper figures
data/            local traces; large CSV files are not committed
archive/         superseded code, configs, notes, and generated results
```

The separation follows the same practical idea used by mature systems
repositories: keep the core package, tests, tools, documentation/assets, and
specialized implementations visibly distinct.

## Setup

```bash
uv venv .venv
uv sync --no-editable
source .venv/bin/activate
```

## Run

The unified CLI defaults to smoke configurations:

```bash
glint-sim rq1
glint-sim static-baseline
glint-sim skew-threshold
glint-sim work-stealing
glint-sim adaptive-zone-upper-bound
glint-sim capacity-scalability
glint-sim azure-capacity-scalability
```

Run a full experiment by selecting its full config:

```bash
glint-sim rq1 \
  --config experiments/rq1-natural-skew/full.json
```

The equivalent explicit runners live in `scripts/`.

The active scheduling and architecture studies use explicit runners:

```bash
python scripts/run_zone_nozone_trace.py --smoke
python scripts/run_windowed_cbs_study.py
python scripts/run_virtual_nozone_study.py
python scripts/run_buffered_32rack_study.py
```

## Test

```bash
python -m unittest discover -s tests -v
```

## Data and Results

The current trace files remain under `data/` locally. They are intentionally
ignored by Git because the full trace exceeds GitHub's normal single-file
limit. See [`data/README.md`](data/README.md) for the required filenames.

Detailed CSV outputs are regenerable and ignored. Research reports, summary
JSON files, and figures under `results/` are kept as the reviewable evidence.

The latest advisor-discussion deck is
[`results/capacity-scalability/glint_capacity_zoning_discussion.pptx`](results/capacity-scalability/glint_capacity_zoning_discussion.pptx).

## Archive Policy

Archived files are not imported, tested, or referenced by the current
workflow. They preserve earlier single-reader, feeder-buffer, static-zone v1,
Zipf, and artificial temporal/batch-skew explorations. See
[`archive/README.md`](archive/README.md) before restoring any historical code.
