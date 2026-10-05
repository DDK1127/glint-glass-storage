# 簡報故事線與講者備註

## 1. 讓 Reader 持續有玻璃可讀

本簡報是合成離散事件模擬的研究討論稿，非實機測量或已完成投稿結果。研究單位已修正為單一 partition、多 shuttle、一 reader。所有數字來自本次新實驗。增加 shuttle 的主要作用是平行供料與減少排隊，不保證單一 request 的實際移動時間下降。

## 2. 一次讀取：搬運、交付、讀取三段接力

整個系統可以有很多個 partition，這次只看其中一個。圖中的 8 是儲存架的 rows，不是 8 個 reader。每次讀取都要經過三段：shuttle 取出玻璃並送到交付站、在交付站把玻璃交給 reader（reader 忙的時候先放進 feeder buffer）、reader 裝載後讀取。讀完之後玻璃要送回原位，這段歸還的時間也會占用 shuttle，所以全部計入成本，但這次不對歸還策略做最佳化。

## 3. 瓶頸在搬運：Reader 大部分時間在等玻璃

數據來自 shuttle 數量實驗的 N=1：32 m rack、read=8 s、B=4、Non-Zone FIFO、均勻 closed batch。只有一台 shuttle 時沒有交通干擾，所以這是單台 shuttle 服務一片玻璃的純時間：取件加送到 reader 約 38 秒，交付和讀後歸還約 28 秒，平均每片約 66 秒。Reader 處理一片只需要 load+mount 2 秒、讀取 8 秒、unload 1 秒，共 11 秒。所以 reader 大部分時間在等玻璃，利用率只有 17%。瓶頸在搬運，不在讀取，因此需要多台 shuttle 平行供料；理想配比約為 66 / 11，約 6 台。

## 4. 單台 Shuttle：Reader 可能大部分時間在等

數據E1 length=64m read=8s policy=zone B=4 uniform batch。Reader utilization分母為第一request到最後unload，不含最後return drain；分子包含load/read/unload。N改變時Zone劃分也改變，是整體provisioning比較。不是單一request movement變短的證明。

## 5. 一個 Partition 配置幾台 Shuttle 才合理？

虛線是理想情況：把 N=1 的結果直接乘以 N，假設 shuttle 之間完全不互相干擾，大約 6.0 台就能讓 reader 滿載。實線是模擬結果：要 12 台才超過 90%（94.2%），16 台達到 98.9%，之後再加車沒有幫助。兩條線之間的差距就是多台 shuttle 共用路段的協調成本：每個 request 的路段等待從 N=4 的 17 秒增加到 N=12 的 66 秒。這個配比是在目前的模擬假設下得到的，不是實機校準值；rack 長度或讀取時間改變時，配比也會跟著改變。

## 6. 車太多反而變慢：最佳點落在 8 台

兩條線使用同一個 partition、同樣的 requests，只差在有沒有擁擠成本。擁擠模型的意思是：路線每被一台已預約的車擋到一次，就多一次停下再起步，這段時間仍佔用該路段，所以車越密集，共用路段實際能通過的車越少。沒有擁擠成本時，加車到約 16 台後吞吐量持平，但不會下降。有擁擠成本時，吞吐量在 8 台達到最高（3.26 req/min），之後越加越慢；32 台時只剩 0.90 req/min，和只有 1 台（0.91）差不多，因為 shuttle 有 90% 的時間在等其他車。注意：每次停走成本設為 0.9 秒，這個值是為了讓最高點落在 8 台而選的示意情境，不是實機量測；成本較小時最高點會往更多台移動（例如 0.5 秒時約 12 台），成本較大時則往更少台移動。這頁要說明的是「擁擠成本存在時，會有一個最佳配比，超過就幫倒忙」，而不是「最佳配比一定是 8 台」。

## 7. 固定台數下，怎麼分工？從 Zone 到 Non-Zone 是一條光譜

