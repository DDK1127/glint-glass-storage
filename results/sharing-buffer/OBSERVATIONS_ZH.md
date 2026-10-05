# 八區 baseline：第一輪觀察與動機界線

本輪完成 252 組有限長度合成實驗：8 zones、8 shuttles、8 readers，7 種共享模式／範圍組合、3 種待讀容量、2 種需求分布、2 個共同到達速率與 3 個 seed。每組 480 requests，全部讀取後歸還。另完成 84 組 smoke runs。

這是機制診斷用 baseline，不是大型實機效能估計。物理假設、排程細節與所有結果在 [ANALYSIS_ZH.md](ANALYSIS_ZH.md) 及 [實驗說明](../../experiments/sharing-buffer/README.md)。

## 一個配對切面：局部繁忙、到達率為校準值的 0.9 倍

下面是三個 run 各自 p99 的平均，非 pooled p99；sample SD 與逐次數字保留在 CSV。所有方法使用相同 requests、時間與讀取量。

| 服務方式 | 0 待讀位 p99 | 1 待讀位 p99 | 4 待讀位 p99 |
| --- | ---: | ---: | ---: |
| 固定分區 | 11.21 min | 11.69 min | 11.69 min |
| 2 區共享搬運，reader 固定 | 39.65 min | 35.57 min | 37.24 min |
| 2 區共享搬運與 reader | 39.20 min | 38.55 min | 37.36 min |
| 8 區共享搬運與 reader | 149.80 min | 154.40 min | 155.37 min |

## 已觀察到的事實

1. **擴大共享在這套拓樸與控制器下代價很高。** 以上切面，固定分區無 route waiting；8 區 joint sharing/B=0 的 traffic wait 約 133.07 shuttle-seconds/request，movement 約 34 秒/request。交通等待遠大於單純增加的移動時間。
2. **減少交付阻塞不保證改善 request p99。** 8 區 joint sharing 的 delivery wait 從 B=0 的約 4.01 秒/request 降至 B=4 的約 0.05 秒/request，但 p99 增加。2 區 transport sharing 從 B=0 到 B=1 則同時降低交付等待與 p99，後者下降約 10.3%。這些是個別切面的描述，不是穩定改善保證。
3. **輸入 buffer 改變讀後回收時序。** 固定分區/B=0 的 reader output-block 總時間為零；B=1 約 127.61 reader-seconds/run。8 區 joint sharing 的 output-block 總時間從 B=0 約 2709.27 增至 B=1 約 9290.92 reader-seconds/run。需要看完整回收流程，不能只看輸入端等候。
4. **Reader 分配的自由度沒有被充分使用。** 8 區 joint sharing/B=0 約只有 0.625% requests 使用非 home reader；B=1 約 1.042%。此輪尚未形成充分測試 reader 分配價值的場景。

## 合理解讀與不能主張的結論

- **推論：** 單一 exclusive trunk、整條路徑一起預約的保守規則，以及 oldest-feasible dispatch 的跨區選擇，很可能使交通成本支配結果。要分離各項因果貢獻，需要另外的配對敏感度；目前不能將所有差距單獨歸因於 trunk。
- 不能主張「共享普遍比固定分區差」或「buffer 沒有用」。這些數字依賴具體硬體拓樸、歸還優先權與負載；共享策略也沒有選擇模仿固定分區的效益門檻。
- 不能把 excluded-work idle time 減至零當作效能改善證據：全域共享時此指標按 eligibility 定義必然為零，並不代表所有支援都有價值。
- 不能把 480 筆 request 的 p99 及三個 seed 當作真實系統 tail 的穩健估計；這是初步有限 episode 診斷。
- 需求熱區 3/4 恰跨過 2/4 區共享群組的界線。擴大 group 同時改變可支援關係，不能只用這個放置主張普遍的 group-size 趨勢。

## 對論文動機的影響

本輪支持保留「局部硬體改善不必然變成端到端收益，需要追蹤搬運、交付與歸還的相互影響」作為待深入研究的問題。

但 reader assignment 與 buffer 是否值得作為共同論文主軸，尚未由這批結果證明。下一步宜先檢查模型中共用通道的限制是否符合預期架構，再用更小的診斷情境讓 reader 負載不均清楚出現；不要為了得到預期故事而只保留有利結果。

目前沒有實作新協同演算法、沒有使用自然 trace，也沒有採用舊 32-rack 結果作為本輪證據。
