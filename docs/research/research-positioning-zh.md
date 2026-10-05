# 研究定位（一頁版，2026-10-05 討論稿）

> 每一句都標註來源。**[事實]** 有論文或資料依據；**[模擬]** 來自本專案模擬，數值受假設影響；**[假設]** 尚待驗證。

## 一句話

**真實讀取負載會出現短時間熱區；固定分區（Silica 的 partition）在熱區時會閒置其他 shuttle，而 Silica 的補救方式 work stealing 反應慢，又會帶來額外移動和擁擠。我們要找的是一種在熱區時能快速借用閒置 shuttle、又不會把共用路段塞滿的調度方法。**

## 動機句型

| 要素 | 內容 | 依據 |
| --- | --- | --- |
| 系統 | Project Silica 式的玻璃儲存 library：platter 固定在架上，shuttle 搬到 read drive | [事實] Silica SOSP'23 §2、§4 |
| 會發生的條件 | 短時間熱區：每 100 個 request 為一段時，最忙的 zone 分到 47% 的工作（8 zones，平均分配是 12.5%）；拉長到 5,000 個 request 只剩 17.7% | [事實] 本專案 Azure trace 分析（`results/natural-trace-skew-rq1`），隨機放置 |
| | 放置保留局部性時，偏斜會持續存在：連續 LBA 放置時，最忙 zone 佔 55.6%；依應用程式放置時，固定分區的吞吐量是理想值的 74.9% | [事實] 同上；`results/azure-static-zone-pilot`。真實 platter 放置未知，屬條件性證據 |
| 現有做法 | 分區數 = shuttle 數，每區 1 台 shuttle、至少 1 個 read drive；正常時 shuttle 不出區。負載差超過門檻時觸發 work stealing，以最短路徑跨區，論文自述「may create additional congestion」 | [事實] Silica §4 |
| 現有做法的損失 | Zipf 偏斜下：不做平衡時尾端完成時間超過 21 h；work stealing 降到 11.5 h，但尾端搬運時間從 29.4 s 增加到 76 s。沒有搬運成本的理想情況（NS）為 7.5 h | [事實] Silica §7.5、Fig. 7(c) |
| 另一端也不好 | 完全共享、不分區（SP）在車多時受停走成本拖累：IOPS 負載下尾端完成時間 5 h，分區是 2.8 h | [事實] Silica §7.5、Fig. 5(c)、7(a) |
| 機制 | 固定分區：熱區只有該區的車能搬，其他車閒著；work stealing：要等積壓差超過門檻才觸發，熱區移走時幫手可能才剛到；完全共享：車多就互相擋路 | [假設] 由上面的事實推論，需要 headroom 實驗量化 |

**由事實直接推得的空間：** Silica 的 work stealing（11.5 h）距離理想值（7.5 h）還差約 53%。NS 不是可實現的系統，只是上界，但它說明原論文本身就留有改善空間。

## 和 Silica 的設定差異（必須講清楚）

- Silica：1 台 shuttle 對 1 個 partition，每個 partition 至少 1 個 read drive（實驗為 20 drives，shuttle 數 8–40）。
- 本專案：1 個 partition、1 個 reader、N 台 shuttle，Zone 是 partition 內部的分工。
- 為什麼要多台 shuttle 對一個 reader：讀取量小（IOPS 型）時搬運比讀取慢很多。**[模擬]** 搬一片約 66 s、讀一片約 11 s。**[事實]** Silica 在 IOPS 負載下，shuttle 從 8 台加到 40 台（每個 drive 2 台），尾端完成時間從 10 h 降到 1 h 20 min，20 台以後收益遞減。
- 待確認：我們的讀取時間（8 s）是否接近 IOPS 型負載的實際值。若讀取時間長，1:1 配置就夠，本專案的多 shuttle 設定就沒有必要。

## 三層內容怎麼安排

| 層 | 角色 | 理由 |
| --- | --- | --- |
| A. 熱區 × 分區 × work stealing | **主軸** | 有 trace 和原論文雙重事實支撐 |
| C. Shuttle 台數與擁擠 | 配角：說明「為什麼不能加車解決」 | [事實] Silica SP 的停走成本；[模擬] 擁擠模型的最佳點依參數而變 |
| B. Feeder buffer | 方法中的一個元件（准入控制、buffer credit），不是獨立主題 | [模擬] 收益 3–11%，有正有負 |

## 什麼結果會讓我們放棄這個方向

Headroom 實驗：在「會移動的短時間熱區」下，比較 Zone、Zone + work stealing、Non-Zone FIFO，以及兩個參考上界。

- 若 Zone + work stealing 和上界的差距**小於約 10%**（p99 或吞吐量），主軸 A 不成立，需要換題目或換情境。
- 若差距只在不切實際的熱區強度（遠超過 trace 的 47%）才出現，動機要降級為條件性。
- 若差距明顯，而且出現在 trace 支撐的強度，就用這個差距當作動機的數字。

## 要和老師確認的問題

1. 主軸放在 A（熱區調度）可以嗎？B（buffer）降為方法元件是否可接受？
2. 「1 個 reader 配多台 shuttle」這個設定，老師是否認為合理？是否需要改回 Silica 的 1:1 分區，在多 partition 之間做借用？
3. 目標會議（DAC／ICCAD）要求的硬體或控制開銷面向，要放多少比重？

## 來源

- Project Silica, SOSP 2023：`docs/references/ProjectSilica-SOSP23.pdf`（§4 traffic management、§7.5 shuttle management）
- Azure trace 短時間偏斜：`results/natural-trace-skew-rq1/RQ1_NATURAL_TRACE_CHARACTERIZATION.md`
- 放置與分區損失：`results/azure-static-zone-pilot/AZURE_STATIC_ZONE_PILOT_ZH.md`
- 搬運／讀取時間比：`results/partition-shuttle-provisioning/summary.json`