這一段不放實驗圖，改講怎麼實作。Zone 和 Non-Zone 不是二選一，而是一條光譜的兩端。左端 Zone：每台車只搬自己負責那幾排，控制器幾乎不用做全域決策，但熱區只有一個人能搬。右端 Non-Zone：誰有空誰搬，人手不會閒著，但控制器要做全域派工、路段預約和避讓，而且前一頁看到車太多會塞車。中間是混合做法：平常各管各的，需要時才跨區。接下來三頁分別講兩端怎麼實作，以及我們想嘗試的中間做法。

## 8. Zone 怎麼實作：各管各的，但入口要協調

Zone 的實作需要三個元件。第一是分區表：N 台車平分 8 排，所以 N 必須整除 8。第二是各區的工作佇列：每台車只看自己區的 request，最舊的先搬。第三是共用區協調：不管怎麼分區，所有車都要經過接駁段和 reader 入口，這裡仍然要用預約或排隊，一次只放一台。模擬中的 Zone 就是這樣實作，共用路段和 Non-Zone 使用同一套預約規則，沒有假設 Zone 在 reader 前完全不會衝突。好處是決策簡單、區內不互卡；限制在後面第 17 頁以後會用數據展開：熱區只有一台能搬、N 要整除排數、壞一台整區讀不到。

## 9. Non-Zone 怎麼實作：派工、路段預約、限流

Non-Zone 的控制器要回答三個問題。一、派哪台車：所有 request 放在同一個全域佇列，從空車中選預計最早把玻璃送到 reader 的那台；模擬目前的 Non-Zone FIFO 就是這樣做。二、走哪條路、何時出發：用路段預約表，每段路在時間軸上先訂位，有衝突就延後出發；進階做法是在一個小時間視窗內把幾台車一起規劃（例如 windowed CBS）。三、同時放幾台上路：前一頁看到車太多會塞車，所以共用區同時上路的車數要有上限 K，K 是可以調的參數，而不是把車賣掉。風險是每次派工都要評估「工作 × 車」的組合，車越多計算量越大；規則不好時車會跨區亂跑、互相擋路。

## 10. 中間路線：四個想嘗試的做法

四個中間做法。一、Work stealing：Project Silica 的既有做法，某區積壓超過門檻時，閒的鄰區車過來幫忙，並限制同時幫忙的車數；這是強基準，新方法要贏它才有意義。二、軟分區：派工分數等於預計送達時間加上跨區懲罰，懲罰很大時等於 Zone，懲罰為零時等於 Non-Zone，只用一個參數就能在光譜上連續移動，可以畫出取捨曲線。三、動態重劃區：每隔一段時間依各區積壓重新分配每台車負責的排數，處理熱區會移動的情況，難點是重劃時正在搬的車怎麼處理。四、限流：reader 共用區同時最多 K 台，直接對應前面車太多會塞的結果。二到四都是待驗證構想，還沒有本輪數據。

## 11. 搬運與讀取的時間接不上

前面看到 shuttle 服務一片玻璃約 66 秒，reader 只要 11 秒，所以要多台 shuttle 平行供料。但多台 shuttle 的抵達時間不規則：有時同時到、有時一段時間都沒有車到。沒有暫存位置時，早到的 shuttle 只能載著玻璃等 reader，晚到時 reader 只能空等。想法是在 reader 前面留一小塊位置，讓下一批玻璃先就位，把搬運時間藏在讀取時間後面。Buffer 只能吸收時間差，不能補足長期不足的搬運吞吐量，也不會縮短實體搬運距離。

## 12. Prefetch Buffer 架構：在 Reader 前方劃出待讀區

圖為示意：一個 partition 有 8 條 rack，每條 80 個 slot；圖中畫 N=4 台 shuttle，每台在 Zone 下負責 2 條相鄰 rack，但可以在多條 rack 間移動。Reader 在 partition 右下角，reader 前方 rack 的最後幾個 slot 由軟體劃為 prefetch buffer：黃色是已預取、等待讀取的玻璃，白色是空位。Request 已知時，shuttle 先把玻璃搬進 buffer，reader 讀完目前這片就直接讀下一片。讀完的玻璃仍要送回原 slot。模擬中 buffer 以 reader 前的 B 個 slots 建模，實體位置做了抽象；接下來的實驗固定 N=8，比較 B=0/8/16。

