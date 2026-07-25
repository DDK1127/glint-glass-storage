# Access-Pattern-Aware Request-Centric Virtual Zones

> 目前較聚焦的研究主線請先參考 [Static-Zone Hotspots and Locality-Aware Work Stealing](static-zone-hotspot-work-stealing.md)。本文件保留較廣的 request-centric virtual-zone 構想，作為後續延伸。

## 文件定位

這份文件記錄目前研究的主要問題、動機、初步觀察、預期效果與後續實驗方向。現階段的重點不是先決定完整演算法，而是先建立一個合理、清楚且可被驗證的研究故事。

目前建議的核心方向是：

> 不再長期按照完整的實體儲存空間配置 shuttle 與 reader，而是根據目前真正需要服務的 glass requests，動態形成暫時性的 virtual service zones。

換句話說，我們希望從「partition the physical storage capacity」改成「partition the active workload」。

---

## 1. 研究背景

### 1.1 Glass storage library 的基本條件

我們考慮一個由下列元件組成的 glass storage library：

- Glass platters 長期存放在 rack slots 中。
- 每片 glass 的實體位置固定，讀取完成後會放回原本的位置。
- Shuttle 負責從 rack 取出 glass、送到 reader，並在讀取後將 glass 放回。
- Reader 負責 mount、seek 與實際資料讀取。
- 一個 request 所需要的資料可能只占 glass 的一部分。
- 同一片 glass 上的多筆 requests 可以合併為一次 physical glass fetch，再由 reader 完成所有相關讀取。
- Shuttle 的水平與垂直移動成本不同，且 pick、place、load、unload 都具有不可忽略的固定機械成本。

因此，一筆 logical request 的成本不能只用 request bytes 表示。真正影響系統完成時間的因素至少包含：

1. 需要搬運多少片不同的 glass。
2. 每片 glass 位於什麼位置。
3. Shuttle 到 glass 和 reader 的移動時間。
4. Pick、place、load、unload 的固定時間。
5. Merge 後 reader 真正需要讀取的資料量。
6. Reader queue 與 shuttle queue 的等待時間。

### 1.2 Project Silica 的 partitioning 方法

Project Silica 的 shuttle 在物理上可以於 panel 中自由移動，但完全共享的移動空間會形成複雜的 multi-agent path finding 與 congestion 問題。為了讓 traffic management 簡單且可預測，Project Silica 將 panel 分成與 active shuttles 數量相同的 rectangular logical partitions。

每個 logical partition：

- 包含一台 shuttle。
- 至少包含一個 read-drive slot。
- 在正常情況下只由自己的 shuttle 服務。
- Shuttle 通常不離開自己的 partition，以降低 reader ingress 與共享路徑上的 congestion。

需要特別注意的是，Project Silica 論文描述了 rectangular static partitions，但沒有明確說明每個 partition 必然等面積。因此，本研究不應直接宣稱「Microsoft 一定將 panel 平均切割」。更準確的描述是：

> 正常執行時，physical regions 與 shuttle service ownership 相對固定，並不會根據每一個當前 active request set 重新形成 partitions。

當 partition 之間的資料量不平衡超過 threshold 時，Project Silica 會使用 work stealing，讓 lightly loaded partition 的 shuttle 暫時進入 overloaded partition 取 glass。

參考資料：

