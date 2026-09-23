# Static Zone vs. Coordinated No-Zone

## 這個實驗回答什麼

用相同 Azure head-100k trace-derived closed batch、相同 platter packing/placement、8 readers 與 8 shuttles，比較 strict static ownership 與可跨 zone 的 nearest-idle dispatch。

## 主要差異

- Static Zone：每片 platter 只能由其 level-band owner 處理，每個 owner 使用固定 reader；不同 zones 的 conflict 設為零。
- No-Zone Coordinated：同側 panel 最近的空閒 shuttle 接手，使用最近 reader；route 若與已預約的 shuttle path/operation 衝突，controller 比較 direct 與 alternate-level candidates，選最早安全完成者。
- 等待發生在抽象 holding pocket；這是 controller admission model，不代表 prototype 已有相同硬體 buffer。

## 結果

| Side 長度 | Static completion | No-zone completion | No-zone throughput change | Static idle share | No-zone coordination |
| --- | --- | --- | --- | --- | --- |
| 4 m | 33.85 min | 51.10 min | -33.7% | 9.4% | 4689.9 shuttle-s |
| 8 m | 37.97 min | 52.23 min | -27.2% | 9.3% | 3593.3 shuttle-s |
| 16 m | 45.89 min | 59.12 min | -22.3% | 9.2% | 3336.4 shuttle-s |
| 32 m | 61.66 min | 74.26 min | -16.9% | 9.1% | 3522.0 shuttle-s |
| 64 m | 93.34 min | 105.08 min | -11.1% | 9.4% | 3867.4 shuttle-s |

## Observation 1：一次 Glass Service 花在哪裡

圖三使用兩邊完全相同的 640 個 batch-merged tasks，分解 fetch、delivery、return、reader、pick/place 與 conflict avoidance。No-zone 除了 coordination，fetch direct movement 也更長；目前 global FIFO + nearest-idle dispatch 會讓 shuttle 離開原本的 spatial locality。這是此 baseline 的行為，不是所有 MAPF 必然如此。

## Observation 2：兩種 Tail 代價

Static 在所有測試長度都約有 9% shuttle capacity 在等待最慢 zone drain；最快與最慢 zone 的絕對 completion gap 則由約 6.7 分鐘增加到 18.8 分鐘。No-zone 將 idle share 降至約 3%，但 65%--80% tasks 需要 coordination，還同時付出跨 level fetch、reader queue、holding 與 detour。

因此目前觀察不是單純 idle time 對 conflict time：Static 以固定 ownership 換得 collision isolation 和 locality；No-zone 以共享 work pool 降低 stranded capacity，卻失去 locality並承擔 coordination。圖四把兩種代價並列，圖五再顯示 conflict cost 出現在哪個 service phase。

## Evidence boundary

- Azure trace 保留 object identity、bytes、reuse 與自然順序，但實驗在 batch barrier 後一次排程；原始 4.15 h interarrival 沒有重播。
- Azure 沒有 glass locations；object-to-platter 與 platter-to-position 都是 seeded mapping。Seeds 是 placement sensitivity，不是獨立 workload samples。
- Static zero-conflict 是 strict non-overlap abstraction；不代表真實 Silica boundary 永遠零 conflict。
- No-zone waiting 使用抽象 holding pockets；idle parked shuttle 不占 rail。這可能低估真實 traffic cost。
- Route candidates 是 horizontal-first 或經單一 intermediate level；不是完整 MAPF，也沒有 controller CPU time。
- 這是第一版 policy comparison。結論只能套用到目前 geometry、mapping、batch semantics 與 routing rules。