## 13. N=8 Prefetch：先看 p99 是否下降

這張圖來自 results/partition-feeder-prefetch-n8。X是prefetch buffer slots，Y是每個run的p99 latency平均。B=8符合一片/一台shuttle的主要設計點；B=16是額外容量敏感度。

## 14. Prefetch hit：玻璃真的提早到位了嗎？

prefetch hit是handoff早於該片reader start的比例；lead是平均提前秒數；route motion是實體fetch/delivery/return路段時間，不包含traffic wait。這張圖來自N=8、read=8s、uniform。

## 15. B=16 仍有收益，但很快出現遞減

B=8與B=16都在N=8的同一partition。B=16有時提升lead time，但throughput與p99的額外改善很小；Non-Zone hotspot甚至不改善。這支持有限prefetch window的動機，不支持無限buffer。

## 16. 加入到達時間後，再檢查一次

E4 N4 L32 read8，rate=.6/11 req/s。Rate是standalone reader ceiling的60%，不是實際transport系統capacity的60%。在較慢policy可能overload，有限episode p99不是steady-state。Synthetic arrivals，不是Azure trace。

## 17. 下一步：Zone 為什麼不一定好？

這一段是下一輪研究的故事線，不是已完成的結論。比喻：reader 是只有一個出餐窗口的餐廳，shuttle 是外送員，prefetch buffer 是門口的暫存台。Zone 是每位外送員只搬自己負責那幾排貨架；Non-Zone 是誰有空誰去搬。故事分五步：一、平均時 Zone 很好；二、它隱含了四個假設；三、需求不均時 buffer 救不了 Zone；四、除了負載不均，還有幾個不直觀的問題；五、Non-Zone 有彈性但會塞車，因此需要會看 buffer 狀態的 Non-Zone 調度。

## 18. Zone 偷偷假設了四件事

左側數據：N=8、read=8 s、B=0、uniform。Zone 每個 request 的路段移動約 44 秒、路段等待約 6 秒；Non-Zone FIFO 分別約 56 與 37 秒。所以平均時 Zone 的局部性是真的。右側四個假設：需求平均、需求不隨時間變、每台車都可用、一次只讀一片。Silica 論文提到 shuttle 故障可能讓 storage racks 被隔開，平台不可用時要用 cross-platter network coding 讀同一 platter-set 的其他平台，這讓第三、四個假設在真實系統中會被打破。

## 19. Buffer 救得了時間差，救不了人手不均

數據：results/partition-feeder-prefetch-n8，hotspot、N=8、read=8 s。Zone 的 buffer 從 8 格加到 16 格，玻璃平均提前時間從 60 秒增加到 113 秒，但 prefetch hit 只從 44% 變為 45%，throughput 幾乎不變。解讀：多出來的 slot 被冷區提早送來的玻璃占住，熱區玻璃仍然卡在單一 owner。受限閒置（restricted idle）是 shuttle 閒著、但剩下的工作都不屬於它的時間；hotspot 下每個 request 約 144 shuttle-s，uniform 只有約 16。「buffer 被冷區玻璃占住」是推論，需要下一輪的 buffer 組成指標直接量測。

## 20. 負載不均以外，Zone 還沒考慮到的七件事

這一頁是目錄。七件事都來自同一個前提：每台車只看自己那一區。第五件已有本輪 E3 數據，其他是待驗證的假設，接下來每頁會說明 Zone 以為什麼、實際會發生什麼、Non-Zone 怎麼處理，以及怎麼驗證。

## 21. 距離不平均：需求平均，遠區仍然較慢

Zone 以為需求平均就等於每台車的工作量一樣。但工作量是次數乘以每趟時間：每片玻璃都要送到 reader，遠區 owner 每趟要多跨好幾排，來回時間較長，所以遠區的供料速率天生較慢，遠區資料的等待時間會比較長。Non-Zone 可以讓剛好在附近的空車去接，遠區的工作不必全部由同一台車承擔。驗證方式：uniform 負載下，依 rack 分組比較 p99，並計算每台 owner 的忙碌率。這是待驗證假設。

## 22. 先到先讀 = 近的先讀

