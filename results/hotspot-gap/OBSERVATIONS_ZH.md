# 熱區差距實驗：觀察（2026-10-05）

設定與事先登記的問題見 `experiments/hotspot-gap/config.json`。1 個 reader、N = 2/4/8 台 shuttle（Zone 每台負責 8/N 排）、B = N、32 m、read = 8 s；線上 Poisson 到達，到達率 = 同一 N、同一擁擠成本下「平均負載的 Zone」吞吐量的 75%；每組 5 seeds × 2400 requests，共 1500 runs。主要擁擠成本 0.5 s，0 s 為敏感度。Work stealing 依 Silica §4 重建，4 組參數都跑，每格取最好的一組。

## Q1 熱區讓 Zone 損失多少？

以熱區佔 47%（trace 的爆量水準）、熱區每 100 個 request 移動一次為例，Zone 的 p99 是平均負載時的：

| N | 2 | 4 | 8 |
| --- | ---: | ---: | ---: |
| p99 倍數 | 3.0× | 8.1× | 8.3× |

熱區固定不動時倍數更大（N=8 為 72×），因為熱區那一台長時間超載、佇列持續累積。**這類超載格的 p99 會隨實驗長度增加，不是穩態值，只能比較相對大小。**

## Q2 Work stealing 追回多少？

熱區 47% 時，work stealing（最佳參數）追回的差距比例：

| 熱區移動 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: |
| 每 100 個 request | 92% | 66% | 19% |
| 每 500 個 request | 94% | 51% | 21% |
| 固定不動 | 100% | 70% | 44% |

**每個 reader 配的車越多（分區越細），work stealing 追回得越少。** N=2 時幾乎完全追回；N=8 時，熱區移動快的情況只追回約兩成。

## Q3 為什麼 work stealing 在 N=8 不夠

以下皆為 N=8、熱區 47%、擁擠成本 0.5 s：

1. **熱區移動越快，追回越少**：固定 44% → 每 100 個 request 移動時 19%。觸發要等積壓超過門檻，熱區移走時幫手才剛到。
2. **借車造成擁擠**：每個 request 的路段等待從 Zone 的約 2–4 s 增加到 23–66 s，路段移動從約 44 s 增加到 51–53 s。同樣條件下若沒有擁擠成本（0 s），追回比例提高到 52% / 55% / 74%，代表擁擠吃掉了一大部分收益。Silica 論文也提到跨區移動「may create additional congestion」。
3. **借車變成常態，不是例外**：42–73% 的 request 由幫手處理。設計上的「備援」在熱區時成了主要工作方式。
4. **仍有車閒著**：有工作但不屬於自己區、只能閒著的時間，Zone 約 80–158 s／request，work stealing 仍有約 49–58 s／request（門檻與幫手上限所致）。
5. **沒有一組參數到處都好**：最佳參數在不同情境間換來換去（T1H1、T4H1、T4H3、T1H3），最好與最差的參數 p99 可差 1.5 倍以上（例：固定熱區 214 vs 332 分鐘）。

## 結論與限制

- 依事先登記的規則（差距 < 10% 則不成立）：N=4、N=8 時差距遠大於 10%，**動機成立**；N=2 時 work stealing 已接近平均負載，**在只有 2 台車的設定下動機不成立**。
- 因此問題的關鍵不是「library 小」本身，而是**一個 reader 由多少台 shuttle 共用**：reader 少、車多時，分區變細，work stealing 的缺點被放大。
- 限制：合成熱區（以 trace 校準強度）；超載格 p99 非穩態；work stealing 為依論文描述的重建版；擁擠成本為敏感度參數；模擬器未經實機校準。

圖：`fig_gap_zone_vs_ws.png`（N=8，Zone vs work stealing vs 平均負載）、`fig_gap_recovery_by_n.png`（追回比例 × 車數）。資料：`gap.csv`、`aggregate.csv`、`runs.csv`。

## 追加：Non-Zone 在同樣情境下（2026-10-05）

`scripts/run_hotspot_congestion_compare.py`，同一組 request、同一到達率；熱區 47%、每 100 個 request 移動、擁擠成本 0.5 s；5 seeds。結果在 `compare_aggregate.csv`。

| N | 做法 | p99（分鐘） | 每個 request 被擋次數 | 每個 request 路段等待 | shuttle 卡著等的時間比例 |
| --- | --- | ---: | ---: | ---: | ---: |
| 8 | Zone | 43.0 | 2.2 | 4 s | 2.9% |
| 8 | Zone + work stealing | 35.8 | 6.9 | 23 s | 16.8% |
| 8 | Non-Zone FIFO | 439.8 | 24.1 | 146 s | 65.3% |
| 2 | Zone | 23.6 | 0.1 | 0.1 s | 0.1% |
| 2 | Zone + work stealing | 9.0 | 1.1 | 4.5 s | 5.0% |
| 2 | Non-Zone FIFO | 12.9 | 2.1 | 8.3 s | 9.2% |

- 8 台時 Non-Zone 完成速率 2.15 req/min，低於到達率 3.57 req/min，系統跟不上（超載，p99 非穩態）。
- 平均負載（無熱區）時，8 台 Non-Zone 的 p99 也有 10.9 分鐘，Zone 為 5.2 分鐘。
- 敏感度：擁擠成本設為 0 時，8 台熱區下 Non-Zone p99 仍為 185 分鐘（Zone 38 分鐘），所以 Non-Zone 變慢不只是擁擠模型造成的。
- 瓶頸位置檢查（N=8、熱區 47%、3 seeds）：熱區那一排軌道在其熱區期間的忙碌比例為 Zone 52%、work stealing 60%、Non-Zone 27%。**熱區軌道沒有被塞滿**；Non-Zone 的等待主要發生在跨排移動共用的接駁段與 reader 入口。這也表示 Zone 與 work stealing 尚未用滿熱區那一排，仍有改善空間。
