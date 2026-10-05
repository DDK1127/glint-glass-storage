# Feeder buffer：研究方向討論紀錄

## 最新範圍（2026-09-30）

研究單位已重新確認為 **單一實體 partition、單一 reader、多台 shuttle**。Zone 是 partition 內部的取件分工；本輪不研究跨 reader 分配。核心為多車供料、Zone/Non-Zone 協作，以及 feeder-buffer 交接。先前八 reader 設定保留為歷史探索，不能當成本次架構的直接證據。

已完成 [partition-feeder-story](../../experiments/partition-feeder-story/README.md) 的 490 組受控實驗與 [觀察筆記](../../results/partition-feeder-story/OBSERVATIONS_ZH.md)。以下記錄保留討論沿革；以本節和新實驗說明為準。

日期：2026-09-24。狀態：已同意保留的候選方向；原先的演算法構想尚未驗證。後續已開始實作下述八區動機 baseline，兩者需區分。

## 後續確認的八區 baseline

使用者確認規模為約 8 zones、8 shuttles；延續每區一個 reader、交付後 shuttle 可離開的設計。Reader 位置固定，只改變玻璃可以由誰搬、送往哪個 reader，以及每個 reader 有多少待讀 slots。

- Fixed：固定 owner 與 reader。
- Transport sharing：相鄰 2／4／8 區的 shuttle 共享，reader 固定。
- Joint sharing：同範圍同時開放 shuttle 與 reader 選擇。
- 每種模式比較 0／1／4 個待讀 slots；所有模式具有相同有限 docking bays、同一交通模型及一個 reader output slot。
- 先跑均勻／暫時局部繁忙的合成負載與共同校準速率，確認模型與機制。尚未採自然 trace，也不將舊 32-rack 數據當作新動機證據。

實作、完整假設與執行方式見 [sharing-buffer experiment](../../experiments/sharing-buffer/README.md)。下列 E1–E3 是原始研究方向；目前實作的是共享權限與 buffer 容量的基礎矩陣，尚未完成新協同演算法或其 ablation。

首輪已完成 84 組 smoke 與 252 組 baseline；結果與限制見 [觀察筆記](../../results/sharing-buffer/OBSERVATIONS_ZH.md)。此輪單一共用通道的等待相當突出，尚不能據此證明共享、reader 分配或 feeder buffer 在其他架構下的價值。

## 單一研究動機

玻璃搬運與 reader 讀取的時間不匹配。研究如何利用有限的 feeder buffer 與搬運—讀取協同排程，降低 request 的尾端等待時間。

白話說法：玻璃不只要搬得快，也要在適當的時間送到；用少量待讀位置，把搬運與讀取接好。

論述順序：工作需求 → 搬運與讀取接不上的證據 → 暫存空間的用途 → 一般排程的限制 → Glass-aware 方法 → 固定硬體下的效能與容量取捨。

## 範圍與元件邊界

- Shuttle：估計可用時間與玻璃抵達時間。
- Feeder buffer：有限的待讀 slots，管理 admission 與釋放。
- Reader：估計可用時間與每片玻璃的服務時間。
- Loader／handoff 作為明確建模的交接機制，不另立研究主題；不能假定真實 Silica 的 shuttle 必須陪同整段讀取。
- 先只服務已到達的 requests，不加入預測式 prefetch、讀後 cache retention、新資料配置或新交通拓樸。

Buffer 能吸收時間差，不能補足長期不足的搬運吞吐量。必須區分平均供料不足和平均供料足夠但到達時間不匹配。

## 核心假設與方法候選

假設：即使能正確估計搬運時間，只最佳化搬運端仍可能造成 reader 空等或過早占用 buffer；同時考慮抵達時間、reader 狀態、buffer 容量與 request 等待時間，可能改善 p99 latency。

待決策的核心是「搬哪片、何時搬」。FIFO 要明確區分取件順序、buffer admission 與已到達玻璃的讀取順序；已發生的搬運距離不是 buffer 內重排的充分理由。

不預設 FIFO 必然很差，也不預設協同方法一定有效。最短搬運時間、具等待時間保護的方法及相關既有方法都應成為基準候選。

## 最小實驗計畫

| 實驗 | 問題 | 控制與比較 |
| --- | --- | --- |
| E1 | 暫存是否能減少供料空窗？ | 固定 shuttle、reader、工作負載與交接成本，比較直接交付及 1／2／4 個 staging slots；明確定義零 staging 的交付握手 |
| E2 | 單一排程規則缺少什麼？ | 同一硬體比較最早需求優先、最短搬運時間優先、含等待時間保護的基準 |
| E3 | 協同資訊是否帶來獨立收益？ | 與強基準比較，分別移除 reader 狀態、buffer 容量資訊等，檢查收益來源 |

主要指標：request p99 latency。解釋指標：reader 等料時間、buffer 占用／等待、搬運成本、吞吐量及公平性。Reader utilization 不單獨作為成功標準。

同一主題的設計延伸：達到相同 latency 目標時，協同排程是否能減少所需 buffer slots？未設定或承諾改善幅度。

既有 32-rack 結果同時改變 shuttle 數與交接架構，不能單獨歸因於 feeder buffer。新的對照必須隔離這些因素。

## 投稿定位與相關工作邊界

以 DAC／ICCAD 為目標方向，關注物理成本建模、受限資源排程與 buffer 容量—效能取捨；不因題目符合範圍而推定新穎性或可接受性。

- [GAIA: Glass-Aware I/O Middleware, ICCAD 2025](https://doi.org/10.1109/ICCAD66269.2025.11240953)：借鏡物理成本影響決策的論述；本候選方向聚焦 library 層級的供料協調，須和 platter 內部存取排程區分。
- [Project Silica, SOSP 2023](https://www.microsoft.com/en-us/research/wp-content/uploads/2023/09/ProjectSilica-SOSP23.pdf)：已有 platter request grouping、分區與 work stealing 等機制；自建簡化 greedy baseline 不等於完整 Silica 方法。

原定下一步是先量測供料空窗及其成因，再決定是否值得實作協同演算法；後续 baseline 進度以本文開頭與實驗 README 為準。
