# Two-shuttle yielding micro-experiment

## 目的

用一個可檢查的小案例說明：兩台 shuttle 相向時，如何先清空通道再通過，以及各自多花多少時間。這是指定避讓流程的事件模型，不是自動選擇最佳路徑的 scheduler。

## 空間設定

```text
L1 ---------------- R1    空的平行避讓通道
|                    |
L0 ---------------- R0    原本的通道
A ->              <- B
```

A 從 L0 到 R0，B 從 R0 到 L0。兩條水平通道長度均為 6 m，兩端可換道。通道被抽象成具有足夠車體淨空的獨立路徑；不能直接把它解讀為 Silica 相鄰兩條實體 rail，因為 shuttle 的車體與 crabbing 可能占用多條 rail。

## 成本假設與執行結果

沿用現有 simulator 的水平加減速公式：最高速度 2 m/s、加速度 2 m/s²、起終點速度為零。6 m 水平移動需 4 s。每次換道假設為 3 s，實際通道間距與車體 clearance 尚待校準。

| 時間 | A | B |
| --- | --- | --- |
| 0–3 s | 在 L0 等待 | R0 → R1，清空原通道 |
| 3–7 s | L0 → R0 | R1 → L1，沿避讓通道前進 |
| 7–10 s | 已抵達，在 R0 停留 | L1 → L0，回到原通道 |

相同水平距離的獨立通道參考需 4 s。A 完成需 7 s，多 3 s 等待；B 完成需 10 s，多 6 s 換道。兩台累計額外時間為 9 shuttle-seconds，而整體完成時間增加 6 s，兩者不可混用。

參考案例將 B 放在另一條獨立通道，起始狀態不同，因此只作 travel-time reference，不是相同實體起點的無衝突可實現 baseline。

## 驗證與限制

- 每段移動預約 edge 及兩端 nodes；不同 shuttle 不得在重疊時間使用相同資源。
- Waiting 和完成後的 parked shuttle 都持續占用位置。
- 預約採半開區間，允許前一事件結束後，下一事件立即開始；未加入額外安全時間。
- 驗證 trajectory 連續、目的地正確、預約無衝突與時間分解守恆。
- 若完全沒有避讓通道，兩台不能在這個單線圖上交換位置；單純等待不能解決。
- 無 reader、pick/place、request merge、動態 arrivals 或 controller CPU cost。
- B 固定為避讓者；公平性、多台衝突、動態偵測與最佳 dispatch 尚未建模。
- 此結果只證明這個指定流程在抽象圖上可行，不能推論 production congestion 嚴重程度或 zone 優劣。

## 重現

```bash
.venv/bin/python scripts/run_shuttle_yield_demo.py
.venv/bin/python -m unittest tests.test_shuttle_yield_demo -v
```

`events.csv` 記錄逐段路徑與時間，`summary.csv` 記錄每台時間分解，`summary.json` 保存參數與驗證，`fig1_yield_timeline.pdf/png` 為 timeline。
