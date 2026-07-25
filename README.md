# GLINT Glass Storage

GLINT (Geometry- and Load-aware Inter-zone Navigation and Task Scheduling) is
trace-driven research code for studying static service zones, workload
imbalance, and locality-aware work stealing in a Project Silica-style glass
storage library.

## Current Research Status

The active repository contains three connected studies:

| Study | Question | Current result |
| --- | --- | --- |
| RQ1 natural skew | Does natural post-merge demand remain spatially skewed? | Randomized placement shows short bursts; sustained skew is placement-dependent. |
| Static baseline | What does fixed ownership cost under a hotspot? | Hot zones queue while other shuttle-reader resources become idle. |
| Work stealing | Does any idle helper provide the same benefit? | Nearby helpers recover more completion time per unit of added travel. |

The current story and evidence boundaries are documented in
[`docs/research/static-zone-hotspot-work-stealing.md`](docs/research/static-zone-hotspot-work-stealing.md).

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
glint-sim work-stealing
```

Run a full experiment by selecting its full config:

```bash
glint-sim rq1 \
  --config experiments/rq1-natural-skew/full.json
```

The equivalent explicit runners live in `scripts/`.

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

## Archive Policy

Archived files are not imported, tested, or referenced by the current
workflow. They preserve earlier single-reader, feeder-buffer, static-zone v1,
Zipf, and artificial temporal/batch-skew explorations. See
[`archive/README.md`](archive/README.md) before restoring any historical code.
