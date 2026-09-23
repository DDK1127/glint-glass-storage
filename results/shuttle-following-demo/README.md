# 同向追近：減速跟車 micro-experiment

這個案例使用分段解析運動方程，觀察已在行駛的兩台 shuttle 同向追近。前車 A 維持 1 m/s，後車 B 原本為 2 m/s，初始中心間距 4 m，最低中心間距假設為 2 m（包含車體與淨空），後車減速度為 1 m/s²。

## 如何避開衝突

兩台的相對速度為 1 m/s。後車降到與前車同速需要 1 s，期間仍會追近 0.5 m，因此要在間距剩 2.5 m 時開始煞車，不能等剩 2 m 才反應。

| 時間 | 前車 A | 後車 B | 中心間距 |
| --- | --- | --- | --- |
| 0–1.5 s | 1 m/s | 2 m/s | 4 → 2.5 m |
| 1.5–2.5 s | 1 m/s | 2 → 1 m/s，持續減速 | 2.5 → 2 m |
| 2.5–8 s | 1 m/s | 1 m/s 跟車 | 2 m |

B 通過 x=10 m 的 checkpoint：單獨行駛需 5 s，跟車需 8 s，增加 3 s。A 通過同一 checkpoint 需 6 s，未因 B 改變速度。Checkpoint 不是停車目的地，通過後仍繼續前進。

Timeline 的 1 s braking 與 5.5 s following 不是 6.5 s 額外延遲，因為這些時間 B 仍在前進。額外延遲應使用相同 checkpoint 的通過時間差，不能把整段跟車都算成 waiting。

若不控制，2 s 後低於設定安全間距，4 s 時兩中心重合；真實有限車體會更早接觸，因此 4 s 不能稱為真實碰撞時間。圖中的 no-control 虛線只作不安全的解析參考。

## 圖怎麼讀

1. Position：實線是 A 與受控 B，虛線是 B 不減速的反事實。
2. Gap：間距下降到 2 m 後持平。兩條直立虛線標出煞車開始與結束。
3. Timeline：B 依序經過 cruise、brake、follow，全程 stopped waiting 為 0。

## 模型深度建議

第一階段保留通道連通性、車體淨空、位置/速度/加減速、明確 priority、waiting 和 parked occupancy。用這些元素就能測量 head-on 與 following 的 travel penalty。

要進入多台 shuttle 的 zone/no-zone comparison 前，還需要換道占用空間、交叉路口與 reader 入口預約，以及不會互相永遠等待的處理規則。兩個 micro-experiments 的空間表示目前不同：相向案例是整段 edge reservation，本例是連續位置；不能直接把兩者相加當成完成的 library traffic model。

先不加入電池、馬達電流、精密機構控制。這些可以等確認 traffic delay 是否影響主要結論後再補。

## 邊界與驗證

- 前車速度固定；未模擬前車突然煞停。此安全距離公式不可直接用於 emergency-stop 情境。
- 假設即時、精確狀態與零控制延遲；反應延遲與位置誤差需要額外安全 margin。
- 初始時兩台已在行駛；不包含從靜止出發、reader 操作與終點停車。
- 安全性由完整分段解析曲線的最小間距驗證，不依賴 0.02 s 繪圖取樣。
- 結果為參數化示例，不是 Silica 原型量測；未用它推論全系統 throughput 或實際 collision 頻率。

```bash
.venv/bin/python scripts/run_shuttle_following_demo.py
.venv/bin/python -m unittest tests.test_shuttle_following_demo tests.test_shuttle_yield_demo -v
```

參數：`experiments/shuttle-following-demo/default.json`。
圖：`fig1_following_timeline.pdf/png`；逐時位置/速度：`trajectory.csv`；事件：`events.csv`；彙整：`summary.csv/json`。
