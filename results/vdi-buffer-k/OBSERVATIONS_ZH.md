# Read-ahead buffer 容量 K（2026-10-19）

設定：`experiments/vdi-buffer-k/config.json`；腳本：`scripts/run_vdi_buffer_k.py`（用 `.venv/bin/python`）。Fujitsu VDI trace、B1、Zone 8 台車平行搬運、reader 前 buffer 用 FIFO。6 個窗口 × 2,000 筆，中位數。各 K 的到達序列相同。

負載 75% 時：

| K | 0 | 1 | 2 | 4 | 8 | 16 | 32 |
|---|---:|---:|---:|---:|---:|---:|---:|
| contiguous 平均延遲（s） | 250 | 241 | 226 | 222 | 199 | 196 | 196 |
| contiguous p99（s） | 759 | 668 | 654 | 591 | 585 | 582 | 582 |
| hash_1gib 平均延遲（s） | 224 | 182 | 180 | 165 | 165 | 158 | 154 |
| hash_1gib p99（s） | 713 | 556 | 550 | 520 | 481 | 468 | 458 |

- K 從 0 加到 4–8 時改善最多（p99 降 18–33%）；8 以上幾乎沒有差別。建議 **K = 8**。
- 負載 90% 時平均延遲的趨勢有雜訊（不單調），p99 趨勢與 75% 相同。
- **read-ahead 解決不了 reader 空等**：K = 32 時 reader 仍有 17–35% 的時間在空等，因為車的瓶頸不在入口。
- K 越大，趟數略增（例：contiguous 149 → 157）：platter 越早被搬走讀完，後到的同片請求就合併不到。