- [Project Silica SOSP 2023 PDF](https://www.microsoft.com/en-us/research/uploads/prod/2023/09/ProjectSilica-SOSP23.pdf)
- [本地 Project Silica SOSP 2023 PDF](reference-papers/ProjectSilica-SOSP23.pdf)

---

## 2. 核心動機

### 2.1 Physical capacity 是固定的，但 active workload 是動態的

Static partitioning 所分割的是完整的 physical storage space。然而，一個實際 batch 通常不會同時存取 panel 中所有 glass，而只會碰到其中一小部分 active platters。

這會產生一個重要的不對稱：

- Storage capacity 長期存在，而且分布固定。
- Active requests 通常是 sparse、skewed 且隨時間改變的。

如果我們按照完整 storage capacity 建立長期 ownership，那麼每個 shuttle 負責的「空間大小」可能相近，但每個 shuttle 當下真正需要完成的「工作量」可能完全不同。

因此，equal capacity 並不等於 equal work；即使 physical zone 的面積設計合理，也無法保證未來的 access pattern 會平均落在每個 zone。

### 2.2 Spatial skew 會將系統能力限制在最忙的 partition

假設每個 static zone 都有自己的 shuttle 與 reader，而且不允許跨區服務。令 `W_z` 表示 zone `z` 中所有待完成 glass services 的預估工作量，則 static-zone batch completion time 大致由最忙的 zone 決定：

```text
T_static ~= max_z(W_z)
```

如果所有資源可以理想地平衡工作，則完成時間的樂觀下界接近：

```text
T_balanced >= sum_z(W_z) / N
```

因此，可以使用下列指標表示 static ownership 的潛在失衡程度：

```text
Imbalance potential = max_z(W_z) / mean_z(W_z)
```

當 requests 接近 uniform 時，這個值接近 1，static partition 可以同時保有低 congestion 與高 utilization。

當 requests 集中在少數 physical regions 時，hot partitions 的 shuttle 與 reader 會持續忙碌，而 cold partitions 可能提前完成並長時間 idle。此時，整個系統雖然仍有大量閒置資源，batch makespan 仍會被最忙的 partition 決定。

### 2.3 Access pattern 不只會偏斜，也會隨時間改變

Spatial skew 不一定是一個永久固定的 hotspot。可能出現的行為包含：

- 某一個 batch 集中讀取特定資料集合。
- 下一個 batch 轉而讀取另一組 glass。
- 一段時間內形成穩定 hotspot，之後逐漸冷卻。
- Burst workload 短時間集中在單一 physical region。
- Request merge 使 logical popularity 與真正的 physical fetch demand 不一致。

因此，只根據 library geometry 建立一次 partitions，難以持續適應 non-stationary access patterns。

### 2.4 Work stealing 是補救，不是重新組織 active workload

Work stealing 能改善 static partition 的極端失衡，因此本研究不能假設它完全無效。Project Silica 的 skew evaluation 顯示：

- 沒有 load balancing 時，tail completion time 超過 21 小時。
- 使用 work stealing 後，tail completion time 降至 11.5 小時。
- 但 tail travel time 從 29.4 秒增加至 76 秒。
- 理想化、沒有 shuttle overhead 的 baseline 為 7.5 小時。

這說明 work stealing 確實恢復了部分 flexibility，但也暴露了 static ownership 與跨區補救之間的代價。

從研究角度來看，work stealing 仍有以下值得探討的限制：

1. **Reactive behavior**：先保留固定 ownership，失衡達到 threshold 後才跨區處理。
2. **Task-level exception**：它改變個別任務的執行者，但沒有根據整個 active request set 重新組織服務區域。
3. **Cross-partition traffic**：多台 helper shuttles 進入 hot region 時，可能增加共享路徑、partition boundary 與 reader ingress 的壓力。
4. **Load signal**：論文描述的 trigger 監控各 partition 待讀取的 data volume；但相同 bytes 可能對應完全不同的 unique glass count 與 mechanical work。
5. **Temporal adaptation**：論文沒有詳細說明面對 shifting hotspot 時，threshold、reaction delay、oscillation 與 repeated stealing 的行為。

上述第 3 至第 5 點是研究假設與待驗證問題，不應在取得實驗證據前寫成已證實缺陷。

### 2.5 我們想改變的核心觀念

Static partition 的基本問題是：

> 它先分割所有 physical storage，再將 active requests 放入已經存在的 partitions。

本研究希望反過來：

> 先觀察目前 active requests 的位置與成本，再將這些真正需要被處理的 glass tasks 分配給 shuttle-reader resources。

這會形成 request-centric virtual zones：

- Hot region 可以被切成多個較小的 service groups，由多組資源平行處理。
- Cold region 如果沒有 active requests，不需要長期占用固定的 service capacity。
- 每個 batch 或 control epoch 可以依照新的 access pattern 重新形成 virtual ownership。
- Glass 的 physical location 不需要改變，也不需要進行 background data migration。
- 在單一 epoch 內可以維持 stable ownership，降低 per-request arbitrary crossing 與排程震盪。

這個研究的核心不是單純讓 shuttle 更自由，而是：

> 讓 shuttle 與 reader 的服務責任隨 active working set 改變，同時保留 spatial locality 與可控制的 traffic structure。

---

## 3. 研究問題

### 3.1 主要研究問題

> Can a glass storage library partition its active platter requests, rather than its physical storage capacity, to adapt to evolving access patterns while retaining spatial locality and predictable shuttle traffic?

中文表述：

> Glass storage library 是否能不再長期按照完整 physical capacity 綁定 shuttle，而是根據目前 active platter requests 動態形成服務區域，在改善負載平衡的同時，仍維持移動 locality 與可預測的 shuttle traffic？

### 3.2 子問題

1. Static partition 在什麼程度的 spatial skew 下開始出現明顯的 utilization imbalance？
2. Request merge 如何改變 logical request skew 與 physical glass-service skew 的關係？
3. 根據 active requests 形成 virtual zones，能否縮短 batch makespan 與 tail latency？
4. Load balancing 與 spatial locality 之間的 crossover 在哪裡？
5. Access pattern 改變多快時，重新配置仍然值得？
6. 相較於 work stealing，virtual zones 能否使用較少 cross-region travel，取得接近 shared-pool 的效能？
7. 當系統轉為 reader-bound 時，dynamic assignment 是否仍有幫助？

### 3.3 V1 的範圍

第一版先將問題限制為 batch-aware scheduling：

- 一個 batch 的 requests 同時可見。
- 先按照 platter 合併 requests。
- Glass physical locations 固定。
- Shuttle 與 reader 數量固定。
- 每個 virtual service group 暫時分配一組 shuttle-reader pair。
- Batch 執行期間先不頻繁重新分組。
- 下一個 batch 可以根據新的 access pattern 重新配置。
- 第一版 collision 使用 coarse conflict/overlap penalty，不直接處理完整 MAPF。

這個設定可以先回答最重要的問題：如果 scheduler 已經知道目前 pending batch 的需求，按照 active workload 分組是否比固定 physical partition 更合理？

Online sliding-window adaptation、prediction error 與 batch 執行中的 reconfiguration 留到後續版本。

---

## 4. 初步觀察

### 4.1 完整 static-zone baseline study

目前 panel baseline 使用：

- `4 rows x 2 sides = 8 zones`
- 每個 zone 一台 shuttle 與一台 local reader
- 10,000 logical requests
- 每筆 request 64 MiB
- Direct fetch、read、return-to-origin
- 5 個 paired random seeds
- Hot-region request share：`12.5%, 25%, 50%, 80%`
- Request merge 是預設且固定的 scheduling behavior

所有結果都先將同一片 glass 的 requests 合併，再排程 physical glass services：

| Metric | Balanced，12.5% hot share | Heavy skew，80% hot share |
|---|---:|---:|
| Mean physical glass services | 5,066 | 2,487 |
| Mean makespan | 5.97 h | 9.27 h |
| Logical throughput | 0.4656 req/s | 0.2996 req/s |
| Static capacity efficiency | 98.0% | 32.9% |
| Stranded zone-time capacity | 2.0% | 67.1% |
| Makespan / balanced-work lower bound | 1.02x | 3.04x |

Merge 會讓 hot working set 中的 repeated requests 共用 glass fetch，因此 heavy-skew physical services 比 balanced case 少。然而，即使 skew workload 獲得這個有利條件，它的 makespan 仍增加 55%，而 67.1% 的 zone-time capacity 在 hot work 尚未完成時處於 idle。

這個結果特別有意義：heavy-skew workload 真正要搬運的 glass 比 balanced workload 少約一半，但因為這些 merged glass tasks 集中在少數 static owners，反而需要更長時間才能完成。問題不是全系統工作總量太大，而是 active work 無法使用其他 idle shuttle-reader pairs。

這個現象支持以下初步觀察：

> 在 strict static ownership 下，aggregate resource capacity 並不能直接轉化為 batch throughput；最忙 partition 的完成時間才是主要限制。

完整結果：

- [Static baseline bottleneck analysis](../outputs/static-baseline-study/STATIC_BASELINE_BOTTLENECK_ANALYSIS.md)
- [Aggregate metrics](../outputs/static-baseline-study/aggregate_summary.csv)
- [Paper-style research story figure](../outputs/static-baseline-study/figures/fig7_research_story_panel.pdf)

### 4.2 目前觀察的限制

目前 study 已經完成的控制包含：

- Uniform 與 skew 使用 paired local level/slot coordinates。
- Request merge 在所有 workload 與後續 policy 中固定啟用。
- 同時記錄 logical requests 與 merge 後 physical glass services，避免混淆兩種 throughput。
- 使用 5 個 seeds，圖表回報 mean 與 variation。
- Shuttle return 後的位置會正確延續到下一個 task。

仍然存在的 evidence boundaries：

- Workload 是 synthetic，不是原始 trace-driven placement。
- Direct cycle 沒有 feeder prefetch 或 shuttle-reader pipelining。
- Strict zone 內只有一台 shuttle，因此不會發生 zone 內 collision。
- Shared pool、work stealing 與 proposed method 尚未放入同一個 corrected simulator 比較。
- 現在證明的是 static ownership 問題存在，尚未證明 request-centric virtual zones 一定能以低 congestion cost 解決它。

### 4.3 Trace-derived consecutive batches 與正確 merge scope

目前研究主線使用既有的 `2016022211-LUN0` read trace。實驗保留相同的 100,000 筆 requests、offsets、sizes、address-to-glass mapping 與 whole-trace per-zone totals，只重新排列 requests 如何依序進入 batches。

完整 trace 被組成 20 個連續 batches，每個 batch 有 5,000 logical requests。Merge 的語意固定為：

1. 收齊目前 batch 的 5,000 筆 logical requests。
2. 根據 physical `glass_id` 對整個 batch 分組。
3. 同一片 glass 的 request bytes 全部加總，只產生一次 physical glass service。
4. 使用該 batch 中最早出現的 request 作為 merged task priority。
5. Merge 不跨越 batch boundary；同一片 glass 若在下一個 batch 再被要求，下一個 batch 仍需重新 fetch。

三種 order 為：

1. **Normal batches**：按照 trace 原始 timestamp 順序，每 5,000 requests 形成一個 batch。
2. **Moderate skew**：每個 batch 目標讓 50% logical requests 來自一個 temporary hot zone。
3. **Severe skew**：每個 batch 目標讓 80% logical requests 來自一個 temporary hot zone。

因為 batch membership 會改變哪些 requests 可以互相 merge，三種 workload 的 physical service count 不必相同。這不是額外修改 workload，而是正確 batch-wide merge 自然產生的結果，因此必須同時報告 logical skew、post-merge work skew 與 physical services。

最後少數 batches 屬於 finite-trace residual drain；當各 zone queue 接近耗盡時，已沒有單一 zone 保有足夠 requests 維持 50% 或 80% target。因此主要以 P95 batch skew 表示 workload 強度，避免讓尾端排空行為改變定義。

### 4.4 核心觀察：Merge 減少搬片數，但 static owner 仍限制 hot batch

| Workload | P95 busiest-zone requests | P95 post-merge work | Physical services | Capacity efficiency | Makespan | Throughput | P99 latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Normal batches | 28.4% | 17.3% | 12,090 | 85.1% | 15.29 h | 1.817 req/s | 0.79 h |
| Moderate skew | 50.0% | 44.3% | 10,693 | 35.4% | 32.50 h | 0.855 req/s | 1.75 h |
| Severe skew | 80.0% | 64.1% | 8,783 | 22.1% | 42.79 h | 0.649 req/s | 2.39 h |

這組結果顯示 request merge 確實能吸收一部分 logical skew。Severe workload 中，最忙 zone 的 logical request share 為 80%，merge 後 active-work share 降為 64.1%，而 physical glass services 甚至比 normal 少 27.4%。

但 severe workload 仍需要 normal 的 `2.80x` completion time。這代表：

> Merge 可以減少需要搬運的 glass 數量，卻不能讓屬於 hot physical zone 的剩餘工作使用其他 static owners。即使全系統總 physical work 更少，只要每個 batch 的 critical work 集中在少數 zones，其他 shuttle-reader pairs 仍會提前完成並等待。

這比單純用 logical request count 描述 skew 更準確，也直接支持 merge-aware adaptive ownership：scheduler 應根據 merge 後的 unique glass tasks、bytes 與預估 mechanical cost 判斷 batch imbalance，而不是只看原始 request 數量。

目前 batches 依序執行，batch N+1 在 batch N drain 後開始，符合一次處理一個 batch 的語意。若未來要研究 overlapping online batches，則需要另一個 arrival-rate queueing experiment，不能直接沿用這裡的 makespan amplification。

- [Consecutive multi-batch analysis](../outputs/trace-batch-skew-static/TRACE_MULTI_BATCH_SKEW_ANALYSIS.md)
- [Batch skew and useful capacity](../outputs/trace-batch-skew-static/figures/fig1_batch_skew_and_capacity.pdf)
- [Performance comparison](../outputs/trace-batch-skew-static/figures/fig2_performance_comparison.pdf)
- [Temporary hotspots before and after merge](../outputs/trace-batch-skew-static/figures/fig3_temporary_hotspots_by_batch.pdf)
- [Batch-wide merge effect](../outputs/trace-batch-skew-static/figures/fig4_batch_merge_effect.pdf)
- [Paper-style multi-batch story](../outputs/trace-batch-skew-static/figures/fig5_multi_batch_research_story.pdf)

---

## 5. 研究假設與預期效果

### H1：Uniform workload 下不應破壞 static partition 的優點

當 active requests 接近 uniform 時，static zones 已經有合理的 load balance，而且具有短路徑與低 congestion 的優勢。

預期：

- Request-centric 方法的 makespan 應接近 static baseline。
- Dynamic grouping overhead 應控制在約 3% 至 5% 以內。
- 如果方法在 uniform workload 明顯退化，表示 locality 或 assignment stability 設計不足。

### H2：Spatial skew 下 virtual zones 可以降低 hot-region bottleneck

當 active glasses 集中在少數 physical regions 時，request-centric grouping 應將 hot tasks 分給多組 shuttle-reader pairs，而不是讓 cold resources 長時間 idle。

預期：

- Makespan 與 P95/P99 latency 下降。
- Shuttle 與 reader utilization standard deviation 下降。
- Hot-region completion time 更接近整體平均。
- 效能介於 static partition 與 ideal shared pool 之間。

### H3：Virtual zones 應比 unconstrained sharing 保有更好的 locality

只追求 load balance 可能把同一 shuttle 的 requests 分散到整個 panel，增加 travel 與 congestion。

預期：

- 加入 spatial compactness 後，總 travel time 低於純 earliest-finish shared scheduling。
- 效能可能略低於無 collision 的 ideal shared pool，但 route overlap 與 cross-region travel 應更少。

### H4：Merge-aware workload estimation 比 request count 或 bytes 更準確

一千筆 requests 如果集中在同一片 glass，可能只需要一次 physical fetch；相同 data volume 如果分散在一千片 glass，則需要大量 mechanical operations。

預期：

- Request-count-only policy 會高估高 merge locality region 的搬運工作量。
- Byte-only policy 不能正確反映 unique glass fetches。
- Glass-service-aware cost model 應有較準確的 predicted completion time。

### H5：Access pattern 變動速度會形成 adaptation crossover

如果 hotspot 維持時間很長，重新配置有足夠時間回收成本；如果 hotspot 快速移動，頻繁重新配置可能造成 oscillation 或額外 travel。

預期：

```text
Reconfigure only when:

expected completion-time reduction
>
assignment change + extra travel + congestion cost
```

短 phase 下保持原 assignment 可能較好；長 phase 下 adaptive assignment 應逐步接近 oracle。

### H6：Reader-bound 場景會限制 dynamic zoning 的收益

如果 reader throughput 或 load/unload 已經完全飽和，重新配置 shuttle 無法突破 reader capacity。

預期：

- Shuttle-bound 或 mixed-bound 場景有最大收益。
- Reader-bound 場景中，各方法 throughput 會接近。
- Dynamic method 的主要價值會轉為降低 tail latency 或 reader utilization imbalance，而不是提高 aggregate throughput。

---

## 6. 實驗規劃

### 6.1 實驗原則

所有 policy comparison 應遵守：

- 使用相同的 logical requests、request sizes、arrival times 與 physical glass locations。
- 使用相同的 shuttle、reader、rack geometry 與硬體參數。
- Request merge 必須在 policy scheduling 前完成，且所有 policies 使用相同 merge 結果。
- Synthetic workload 使用固定 seeds，正式結果至少執行 5 個 seeds。
- 同時報告 logical request metrics 與 physical glass-service metrics。
- Shared pool 如果未模擬完整 collision，只能定位為 optimistic upper bound。

### 6.2 Experiment 0：Simulator foundation audit

目的：先確認後續 policy comparison 不被 simulator behavior 影響。

需要驗證：

- Shuttle 完成 storage place 後，下一個 task 從正確位置開始。
- Reader 與 shuttle busy time 定義一致。
- 每筆 request 滿足合法事件順序。
- Merge 前後總 logical bytes 不變。
- 每片 glass 的 merged request count 正確。
- Static policy 不會跨越 ownership boundary。
- 所有 policies 使用完全相同的 workload instance。

### 6.3 Experiment 1：Strict static imbalance characterization

目的：單純證明 physical static ownership 在什麼條件下開始失衡，不先加入 proposed method。

設定：

- 8 static zones。
- Request merge 固定啟用，policy comparison 使用相同的 merged glass-task set。
- Hot-zone request share：`12.5%, 25%, 50%, 80%`。
- `12.5%` 對 8 zones 代表接近 uniform。
- Hotspot width：`1, 2, 4 zones`。
- 至少 5 seeds。

觀察：

- Makespan 對 hot fraction 的變化。
- `max zone work / mean zone work` 是否能預測 slowdown。
- Hot/cold zone completion gap。
- Shuttle/reader utilization imbalance。

### 6.4 Experiment 2：Policy comparison

比較：

| Policy | 目的 |
|---|---|
| Strict Static Zones | 最簡單的固定 ownership baseline |
| Static + Microsoft-style Work Stealing | 現有 load-balancing baseline |
| Request-Centric Virtual Zones | Proposed direction |
| Global Shared Pool | Optimistic flexibility upper bound |
| Offline Oracle Grouping | 已知完整 batch 時的理想 grouping upper bound，可選 |

主要問題：

- Proposed method 能回收多少 static imbalance loss？
- 與 work stealing 相比，是否減少跨區 travel 與 congestion exposure？
- 與 shared pool 相比，犧牲多少 throughput 來保留 spatial structure？

### 6.5 Experiment 3：Merge 與 active working set

目的：分離 logical popularity 與 physical glass fetch demand。

變因：

- Requests per glass。
- Unique glass count。
- Hot-region working-set size。
- Request bytes distribution。
- Batch size。

需要固定其中一項、改變另一項，避免 merge ratio 與 spatial skew 同時變化後無法解釋。

### 6.6 Experiment 4：Temporal access-pattern changes

目的：測試系統是否能適應 non-stationary workload。

Workload phases：

- Stable hotspot。
- Hotspot 依序在 zones 之間移動。
- Alternating two hotspots。
- Short burst followed by uniform traffic。
- Gradually drifting hotspot。

控制參數：

- Phase duration。
- Observation window。
- Reconfiguration interval。
- Hysteresis threshold。

觀察：

- Adaptation lag。
- Boundary/group changes 次數。
- Reconfiguration 前後 queue imbalance。
- 是否出現 oscillation。

### 6.7 Experiment 5：Bottleneck sensitivity

目的：確認方法在哪些硬體條件下真正有用。

Sweep：

- Reader throughput。
- Reader load/unload time。
- Shuttle count 與 reader count。
- Rack length。
- Vertical movement cost。
- Coarse conflict penalty。

預期找出：

- Shuttle-bound region。
- Reader-bound region。
- Mixed-bound crossover。
- Dynamic assignment 有效與無效的邊界。

---

## 7. 評估指標

### 7.1 Primary metrics

- Batch makespan。
- Throughput in logical requests/s。
- Throughput in physical glass services/s。
- Throughput in MiB/s。
- Latency P50/P95/P99。

### 7.2 Resource balance

- Shuttle utilization avg/max/std 或 coefficient of variation。
- Reader utilization avg/max/std 或 coefficient of variation。
- Per-group predicted and actual completion time。
- `max zone work / mean zone work`。
- Idle resource time while requests remain pending elsewhere。

### 7.3 Movement and congestion cost

- Total horizontal and vertical travel time。
- Total travel distance。
- Cross-region task ratio。
- Route-overlap/conflict count。
- Block or stop waiting time。
- Reader-ingress waiting time。

### 7.4 Adaptation overhead

- Number of virtual-zone reconfigurations。
- Tasks whose ownership changes。
- Reconfiguration decision time。
- Adaptation lag after hotspot change。
- Performance loss relative to offline oracle。

---

## 8. 預期結果與合理行為

| Workload | Strict Static | Work Stealing | Request-Centric Virtual Zones |
|---|---|---|---|
| Uniform | 應表現良好 | 少量或不觸發 | 應接近 static，不能明顯退化 |
| Moderate skew | Hot zone 開始形成 queue | 可改善但有跨區 travel | 應平衡 workload 並維持 compact groups |
| Heavy skew | Makespan 由 hot zone 主導 | 更多 helpers 進入 hot region | Hot tasks 應分成多個 service groups |
| Shifting hotspot | 固定 ownership 持續落後 | 依 threshold 反應 | 每個 epoch 或 batch 重新形成 groups |
| High merge locality | Physical fetch 數量大幅下降 | Stealing 需求可能降低 | Merge-aware model 應避免錯估 hotness |
| Reader-bound | Throughput 接近 reader limit | 改善有限 | 改善有限，主要降低 imbalance |
| Very small batch | Static overhead 最低 | 通常不需觸發 | Dynamic grouping 可能沒有收益 |

研究結果不應預設 proposed method 永遠最好。合理且可信的結果應該顯示：

- Static zones 在 balanced workload 下有明確價值。
- Dynamic virtual zones 在 persistent 或 batch-level spatial skew 下有明顯收益。
- Workload 太小、變動太快或 reader 完全飽和時，adaptation 收益會消失。
- Proposed method 的價值是擴大系統能有效使用 aggregate resources 的 workload range，而不是取代所有 static operation。

---

## 9. 初步方法構想

目前先保留三個候選方向，不在此階段過早固定演算法。

### Idea A：Request-Centric Virtual Zones，主要推薦

只針對目前 active glass tasks 形成 `K` 個 spatially compact、service-time-balanced groups，其中 `K` 對應可使用的 shuttle-reader pairs。

每個 task 的 assignment score 可以同時考慮：

```text
projected group completion time
+ spatial spread penalty
+ reader queue cost
+ route-overlap penalty
```

優點：

- 直接對應 batch access pattern。
- 不需要重新放置 glass。
- Hot region 可得到多組服務資源。
- Cold physical capacity 不會自動占用固定服務能力。
- 很適合先用 weighted greedy 或 balanced clustering 實作。

### Idea B：Demand-Shaped Physical Boundaries

仍保留完整且互斥的 physical zones，但依照近期 demand 調整 zone boundaries，使每個 zone 的預估工作量接近，而不是讓每個 zone 面積接近。

優點是較容易保留 partition-based collision control；缺點是受到 reader 位置、rectangular constraint 與 boundary granularity 限制，對高度集中的 hotspot 可能無法分配足夠資源。

### Idea C：Epoch Zones with Bounded Overflow

每個 epoch 先按照 active requests 形成 stable virtual zones。只有實際 workload 與 prediction 差距過大時，才允許少量 bounded overflow 或 neighbor assistance。

這是 virtual zoning 與 work sharing 的混合方法：

- 大部分 tasks 保留 epoch ownership。
- 只允許相鄰或有限數量 helpers。
- 使用 hysteresis 與 cooldown 避免反覆 reconfiguration。

此方向可以作為 Idea A 的後續完整化，而不是 V1 一開始就加入。

---

## 10. 新穎性邊界

Dynamic zoning 在一般 AGV 與 AMR warehouse 領域已有相關研究，因此「根據 load 動態改 zone」本身不足以構成研究貢獻。例如：

- [Dynamic Zoning of Industrial Environments with Autonomous Mobile Robots](https://arxiv.org/abs/2411.07382)

本研究需要強調 glass storage library 特有的問題組合：

- Glass 是 WORM media，physical placement 長期固定。
- Fetch cost 與 mechanical operations 可能高於單筆資料讀取成本。
- Requests 可按照 platter merge，因此 logical popularity 不等於 physical fetch demand。
- Reader 與 shuttle 是兩種不同且可能交替成為 bottleneck 的資源。
- 水平、垂直、stop/start 與 pick/place 成本不對稱。
- Archive read requests 適合以 batch 或較長 control epoch 進行資源規劃。
- 需要在 load balance、travel locality、reader assignment 與 congestion exposure 之間做聯合取捨。

初步貢獻可以定位為：

1. 定義 physical-capacity partition 與 active-workload partition 的差異。
2. 建立 merge-aware、mechanical-cost-aware 的 glass service workload model。
3. 設計 request-centric virtual zoning，讓 shuttle-reader responsibility 隨 batch access pattern 改變。
4. 量化 static、work stealing、virtual zoning 與 global sharing 在 spatial-temporal skew 下的 crossover。

正式宣稱 novelty 前，仍需要完成更完整的 robotic warehouse、AS/RS、multi-robot task allocation 與 dynamic zoning related-work review。

---

## 11. 目前假設與尚未決定的問題

### 已採用的初步假設

- 第一版以 batch-at-time-zero 為主。
- Request merge 是正常 scheduling behavior。
- Glass physical location 不改變。
- 第一版不實作完整 MAPF。
- Reader 與 shuttle 數量固定，policies 使用相同硬體資源。
- Dynamic policy 只改 task ownership 與 service grouping。

### 尚未決定

- Virtual zone 必須是嚴格 rectangular、connected region，或只需是 compact task group。
- 一個 virtual zone 是否固定綁定一個 reader。
- Reader assignment 與 shuttle grouping 是聯合決策或分成兩階段。
- Batch 內是否允許重新配置。
- Collision model 第一版使用 lane resource、coarse penalty 或 overlap proxy。
- Work stealing baseline 的 threshold 與 helper selection 如何忠實重建。
- Online version 使用 queue observation、EWMA 或 trace prediction。

這些問題不影響目前的核心動機，但會決定方法的實作複雜度與最終 contribution 範圍。

---

## 12. 建議的下一步

1. [Completed] 修正並驗證 panel static-zone simulator 的 shuttle state 與 paired workload generation。
2. [Completed] 建立以 request merge 為預設行為的 strict-static spatial-skew characterization。
3. 實作統一 policy interface，讓所有 policies 使用同一份 merged glass tasks。
4. 建立 Microsoft-style work-stealing baseline。
5. 先實作最簡單的 batch-aware weighted greedy virtual grouping。
6. 比較 load-balance-only、locality-only 與 combined objective。
7. 成功驗證 stationary skew 後，再加入 shifting hotspot 與 epoch adaptation。

在完成 work-stealing baseline 與最簡單 virtual grouping 前，不應過早加入複雜 prediction、learning-based policy 或完整 collision planning。下一個里程碑應回答：

> 當 batch 的 active glass locations 已知時，request-centric grouping 是否能在不顯著增加 travel 的前提下，改善 static physical ownership 的 hot-zone bottleneck？
