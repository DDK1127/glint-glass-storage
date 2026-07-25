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
