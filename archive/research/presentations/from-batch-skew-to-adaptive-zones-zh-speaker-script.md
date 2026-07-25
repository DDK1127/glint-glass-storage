# 《From Batch-Level Skew to Adaptive Service Zones》中文逐頁講稿

這份講稿對應 [英文簡報](from-batch-skew-to-adaptive-zones-en.pdf)。文字刻意從第一次接觸 Project Silica 的聽眾角度撰寫，可以直接照著說，再依實際報告時間刪減。

## Slide 1 — From Batch-Level Skew to Adaptive Service Zones

### 建議講稿

「大家好，今天我要談的是 Microsoft Project Silica 裡面 shuttle service region 的設計問題，以及我們為什麼想研究 adaptive service zones。

在開始之前，我先用很簡單的方式介紹這個系統。Project Silica 是把資料寫在玻璃媒體上的 archival storage system。這些玻璃媒體，也就是我們後面會說的 platter，會放在一個大型儲存面板裡。當系統收到 read request 時，需要由 shuttle 把指定的 platter 從儲存位置搬到 reader，讀完之後再放回去。

所以，這個系統的效能不只取決於 reader 有多快，也取決於 shuttle 要走多遠、不同 shuttle 會不會互相阻塞，以及工作是不是平均分配給所有 shuttle。

今天的核心問題是：如果不同時間被存取的資料位置不一樣，我們是否仍應該讓每台 shuttle 永遠負責同一塊固定區域？還是 service region 應該根據目前真正 active 的 requests 進行調整？

我的結論先講在前面：static partition 在 balanced workload 下有很好的 locality 和 congestion control；但是當 active requests 發生空間或時間上的偏斜時，固定 ownership 可能讓一部分資源很忙、另一部分資源閒置。我們想研究的是，在不放棄 locality 的前提下，讓 service ownership 能夠配合 workload 改變。」

### 轉場

「不過在討論 Microsoft 的設計以前，我想先用一個 controlled experiment，說明 access skew 到底可能對系統造成什麼影響。」

---

## Slide 2 — A Controlled View of Batch-Level Access Skew

### 建議講稿

「這一頁先說明我們怎麼建立 skew workload。這裡的 skew，可以先把它理解成 requests 沒有平均落在所有 zones，而是集中在某一個 zone。

我們使用同一組 100,000 筆 trace requests，切成 20 個連續 batches，每個 batch 有 5,000 筆 logical requests。這裡的 batch 就是一組一起進入排程、而且要等這組工作處理完，下一組才開始的 requests。

三個 workloads 使用完全相同的 requests、offsets、sizes 和 physical mapping。我們唯一改變的是 requests 進入各個 batch 的順序。Normal case 保留原本的 timestamp order；moderate case 讓每個 batch 目標有 50% requests 來自一個 temporary hot zone；severe case 則提高到 80%。

另外，同一個 batch 裡如果有多個 requests 對應到同一片 glass，我們會做 request merge，也就是把它們合併成一次 physical glass service。因此，logical request 數量和 shuttle 真正需要執行的搬運工作量不一定相同。

這裡需要先強調：50% 和 80% 是我們為了觀察影響而控制出來的 skew 程度。這個實驗能回答『如果出現這種 skew，系統會發生什麼事』，但不能回答『真實 workload 多常出現這種 skew』。」

### 轉場

「接著先看左圖。我們要先分清楚 logical request skew 和真正 physical work skew 的差別。」

---

## Slide 3 — Logical Skew Is Not Physical Work Skew

### 建議講稿

「這張圖的左半邊是在看，每一個 batch 裡最忙的 zone 到底占了多少比例。

我們的模型有 8 個 zones。如果工作完全平均，每個 zone 應該大約負責八分之一，也就是 12.5%，所以圖上的虛線代表 perfect balance。

藍色柱子是 logical requests。Normal batches 的 P95 busiest-zone request share 是 28.4%；moderate skew 被控制在 50%；severe skew 則是 80%。P95 的意思是，大部分 batches 都不會超過這個數值，只有最偏斜的少數 batches 可能更高。

紅色柱子是 merge 之後真正需要執行的 active work。可以看到，80% logical request skew 最後只轉換成 64.1% post-merge work skew。原因是很多 requests 可能指向同一片 glass，最後只需要進行一次 platter fetch。

