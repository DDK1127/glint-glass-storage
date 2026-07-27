# Static Ownership Throughput Threshold

## 問題

當最忙 partition 擁有越來越多 post-merge physical tasks 時，static ownership 從什麼程度開始造成明顯 throughput loss？

## 控制條件

- 固定 8 個 static non-overlapping partitions、8 個 shuttles 與 8 個 readers。
- 每個 batch 固定 100,000 個 64 MiB requests。
- Batch-wide merge 後固定為 640 個 tasks。
- 共 16 個 concentration points，每點使用 10 個 paired seeds。
- 所有 points 使用相同 reader-relative coordinates 與 merge multiplicities。
- 不包含 Adaptive、work stealing、Zipf 或真實 trace。

## Throughput loss crossings

- 10% loss：最早出現在 hot-owner share 15.00%；實測 throughput loss 為 16.3%，stranded capacity 為 16.7%。
- 20% loss：最早出現在 hot-owner share 16.25%；實測 throughput loss 為 22.8%，stranded capacity 為 23.1%。
- 30% loss：最早出現在 hot-owner share 18.75%；實測 throughput loss 為 33.1%，stranded capacity 為 33.4%。
- 50% loss：最早出現在 hot-owner share 30.00%；實測 throughput loss 為 58.2%，stranded capacity 為 58.4%。

## Skew-impact knee

- 最大 normalized loss-over-skew gap 出現在 25.00% owner share。
- 此時 throughput loss 為 49.8%，stranded capacity 為 50.0%。
- 這是 sweep 內兼顧較低 skew 與較高 throughput loss 的代表點，不是系統的物理臨界點。

## 代表結果

- 25% hot-owner share：保留 50.2% throughput，損失 49.8%。
- 50% hot-owner share：保留 25.1% throughput，損失 74.9%。

## 解讀

本實驗不預設存在突然的物理斷層。圖中的 crossing 是相對 balanced case 的工程門檻。若曲線平滑下降，正確結論是 static ownership 在偏離均衡後便持續損失 throughput，而不是宣稱存在神奇臨界點。

## Figure guide

- `fig1_throughput_vs_owner_concentration`：單一 throughput 主線與 skew-impact knee。
- `fig2_why_throughput_drops`：同一 knee workload 的八個 shuttle working/idle timeline。
