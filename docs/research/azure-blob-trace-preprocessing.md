# Azure Blob Trace Preprocessing

## Purpose

Create a canonical, chronological read trace from the Microsoft Azure
Functions Blob Access Trace 2020 without introducing platter-placement or
static-owner assumptions.

## Research Rationale

The Project Silica SOSP 2023 methodology replays read requests but not writes:
writes are buffered and disaggregated from the customer read path. Its
controller also groups requests for the same platter and services them
together once that platter is mounted. Therefore:

1. preprocessing retains every row where `Read == True` and size is known;
2. it does not deduplicate repeated blob accesses;
3. batch-wide merge is deferred until after objects are mapped to platters.

The released Azure CSV is not chronological. Stable ordering uses
`(Timestamp, SourceRow)`, preserving source order when timestamps tie.

## Transformations

| Transformation | Applied | Reason |
| --- | --- | --- |
| Verify source SHA-256 | Yes | Detect source drift or partial downloads |
| Parse with a CSV parser | Yes | Preserve structured fields correctly |
| Filter `Read == True` | Yes | Match the Silica read-path evaluation |
| Stable timestamp sort | Yes | Required for valid temporal batches |
| Normalize integral byte counts | Yes | Remove CSV float notation without changing values |
| Exclude reads with missing `BlobBytes` | Yes | Packing and service work cannot be inferred without size |
| Deduplicate blob versions | No | Repeated accesses are workload behavior |
| Merge requests | No | Merge is defined only within an experiment batch and platter |
| Pack blobs into platters | No | This is a placement assumption, not data cleaning |
| Assign platters to owners | No | This is an experimental variable |

Missing sizes are not replaced with zero, a mean, or a median. Such imputation
would create unsupported service-time and packing behavior. The manifest
reports the exact exclusion count so its materiality can be assessed.

## Identity and Later Mapping

`(AnonBlobName, AnonBlobETag)` identifies a blob version. It is not a physical
platter identifier. The later experiment must report:

- platter capacity;
- object packing policy;
- treatment of objects larger than one platter;
- static-owner placement policy; and
- batch definition.

Project Silica reports multiple TB of user data per platter but does not expose
one fixed production capacity. Capacity must therefore be swept or justified,
not silently inherited from an unrelated trace.

## Commands

Smoke validation:

```bash
python3 -m glass_sim preprocess-azure-blob
```

Full preprocessing:

```bash
python3 -m glass_sim preprocess-azure-blob \
  --config experiments/azure-blob-preprocessing/full.json
```

The full output and sample are local generated data and are excluded from Git.
The full manifest remains trackable.

## Pilot Batch

The first pilot follows the existing
`2016022211-LUN0-readonly-head-100k-sorted.csv` convention: select the first
100,000 eligible reads after timestamp sorting. This is a deterministic
count-based batch, not a selected peak interval.

```bash
python3 -m glass_sim extract-azure-batch
```

The Azure and LUN0 batches retain their natural time spans. They are not
rate-normalized. The pilot batch does not yet perform object-to-platter
packing or platter-level request merge.
