# Static Ownership 動機實驗

## 研究問題

等面積 partition 可以平均分配儲存空間，但它是否也能讓每個 batch 在 merge 後的 physical work 平均？

## 控制方式

- 固定 8 個 non-overlapping partitions、8 個 shuttles 與 8 個 active readers。
- 每個 case 都有 640 個 64 MiB unique platter targets，使用 10 個 paired seeds。
- 三個 cases 使用相同的 reader-relative local coordinates；只改變 target 的 owner。
- 補充實驗把 10,000 個 logical requests 平均配對到同一批 640 個 targets，再做 batch-wide merge。
- 不包含 Adaptive、work stealing、Zipf、boundary movement 或真實 trace。

## 結果

### Balanced `80/80/80/80/80/80/80/80`

- Busiest-owner task amplification：1.00x。
- Unique-task system drain / balanced：1.00x；stranded capacity：2.7%。
- Logical-request-plus-merge system drain / balanced：1.00x；stranded capacity：1.8%。

### Moderate `160/69/69/69/69/68/68/68`

- Busiest-owner task amplification：2.00x。
- Unique-task system drain / balanced：1.95x；stranded capacity：50.2%。
- Logical-request-plus-merge system drain / balanced：1.97x；stranded capacity：50.1%。

### Strong `320/46/46/46/46/46/45/45`

- Busiest-owner task amplification：4.00x。
- Unique-task system drain / balanced：3.90x；stranded capacity：75.0%。
- Logical-request-plus-merge system drain / balanced：3.93x；stranded capacity：75.0%。

## 解讀

這個結果隔離出 static ownership 的基本機制：總 physical work 沒有減少，但工作集中到單一 owner 後，其他 partition 的 shuttle 提早 idle，batch 仍必須等待最忙 owner 完成。Request merge 只合併同一 platter 的重複請求，不會把 merge 後的 platter task 重新分配給其他 owner。

本實驗只證明這個 causal mechanism，不宣稱 moderate 或 strong distribution 在 production Silica 中出現的頻率。真實 placement 與 trace prevalence 應在下一階段另外驗證。

## 圖表

- `fig1_equal_area_unequal_work`：normalized completion 與 moderate timeline。
- `fig2_merge_does_not_balance_ownership`：merge 前後的 ownership slowdown 與 stranded capacity。

## 驗證

- 60 runs 全部維持 640 個 physical tasks。
- Logical case 精確保留 10,000 requests 並 merge 成 640 tasks。
- 每片 platter 只有一個 owner，沒有 partition overlap。
- Completion time 與 stranded capacity 隨 owner imbalance 單調增加。