Zone 以為 buffer 先進先出很公平。但 FIFO 的「先」是玻璃送到 buffer 的時間，不是使用者發出請求的時間。近區的車來回快，總是比較早送到，因此一直排在前面；遠區的請求就算最早發出，也可能最後才被讀，尾端延遲被放大。Non-Zone 可以優先派車去搬等最久的那一片，最急的工作不會被綁在某一台忙碌的車上。驗證方式：計算請求順序與讀取順序之間的逆序數，並比較各區 p99。這是待驗證假設。

## 23. Buffer 落在某一區：最擠的地方沒有分區保護

Zone 的賣點是各區互不干擾。但照我們的架構，prefetch buffer 是 reader 前方的 rack slots，必然落在某一區裡，圖中是 S4 的 Rack 3。每一台車都要開進 S4 的地盤交貨，所以整個 partition 最擁擠的地方剛好沒有分區保護，而 S4 自己的取件工作還會被其他車擋住。Non-Zone 本來就假設路段是共用的，從一開始就把 reader 前的交通納入調度。驗證方式：比較 buffer 所在區與其他區的路段等待，並改變 buffer 位置看敏感度。這是待驗證假設。

## 24. 空車回程與停車位置

Zone 以為只在自己區裡跑，路線最短。但每一趟都一定要到 reader：送完之後，車只能空車回自己的區；讀完的玻璃也只能由原本的 owner 送回去。閒置時，車也只能停在自己區，可能離 reader 很遠。Non-Zone 送完可以順路帶一片讀完的玻璃回附近的 rack，再接附近的下一單；閒置的車也可以停在 reader 附近待命。驗證方式：統計空車行駛距離比例，以及歸還造成的額外趟數。這是待驗證假設。

## 25. Buffer 前排成車隊：加了 buffer，Zone 的車卻沒少等

數據：E3，uniform、N=8、32 m、read=8 s。等交付時間是 shuttle 抵達 reader 端後等待交貨的時間，除以 request 數。Non-Zone FIFO 從 B=0 的 12.4 秒降到 B=4 的 0.2 秒；Zone 從 30.2 秒變成 35.3 秒，沒有減少。一個可能的解釋是：Zone 的各台車各自決定何時出發，常常同時抵達，在 buffer 前排成車隊；Non-Zone 由中央指派，抵達時間比較分散。這是已觀察到、但原因未確定的現象，需要記錄抵達時間分布與排隊長度才能確認。

## 26. 短時間的擁擠：長期平均均勻，短期一直有熱點

Zone 以為長期平均是均勻的，所以每一區都一樣忙。但真實的請求常常成串出現，例如同一個檔案、同一個使用者的連續讀取，幾分鐘之內就集中在同一排。分區是依長期平均設計的，排隊卻發生在短時間內：每個時段都有一區忙翻、其他區閒著。Non-Zone 在每個當下把閒著的車派去最忙的地方，不需要長期平均成立。驗證方式：總體均勻、但連續 k 個請求落在同一排，k 從 1 掃到 32。這是待驗證假設。

## 27. 車不可用：故障、充電、磨損，整區停擺

Zone 以為每台車隨時可用。但 Project Silica 的 shuttle 是用電池的，熱區 owner 跑最多趟，最常需要充電、磨損也最快。每次它不在，不管是故障、充電還是維修，它負責的那一區就暫時讀不到。Silica 論文提到 shuttle 故障可能讓 storage racks 被隔開；平台不可用時，系統要讀同一 platter-set 的其他平台，用 cross-platter network coding 還原，原本讀一片變成要讀好幾片。Non-Zone 少一台只是少一份人力，其他車分攤；工作分散，充電與磨損也比較平均。驗證方式：讓一台車停機 T 分鐘，或加入週期性充電，比較掉速與受影響的 request 數。

## 28. Non-Zone 也有代價：單純共享會塞車

數據：hotspot、N=8、read=8 s。Non-Zone FIFO 的 throughput 從 B=0 的 2.90 降到 B=8 的 2.72 req/min，每個 request 的路段等待從 96 秒增加到 109 秒。推測：有 buffer 後 shuttle 交貨就被釋放，同時上路的車變多，交通更擁擠；這個因果還沒有獨立驗證。這一頁的重點是：Zone 的問題是結構性的，加 buffer 修不好；Non-Zone 的問題是調度上的，有機會用方法修好。這就是下一步方法的位置。

