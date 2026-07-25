# Research Knowledge Base

這個目錄保存可持續演進的論文知識，而不是全文備份。Markdown 是可閱讀、可修改、可由 Git 追蹤的 source of truth；`catalog.jsonl` 提供結構化檢索。

## 使用方式

對 Codex 可以直接說：

- 「把這篇 paper 加入研究庫。」
- 「用研究庫分析這個 Glass scheduling 問題。」
- 「從以前的 papers 找三個可轉移到這個 bottleneck 的 pattern。」
- 「檢查這個 DAC story 的 claim–evidence chain。」
- 「這個結果比較適合 DAC、ICCAD 還是 NeurIPS？」

全域 `research-knowledge-base` skill 會自動搜尋本目錄，閱讀相關 paper cards 與 patterns，再區分 source-backed evidence、reviewer inference 和 transfer hypothesis。

## 資料結構

- `catalog.jsonl`：每篇論文一筆結構化索引。
- `papers/`：claim–evidence paper cards。
- `patterns/`：跨論文、可重複使用的研究模式與 venue lenses。
- `questions/`：研究問題、狀態、支持與反對證據。
- `schema/`：新增論文時使用的固定模板。

## 讓知識庫持續變強

每加入一篇 paper，不只新增摘要，也要回答：

1. 它支持、限制或反駁哪個既有 pattern？
2. 它讓哪一個 research question 更可測試？
3. 它揭露哪個新的 semantic signal、physical constraint 或 crossover？
4. 它需要什麼 evidence 才能轉移到 Glass？

每累積五篇新 paper，做一次 consolidation：合併重複 patterns、標明衝突條件、檢查過時問題，並把已完成實驗的結果回寫。

## 本機查詢

```bash
python3 ~/.codex/skills/research-knowledge-base/scripts/research_kb.py locate
python3 ~/.codex/skills/research-knowledge-base/scripts/research_kb.py stats
python3 ~/.codex/skills/research-knowledge-base/scripts/research_kb.py search "movement time scheduling"
python3 ~/.codex/skills/research-knowledge-base/scripts/research_kb.py validate
```