因此，這一頁真正要表達的不是『80% request skew 很嚴重』而已，而是 scheduler 不能只看 request count。它至少還要知道 merge 之後有多少 unique glass tasks、要讀多少 bytes，以及 shuttle 需要付出多少 mechanical work。」

### 指圖方式

先指出 12.5% 虛線，再依序指 normal、moderate、severe 的藍紅柱差距。不要一開始就念所有數字，先解釋藍色和紅色代表什麼。

### 轉場

「知道 work skew 之後，下一個問題是：這些不平均的工作，會如何影響整個系統可使用的 capacity？」

---

## Slide 4 — Under Fixed Ownership, Skew Strands Capacity

### 建議講稿

「右圖呈現的是同一個現象對系統 capacity 的影響。

這裡的 working capacity，表示所有 shuttle-reader pairs 在整個 batch drain 期間，有多少比例的時間真的在處理自己的 queue。Waiting 則表示某些 zones 已經沒有 local work，但仍然必須等待最忙的 zone 完成。

Normal workload 下，85.1% 的 capacity 在工作，只有 14.9% 處於等待。到了 moderate skew，working capacity 降到 35.4%；severe skew 更只剩下 22.1%。換句話說，severe case 中有 77.9% 的 zone-time capacity 沒有被利用，但整個 batch 還不能結束。

這裡最重要的直覺是：系統並不是缺少 shuttle，也不是所有 readers 都已經飽和。相反地，系統裡還存在很多 idle resources，只是 strict static ownership 不允許它們去處理 hot zone 的 queue。

因此，整個 batch 的完成時間不是由 aggregate capacity 決定，而是由最忙的 static owner 決定。Hot zone 變成 critical path，其他 zones 即使提早做完，也無法縮短最後完成時間。」

### 轉場

「Capacity utilization 的下降最後會反映在 makespan、throughput 和 tail latency 上。下一頁就是這些 system-level consequences。」

---

## Slide 5 — The Performance Consequence

### 建議講稿

「這一頁把前面的 capacity imbalance 轉換成比較直觀的效能指標。

Makespan 是完成全部 20 個 batches 所需要的總時間。Normal order 需要 15.29 小時；moderate skew 增加到 32.50 小時；severe skew 則增加到 42.79 小時，相對於 normal case 是 2.8 倍。

Throughput 是每秒完成多少 logical requests。它從 1.817 requests per second 降到 0.649。P99 latency 則代表最慢的 1% requests，其 latency 從 0.79 小時增加到 2.39 小時。

這三個指標其實都來自同一個原因：hot zone 的 local owner 必須依序處理大量工作，而其他 zones 的資源不能有效加入。也就是說，真正的 bottleneck 不是系統總共有多少資源，而是 active work 被哪個 owner 綁住。

但這裡要小心，這些數字是在 sequential-batch model 下得到的。我們假設下一個 batch 必須等待前一個 batch drain。如果是真正 online arrivals，不同時間的 backlog 可能重疊，最後 throughput degradation 不一定完全相同。」

### 轉場

「所以這個實驗顯示 skew 可能很重要，但在把它當成研究動機之前，我們也必須先誠實說明目前證據的限制。」

---

## Slide 6 — Evidence Boundary: Batch Size Matters

### 建議講稿

「這一頁是我認為很重要的 evidence boundary，也就是我們目前可以說到哪裡、不能說到哪裡。

第一，50% 和 80% skew 是透過 request reordering 控制出來的，不是直接從 trace 中量到的自然分布。因此，我們目前證明的是 sensitivity，不是 prevalence。也就是說，我們知道 skew 發生時 static ownership 會受到影響，但還不知道真實 workload 多常、持續多久會形成這種 skew。

第二，目前 batch size 固定為 5,000。當 batch size 增加時，一個 batch 可能包含更多彼此獨立的 requests，短時間的 hotspot 就可能被平均掉。這也是為什麼在某些 datasets 中，batch 越大，觀察到的 skew effect 可能越小。

但是這不能寫成『batch size 越大，skew 一定越小』。如果 hotspot 是持續存在的 spatial hotspot，即使 batch 很大，requests 還是可能集中在相同區域。Request merge 也可能讓 logical skew 和 physical work skew產生不同變化。

因此，下一步必須對 batch size、observation window 和 online arrival rate 做 sensitivity sweep。這樣我們才能回答：這個問題在什麼 workload 條件下最明顯，以及什麼時候 static partitions 已經足夠好。」

