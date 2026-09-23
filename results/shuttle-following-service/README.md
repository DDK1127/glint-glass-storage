# Pickup-to-reader following example

這次範圍從取出玻璃開始，到放入 reader 完成；不包含光學讀取、送回 storage 或 reader queue。

B 初始在 x=0，A 在 x=4。兩台同時取件 3 s，再由靜止加速。A 最高速度 1 m/s，B 為 2 m/s，加減速度大小均為 1 m/s²，最低中心間距假設 2 m。A 前往 x=12 的 reader，B 前往 x=10 的另一個 reader，兩個 reader 都可立即使用。

B 單獨服務需 13 s：取件 3 s + 移動 7 s + 放入 reader 3 s。受前車影響需 15 s：取件 3 s + 移動 9 s + 放入 reader 3 s。移動的加減速和目的地停車均已計入。

| 服務時間 | B 動作 |
| --- | --- |
| 0–3 s | 取件 |
| 3–5 s | 加速到 2 m/s |
| 5–6 s | 維持 2 m/s |
| 6–7 s | 因前車減速到 1 m/s |
| 7–11 s | 以 1 m/s 跟車 |
| 11–12 s | 在 reader 前煞停 |
| 12–15 s | 放入 reader |

減速 1 s + 跟車 4 s，共 5 s 處於受影響狀態，占服務時間 33.3%；期間仍然在移動，不是 5 s 停車等待。真正增加的服務時間為 15−13=2 s，占實際服務時間 13.3%，相對基準服務時間增加 15.4%。Stopped waiting 為 0。

這是一個新的含起步與停車的 service 案例，和先前兩台已在行駛、以 10 m checkpoint 計時的 5→8 s 案例不同。

安全性檢查採分段曲線端點與相對速度為零的時刻，確認連續時間最小中心間距為 2 m；並驗證終點速度為零。未包含控制延遲、緊急煞停、不確定速度與精確車體形狀，因此屬於規則可行性示例，非 production safety guarantee。

```bash
.venv/bin/python scripts/plot_following_service_demo.py
```

逐段服務事件在 `events.csv`，搬運細節在 `movement_events.csv`，參數與計算結果在 `summary.json`。圖的末端 +2 s 箭頭表示兩種完成時間之差，不代表該區間真的停車等待。
