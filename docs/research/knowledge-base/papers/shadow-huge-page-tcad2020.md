# Shadow Huge Pages for Ultra-Low-Latency Storage

paper_id: shadow-huge-page-tcad2020

## Metadata

- Source: `/Users/dongchengen/Desktop/Papers/Tutorial Papers 3/OS/S2_When Storage Response Time Catches Up With Overall Context Swtich Overhead, What Is Next (TCAD'20 & CODES+ISSS'20).pdf`
- Venue/year: IEEE TCAD 2020 / CODES+ISSS 2020
- Review date: 2026-07-26
- Evidence confidence: medium；story與分析模型完整，但 simulator、single-core 與 hardware change 限制 deployability。

## 30-second recall

當 ultra-low-latency SSD 降到約 3–10 μs，而 context switch 加上 cache/TLB disruption 約為 7 μs 時，page fault 後切換 thread 不再必然合理。4KB synchronous I/O fault 太頻繁，2MB async huge page 又可能搬太多無用資料。SHP 用 shadow-page promotion 和 variable-sized prefetch，依 locality 在 sync/async 與 transfer granularity 間切換。

## Story chain

```text
Virtual memory hides historically slow storage by context switching
→ ULL storage approaches software-switch overhead
→ synchronous small I/O wins below a crossover, but faults too often
→ huge async I/O amortizes faults but wastes transfers
→ observe locality and choose mode/granularity
→ reduce CPU wasting time and total execution time
```

## Source-backed claims

- Motivational analysis：3 μs device latency 且 I/O 不超過約 32KB 時，synchronous behavior 可能較好。
- Huge-page utilization 在多個 traces 中不足，顯示固定 2MB prefetch 的浪費。
- Paper report：CPU wasting time savings 約 15–60%，total execution time savings 約 7–39%，依 baseline/workload 而異。
- Evaluation 包含 device response、DRAM hit ratio、tail metric、energy 與 context-switch sensitivity。

## Mechanism map

| Component | Observation it addresses | Decision changed |
| --- | --- | --- |
| Shadow page promotion | only part of huge page is resident/useful | promotion granularity |
| Present map | huge TLB needs partial-presence state | per-subpage access handling |
| Variable prefetcher | locality changes over time | sync/async and prefetch size |

## Reviewer inference

這篇是「先找 technology crossover，再讓 policy 依 inequality 切換」的完整範本。方法名稱不是故事核心，舊 abstraction 的 turning point 才是。

## Evidence gaps

- Trace-driven、single-core simulator；modern multicore kernel behavior 更複雜。
- Huge TLB 增加 512-bit present map，hardware deployment cost 不小。
- Working-set DRAM sizing偏寬鬆，可能低估 memory pressure。
- Energy 相對 4KB policy 不一定全面改善。
- Tail metric 定義較不常見。

## Transfer hypotheses

- Glass work stealing 應存在類似 crossover：hotspot 剩餘服務時間若小於 helper repositioning/context cost，就不應啟動。
- Cheapest falsification：量 local service completion time 與 helper activation-to-first-useful-service time，找交叉邊界。

## Reusable patterns

- `technology-crossover`
- `fixed-granularity-trap`
- `phase-aware-adaptation`
- `analytical-switching-rule`

## Update history

- 2026-07-26: Initial ingestion.
