# READER: Joint SSD Management for Deep Recommendation Training

paper_id: reader-dac2022

## Metadata

- Source: `/Users/dongchengen/Desktop/Papers/Tutorial Papers 3/Codesign/DAC_2022_Chun-Feng (1) (1).pdf`
- Venue/year: DAC 2022
- Review date: 2026-07-26
- Evidence confidence: medium；方法與主要數據清楚，但 workload 與 ablation 有限制。

## 30-second recall

Recommendation training 以完整 feature 為讀取單位，但 SSD/LSM middleware 只看 KV/page，導致同一 feature 分散並讀入未使用資料。READER 把 feature access semantics 傳給 storage management，透過 recommendation-aware merger、pinner 與 metadata manager 改善 layout 和 cache usage。論文報告 read time 降低 20–38%、training throughput 提升 1.16–1.33×。

## Story chain

```text
SSD capacity supports large recommendation models
→ generic LSM layout cannot see feature-level access
→ one training read fetches 1.47–1.85× extra data
→ expose feature identity and reuse semantics
→ co-design merge and pin decisions
→ lower read time and improve training throughput
```

## Source-backed claims

- Baseline 讀取比實際使用量多 1.47–1.85×，read time 增加 1.53–2×，throughput 下降 22–31%。
- READER report：read time 降低 20–38%，throughput 提升 1.16–1.33×，距 paper-defined optimal within 12%。

## Mechanism map

| Component | Observation it addresses | Decision changed |
| --- | --- | --- |
| Rec-aware merger | feature items are split across storage structures | which items merge and colocate |
| Pinner | some feature data has higher reuse/value | what remains in fast memory |
| Metadata manager | storage lacks recommendation semantics | metadata exposed across layers |

## Reviewer inference

真正貢獻是「最小 cross-layer metadata 改變 storage decision」，而非推薦系統專用 cache 本身。

## Evidence gaps

- 主要使用 synthetic datasets 與 uniform updates。
- Merger、pinner 與 metadata 的獨立 ablation 不夠清楚。
- Storage metrics 強於完整 model convergence/time-to-quality 證據。

## Transfer hypotheses

- Glass request 若具有 object relation、deadline、popularity 或 batch membership，應先測試這些語意是否會改變 placement/scheduling ranking。
- Cheapest falsification：固定 request trace，只增加 semantic labels；若決策與結果幾乎不變，cross-layer design 不成立。

## Reusable patterns

- `semantic-gap`
- `cross-layer-metadata`
- `placement-scheduling-codesign`
- `claim-evidence-chain`

## Update history

- 2026-07-26: Initial ingestion.
