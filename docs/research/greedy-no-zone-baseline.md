# Greedy No-Zone Baseline and MAPF Solver Direction

## 一句話定義

目前的 Greedy No-Zone baseline 讓同側 shuttle 共享所有 platter 工作，再用依序提交的路徑預約避免衝突；它是用來暴露 shared mobility 成本的初始 heuristic，不是完整 MAPF 或最佳 No-Zone。

## 目前怎麼做

Natural-arrival replay 保留 Azure trace 的 arrival time、request order、object identity 與 bytes。已到達且映射到同一 platter 的 requests 可在 dispatch 時合併；未來才到達的 request 不會提前加入。

每次 dispatch 的流程是：

1. 先選等待最久且 platter 可用的 pending work。
2. Static Zone 只能使用固定 owner；No-Zone 可使用同側當下空閒的 shuttle。
3. No-Zone 從符合條件的 shuttle 中選擇目前位置離 platter 最近者。
4. Static 使用固定 zone reader；No-Zone 先按距離選最近 reader，reader availability 只作為距離相同時的 tie-breaker。
5. Controller 依序規劃 fetch、pick、delivery、reader service、return 與 place。若直接路徑與已提交路徑衝突，則比較延後出發及經其他 level 繞行的候選方案。
6. 先提交的工作不重新規劃；等待發生在容量無限、進出成本為零的抽象 holding pocket。

## 目前結果代表什麼

這個 baseline 會降低 static ownership 造成的 idle capacity，但同時會產生三種成本：跨 level dispatch 破壞 fetch locality、路徑等待或繞行、以及距離優先 reader selection 造成的少量 reader queue。因此目前結果只能描述這個 greedy policy，不能推論所有 No-Zone 或 MAPF 方法都較差。

更根本的 sanity condition 是：若 No-Zone 的合法策略集合包含 Static Zone，而且兩邊使用相同碰撞與資源規則，最佳 No-Zone 至少可以模仿 Static schedule，理論上不應更差。現有比較尚未滿足這個條件，因為 Static 的跨 zone conflict 直接設為零，而 No-Zone 的所有軌跡都接受 clearance 檢查。

## MAPF 和 CBS 的關係

MAPF（Multi-Agent Path Finding）是問題：為多台 agent 找到互不碰撞的路徑。CBS（Conflict-Based Search）是求解 MAPF 的一種演算法，不是與 MAPF 並列的另一個問題。

標準 CBS 先各自規劃最短路徑；若兩台 agent 在相同位置和時間衝突，高層 constraint tree 分成兩個分支，分別禁止其中一台 agent 使用該位置與時間，再對受影響 agent 重新規劃。它可以提供 completeness 與 optimality，但衝突密集時 constraint tree 可能快速成長。

Glass library 與標準 MAPF 還有差距：request 持續到達、controller 必須同時決定 task assignment，工作包含 pickup、delivery、reader service 和 return，movement 是 continuous time，且 reader 是有服務時間的共享資源。因此更接近 MAPD（Multi-Agent Pickup and Delivery）或 lifelong MAPF，而不是一次性的固定 start-goal MAPF。

## 建議定位

CBS 適合先作為小規模 oracle：固定一個 batch、task assignment 和 reader assignment，使用 CBS 或 Continuous-Time CBS 求出高品質 collision-free routes，量出現有 greedy reservation 與較佳 routing 的差距。

完整線上 baseline 應採分層設計：外層決定 platter task、shuttle 與 reader；內層用 rolling-window continuous-time MAPF 處理未來一小段時間的路徑。若內層使用 CBS，較合適的是 bounded-suboptimal、windowed 或 continuous-time variant，而不是每個 request 都重跑全域 optimal CBS。

下一個實驗順序：

1. `Static emulation under the same collision engine`：確認 No-Zone simulator 能重現 Static assignment 和成本。
2. `Greedy No-Zone`：保留目前結果作為簡單 heuristic baseline。
3. `Locality-aware dispatch`：共同評估 task、shuttle 和 reader 的預計完成時間。
4. `Small-batch CCBS oracle`：固定 task assignment，比較 greedy route reservation 與高品質 continuous-time routing。
5. `Rolling-window MAPD`：最後才處理原始 arrival stream。

目前已完成 `Windowed CBS` closed-batch 初版。它在每側以兩個 tasks 為小視窗，先做 locality-aware shuttle matching，再以 continuous segment constraints 解衝突，並按照預計完成時間選 reader。10-seed 結果相對 Greedy No-Zone 改善 5.0%--10.4%，但仍比 Static 慢 6.9%--35.3%。詳見 [Windowed CBS experiment](../../experiments/windowed-cbs/README.md) 與 [result report](../../results/windowed-cbs/ANALYSIS_ZH.md)。

## 目前 rack 假設

- 兩個不連通 panel sides，每側 8 levels。
- Level center spacing 為 0.5 m，中心座標範圍為 0 至 3.5 m，名義堆疊高度約 4 m。
- 每個 level 100 slots；640 platters 映射到總共 1600 cells。
- Vertical movement 為每跨一個 level 3 秒，跨 7 levels 最多 21 秒。
- Vertical clearance 為 0.65 m，大於相鄰 level 的 0.5 m spacing；No-Zone 可能將相鄰 levels 的同位置活動判為 conflict，Static 則跳過跨 zone 幾何檢查。

這些是研究模型參數，不是已校準的 Project Silica 實機尺寸。

## 來源

- Sharon et al., [Conflict-Based Search for Optimal Multi-Agent Path Finding](https://doi.org/10.1609/socs.v3i1.18222), SoCS 2012.
- Andreychuk et al., [Multi-Agent Pathfinding with Continuous Time](https://doi.org/10.24963/ijcai.2019/6), IJCAI 2019.
- Ma et al., [Lifelong Multi-Agent Path Finding for Online Pickup and Delivery Tasks](https://www.ifaamas.org/Proceedings/aamas2017/pdfs/p837.pdf), AAMAS 2017.
- Liu et al., [Task and Path Planning for Multi-Agent Pickup and Delivery](https://www.ifaamas.org/Proceedings/aamas2019/pdfs/p1152.pdf), AAMAS 2019.
