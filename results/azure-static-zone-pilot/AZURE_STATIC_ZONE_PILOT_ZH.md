# Azure 100k Batch Static-Zone Pilot

## 問題

在相同 100,000 筆真實 Azure Blob reads 下，static non-overlapping
ownership 造成多少 post-merge work imbalance？

## Mapping 範圍

- `Uniform object hash`：保守 baseline；blob version 均勻 hash 到
  6,400 個 panel slots。
- `Application owner affinity`：placement-correlation sensitivity；每個
  blob version 依第一次出現的 application 限制在單一 static owner。
  這不是 production placement 的宣稱。
- 兩者各自與「相同 merged physical work 的 work-conserving ideal」比較。
  因為 mapping 會改變 merge cardinality，不直接用兩者 raw throughput
  相減來宣稱 static-zone gain。

## Dataset 如何處理

1. 從原始 Azure Functions Blob Access Trace 保留 `Read == True` 且
   `BlobBytes` 已知的紀錄，再依 timestamp 穩定排序。
2. 取排序後最前面的 100,000 筆 reads；沒有挑選 hotspot、application、
   region 或 peak interval。
3. 保留所有重複 request，不預先 deduplicate。這個 batch 包含
   79,751 個 unique blob versions。
4. 實驗才將 blob versions 映射到 synthetic platter slots，並在整個
   batch 內合併落在同一 platter 的 requests。
5. 100,000 筆 requests 全部視為同一個已到達的 batch；原本約四小時的
   arrival spacing 不用來模擬 queueing。

原始下載檔與 canonical read trace 都沒有被覆寫。Platter mapping 與
application-owner affinity 是實驗模型，不是 Azure dataset 提供的欄位，
也不是 production Silica placement 的宣稱。

## 結果

| Placement | Max logical share | Max post-merge work share | Work max/mean | Throughput loss vs own ideal |
| --- | ---: | ---: | ---: | ---: |
| Uniform object hash | 14.12% | 12.54% | 1.003x | 0.31% |
| Application owner affinity | 61.07% | 16.93% | 1.354x | 25.09% |

Uniform hashing touches approximately
6400 physical platters and nearly removes
owner-level work skew. Static ownership alone is therefore not a strong
bottleneck for this batch under well-dispersed placement.

When access affinity and physical ownership are correlated, logical demand is
highly concentrated. Batch-wide merge reduces that concentration substantially,
but does not remove it: the average post-merge busiest-owner work share remains
16.93%, compared with the balanced
12.5%. Static ownership then retains
74.91% of the same-work ideal
throughput on average. Across the 10 deterministic placement seeds, the
static throughput loss ranges from
13.96% to
41.90%.

## 圖表讀法

- Figure 1 只回答「static ownership 損失多少 throughput」。越低越好。
  每個 placement 都與它自己相同 merged work 的 ideal 比較。
- Figure 2 直接畫出 representative seed 的 8 個等面積 static zones。
  完全平衡時每個 zone 應承擔 12.5% work；提早完成的 cold zone
  無法協助仍然 busy 的 zone。

## 可支持的結論

這個 pilot 支持條件式主張：access skew 本身不足以證明 static zones
有問題；真正的風險是 access popularity 與 physical ownership
correlated。下一階段應在多個連續 batches 與不同 affinity width 下驗證
這個條件的發生頻率，而不是只展示單一最壞案例。