### 轉場

「在承認這些限制之後，我們再回到 Microsoft Project Silica，先理解它為什麼要採用 static partitions。」

---

## Slide 7 — Why Microsoft Uses Static Partitions

### 建議講稿

「Microsoft 把一個 panel 分成多個 rectangular logical partitions。每個 partition 至少包含一台 shuttle 和一個 read-drive slot。在正常情況下，每台 shuttle 只在自己的 partition 裡移動。

這個設計的目的不是因為 shuttle 在硬體上不能跨區，而是 Microsoft 刻意限制正常服務範圍，以換取可預測性。

如果每台 shuttle 都能任意去任何地方，traffic manager 就必須同時處理大量可能交叉的路徑、collision avoidance、stop-and-go，以及 reader ingress competition。這對 real-time scheduling 會非常複雜。

Static partition 把問題局部化之後，每台 shuttle 的路徑通常更短，與其他 shuttle 發生 conflict 的機會也比較低。Microsoft 的實驗也顯示，partitioning 在 balanced workload 下能降低 congestion，並有 power 和 predictability 上的優勢。

所以，我們不能把故事寫成『Microsoft 不應該限制 shuttle』。更準確的說法是：Microsoft 暫時犧牲部分 global flexibility，換取 normal operation 下更容易控制的 traffic。這是一個合理的 tradeoff。」

### 轉場

「既然 static partition 有這些優點，那研究空間在哪裡？問題出現在固定的 service ownership 遇到會變動的 access pattern。」

---

## Slide 8 — Where Fixed Ownership Becomes Restrictive

### 建議講稿

「Static partition 的 service ownership 主要根據 panel geometry 建立，也就是先把 physical panel 切成幾個固定區域，再把落在每個區域裡的 active requests 交給對應 shuttle。

但是 workload 並不是依照 panel geometry 平均產生。某一段時間可能有大量 requests 指向 Zone 0，下一段時間 hotspot 又移到 Zone 4。也可能出現短時間 burst，或者某一組熱門資料持續被存取。

這就產生 geometry-driven ownership 和 time-varying demand 之間的 mismatch。Hot zone 的 shuttle 和 reader 會持續忙碌，cold zones 的資源可能很早就 idle；而且 fixed zone 不會因為目前沒有 requests 就自動縮小，也不會因為某個 region 變熱就自動得到更多服務資源。

從 shuttle 的角度來說，它本來具有在 panel 中移動的硬體能力；static ownership 在 normal operation 下沒有使用完整的 global flexibility。這個限制在 balanced workload 下是有價值的，但在 strong or shifting hotspot 下可能變成 performance bottleneck。

因此，我們真正質疑的不是 partitioning，而是 service ownership 是否應該長時間完全固定、只按照 physical geometry 決定。」

### 轉場

「Microsoft 其實也知道 fixed ownership 可能造成 load imbalance，所以它提出了 work stealing 作為 fallback。」

---

## Slide 9 — Work Stealing Restores Some Flexibility

### 建議講稿

「Project Silica 的 controller 會監控每個 partition 還有多少 data volume 等待讀取。當最忙和最閒 partitions 的 load difference 超過 threshold，就可能觸發 work stealing。

Work stealing 的做法是讓 lightly loaded partition 的 shuttle 暫時離開自己的 partition，到 overloaded partition 取 platter。跨區時仍然使用 shortest-path routing。這樣原本 idle 的 resource 就能協助 hot queue，恢復一部分被 static ownership 限制的 flexibility。

而且 work stealing 確實有效。在 Microsoft 的 skew evaluation 中，如果沒有 load balancing，tail completion time 超過 21 小時；加入 work stealing 後降到 11.5 小時。因此，我們不能把 work stealing 描述成沒有用，或只是額外 overhead。

但這個改善也有代價。Microsoft 報告的 tail travel time 從 29.4 秒增加到 76 秒，論文也明確指出 shuttle 在 partition 外移動可能造成 additional congestion。

所以 work stealing 建立了一個新的 tradeoff：它改善 load balance，但同時重新引入 static partition 原本想避免的 cross-partition movement。」

### 轉場

「接下來用一張簡單的圖說明，為什麼只知道哪個 partition 最閒，還不足以決定誰應該幫忙。」

---

## Slide 10 — The Remaining Work-Stealing Cost

