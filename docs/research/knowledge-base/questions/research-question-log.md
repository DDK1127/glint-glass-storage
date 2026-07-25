# Research Question Log

## RQ-GLASS-001 — Cost-aware helper selection

- Status: experimenting
- Question: Static-zone glass library 應如何選擇與限制 helpers，使 hot-zone completion gain 超過 repositioning、platter round trip、intermediate interference 與 ingress congestion？
- Existing support: GAIA 顯示 geometric distance 不是完整 movement cost；SMR paper 顯示 current-state proxy 可能不如 future cost；目前 local experiment 顯示 nearby helper 可能優於 coldest helper。
- Missing evidence: multi-helper contention、route reservation、assistance duration、return-to-owner cost。
- Cheapest next test: 在相同 hot queue 下比較 load-only、distance-only、full-cost donor ranking，控制 helper 數量並量 makespan、tail latency、aggregate travel。

## RQ-GLASS-002 — Assistance crossover rule

- Status: characterizing
- Question: Hotspot 持續多久、queue 差距多大時，work stealing 的收益才超過 helper 啟動與回復成本？
- Pattern basis: technology-crossover、analytical-switching-rule。
- Missing evidence: burst-duration distribution、helper arrival time、local shuttle service rate。
- Cheapest next test: sweep hotspot duration × queue skew × helper distance，找 decision boundary。

## RQ-GLASS-003 — Semantic request grouping

- Status: seed
- Question: Request lifetime、deadline、object popularity 或 multi-block relation 是否能比 LBA/queue length 更好地指導 Glass placement 與 scheduling？
- Pattern basis: semantic-gap、cross-layer-metadata。
- Risk: metadata cost可能高於 scheduling benefit，且 workload 未必提供穩定語意。
- Cheapest falsification: 使用 trace-derived labels 重播相同 requests，比較 decision 是否真的改變。

## RQ-GLASS-004 — Axis- and route-aware placement/scheduling co-design

- Status: seed
- Question: 在 library-level shuttle movement 與 media-level X/Y/Z access 同時存在時，局部最佳 placement 是否會增加全域 shuttle congestion？
- Pattern basis: placement-scheduling-codesign、asymmetric-resource-axis、physical-cost-model。
- Missing evidence: media-level latency 相對於 library movement 的比例，以及兩層 queue interaction。
- Cheapest falsification: 分別最佳化 media access、shuttle routing 與 joint objective，尋找 ranking reversal。

## RQ-ML-001 — Quality-preserving near-data execution

- Status: seed
- Question: Quantization、partitioning 或 approximate distance 在 PIM 上帶來的 acceleration，如何與 recall/accuracy 共同最佳化？
- Pattern basis: operation-aware-offload、semantic-partitioning、side-effect-accounting。
- Missing evidence: per-dataset quality sensitivity、transfer overhead、energy。
