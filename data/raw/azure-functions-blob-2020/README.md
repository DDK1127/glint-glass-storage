# Azure Functions Blob Access Trace 2020

Official source:

https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsBlobDataset2020.md

Official download:

https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-blob-2020/azurefunctions_dataset2020_azurefunctions-accesses-2020.csv.bz2

License: CC-BY Attribution License. Publications using the trace should cite
the Faa$T SoCC 2021 paper listed on the official dataset page.

## Local Files

- `azurefunctions_dataset2020_azurefunctions-accesses-2020.csv.bz2`: complete
  compressed trace; excluded from Git.
- `SHA256SUMS`: checksum calculated after download.
- `sample_audit.json`: integrity, row-count, and first-million-row audit.

Keep the source compressed. Python's `bz2` module can stream the CSV without
creating a multi-gigabyte uncompressed copy.

The released CSV is not ordered by `Timestamp`. It must be externally sorted
before rows are divided into temporal or request-count batches. The checked
local copy contains 44,282,912 records excluding the header.

## Relevant Fields

- `Timestamp`: access time in milliseconds since the Unix epoch.
- `AnonBlobName`: anonymized blob identity.
- `AnonBlobETag`: anonymized blob version.
- `BlobBytes`: blob size in bytes.
- `Read` and `Write`: operation indicators.

For GLINT, `(AnonBlobName, AnonBlobETag)` identifies an immutable blob version.
It is not yet a platter ID. A separately documented packing policy must map
blob versions to platters before batch-wide platter merge is applied.