## 29. 下一輪實驗：畫出 Zone 的適用邊界

實驗順序依成本與證據強度排列。一、熱區比例從 25%（均勻）掃到 90%，找 Zone 與 Non-Zone 的交叉點；只要把 make_requests 的 0.75 參數化。二、新增 buffer 組成指標：reader 空等時，buffer 裡有幾片別區的玻璃；並記錄各區 p99。三、距離公平性：uniform 下比較遠區與近區 p99。四、短時擁擠：總體均勻，但連續 k 個 request 落在同一排。五、shuttle 故障：一台停機 T 分鐘。六、最後才是 buffer-aware Non-Zone 方法，與 Zone、Zone + work stealing 強基準比較。所有設定先登記再跑，負向結果保留。

## 30. 三個設計，對應三種不同的等待

本輪完成motivation characterization，不能稱paper-ready實驗、實機validate或新方法。每個設計點後接它需要觀察的metric，不用片面utilization下結論。

## 31. 下一步方法：先補上決策需要的資訊

這是下一步研究構想，不是本輪已驗證方法。待服務玻璃queue記錄位置/等待時間；shuttle狀態表與routecalendar提供可用時間；bufferreader表提供slot與expectedfree。不需要先引入大規模MAPF oracle或複雜ML。未來要與earliest-delivery及lookahead強基準比較。

## 32. 目前能說什麼，還需要補什麼？

目前實驗可以說明所定義的model內三類mechanism。不能證明真實大型glasslibrary效能，或實際碰撞安全。模型驗證主要是resource互斥與conservation。reader isolatedinput+8docks/output都是explicit hardware assumption。真實workload、更長episode、warmup和moreseeds仍需補充。

## 33. 附錄：硬體、交通與服務假設

完整資料experiments/partition-feeder-story/README.md。Silica§7.1支持約0.5s定位與約3s crabbing量級；2m/s與2m/s²、1spickplacehandoffunload、2sloadmount等均為controlled assumptions。每row80slot共640；length16/32/64，singlepartitiononerdr。所有policy使用sameexclusiveblocks。

## 34. 附錄：證據檔案與重現入口

Source paper: https://www.microsoft.com/en-us/research/wp-content/uploads/2023/09/ProjectSilica-SOSP23.pdf
Main config: experiments/partition-feeder-story/full.json
Prefetch config: experiments/partition-feeder-story/prefetch-n8.json
Prefetch run: .venv/bin/python scripts/run_prefetch_n8.py --config experiments/partition-feeder-story/prefetch-n8.json
Deck: node scripts/build_partition_feeder_story.js
Runs: results/partition-feeder-prefetch-n8/runs.csv
Aggregate: results/partition-feeder-prefetch-n8/aggregate.csv
Exact effective configs/source hashes: run_configs.json and summary.json
All means are over 5 synthetic seeds. SD is in CSV and standalone figures.

## 35. 附錄：相同硬體，調度方式會改變供料效率

E2uniform：N2/4/8、32m、read8、B4。Policy zone/fifo/lookahead由相同geometry與resource rules比較。Lookahead是16個候選加120秒aging的簡單基準，不宣稱新方法。曲線來自full matrix，不挑seed。

## 36. 附錄：工作集中時，固定分區的代價也會浮現

此hotspot是人為診斷場景，非Azure實測分布；Zone的row0/1在N4由同一owner負責，在N8由兩owner負責。N變化也會改變hotspot對owner的集中程度，不能把所有差異只歸因機器人數量。需與uniform同時解讀。

## 37. 附錄：增加 Shuttle，也可能增加協調負擔

數據E2uniform。Traffic wait是所有shuttle累計等待除requests，不是使用者latency。Candidate evaluations是對request-shuttle pair評估次數，不是硬體clock cycles或real controller latency。若吞吐量未下降，不能把更多trafficwait誇大成more robots always worse。
