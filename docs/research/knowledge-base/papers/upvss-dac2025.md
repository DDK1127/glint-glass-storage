# UPVSS: Vector Similarity Search on Near-Memory Processing

paper_id: upvss-dac2025

## Metadata

- Source: `/Users/dongchengen/Desktop/Papers/Alumni/UPVSS_JJ (3).pdf`
- Venue/year: DAC 2025；bibliographic detail inferred from related citation and should be confirmed
- Review date: 2026-07-26
- Evidence confidence: medium；real UPMEM evaluation is strong, but ANN quality and production-scale behavior are missing.

## 30-second recall

High-dimensional IVF search saturates CPU memory bandwidth as threads increase。UPVSS 將 cluster 均勻 striping 到所有 DPUs，host 選 nprobe clusters 並廣播 query，DPUs 執行 distance computation，只回傳 compact top candidates 給 host merge。Paper report search time 降低 30–46%，約 1.42–1.86× speedup。

## Story chain

```text
Vector search is dominated by high-volume distance reads
→ CPU thread scaling reaches DRAM bandwidth ceiling
→ UPMEM provides aggregate internal bandwidth but isolated small memories
→ partition IVF clusters across every DPU
→ offload simple distance work and return compact pairs
→ improve search time and scale with DPU count
```

## Source-backed claims

- FAISS-IVF profiling：超過約 8 threads 後 performance saturation，CPI/load latency 增加，DRAM bandwidth 接近峰值。
- Real system：dual Xeon Silver 4216、8 UPMEM DIMMs、1024 DPUs。
- Evaluation 維度包含 2048/3072/4096，並分析 tasklets、DPU count 和 nlist。
- Pipeline utilization 約在 12 tasklets 飽和。

## Mechanism map

| Component | Observation it addresses | Decision changed |
| --- | --- | --- |
| DPU-aware cluster partition | cluster skew leaves DPUs idle | placement across DPUs |
| Coordinator | DPUs cannot communicate directly | host/DPU orchestration |
| WRAM caches | 2KB transfers and small local memory | query/vector/result buffering |

## Reviewer inference

最有價值的不是 PIM 本身，而是用 IVF cluster semantics 保證每個 query 都能動員所有 DPUs。

## Evidence gaps

- 缺少 recall/accuracy 或與 baseline 結果等價性的證明。
- Synthetic high-dimensional data、1M vectors、1000 queries，離 production vector DB 規模仍遠。
- Index construction、updates、batching、tail latency、energy 未完整涵蓋。
- All-DPU broadcast 在高 QPS 可能成為新瓶頸。
- CPU baseline、host 規格與 quantization fairness 需更清楚。

## Transfer hypotheses

- 若 Glass workload 可分為 object groups，partition 應依 request semantics 保證資源 participation，而非單純均勻 LBA range。
- Cheapest falsification：對 skewed groups 比較 byte-balanced 與 semantic-balanced partition 的 utilization 和 tail latency。

## Reusable patterns

- `resource-saturation-first`
- `operation-aware-offload`
- `semantic-partitioning`
- `compact-result-return`

## Update history

- 2026-07-26: Initial ingestion.
