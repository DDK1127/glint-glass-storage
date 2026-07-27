# Local Trace Data

Trace CSV files are intentionally excluded from Git. Current local files:

| Filename | Role |
| --- | --- |
| `2016022211-LUN0.csv` | Full one-hour LUN trace used by RQ1 |
| `2016022211-LUN0-readonly-head-100k-sorted.csv` | Earlier 100k-read subset |
| `2016022211-LUN0-readonly-head-100k-size-x1000-sorted.csv` | Historical size-scaled subset |
| `systor-traces-sample.csv` | Small historical sample |
| `systor-traces-sample-sorted.csv` | Sorted historical sample |

The active RQ1 full and smoke configs both expect
`data/2016022211-LUN0.csv`. Unit tests do not require external trace data.

## Azure Functions Blob Access Trace 2020

The Microsoft Azure Functions Blob Access Trace is stored locally under:

`data/raw/azure-functions-blob-2020/`

The compressed trace is intentionally excluded from Git. Dataset metadata,
download instructions, and its local checksum are kept in that directory.

This trace records blob accesses rather than physical glass-platter locations.
Experiments must therefore document both:

1. how immutable blob versions are packed into platters; and
2. how those platters are assigned to the eight static owners.

All requests in a batch that map to the same platter must be merged before
static-owner work is measured.

The canonical read-only trace generated from this source is stored locally
under `data/processed/azure-functions-blob-2020/`. The preprocessing stage
only filters and sorts requests. It deliberately does not deduplicate objects,
pack objects into platters, merge requests, or assign static owners.
