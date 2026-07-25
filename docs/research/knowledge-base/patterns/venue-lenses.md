# Venue Lenses

這些是規劃與自我檢查用的 lenses，不取代當年度官方 Call for Papers。

## DAC

適合 hardware-aware system、architecture、HW/SW co-design 與 design methodology。六頁篇幅下，故事要集中在一個 broken assumption、一個關鍵 insight、少量必要元件和明確 ablation。

常見證據需求：

- 實機或經校準的 simulator/model。
- hardware constraint 與 design decision 的直接連結。
- latency/throughput/energy/area 或 implementation overhead。
- 對 workload、system scale 與關鍵參數的 sensitivity。

## ICCAD

除了系統與 architecture，應強化 cost model、optimization formulation、design-space exploration 或可重現的 CAD flow。只有 heuristic 結果較好通常不夠；需要說明 objective、constraints、complexity 與近似邊界。

## NeurIPS

SysML infrastructure 可以是範圍，但單純加速 ML workload 不是充分條件。至少需要讓 ML 社群關心的核心主張成立，例如：

- accuracy/recall/quality 與 systems cost 的共同 tradeoff；
- 對模型、資料或 learning behavior 的新 insight；
- 跨資料集與設定的 generalization；
- 統計完整性、強 ML baselines、reproducibility；
- 新的 evaluation、negative result 或 use-inspired contribution。

UPVSS 若朝 NeurIPS，需要補 recall-quality 與 production ANN evaluation。UPForest 需要更完整的 learning quality、forest sizes、統計與同演算法 baselines。
