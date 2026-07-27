# Adaptive Zone Dense Skew Sweep 分析

## 實驗目的

這組實驗固定 10,000 個 64 MiB requests、batch-wide platter merge、
8 個 shuttle、8 個 active reader 與單一 hot zone，只改變分配到原始
hot zone 的 request 比例。

總共測試 40 個 skew 點。12.5% 至 30% 以及 50% 至 80% 的間距為
2.5%，可能發生轉換的 30% 至 50% 區間則縮小為 1%。每個點使用
10 個相同 seeds 比較 static 與 adaptive layout，共完成 400 組
paired runs。

## 主要結果

| Request skew | Post-merge hot work | Layout changed | Throughput gain | Static → adaptive stranded capacity |
| ---: | ---: | ---: | ---: | ---: |
| 33% | 17.80% | 0% | 0.00% | 29.8% → 29.8% |
| 34% | 18.01% | 20% | -0.30% ± 0.39 pp | 30.6% → 30.8% |
| 35% | 18.20% | 50% | -0.25% ± 0.33 pp | 31.3% → 31.5% |
| 36% | 18.44% | 90% | +0.03% ± 0.62 pp | 32.2% → 32.2% |
| 37% | 18.66% | 100% | +1.40% ± 0.75 pp | 33.0% → 32.1% |
| 40% | 19.29% | 100% | +5.81% ± 1.02 pp | 35.2% → 31.4% |
| 44% | 20.18% | 100% | +11.29% ± 1.11 pp | 38.0% → 31.1% |
| 50% | 21.82% | 100% | +22.96% ± 1.00 pp | 42.7% → 29.6% |
| 57.5% | 24.19% | 100% | +37.45% ± 1.14 pp | 48.3% → 29.5% |
| 80% | 37.98% | 100% | +123.62% ± 0.41 pp | 67.1% → 28.1% |

這裡的 ± 數值是跨 10 seeds 的 95% confidence interval。

## 圖表解讀

### Figure 1：Performance

Static throughput 隨 request skew 增加而持續下降，因為越來越多工作被
限制在同一個 owner zone。Adaptive curve 在 33% 以前與 static 完全
重疊，34% 至 36% 進入邊界選擇不穩定的轉換區，37% 以後才穩定分離。

高 skew 下 adaptive raw throughput 反而上升，不能單獨解讀成偏斜越高
越好。原因是更多重複 hot-platter requests 被 merge，physical service
總數同時下降。Static 與 adaptive 使用完全相同的 merged trace，因此兩條
曲線之間的差距才是 ownership/layout 帶來的效果。

### Figure 2：Work imbalance 與 stranded capacity

Static maximum-to-mean zone work ratio 從接近 1 持續增加到 3.04。Adaptive
在第一次有效調整後將比例控制在約 1.25 至 1.47，表示新增的 zone
ownership 確實把 hot-region work 分給更多 shuttle。

Adaptive stranded capacity 並沒有降到零。80% request skew 時，post-merge
hot work 仍占 37.98%，但 8-level、4-zone-per-side 的物理限制最多只能把
原本兩個 hot levels 拆給兩個主要 owner。這說明 adaptive rectangular
zones 能緩解 static ownership，但不能等同於完全自由的 work-conserving
scheduler。

### Figure 3：Gap to ideal

Static gap to its work-conserving lower bound 在 80% skew 達到 3.04x；
adaptive 降到 1.39x。剩餘差距來自離散 rack-level boundaries、每側固定
4 個 zone，以及每個 request 必須由單一 zone shuttle 完成完整 cycle。

### Figure 4：80% layout

Static `2/2/2/2` layout 將代表性 run 的約 37.8% work 放在一個 zone。
Adaptive hot side 改成 `1/1/3/3`，將相同 hot physical range 拆成兩個
1-level zones，兩個 shuttle 分別承擔約 17.4% 與 17.2% work。Cold side
維持 `2/2/2/2`，表示 optimizer 沒有移動不需要調整的區域。

### Figure 5：Discrete transition

Dense sweep 顯示三個不同事件：

1. 34% request skew：2/10 seeds 首次改變 layout，但平均 throughput
   反而下降 0.30%。
2. 37% request skew：10/10 seeds 都改變 layout，平均 gain 達 1.40%；
   此時原 hot zone 實際承擔 18.66% post-merge work。
3. 55% 至 57.5%：hot side 從以 `1/2/2/3`、`1/2/3/2` 為主，進一步穩定
   變成 `1/1/3/3`。

因此這不是一條單純的連續反應曲線。Workload skew 連續增加，但合法
boundary 只有少量離散選擇，所以系統呈現階梯式轉換。

## 研究解釋

這組設定下可以把 37% request skew 視為第一個「有淨收益的 operational
crossover」，但不能稱為普遍臨界點。更接近 physical bottleneck 的說法是：
當原 hot zone 的 post-merge work share 接近 18.7% 時，拆分 ownership
開始產生可測得的收益。

34% 至 36% 的結果也指出，adaptive controller 不應只要偵測到 skew 就立刻
改變 boundary。即使本實驗尚未計入 reconfiguration cost，過早調整仍可能
因 workload estimator 與實際 shuttle sequence 的差異而沒有收益。因此後續
方法應加入 minimum expected gain、hysteresis 或持續時間條件。

目前結果是 batch-oracle upper bound。下一步應在不同 batch size 與
working-set size 下重複這個 dense transition experiment，確認 18.7% 附近
的 post-merge work crossover 是否穩定，再加入 boundary reconfiguration
cost 與時間變動 workload。
