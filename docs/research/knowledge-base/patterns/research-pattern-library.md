# Research Pattern Library

這裡保存會改變「怎麼找問題、怎麼設計方法、怎麼證明」的跨論文模式。Paper-specific implementation details 留在 paper cards。

## Problem discovery patterns

### semantic-gap

下層系統以 block、page、zone 或 byte 操作，但上層知道 feature、lifetime、phase、cluster 等會改變最佳決策的語意。

判斷問題：加入該語意後，在相同工作量下，最佳 placement、scheduling、caching 或 reclamation 決策是否不同？

Evidence: READER、SMR deduplication、NVM hotspot。

### proxy-mismatch

既有 policy 最佳化容易測量的 proxy，而非真正成本。典型例子是 GAIA 中的 geometric distance 與包含 acceleration、direction switch、axis asymmetry 的 movement time。

最便宜的證明是找出「proxy 排序 A 優於 B，但真實成本 B 優於 A」的 counterexample。

### technology-crossover

新硬體縮短主要操作後，周邊 software overhead 超過原本要隱藏的成本，使舊 abstraction 失效。

需要同時測量兩側成本並找 crossover point，而不是只顯示新 device 比舊 device 快。Evidence: Shadow Huge Page。

### resource-saturation-first

在提出 accelerator 或 PIM 方法前，先用 thread scaling、bandwidth、CPI、load latency 或 phase time 證明瓶頸。

這能回答「為什麼需要新硬體」以及「應該搬哪個 operation」。Evidence: UPVSS、UPForest。

### fixed-policy-trap

固定 allocation、granularity 或 threshold 在不同 phase/locality 下落入兩端 tradeoff。方法應先證明 workload state 真的變化，再設計狀態觀測與切換規則。

Evidence: NVM hotspot、Shadow Huge Page。

## Mechanism design patterns

### cross-layer-metadata

只傳遞足以改變決策的最小 metadata，避免把整個上層抽象搬進底層。

### future-cost-over-current-proxy

目前 invalid ratio、queue length 或 idle state 不一定代表長期成本。若未來 lifetime、assistance duration 或 return cost 可估計，應比較完整 future cost。

### phase-aware-adaptation

以 observation stage 取得 phase/locality，再調整 pin ratio、prefetch size 或 sync/async mode。必須量化偵測延遲、錯判與震盪。

### physical-cost-model

把 acceleration、direction changes、transfer lanes、contention 或 topology 寫入成本函數，並以實機或可信資料校準。

### placement-scheduling-codesign

Placement 決定未來 scheduler 看見的選項；scheduler 決定 placement 的價值。兩者合併時需分離 ablation，避免主要增益被單一元件掩蓋。

### asymmetric-resource-axis

當不同軸、memory domain 或 execution substrate 的成本差距大時，先沿便宜維度配置工作，再使用昂貴維度。

### operation-aware-offload

依 data volume、arithmetic intensity、instruction cost 和 communication cost 切分 algorithm，而非整體 offload。

### semantic-partitioning

依演算法真正使用的 semantic axis 分割資料，例如 IVF cluster 或 RF feature，而非均勻 byte range。

### compact-result-return

將大量獨立計算留在 near-data side，只回傳 top-k、statistics 或 partial aggregate，降低 host communication。

### hardware-constraint-as-method

隔離記憶體、無跨 DPU 通訊、弱 floating point 等限制，不只是 implementation issue；它們可推導 local sort、host aggregation 或 quantization 等方法。

### fixed-granularity-trap

小 granularity 造成過多 control events，大 granularity 搬運無用資料。以 locality 或 cost crossover 選擇中間值。

### analytical-switching-rule

用簡單、可解釋的 inequality 決定何時切換 policy。Equation 必須使用 runtime 可觀察量，並做 parameter sensitivity。

## Evidence patterns

### claim-evidence-chain

一個完整主張至少要能追到：

```text
characterization
→ mechanism
→ correct baseline
→ component ablation
→ sensitivity/scaling
→ side effects and quality
→ end-to-end result
```

### side-effect-accounting

Primary metric 改善時，同時量出被轉移的成本，例如 endurance 對 performance、latency 對 fairness、prefetch 對 energy、offload 對 accuracy。
