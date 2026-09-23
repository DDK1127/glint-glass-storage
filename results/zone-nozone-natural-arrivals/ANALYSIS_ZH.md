# 真實到達時間：Static Zone / No-Zone

## 主圖要回答的問題

同一份 Azure 原始 requests，採用 zone 或讓最近的空閒 shuttle 跨區接手，使用者等待資料的時間差多少？圖一直接呈現 p99 latency 與 no-zone 的額外比例；圖二再解釋每次 physical service 的時間花在哪裡。

## 結果

| 長度 | Policy | 平均 latency | p99 | Physical services | 最後 request 後 read drain |
| --- | --- | --- | --- | --- | --- |
| 2 m | static_zone | 13.82 min | 29.44 min | 6264 | 30.81 min |
| 2 m | no_zone_coordinated | 26.38 min | 53.63 min | 3645 | 55.27 min |
| 16 m | static_zone | 20.54 min | 43.17 min | 4479 | 45.17 min |
| 16 m | no_zone_coordinated | 28.63 min | 57.48 min | 3410 | 58.33 min |
| 64 m | static_zone | 42.35 min | 88.25 min | 2530 | 92.47 min |
| 64 m | no_zone_coordinated | 51.25 min | 102.23 min | 2207 | 103.91 min |

## 最直接的觀察

- 2 m：no-zone 的 p99 比 static zone 高 82.1%。
- 16 m：no-zone 的 p99 比 static zone 高 33.2%。
- 64 m：no-zone 的 p99 比 static zone 高 15.8%。

## Observation 1：時間花在哪裡

- 2 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 12.4 秒完成讀取。
- 2 m / no_zone_coordinated：平均 latency 的 98.1% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 30.9 秒完成讀取。
- 16 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 18.6 秒完成讀取。
- 16 m / no_zone_coordinated：平均 latency 的 98.2% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 30.5 秒完成讀取。
- 64 m / static_zone：平均 latency 的 98.5% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 38.7 秒完成讀取。
- 64 m / no_zone_coordinated：平均 latency 的 98.3% 是 request 在 dispatch 前等待 shuttle；dispatch 後平均 51.6 秒完成讀取。

這表示自然 arrival replay 的 tail 主要不是單次 collision delay 直接構成，而是每次 service 的 movement/coordination 成本降低 drain rate，讓 queue 持續累積。完整 platter service 還包含 request 完成後的 unload、return 與 place；圖二和圖五刻意把 resource occupancy 與 request latency 分開。

## Observation 2：No-Zone conflict 多嚴重

- 2 m：86.4% physical services 遇到 coordination；受影響 service 平均增加 14.0 秒，所有 service 的 coordination-delay p95 為 29.6 秒。
- 16 m：72.1% physical services 遇到 coordination；受影響 service 平均增加 9.0 秒，所有 service 的 coordination-delay p95 為 18.1 秒。
- 64 m：64.6% physical services 遇到 coordination；受影響 service 平均增加 12.5 秒，所有 service 的 coordination-delay p95 為 23.9 秒。

2 m 時 conflict 主要出現在 fetch/rack access；panel 拉長後，rack-side coordination 降低，而 platter-to-reader delivery 變成較大的部分。這是目前 route-reservation 模型的結果，不等於真實硬體碰撞熱點。

在這個模型中，zone 在三種長度都較快；但差距隨 panel 變長而縮小。這支持一個有限度的說法：當 shuttle 活動集中在較短空間時，隔離路徑衝突的價值較高；空間拉長後，這項價值下降。實驗尚未找到 no-zone 反超的 crossover。

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
