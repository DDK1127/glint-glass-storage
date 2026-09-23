# Windowed CBS No-Zone Study

## 實驗問題

在相同 640 個 Azure trace-derived batch-merged platter tasks、相同 placement、8 shuttles 與 8 readers 下，小視窗 conflict-tree planning 能否改善既有 Greedy No-Zone？

## 結果

| Panel | Static | Greedy No-Zone | Windowed CBS | CBS vs. Greedy | CBS vs. Static | Fallback windows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 m | 33.85 min | 51.10 min | 45.79 min | 10.4% faster | 35.3% slower | 5.2% |
| 8 m | 37.97 min | 52.23 min | 48.52 min | 7.1% faster | 27.8% slower | 3.2% |
| 16 m | 45.89 min | 59.12 min | 55.68 min | 5.8% faster | 21.3% slower | 1.2% |
| 32 m | 61.66 min | 74.26 min | 70.56 min | 5.0% faster | 14.4% slower | 0.7% |
| 64 m | 93.34 min | 105.08 min | 99.82 min | 5.0% faster | 6.9% slower | 0.3% |

## 觀察

Windowed CBS 在所有長度都優於 Greedy No-Zone。主要收益不是把所有 conflict 消除，而是 task-to-shuttle matching 保留較好的 fetch locality，並用 estimated reader completion 幾乎消除 reader queue。4--16 m 還能降低部分 holding/detour；32--64 m 的 coordination time 沒有改善，但較短 fetch movement 仍使 batch 更早完成。

CBS 相對 Greedy 的改善由 4 m 的 10.4% 降到 64 m 的 5.0%。相對 Static 的差距則由 35.3% 降到 6.9%。這表示部分解耦確實回收 No-Zone 的排程損失，但尚未證明 shared mobility 能打敗 Static 的 locality 與理想化零衝突假設。

平均每個 window 展開約 2.3--5.0 個 constraint-tree nodes。Fallback 比例由 4 m 的 5.2% 降到 64 m 的 0.3%，所以多數結果來自 conflict-tree solution；fallback 已獨立記錄。

## 方法邊界

- 這是 closed-batch experiment；尚未重播原始 ArrivalMs。
- 每側每個 window 只規劃兩個最早 tasks，並最佳化其 shuttle matching。
- Constraint 使用另一台 shuttle 的完整 continuous segment，較標準 CCBS unsafe interval 保守。
- CBS node cap 為 64；超過時使用 sequential reservation fallback。
- Static 仍由模型直接假設跨 zone conflict 為零，因此不是完全對稱的 collision-engine comparison。
- Windowed CBS 同時改變 matching、reader selection 與 routing，現在不能把全部收益單獨歸因於 CBS search。

## Reproduce

```bash
.venv/bin/python scripts/run_windowed_cbs_study.py --config experiments/windowed-cbs/full.json --workers 4
```
