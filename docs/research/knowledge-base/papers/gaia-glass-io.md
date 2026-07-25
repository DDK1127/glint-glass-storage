# GAIA: Glass-Aware I/O Middleware

paper_id: gaia-glass-io

## Metadata

- Source: `/Users/dongchengen/Desktop/Papers/Alumni/GlassScheduling_HungYuan (6).pdf`
- Venue/year: draft；bibliographic details need confirmation
- Review date: 2026-07-26
- Evidence confidence: medium；核心物理直覺明確，但 mapping、model calibration 與 component isolation 仍需補強。

## 30-second recall

Glass storage 的 X/Y mechanical motion 具有 acceleration、deceleration 與 direction-switch cost，Z optical focusing 則快得多。FCFS/SSDF 使用 distance proxy，無法反映真實 movement time 與軸向不對稱。GAIA 結合 zigzag placement、Z-axis-first placement 與 Shortest Moving Time First scheduling；paper report 最高約 62–82% latency reduction。

## Story chain

```text
Glass offers durable and dense archival storage
→ hybrid mechanical/optical access violates disk-style distance assumptions
→ short distance can still have long movement time
→ model acceleration, direction changes, and axis asymmetry
→ coordinate placement and movement-time scheduling
→ reduce average access latency
```

## Source-backed claims

- Conventional FCFS/SSDF 對 medium/large configurations 差距很小。
- Zigzag 的效果隨 glass size 增大而降低。
- SMTF+zigzag 額外帶來明顯 reduction；完整 GAIA 的最大數字約 62–82%。
- Evaluation 使用 Fujitsu block traces、queue size 10，以及 small/medium/large glass configurations。

## Mechanism map

| Component | Observation it addresses | Decision changed |
| --- | --- | --- |
| Zigzag placement | row reset and direction changes | logical-to-physical row order |
| Z-axis first | Z focusing is cheaper than X/Y movement | depth-first placement order |
| SMTF | distance is not movement time | next request selection |

## Reviewer inference

最大提升很可能主要由 Z-axis-first 貢獻。真正 paper claim 應是「physical-cost-aware placement/scheduling」，而不是三個元件同等重要。

## Evidence gaps

- 需要 clean ablation：FCFS、SSDF、zigzag only、Z-first only、SMTF only、joint。
- LBA trace 到 3D coordinates 的 mapping 可能預先決定 locality。
- Mechanical/optical model 需要實機或來源校準。
- 缺少 tail latency、throughput、fairness、online placement cost 和 metadata overhead。
- Queue-depth sensitivity 只在有限 workload 展示。

## Transfer hypotheses

- Library-level helper ranking 應使用 completion-time benefit minus full movement/congestion cost，不只 queue load 或 zone distance。
- Media-level placement 與 library-level shuttle routing 可能互相衝突，需要 joint cost。
- Cheapest falsification：找出 distance-only 與 calibrated movement-time ranking reversal。

## Reusable patterns

- `proxy-mismatch`
- `physical-cost-model`
- `placement-scheduling-codesign`
- `asymmetric-resource-axis`

## Update history

- 2026-07-26: Initial ingestion.
