# Azure no-zone conflict exposure pilot

## 設定

使用本機已排序的 Azure head-100k read batch，整批在 t=0 可見。保留真實 object identity、bytes、重複存取，沿用 deterministic uniform packing 裝入 640 個 virtual platters，每片只服務一次。這不是原始 arrival-time replay。

8 shuttles、8 readers，兩個不連通的 panel sides 各 4 台與 4 個 readers。Shuttle 可服務自己 panel 的全部高度與位置，沒有 static zone ownership。

依最早 request 的 platter 順序派工；若其 panel 沒有空閒 shuttle，可先派另一側最早的工作。選 Manhattan 實體路徑距離最近的空閒 shuttle（平手取小 ID），reader 也取最近者。水平先走、再垂直 crabbing，水平包含加減速；每次換軸停車。讀完放回原位再接下一個工作。

各 seed 使用相同物件分組與固定 side/level/normalized x，只有水平長度隨 2/16/64 m 改變。所有長度的每側每層 mapping slots 固定 100：本輪是 footprint sweep，不能當成真實 slot-density scaling。

## 衝突如何定義

用連續時間的軌跡判定兩台的中心間距是否同時低於 x=0.5 m、y=0.65 m。這是示例矩形占用範圍（車體+margin），不是 Silica 測得的尺寸。取放、reader queue、讀取期間和 idle 都繼續占位。

圖中比例的分母是 640 個 tasks；fetch、delivery、return 分開計，每個 task 在該階段只算一次。完整服務受影響比例是聯集，不能把三個百分比相加。不同 phase/category 可分成多個 episode，episode 次數不是獨立碰撞數。

## 結果（10 seeds 平均）

| Side 長度 | Fetch 受影響 | Delivery 受影響 | Return 受影響 | 完整服務受影響 |
| --- | --- | --- | --- | --- |
| 2 m | 73.0% | 65.3% | 64.0% | 94.2% |
| 16 m | 49.3% | 57.2% | 55.2% | 89.1% |
| 64 m | 39.3% | 52.4% | 52.1% | 86.1% |

## Penalty 解讀

預設 head-on=6 s、same-direction=2 s，其餘 stopped/crossing=3 s。這些僅借用小案例的量級，不是由軌跡求出的真正等待或繞行成本。每對 shuttle/task 只收一次最高類別 penalty，idle 以 task=-1 表示；再乘 0.5/1/2 做敏感度分析。

輸出是累計額外 shuttle-seconds；沒有分配到個別 shuttle，也不改動後續路徑，因此不能換算成可信的 penalty-adjusted throughput。原本軌跡已存在未解決重疊，高受影響比例代表需要協調，不代表套固定 penalty 就能安全執行。

## 必須保留的解讀限制

- 不是實際碰撞機率，只是這個 trace/mapping/routing/clearance 下的潛在接觸比例。
- Clearance、水平先走、固定 reader 位置都會強烈影響結果；clearance_sensitivity.csv 保留 0.5/1/1.5 倍的檢查。
- 有些衝突涉及 parked robot 或 reader queue，單靠兩台迎面/跟車的小案例不足以估計它們的避障成本。
- 這次沒有配對 static-zone traffic baseline，不能直接和舊 simulator 的 throughput 數字比較或宣稱 no-zone 輸贏。
- 只有一個真實 batch；seeds 改變的是人工 placement，不代表十個獨立 workload samples。

## 重現

```bash
.venv/bin/python scripts/run_no_zone_conflict.py
.venv/bin/python -m unittest tests.test_no_zone_conflict -v
```

runs.csv / aggregate.csv：每 seed 與彙整數據。conflicts.csv：時刻、參與 shuttle/task/phase。audit-*m：第一個 seed 的完整派工與軌跡。summary.json：參數、來源和驗證。
