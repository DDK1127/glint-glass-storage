# Virtual Collision-Free No-Zone

## 定義

這個 virtual policy 允許同側 shuttles 的軌跡互相穿越，固定使用 direct shortest routes，因此 conflict waiting、detour 與 collision penalty 都是零。Reader 仍一次只能讀一片，pick/place、reader service 與 platter return 全部保留。

Closed batch 在所有 tasks 已知時選擇預計最早完成的 task-shuttle-reader 組合。Natural replay 採 local-first：owner 有 local work 時保留 owner 與 local reader；只有 helper 的 read-time benefit 大於跨區後回到 home anchor 的 recovery cost 時才協助。兩者都不是全域數學最優排程，因此應稱為 collision-free virtual references，而不是 optimal schedules。

## Raw-arrival latency

| Panel | Static mean / p99 | Greedy mean / p99 | Virtual mean / p99 | Virtual p99 vs. Static | Virtual p99 vs. Greedy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 m | 14.89 / 31.66 min | 24.62 / 49.79 min | 14.89 / 31.64 min | -0.1% | -36.5% |
| 8 m | 16.85 / 35.54 min | 25.26 / 50.83 min | 16.85 / 35.52 min | -0.1% | -30.1% |
| 16 m | 20.54 / 43.17 min | 28.63 / 57.48 min | 20.54 / 43.11 min | -0.1% | -25.0% |
| 32 m | 27.78 / 58.11 min | 36.17 / 72.43 min | 27.77 / 58.02 min | -0.2% | -19.9% |
| 64 m | 42.35 / 88.25 min | 51.25 / 102.23 min | 42.32 / 87.95 min | -0.3% | -14.0% |

## Closed-batch completion

| Panel | Static | Greedy | Virtual | Virtual completion vs. Static | Virtual completion vs. Greedy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 m | 33.85 min | 51.10 min | 28.72 min | -15.2% | -43.8% |
| 8 m | 37.97 min | 52.23 min | 31.95 min | -15.8% | -38.8% |
| 16 m | 45.89 min | 59.12 min | 37.89 min | -17.4% | -35.9% |
| 32 m | 61.66 min | 74.26 min | 49.66 min | -19.5% | -33.1% |
| 64 m | 93.34 min | 105.08 min | 72.55 min | -22.3% | -31.0% |

## 主要觀察

Closed batch 中，所有 640 個 merged tasks 一開始都已知，Virtual 可以持續選擇附近工作：相對 Static 縮短 15.2%--22.3%，相對 Greedy 縮短 31.0%--43.8%。這表示若 collision 與繞路完全消失，shared mobility 的理想容量潛力很高。

Raw arrivals 中，local-first benefit gate 讓 Virtual p99 相對 Greedy 改善 14.0%--36.5%，並比 Static 小幅降低 0.06%--0.34%。平均 latency 也與 Static 幾乎相同。這表示 scheduler 已避免先前有害的自由移動，但目前 raw trace 下可安全利用的跨區機會有限。

50 個 paired cases 中有 37 個 Virtual p99 低於 Static、13 個略高；最差 regression 為 0.45%。因此這是經驗上的 near-no-regret 結果，還不是對任意未來 arrivals 的形式保證。

Cross-zone helper 完成工作後會回到自己的 home anchor；此 repositioning 真的延後 helper 的下一次可用時間。4--64 m 每個完整 trace 累積約 139--400 shuttle-seconds recovery，因此結果不是假設 helper 免費停留在任意位置。

因此 Greedy No-Zone 的損失至少有兩部分：collision/coordination，以及不受控制的 locality loss。移除 collision，再對跨區行為加入 locality-aware gate，才能回到不劣於 Static 的區域。

## Evidence boundary

- Static and Greedy rows are reused from the validated paired baseline runs; Virtual uses identical seeds, trace, and position mapping.
- Natural replay can produce different physical service counts because faster dispatch changes online merge opportunities.
- Ignoring shuttle collisions is physically impossible and is used only to quantify the value of perfect coordination.
- Reader exclusivity remains enforced; this is not an infinite-reader lower bound.
- The natural virtual dispatcher is an online local-first heuristic; its small average gain is not a formal competitive guarantee for arbitrary traces.
