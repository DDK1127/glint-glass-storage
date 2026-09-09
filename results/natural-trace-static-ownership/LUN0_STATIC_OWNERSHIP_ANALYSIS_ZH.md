# LUN0 Natural Trace under Static Ownership

## 問題

將 `2016022211-LUN0.csv` 保留自然 timestamp order 並做 window-local merge 後，
strict static ownership 的 work skew 有多大？相對完全平均的理想 lower bound，
throughput 會保留多少？

## 實驗契約

- Trace reads：1,399,055。
- Trace span：60.0 minutes。
- 每個 window 以 batch mode replay；timestamp 用來維持順序與切 time windows，
  window 內所有 tasks 在 time 0 ready。
- Static case 使用 exact 8-zone shuttle/reader simulator。
- Ideal balanced reference 將同一批 exact productive cycle time 完全平均除以 8；
  它是 throughput upper bound，不是 physically realizable policy。
- LUN trace 沒有真實 platter mapping，因此 randomized hash 與 contiguous-LBA
  sensitivity 必須分開解讀。

## Randomized-hash placement

| Scale | P50 busiest work | P95 busiest work | Aggregate throughput retained | Aggregate loss |
| --- | ---: | ---: | ---: | ---: |
| full trace | 12.6% | 12.6% | 99.2% | 0.8% |
| 5000 requests | 14.8% | 17.6% | 84.8% | 15.2% |
| 60 seconds | 13.8% | 14.8% | 91.0% | 9.0% |

## Contiguous-LBA sensitivity

| Scale | P50 busiest work | P95 busiest work | Aggregate throughput retained | Aggregate loss |
| --- | ---: | ---: | ---: | ---: |
| full trace | 18.1% | 18.1% | 69.0% | 31.0% |
| 5000 requests | 32.3% | 55.7% | 38.1% | 61.9% |
| 60 seconds | 24.6% | 38.1% | 49.6% | 50.4% |

## Evidence boundary

- 數值是 static batch-drain throughput，不是 online arrival-limited throughput。
- Randomized hash 是缺少真實 mapping 時的 primary assumption。
- Contiguous LBA 是 placement-locality sensitivity bound，不能當成 deployed Silica mapping。
- 完全平均 reference 不含 rebalancing travel、boundary change 或 work-stealing overhead。
