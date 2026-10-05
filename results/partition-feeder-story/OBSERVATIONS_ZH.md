# 單一 partition：故事線、觀察與未被證明的主張

## 這次研究的是什麼？

一個實體 partition 裡有 8 條儲存架 rows、**一個 reader**、1／2／4／8 台 shuttle，以及 0／1／2／4 個 feeder-buffer 待讀位置。Zone 是 partition 內的取件所有權；所有車最後仍匯流到同一個交付站。

完整矩陣 490 runs，5 seeds/cell，每次 384 requests，共 188,160 次讀取與歸還循環。參數在 full.json 中事先列出，所有 cell（含負向結果）保留。這是受控合成工作負載，尚非實機校準或投稿完成版的泛化證據。

## 1. 為何讓多台 shuttle 服務一個 reader？

E1 的 64 m、optical read 8 s、Zone/B=4 下，reader load/read/unload 利用率從單台 shuttle 的約 **11.4%**，提高到 8 台的約 **83.8%**。16 m 的相同比較約為 **22.0% → 93.1%**。

這說明此模型中單台供料不足，多車配置可以回收 reader 等料時間。但 E1 增加了硬體，而且 Zone 也隨 N 細分，收益包含並行與分工局部性，不能全歸因於單一方法。

**精確說法：** 改善的是供料間隔與排隊，不保證每個 request 的實際 movement time 都下降。長讀取较容易逼近 reader 上限，短讀取／長距離仍可能搬運受限；不能據此宣稱固定的最佳 shuttle:reader 比例。

## 2. Zone 與 Non-Zone 各自在哪裡有空間？

E2 固定 32 m、read=8 s、B=4。在 4 shuttles 的相同硬體下：

| Address 場景 | Zone 完成速率 | Non-Zone FIFO 完成速率 |
| --- | ---: | ---: |
| Uniform | 3.204 req/min | 2.885 req/min |
| 75% requests 位於 rows 0/1 | 1.225 req/min | 2.206 req/min |

均勻場景下，固定分工有局部性優勢；人工熱區中，共享可回收固定 owner 用不到的其他搬運能力。兩邊仍使用相同衝突規則，Zone 沒有被假設在 reader side 完全無衝突。

Non-Zone FIFO 的 uniform traffic wait 約從 N=2 的 **5.96** 增到 N=8 的 **43.75 shuttle-s/request**。但完成速率仍從 **1.660** 增至 **4.376 req/min**。

**因此本輪沒有證明「增加 shuttle 讓整體更慢」。** 支持的結論是新增資源伴隨更多協調成本，收益不是線性。不能將較高 traffic wait 直接寫成吞吐量反轉。

Lookahead 基準沒有穩定優於 FIFO，且需要更多候選評估。尤其 closed batch 的大部分 requests 很快超過 120 s aging 門檻，使 lookahead 回到 oldest-first；這不是高品質聯合排程上界。Pair evaluations 是決策工作量 proxy，不是已量測的 embedded-controller overhead。

## 3. Feeder buffer 解決了什麼？還沒解決什麼？

E3 固定 8 shuttles、32 m、read=8 s、uniform batch，只改待讀容量：

| 方法 | B=0 完成速率 | B=4 完成速率 | B=0 等交付 | B=4 等交付 |
| --- | ---: | ---: | ---: | ---: |
| Zone | 4.432 req/min | 4.924 req/min | 30.16 shuttle-s/request | 35.30 shuttle-s/request |
| Non-Zone FIFO | 4.247 req/min | 4.376 req/min | 12.36 shuttle-s/request | 0.23 shuttle-s/request |

Zone throughput 均值增加約 **11.1%**，但 shuttle 等交付總量沒有同步減少；Non-Zone 的等交付幾乎消失，throughput 卻只增加約 **3.0%**。這表示 buffer 能改變時序，但不能單靠一個局部等待指標判斷效果。

**推論邊界：** 交接、歸還優先權、路段預約及取件順序都會隨事件時序相互影響。上面的反向變化是觀察，尚未用獨立 ablation 把它完全歸因到其中一項。

### Prefetch 成效的正式量測

本版 B>0 明確代表「request 已知後，reader 忙碌時先把下一片送入有限 buffer」；不是未知 request 的 speculative prefetch，也不是讀後 cache。`runs.csv` 新增：

- `prefetch_hit_fraction`：handoff 早於該片 reader start 的工作比例。
- `prefetch_lead_mean_s`：上述 hit 的平均提前秒數。
- `route_motion_s`：fetch/delivery/return 路段被占用的總時間，與 `traffic_wait_s` 分開。

在 E3、N=8、read=8 s 的 full matrix：

| Policy | B | Prefetch hit | Lead time | Route motion / request | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zone | 0 | 0.0% | 0.0 s | 44.47 s | 84.14 min |
| Zone | 4 | 95.6% | 42.0 s | 40.29 s | 75.37 min |
| Non-Zone FIFO | 0 | 0.0% | 0.0 s | 55.74 s | 89.41 min |
| Non-Zone FIFO | 4 | 75.7% | 14.8 s | 52.98 s | 86.79 min |

這支持的說法是：**prefetch buffer 讓已知的下一片玻璃提早到位，並讓 shuttle 與 reader time overlap；它不會把儲存架到 reader 的物理距離變成零。** Route motion 仍然存在，且共享交通會改變它。若要減少物理 movement 本身，需要另行研究 near-reader retention/cache 或更近的 storage placement。

## 4. 到達時間檢查保留了不利結果

E4 N=4、Poisson arrival rate 為 standalone reader ceiling 的 60%，其實不保證低於每種搬運 policy 的服務能力。有限 episode 的平均 run p99：

| Pattern / policy | B=0 | B=4 |
| --- | ---: | ---: |
| Uniform / Zone | 16.78 min | 13.79 min |
| Uniform / Non-Zone FIFO | 15.80 min | 17.09 min |
| Hotspot / Zone | 192.21 min | 189.99 min |
| Hotspot / Non-Zone FIFO | 48.50 min | 51.34 min |

這些是五個 run 的均值描述。完整 sample SD 在 CSV／PNG 圖，未宣稱統計顯著性或穩態 tail。不能只展示 buffer 有改善的 cell。

## 可以用在報告的連續敘事

1. 資料與 reader 分離，因此需要搬運；單台 shuttle 可能讓 reader 缺料。
2. 多台提供並行供料，但如何分工會影響局部性、忙閒差與交通成本。
3. 不論 Zone 或 Non-Zone，玻璃最後都集中到同一交付站；有限 buffer 提供提前交付的空間。
4. Buffer 的收益取決於供料／讀取比例，也會與調度時序互相影響，並非越大越好。
5. 後續方法應根據主要損失決定需要哪些狀態資訊，再做同硬體 ablation；本輪不宣稱新演算法已成立。

## 可重現性與限制

- [完整方法與參數](../../experiments/partition-feeder-story/README.md)
- [全部設定及均值／SD](ANALYSIS_ZH.md)
- [投影片故事線與講者備註](STORYLINE_ZH.md)
- 實機 rack/junction/docking 幾何、服務時間分布、真實 trace、warm-up 與更長 tail 量測仍待補強。
- 固定有限 output staging 與 return-first，歸還成本已計入；return 最佳化留待後續。
