# UPForest: Random Forest Training on Real PIM

paper_id: upforest-tetc2025

## Metadata

- Source: `/Users/dongchengen/Desktop/Papers/Alumni/UPForest_YiPeng.pdf`
- Venue/year: IEEE TETC draft, 2025
- Review date: 2026-07-26
- Evidence confidence: medium；real hardware 與 phase characterization 有說服力，但 ML evaluation 和 configuration realism 需補強。

## 30-second recall

Random Forest training 的 split trial 反覆掃描資料，約佔 tree construction 85–90%，並使 CPU DRAM bandwidth 很快飽和。UPForest 讓 DPUs 做 data-heavy local split statistics，CPU 做 arithmetic-heavy Gini 與 split selection；feature-based partition、local WRAM sort 與 quantization 避免跨 DPU communication 和弱 arithmetic。

## Story chain

```text
RF training repeatedly scans bootstrap data
→ split trials dominate time and saturate CPU bandwidth
→ UPMEM has bandwidth but isolated MRAM and weak arithmetic
→ decompose by operation character
→ DPU local statistics + CPU Gini + feature partition
→ reduce split and total training time
```

## Source-backed claims

- Ranger profiling：超過約 4 個 concurrent trees 後 bandwidth saturation。
- Split trial 約佔 tree-building time 85–90%。
- HIGGS/HEPMASS/SUSY 上，paper report 相對多個 baselines 的 total execution reductions 約 11–75%，依 dataset/baseline 而異。
- int16/int32 OOB error 與原設定接近，int8 較差。

## Mechanism map

| Component | Observation it addresses | Decision changed |
| --- | --- | --- |
| CPU/DPU task allocation | DPUs weak at division/floating point | operation placement |
| Feature-based partition | split trial operates by feature | data layout |
| Local WRAM sort | global inter-DPU sort is expensive | sort scope |
| Quantization | MRAM/WRAM and arithmetic are constrained | representation |

## Reviewer inference

這篇示範「hardware limitations 推導 algorithm decomposition」；正確問題不是能否 offload RF，而是哪個 associative partial result 可以 local compute、global merge。

## Evidence gaps

- XGBoost 與 Random Forest 並非完全相同演算法，end-to-end 比較需避免 apples-to-oranges。
- 主要 evaluation 的 tree count 偏少，depth 70 也需要解釋。
- 需要更多 feature counts/cardinalities、classes、forest size 和 convergence curves。
- 缺少 energy、initial transfer、preprocessing/quantization cost。
- 「no accuracy loss」需要 error bars、seeds 或 statistical test。
- Paper 內 UPMEM capacity numbers 與 figure references 有 draft inconsistencies。

## Transfer hypotheses

- Glass simulator/optimizer 也應按 operation character 拆分：route planning、cost estimation、queue decision 可能適合不同 execution layer。
- Cheapest falsification：量出每個 phase 的 data movement、compute intensity 與 synchronization，再決定是否值得平行化。

## Reusable patterns

- `resource-saturation-first`
- `operation-aware-offload`
- `semantic-partitioning`
- `hardware-constraint-as-method`

## Update history

- 2026-07-26: Initial ingestion.