### 建議講稿

「這張圖是一個簡化的矩形 panel。左側有四個 zones，右側也有四個 zones。假設左上角 Zone 0 是 hot zone，而右下角 Zone 7 是目前最冷、最有空閒 capacity 的 partition。

如果只根據 load 選 helper，系統可能會選 Zone 7。但 Zone 7 的 shuttle 要協助 Zone 0，必須先經過 Zone 5、Zone 3、Zone 1，再到達 Zone 0。這段移動在開始處理任何 hot request 以前就已經產生 repositioning delay。

取得 platter 後，還需要考慮 platter 要送到哪一個 reader、讀完後如何返回原始 storage slot，以及 helper 完成後是否要回到自己的 service region。也就是說，一次 stealing 的成本不是只有前往 hot zone 的單程距離。

此外，如果 intermediate zones 本來就有正常 local traffic，跨區 helper 可能需要等待、減速或和其他 shuttle 協調。如果同時有多台 helpers 進入 hot zone，也可能競爭相同 ingress path 或 reader resources。

目前這張圖表達的是 potential exposure。Intermediate-zone waiting 和 multi-helper congestion 還沒有在我們的 simulator 中完整證明，所以報告時應該說『可能產生』，而不是說『一定會造成』。」

### 轉場

「這就帶到我們目前最重要的 insight：最冷的 zone，不一定是最適合的 helper。」

---

## Slide 11 — Key Insight: Load Alone Is Not Enough

### 建議講稿

「我們目前做了一個最小的 single-helper experiment。固定 Zone 0 是 strong hotspot，並分別讓不同距離的 zone 提供一台 helper。所有 cases 使用相同的 task list、hotspot intensity 和硬體參數。

在 collision-free model 中，鄰近的 Zone 2 helper 可以讓 makespan 降低 40.6%，並增加 0.68 小時 aggregate travel。遠距的 Zone 7 helper 只能降低 27.4% makespan，卻增加 1.91 小時 aggregate travel。

為什麼遠距 helper 的改善比較少？因為 helper 必須花更多時間在 cross-zone movement 上，所以它能夠實際偷走並完成的 hot tasks 比較少。也就是說，即使 Zone 7 比 Zone 2 更空，它提供的 net benefit 仍可能比較低。

因此 helper selection 不能只看 load difference，而應該考慮 expected completion-time reduction，扣掉 repositioning、platter round trip 和其他 movement cost。未來加入 collision model 之後，還需要扣掉 intermediate-zone interference 和 hot-zone congestion。

這裡同樣要標明證據邊界：現有結果證明的是 direct movement cost 和 locality effect，還沒有證明實際 collision delay。」

### 轉場

「既然 task-level work stealing 需要反覆支付 cross-zone cost，我們想問：能不能不要只在失衡發生後偷幾個 tasks，而是重新調整整個 active workload 的 service ownership？」

---

## Slide 12 — Proposed Direction: Adaptive Service Zones

### 建議講稿

「我們提出的方向是 adaptive service zones，或者也可以稱為 request-centric virtual zones。

這裡要先澄清，它不是讓每台 shuttle 對每個 request 都可以任意穿越整個 panel。如果完全取消 spatial structure，很可能重新遇到 Microsoft 在 global shortest-path baseline 中觀察到的 congestion 和 routing complexity。

我們希望改變的是 logical service responsibility。Controller 先觀察目前 active requests 位於哪些 glass、分布在哪些 regions，以及 merge 後真正需要多少 mechanical work，再決定這個 control epoch 中每台 shuttle-reader pair 應該負責哪一組 tasks。

如果某個 region 很熱，它的原本 static zone 可以縮小，或者切成多個 temporary service groups，讓多組資源共同處理。如果某個 cold region 目前沒有 active requests，就不需要長期保留完整 service capacity。

但是每個重新形成的 service region仍應保持 spatially compact，限制最大跨區距離和同時 helpers 數量。Assignment 在一個 epoch 內保持穩定，並使用 hysteresis，避免 workload 稍微變動就不斷重新配置。

Glass 的 physical location 不需要改變，也不需要做 background data migration。我們改變的是誰負責服務目前的 glass tasks，而不是把資料搬到新的位置。」

### 轉場

「接著要把這個方向轉換成可以被實驗驗證或否定的 research hypothesis。」

---

## Slide 13 — Research Hypothesis

