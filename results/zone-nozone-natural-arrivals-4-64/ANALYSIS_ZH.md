# 真實到達時間：Static Zone / No-Zone

## 主圖要回答的問題

同一份 Azure 原始 requests，採用 zone 或讓最近的空閒 shuttle 跨區接手，使用者等待資料的時間差多少？圖一直接呈現 p99 latency 與 no-zone 的額外比例；圖二再解釋每次 physical service 的時間花在哪裡。

## 結果

| 長度 | Policy | 平均 latency | p99 | Physical services | 最後 request 後 read drain |
| --- | --- | --- | --- | --- | --- |
| 4 m | static_zone | 14.89 min | 31.66 min | 5869 | 33.18 min |
| 4 m | no_zone_coordinated | 24.62 min | 49.79 min | 3859 | 50.86 min |
| 8 m | static_zone | 16.85 min | 35.54 min | 5290 | 36.91 min |
| 8 m | no_zone_coordinated | 25.26 min | 50.83 min | 3769 | 51.38 min |
| 16 m | static_zone | 20.54 min | 43.17 min | 4479 | 45.17 min |
| 16 m | no_zone_coordinated | 28.63 min | 57.48 min | 3410 | 58.33 min |
| 32 m | static_zone | 27.78 min | 58.11 min | 3498 | 60.97 min |
| 32 m | no_zone_coordinated | 36.17 min | 72.43 min | 2848 | 73.83 min |
| 64 m | static_zone | 42.35 min | 88.25 min | 2530 | 92.47 min |
| 64 m | no_zone_coordinated | 51.25 min | 102.23 min | 2207 | 103.91 min |

## 最直接的觀察

- 4 m：no-zone 的 p99 比 static zone 高 57.3%。
- 8 m：no-zone 的 p99 比 static zone 高 43.0%。
- 16 m：no-zone 的 p99 比 static zone 高 33.2%。
- 32 m：no-zone 的 p99 比 static zone 高 24.6%。
- 64 m：no-zone 的 p99 比 static zone 高 15.8%。

## Observation 1：時間花在哪裡

- 4 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 13.4 秒完成讀取。
- 4 m / no_zone_coordinated：平均 latency 的 98.1% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 27.6 秒完成讀取。
- 8 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 15.2 秒完成讀取。
- 8 m / no_zone_coordinated：平均 latency 的 98.2% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 27.5 秒完成讀取。
- 16 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 18.6 秒完成讀取。
- 16 m / no_zone_coordinated：平均 latency 的 98.2% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 30.5 秒完成讀取。
- 32 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 25.3 秒完成讀取。
- 32 m / no_zone_coordinated：平均 latency 的 98.3% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 37.5 秒完成讀取。
- 64 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 38.7 秒完成讀取。
- 64 m / no_zone_coordinated：平均 latency 的 98.3% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 51.6 秒完成讀取。

這表示自然 arrival replay 的 tail 主要不是單次 collision delay 直接構成，而是每次 service 的 movement/coordination 成本降低 drain rate，讓 queue 持續累積。完整 platter service 還包含 request 完成後的 unload、return 與 place；圖二和圖五刻意把 resource occupancy 與 request latency 分開。

## Observation 2：No-Zone conflict 多嚴重

- 4 m：80.7% physical services 遇到 coordination；受影響 service 平均增加 10.3 秒，所有 service 的 coordination-delay p95 為 22.5 秒。
- 8 m：76.1% physical services 遇到 coordination；受影響 service 平均增加 8.8 秒，所有 service 的 coordination-delay p95 為 18.9 秒。
- 16 m：72.1% physical services 遇到 coordination；受影響 service 平均增加 9.0 秒，所有 service 的 coordination-delay p95 為 18.1 秒。
- 32 m：68.3% physical services 遇到 coordination；受影響 service 平均增加 10.5 秒，所有 service 的 coordination-delay p95 為 19.9 秒。
- 64 m：64.6% physical services 遇到 coordination；受影響 service 平均增加 12.5 秒，所有 service 的 coordination-delay p95 為 23.9 秒。

4 m 時 conflict 主要出現在 fetch/rack access；panel 拉長後，rack-side coordination 降低，而 platter-to-reader delivery 變成較大的部分。這是目前 route-reservation 模型的結果，不等於真實硬體碰撞熱點。

在這個模型的所有測試長度中，zone 都較快；但差距隨 panel 變長而縮小。這支持一個有限度的說法：當 shuttle 活動集中在較短空間時，隔離路徑衝突的價值較高；空間拉長後，這項價值下降。實驗尚未找到 no-zone 反超的 crossover。

No-zone 因等待較久，反而有更多 requests 能在派工前合併，因此 physical services 較少。即使得到這項優勢，它仍有較高 latency。不過這也表示兩邊不是只差 collision penalty，主結果必須解讀為兩個完整 policy 的比較。圖三把這項診斷獨立列出，不放進主故事。

## 如何模擬

保留 ArrivalMs、request 順序、bytes 與 object version，沒有壓縮時間或人工增加 hot requests。每次派工只合併已到達且尚未服務的同 platter requests；未來 request 不會提前完成。

8 readers、8 shuttles，兩個物理不連通 panel 各 4 個。Static 每兩層一個 owner，No-zone 可服務同側全部位置。No-zone 選當下最近的空閒 shuttle，再使用最近 reader；平距離時考慮可用時間。

主模型仍沿用資料放置假設：blob versions 以固定 seed 排序分裝到 virtual platters，再放到固定 side/level/相對水平位置。Placement 對兩 policy 完全相同，但不是 Azure 實際 glass address。

No-zone 以已預約路徑優先，檢查 direct 與中間高度繞行方案，選 earliest finish；holding、detour 會真的延後完成與下一次派工。

## 不能跳過的模型限制

- Optimistic unlimited off-rail holding at service locations with zero entry/exit cost; not physical collision avoidance.
- Strict static zone skips inter-zone collision checks by assumption; not equivalent geometric safety validation.
- Raw request size/order/timestamps preserved; synthetic object-to-platter placement shared across policies.
- Online merge changes physical service counts across policies; results are whole-policy effects, not isolated conflict penalty.
- A request arriving after dispatch is not added to that in-flight service; no persistent cache.
- Whole jobs reserve ahead with first-committed priority; this simple controller is not optimal.

特別注意：holding pocket 是模型新增的抽象。等待中的機器人被視為離開 rail，未計進出成本且容量無限。零 rail conflict 只表示預約的 rail segments 不重疊，不能宣稱機器人在真實 Silica 上已能安全避障。

不同 policy 的等待會改變可合併 requests 數量，所以 physical service 數和讀取 bytes 不必相同。主張應是這個整體 policy 的 latency 差異，不能把全部差異歸因為 collision。

這組採自然 arrivals，若 throughput 接近 trace 的輸入速率，應看 latency/backlog，而非聲稱兩邊服務能力相等。

## Reproduce

```bash
.venv/bin/python scripts/run_zone_nozone_trace.py
```

runs.csv 保留每個 seed；aggregate.csv 是平均與 sample SD；第一個 seed 的 audit 目錄包含每筆 request 完成時刻、每次派工與軌跡。