### 建議講稿

「我們的核心 hypothesis 是：request-adaptive service zones 可以回收 strict static ownership 下被 stranded 的 capacity，同時使用比 reactive work stealing 更少的 cross-region travel。

要公平驗證這件事，所有 policies 必須 replay 完全相同的 merged glass-task list。不能讓其中一個方法因為 merge outcome 不同而看起來比較快。

我們至少需要四個 baselines。第一是 strict static partitions，用來呈現 fixed ownership bottleneck。第二是 Microsoft-style work stealing，這是最重要的現有方法。第三是我們的 adaptive service zones。第四是 ideal shared pool，讓所有資源沒有 locality 限制，作為 optimistic flexibility upper bound。

評估時不能只報 throughput。我們還要量 makespan、P95 和 P99 latency、各 shuttle-reader pair 的 utilization variance、cross-zone travel、route-conflict waiting，以及 reconfiguration overhead。

如果 proposed method 只降低 makespan，卻產生和 global sharing 一樣高的 congestion，研究主張就不成立。反過來，如果 Microsoft-style work stealing 已經能以很低的 travel cost 接近 ideal result，我們的方法也沒有足夠研究空間。

真正成功的結果應該是：在 balanced workload 下接近 static partitions；在 persistent or shifting skew 下接近 shared-pool performance；同時 travel 和 congestion 明顯低於 unconstrained sharing。」

### 轉場

「最後，我用五個重點把整個故事收回來。」

---

## Slide 14 — Takeaway

### 建議講稿

「第一，controlled batch experiment 顯示，當 active work 集中在少數 zones 時，strict fixed ownership 可能讓 hot queue 和 idle resources 同時存在。

第二，這個結果仍然受到 dataset、batch size、merge behavior 和 sequential-batch assumption 影響，因此我們還需要做 sensitivity study，不能直接宣稱所有真實 workloads 都會有相同問題。

第三，Microsoft 使用 static partitions 有充分理由。它能保留 locality、降低 congestion，並讓 traffic management 更容易即時控制。我們的目標不是完全否定 partitioning。

第四，work stealing 能有效改善 load imbalance，但它是一個 reactive fallback，而且需要額外 cross-zone movement。最冷的 partition 也不一定是 net benefit 最高的 helper。

第五，因此我們看到的研究機會是：讓 service ownership 根據 active requests 調整，而不是讓所有 workloads 永遠使用同一張固定 ownership map。同時，新的 service regions仍必須保持 spatially compact、stable and bounded。

最後一句話總結就是：Adapt ownership to the workload, rather than forcing every workload into the same fixed ownership map。也就是讓 ownership 適應 workload，而不是強迫每一種 workload 都去適應固定 ownership。」

---

## 報告時要避免的四種說法

1. 不要說「Static partition 是錯誤設計」。應說它在 balanced workload 下有 locality、congestion 和 predictability 優勢，但 fixed ownership 對 skew 的適應能力有限。
2. 不要說「Batch 越大，skew 一定越小」。應說 larger aggregation windows 可能平滑 transient skew，但結果取決於 dataset、hotspot persistence 和 merge。
3. 不要說「Work stealing 沒有效果」。Microsoft 的結果明確顯示它大幅降低 tail completion time；我們研究的是它的 movement tradeoff 和更好的 adaptation opportunity。
4. 不要說「我們要讓 shuttle 完全不受限制」。應說我們調整 logical service regions，同時保留 compactness、bounded crossing 和 assignment stability。

## 一分鐘版本

「Project Silica 使用 static partitions，把 shuttle 限制在固定區域，以降低 congestion 並簡化 traffic management。這在 balanced workload 下非常有效；但當 active requests 集中在少數 physical regions 時，hot zone 可能持續排隊，而其他 zones 的 shuttle-reader resources 已經 idle。我們的 controlled batch experiment 顯示，這種 fixed ownership mismatch 可能大幅降低 useful capacity，但實際程度仍取決於 dataset 和 batch size。Microsoft 使用 work stealing 讓 lightly loaded shuttle 暫時跨區協助，能改善 load balance，卻增加 cross-zone travel，而且最冷的 zone 不一定是最適合的 helper。因此，我們想研究 adaptive service zones：根據目前 active and merged glass tasks 調整 logical service ownership，同時限制跨區距離、保持 spatial locality，並避免 unrestricted global movement。」
