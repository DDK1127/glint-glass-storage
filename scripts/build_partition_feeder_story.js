// Requires pptxgenjs 4.0.1. Charts read the retained experiment data, never constants.
const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');
const root = path.resolve(__dirname, '..');
const resultDir = path.join(root, 'results/partition-feeder-story');
const prefetchDir = path.join(root, 'results/partition-feeder-prefetch-n8');
const provisioningDir = path.join(root, 'results/partition-shuttle-provisioning');
const input = JSON.parse(fs.readFileSync(path.join(resultDir, 'chart_data.json'), 'utf8'));
const rows = input.aggregate;
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'GLINT Research';
pptx.subject = 'Single-partition shuttle provisioning, coordination, and feeder buffering';
pptx.title = '讓 Reader 持續有玻璃可讀';
pptx.lang = 'zh-TW';
pptx.theme = { headFontFace: 'Arial Unicode MS', bodyFontFace: 'Arial Unicode MS', lang: 'zh-TW' };
const C = { ink:'21352E', muted:'5F7069', zone:'547465', fifo:'C17A3B', local:'75639B', pale:'EDF3EF', gray:'E5EAE7', white:'FFFFFF', dark:'17382F', gold:'DDB264', red:'B55757' };
const FONT = 'Arial Unicode MS';
const slideNotes = [];
function text(s,t,x,y,w,h,size=18,color=C.ink,extra={}) {
  s.addText(t,{x,y,w,h,fontFace:FONT,fontSize:size,color,margin:0,breakLine:false,valign:'mid',...extra});
}
function box(s,x,y,w,h,fill=C.pale,line=fill) {
  s.addShape(pptx.ShapeType.roundRect,{x,y,w,h,radius:.08,fill:{color:fill},line:{color:line,width:1}});
}
function arrow(s,x,y,w,color=C.muted) {
  s.addShape(pptx.ShapeType.chevron,{x,y,w,h:.24,fill:{color},line:{color}});
}
function item(s,number,title,body,x,y,w=3.7) {
  box(s,x,y,w,2.25);
  text(s,number,x+.22,y+.18,.6,.35,20,C.zone,{bold:true});
  text(s,title,x+.22,y+.72,w-.44,.45,23,C.ink,{bold:true});
  text(s,body,x+.22,y+1.3,w-.44,.7,16,C.muted);
}
function slide(title,subtitle,notes,tag='研究動機 / 單一 PARTITION') {
  const s=pptx.addSlide();
  s.background={color:C.white};
  text(s,tag,.6,.22,11,.23,10,C.muted,{charSpacing:1});
  text(s,title,.6,.72,12.1,.68,32,C.ink,{bold:true});
  if(subtitle) text(s,subtitle,.62,1.48,12.05,.48,15,C.muted);
  text(s,`${slideNotes.length+1}` ,12.15,7.13,.5,.18,10,C.muted,{align:'right'});
  s.addNotes(notes);
  slideNotes.push({title,notes});
  return s;
}
function footer(s,t) { text(s,t,.65,6.78,12,.26,10,C.muted); }
function fitImage(s,file,x,y,w,h,ratio) { let iw=w, ih=w/ratio; if(ih>h){ih=h;iw=h*ratio;} s.addImage({path:file,x:x+(w-iw)/2,y:y+(h-ih)/2,w:iw,h:ih}); }
function get(filters) {
  const r=rows.filter(r=>Object.entries(filters).every(([k,v])=>r[k]===v));
  if(!r.length) throw new Error('No experiment cell '+JSON.stringify(filters));
  return r;
}
function one(filters) { const r=get(filters); if(r.length!==1)throw new Error('Ambiguous cell '+JSON.stringify(filters)); return r[0]; }
function line(s,groups,metric,xfield,x,y,w,h,scale=1,max=null) {
  const series=groups.map(g=>({name:g.name,labels:g.rows.map(r=>String(r[xfield])),values:g.rows.map(r=>r[metric]*scale)}));
  const o={x,y,w,h,catAxisLabelFontFace:'Arial',valAxisLabelFontFace:'Arial',legendFontFace:FONT,
    catAxisLabelFontSize:11,valAxisLabelFontSize:10,legendFontSize:11,legendPos:'b',showLegend:true,
    chartColors:groups.map(g=>g.color||C.zone),showTitle:false,showValue:false,
    showMarker:true,markerSize:5,lineSize:2.5,showBorder:false,
    showCatName:false,valAxisMinVal:0,valGridLine:{color:'DFE7E2',width:1},
    catAxisLineColor:'BBC8C0',valAxisLineColor:'BBC8C0',showShadow:false};
  if(max!==null)o.valAxisMaxVal=max;
  s.addChart(pptx.ChartType.line,series,o);
}
function bars(s,series,x,y,w,h,colors=[C.zone,C.fifo],max=null) {
  const o={x,y,w,h,catAxisLabelFontFace:FONT,valAxisLabelFontFace:'Arial',legendFontFace:FONT,
    catAxisLabelFontSize:10,valAxisLabelFontSize:10,legendFontSize:11,legendPos:'b',
    showLegend:series.length>1,chartColors:colors,showTitle:false,showValue:false,
    showBorder:false,showShadow:false,barDir:'col',barGrouping:'clustered',
    valAxisMinVal:0,valGridLine:{color:'DFE7E2',width:1},catAxisLineColor:'BBC8C0',valAxisLineColor:'BBC8C0'};
  if(max!==null)o.valAxisMaxVal=max;
  s.addChart(pptx.ChartType.bar,series,o);
}
const sort=(list,key)=>[...list].sort((a,b)=>a[key]-b[key]);
const labels={zone:'Zone',nonzone_fifo:'Non-Zone FIFO',nonzone_local:'Non-Zone lookahead'};
const colors={zone:C.zone,nonzone_fifo:C.fifo,nonzone_local:C.local};
const n1=one({experiment:'E1',length_m:64,read_s:8,shuttles:1});
const n8=one({experiment:'E1',length_m:64,read_s:8,shuttles:8});
// Shuttle-count sweep (results/partition-shuttle-provisioning) drives slides 3-4.
const provSummary=JSON.parse(fs.readFileSync(path.join(provisioningDir,'summary.json'),'utf8'));
const prov=provSummary.analysis_by_penalty['0.0'];
const provRows=fs.readFileSync(path.join(provisioningDir,'aggregate.csv'),'utf8').trim().split('\n');
const provHead=provRows[0].split(',');
const provAt=n=>{const r=provRows.slice(1).map(l=>Object.fromEntries(l.split(',').map((v,j)=>[provHead[j],Number(v)]))).find(r=>r.shuttles===n);if(!r)throw new Error('No provisioning cell N='+n);return r;};
const p1=provAt(1), p4=provAt(4), p16=provAt(16), p90=provAt(prov.smallest_n_busy_ge_90pct);
// Congestion sweep (results/partition-shuttle-congestion) drives slide 5.
const congestionDir=path.join(root,'results/partition-shuttle-congestion');
const cong=JSON.parse(fs.readFileSync(path.join(congestionDir,'summary.json'),'utf8'));
const congHold=String(cong.config.focus_hold_s===Math.trunc(cong.config.focus_hold_s)?cong.config.focus_hold_s.toFixed(1):cong.config.focus_hold_s);
const congRows=(()=>{const l=fs.readFileSync(path.join(congestionDir,'aggregate.csv'),'utf8').trim().split('\n');const h=l[0].split(',');return l.slice(1).map(x=>Object.fromEntries(x.split(',').map((v,j)=>[h[j],Number(v)])));})();
const congAt=(hold,n)=>{const r=congRows.find(r=>r.contention_hold_s===hold&&r.shuttles===n);if(!r)throw new Error(`No congestion cell hold=${hold} N=${n}`);return r;};
const congFocus=Number(cong.config.focus_hold_s), congPeak=cong.peaks_by_hold[congHold];
const cPeak=congAt(congFocus,congPeak.peak_shuttles), c1=congAt(congFocus,1), cMax=congAt(congFocus,congPeak.n_max), freeMax=congAt(0,congPeak.n_max);
const shuttleS=prov.single_shuttle_cycle_s, readerS=prov.reader_cycle_s, fetchS=p1.fetch_delivery_mean_s_mean, returnS=shuttleS-fetchS;

// 1
{
 const s=slide('讓 Reader 持續有玻璃可讀','玻璃儲存的搬運、內部分區與 Feeder Buffer：從架構到可檢查的研究動機',
 '本簡報是合成離散事件模擬的研究討論稿，非實機測量或已完成投稿結果。研究單位已修正為單一 partition、多 shuttle、一 reader。所有數字來自本次新實驗。增加 shuttle 的主要作用是平行供料與減少排隊，不保證單一 request 的實際移動時間下降。', 'GLINT / RESEARCH DISCUSSION / 2026-10-01');
 s.background={color:C.dark};
 // Override the title region with a dark, readable composition.
 s.addShape(pptx.ShapeType.rect,{x:0,y:0,w:13.333,h:6.65,fill:{color:C.dark},line:{color:C.dark}});
 text(s,'GLINT / 玻璃儲存架構研究',.75,.48,10,.3,12,'B9D0C4');
 text(s,'讓 Reader\n持續有玻璃可讀',.75,1.18,10,1.7,40,C.white,{bold:true});
 text(s,'一個 Reader 該配幾台 Shuttle？\n多台 Shuttle 如何協作？\n有限 Feeder Buffer 何時值得加入？',.78,3.2,7.7,1.55,21,'DCE8E0');
 ['搬運','交付','讀取'].forEach((t,i)=>{box(s,8.9,1.5+i*1.42,3,1.05,i===1?'365B4A':'294B3F');text(s,t,9.18,1.78+i*1.42,2.4,.45,25,C.white,{bold:true});});
 text(s,'單一 partition · 單一 reader · 配對實驗 · 受控模擬',.78,5.65,11,.4,17,'C4D8CD');
 text(s,'討論稿：機制證據與適用邊界，非實機校準效能',.78,6.85,11,.3,12,'C4D8CD');
}
// 2
{
 const s=slide('一次讀取：搬運、交付、讀取三段接力','研究單位：一個 partition、一個 reader、N 台 shuttle。第一個問題：N 該設多少？',
 '整個系統可以有很多個 partition，這次只看其中一個。圖中的 8 是儲存架的 rows，不是 8 個 reader。每次讀取都要經過三段：shuttle 取出玻璃並送到交付站、在交付站把玻璃交給 reader（reader 忙的時候先放進 feeder buffer）、reader 裝載後讀取。讀完之後玻璃要送回原位，這段歸還的時間也會占用 shuttle，所以全部計入成本，但這次不對歸還策略做最佳化。');
 box(s,.7,2.1,11.95,2.35,'F6F8F6','C8D5CC');
 for(let i=0;i<8;i++){box(s,1,2.35+i*.21,2.6,.12,i%2?C.gray:'CBD9CF');}
 text(s,'8 條儲存架 rows',1,4.08,2.8,.25,14,C.muted);
 arrow(s,3.9,3.1,.5);
 for(let i=0;i<4;i++){box(s,4.6+(i%2)*.7,2.62+Math.floor(i/2)*.7,.5,.5,C.zone);text(s,'S',4.74+(i%2)*.7,2.74+Math.floor(i/2)*.7,.23,.23,14,C.white);}
 text(s,'N 台 Shuttle',4.5,4.08,2.4,.25,14,C.muted);
 arrow(s,6.3,3.1,.5);
 box(s,7,2.6,2.1,1.15,'F4EBDD');text(s,'Feeder\nBuffer',7.22,2.78,1.7,.8,19);
 arrow(s,9.4,3.1,.5);
 box(s,10.2,2.6,1.9,1.15,'DDD8EB');text(s,'1 Reader',10.4,3.0,1.5,.4,19);
 [['01','取件與搬運','Shuttle 取出玻璃，送到交付站'],['02','交付與暫存','Reader 忙碌時，先放進 buffer'],['03','裝載與讀取','Reader 一次處理一片']].forEach((v,i)=>{
  const x=.7+i*4.1; box(s,x,4.75,3.85,1.75);
  text(s,v[0],x+.22,4.92,.6,.32,18,C.zone,{bold:true});
  text(s,v[1],x+.22,5.3,3.4,.4,21,C.ink,{bold:true});
  text(s,v[2],x+.22,5.85,3.4,.4,15,C.muted);
 });
 footer(s,'讀完後玻璃送回原位；歸還時間完整計入 shuttle 成本，但這次不對歸還策略做最佳化。');
}
// 3
{
 const s=slide('瓶頸在搬運：Reader 大部分時間在等玻璃',`搬運一片約 ${shuttleS.toFixed(0)} 秒，讀取一片只要 ${readerS.toFixed(0)} 秒，所以一個 reader 需要多台 shuttle 平行供料。`,
 `數據來自 shuttle 數量實驗的 N=1：32 m rack、read=8 s、B=4、Non-Zone FIFO、均勻 closed batch。只有一台 shuttle 時沒有交通干擾，所以這是單台 shuttle 服務一片玻璃的純時間：取件加送到 reader 約 ${fetchS.toFixed(0)} 秒，交付和讀後歸還約 ${returnS.toFixed(0)} 秒，平均每片約 ${shuttleS.toFixed(0)} 秒。Reader 處理一片只需要 load+mount 2 秒、讀取 8 秒、unload 1 秒，共 ${readerS.toFixed(0)} 秒。所以 reader 大部分時間在等玻璃，利用率只有 ${(100*p1.reader_busy_fraction_mean).toFixed(0)}%。瓶頸在搬運，不在讀取，因此需要多台 shuttle 平行供料；理想配比約為 ${shuttleS.toFixed(0)} / ${readerS.toFixed(0)}，約 ${prov.ideal_shuttles_per_reader.toFixed(0)} 台。`);
 const scale=8.2/shuttleS, x0=2.75;
 text(s,'Shuttle\n服務一片',.7,2.3,1.9,.85,17,C.ink,{bold:true});
 box(s,x0,2.4,fetchS*scale,.65,C.zone); text(s,`取件 + 送達 ${fetchS.toFixed(0)} s`,x0+.15,2.52,fetchS*scale-.2,.4,15,C.white);
 box(s,x0+fetchS*scale+.04,2.4,returnS*scale-.04,.65,'93AD9C'); text(s,`交付 + 歸還 ${returnS.toFixed(0)} s`,x0+fetchS*scale+.19,2.52,returnS*scale-.3,.4,15,C.white);
 text(s,`≈ ${shuttleS.toFixed(0)} s`,x0+8.3,2.52,1.4,.4,18,C.ink,{bold:true});
 text(s,'Reader\n讀取一片',.7,3.4,1.9,.85,17,C.ink,{bold:true});
 box(s,x0,3.5,readerS*scale,.65,C.local); text(s,`${readerS.toFixed(0)} s`,x0+.12,3.62,1.2,.4,15,C.white);
 text(s,'剩下的時間 reader 都在等玻璃',x0+readerS*scale+.25,3.62,5,.4,15,C.muted);
 box(s,.7,4.7,5.8,1.6);text(s,'只有 1 台 Shuttle 時',.95,4.88,5,.3,16,C.muted);
 text(s,`Reader 只有 ${(100*p1.reader_busy_fraction_mean).toFixed(0)}% 時間在工作`,.95,5.35,5.4,.6,26,C.zone,{bold:true});
 box(s,6.85,4.7,5.8,1.6,'F2EDF7');text(s,'理想配比（沒有互相干擾）',7.1,4.88,5,.3,16,C.muted);
 text(s,`${shuttleS.toFixed(0)} ÷ ${readerS.toFixed(0)} ≈ ${prov.ideal_shuttles_per_reader.toFixed(0)} 台 / reader`,7.1,5.35,5.4,.6,26,C.local,{bold:true});
 footer(s,'N=1、32 m rack、read=8 s、B=4、均勻 closed batch；5 seeds 平均。理論上約 6 台就夠，下一頁檢查實際情況。');
}
// 4
{
 const s=slide('單台 Shuttle：Reader 可能大部分時間在等','E1｜固定一個 reader，增加搬運資源；玻璃位置與 requests 配對。',
 '數據E1 length=64m read=8s policy=zone B=4 uniform batch。Reader utilization分母為第一request到最後unload，不含最後return drain；分子包含load/read/unload。N改變時Zone劃分也改變，是整體provisioning比較。不是單一request movement變短的證明。');
 const g=sort(get({experiment:'E1',length_m:64,read_s:8}),'shuttles');
 line(s,[{name:'Reader busy (%)',rows:g,color:C.zone}],'reader_busy_fraction_mean','shuttles',.7,2.12,7.7,4.1,100,100);
 box(s,8.8,2.3,3.65,1.55);text(s,'1 台 Shuttle',9.04,2.5,3,.3,17,C.muted);text(s,`${(100*n1.reader_busy_fraction_mean).toFixed(1)}%`,9.04,2.96,3,.65,38,C.zone,{bold:true});
 box(s,8.8,4.1,3.65,1.55,'F2EDF7');text(s,'8 台 Shuttle',9.04,4.3,3,.3,17,C.muted);text(s,`${(100*n8.reader_busy_fraction_mean).toFixed(1)}%`,9.04,4.76,3,.65,38,C.local,{bold:true});
 footer(s,'64 m rack lane · optical read 8 s · Zone · B=4 · 均勻 closed batch；圖為均值，SD 見實驗圖與 CSV。');
}
// 5
{
 const s=slide(`一個 Partition 配置幾台 Shuttle 才合理？`,'先不考慮避讓時的停走損失；固定 32 m、read=8 s、B=4、Non-Zone FIFO，只改 N = 1 ~ 32。',
 `虛線是理想情況：把 N=1 的結果直接乘以 N，假設 shuttle 之間完全不互相干擾，大約 ${prov.ideal_shuttles_per_reader.toFixed(1)} 台就能讓 reader 滿載。實線是模擬結果：要 ${prov.smallest_n_busy_ge_90pct} 台才超過 90%（${(100*p90.reader_busy_fraction_mean).toFixed(1)}%），${p16.shuttles} 台達到 ${(100*p16.reader_busy_fraction_mean).toFixed(1)}%，之後再加車沒有幫助。兩條線之間的差距就是多台 shuttle 共用路段的協調成本：每個 request 的路段等待從 N=4 的 ${p4.traffic_wait_per_request_s.toFixed(0)} 秒增加到 N=${prov.smallest_n_busy_ge_90pct} 的 ${p90.traffic_wait_per_request_s.toFixed(0)} 秒。這個配比是在目前的模擬假設下得到的，不是實機校準值；rack 長度或讀取時間改變時，配比也會跟著改變。`);
 fitImage(s,path.join(provisioningDir,'fig_shuttle_count.png'),.55,1.95,8.3,4.75,8.6/4.8);
 const kpi=[[`理想：約 ${prov.ideal_shuttles_per_reader.toFixed(0)} 台`,'沒有互相干擾時，reader 就會滿載','F6F8F6',C.muted],
  [`實際：${prov.smallest_n_busy_ge_90pct} 台達 90%`,`Reader 利用率 ${(100*p90.reader_busy_fraction_mean).toFixed(0)}%；多出的車用來抵銷交通等待`,C.pale,C.zone],
  [`${p16.shuttles} 台以上：不再增加`,`利用率停在 ${(100*p16.reader_busy_fraction_mean).toFixed(0)}%，瓶頸變成 reader`,'F2EDF7',C.local]];
 kpi.forEach((v,i)=>{box(s,9.05,2.05+i*1.5,3.7,1.32,v[2]);text(s,v[0],9.27,2.2+i*1.5,3.3,.45,20,v[3],{bold:true});text(s,v[1],9.27,2.7+i*1.5,3.3,.5,13,C.muted);});
 footer(s,`1 reader · 8 rows · 5 seeds × 384 requests · 均勻 closed batch；誤差棒為 sample SD。理想與實際的差距來自共用路段：車越多，互相等待越多。`);
}
// 6
{
 const s=slide(`車太多反而變慢：最佳點落在 ${congPeak.peak_shuttles} 台`,'加入簡單的擁擠模型：每被一台車擋到，就要停下再起步，而且停走期間仍佔用路段。',
 `兩條線使用同一個 partition、同樣的 requests，只差在有沒有擁擠成本。擁擠模型的意思是：路線每被一台已預約的車擋到一次，就多一次停下再起步，這段時間仍佔用該路段，所以車越密集，共用路段實際能通過的車越少。沒有擁擠成本時，加車到約 16 台後吞吐量持平，但不會下降。有擁擠成本時，吞吐量在 ${congPeak.peak_shuttles} 台達到最高（${cPeak.throughput_req_min.toFixed(2)} req/min），之後越加越慢；${congPeak.n_max} 台時只剩 ${cMax.throughput_req_min.toFixed(2)} req/min，和只有 1 台（${c1.throughput_req_min.toFixed(2)}）差不多，因為 shuttle 有 ${(100*cMax.avg_shuttles_traffic_wait_mean/congPeak.n_max).toFixed(0)}% 的時間在等其他車。注意：每次停走成本設為 ${congFocus} 秒，這個值是為了讓最高點落在 ${congPeak.peak_shuttles} 台而選的示意情境，不是實機量測；成本較小時最高點會往更多台移動（例如 0.5 秒時約 12 台），成本較大時則往更少台移動。這頁要說明的是「擁擠成本存在時，會有一個最佳配比，超過就幫倒忙」，而不是「最佳配比一定是 ${congPeak.peak_shuttles} 台」。`);
 text(s,'吞吐量：有 / 無擁擠',.7,1.98,6,.3,15,C.zone,{bold:true});
 fitImage(s,path.join(congestionDir,'fig_congestion_throughput.png'),.55,2.3,6.2,3.45,8.6/4.8);
 text(s,'有擁擠時，Shuttle 的時間花在哪？',6.95,1.98,6,.3,15,C.zone,{bold:true});
 fitImage(s,path.join(congestionDir,'fig_congestion_breakdown.png'),6.85,2.3,6.2,3.45,8.6/4.8);
 box(s,.7,5.85,11.95,.78,C.pale);
 text(s,`${congPeak.n_max} 台時，shuttle 有 ${(100*cMax.avg_shuttles_traffic_wait_mean/congPeak.n_max).toFixed(0)}% 的時間在等彼此，效能掉回 1 台的水準 → 不能只靠加車，固定台數下要靠調度與交接`,.95,5.97,11.5,.55,17,C.ink,{bold:true});
 footer(s,'同一 partition 與 requests，只差擁擠成本；5 seeds 平均，誤差棒為 sample SD。擁擠成本為示意設定，非實機量測。');
}
// 7: design spectrum
{
 const s=slide('固定台數下，怎麼分工？從 Zone 到 Non-Zone 是一條光譜','差別在於「誰可以搬哪片玻璃」，以及控制器要替大家協調多少事。',
 '這一段不放實驗圖，改講怎麼實作。Zone 和 Non-Zone 不是二選一，而是一條光譜的兩端。左端 Zone：每台車只搬自己負責那幾排，控制器幾乎不用做全域決策，但熱區只有一個人能搬。右端 Non-Zone：誰有空誰搬，人手不會閒著，但控制器要做全域派工、路段預約和避讓，而且前一頁看到車太多會塞車。中間是混合做法：平常各管各的，需要時才跨區。接下來三頁分別講兩端怎麼實作，以及我們想嘗試的中間做法。');
 s.addShape(pptx.ShapeType.line,{x:1.2,y:2.3,w:10.95,h:0,line:{color:'BBC8C0',width:2,beginArrowType:'triangle',endArrowType:'triangle'}});
 text(s,'固定分工',1.2,2.42,2.5,.3,13,C.zone,{bold:true});
 text(s,'完全共享',9.65,2.42,2.5,.3,13,C.fifo,{bold:true,align:'right'});
 const cols=[['Zone',C.zone,C.pale,'只有負責那幾排的車','各區各自排隊；\n只協調 reader 前的共用區','簡單、路線短、\n區內不互卡','熱區人手不足；\n壞一台整區停'],
  ['混合',C.local,'F2EDF7','平常各管各的，\n需要時才跨區','判斷何時借人、\n借誰、借多久','保留局部性，\n又有彈性','規則設計不好，\n兩邊缺點都有'],
  ['Non-Zone',C.fifo,'FBF3E2','誰有空誰搬','全域派工 + 路段預約\n+ 避讓與限流','不會有人閒著','跨區移動多、\n車多就塞']];
 const rowsY=[3.6,4.32,5.04,5.76], rowNames=['誰能搬','控制器要做','好處','風險'];
 rowNames.forEach((r,j)=>text(s,r,.7,rowsY[j]+.05,1.4,.3,13,C.muted,{bold:true}));
 cols.forEach((c,i)=>{const x=2.1+i*3.55; box(s,x,2.85,3.35,3.75,c[2]);
  text(s,c[0],x+.2,2.98,3,.4,20,c[1],{bold:true});
  c.slice(3).forEach((v,j)=>text(s,v,x+.2,rowsY[j],3,.62,12.5,C.ink,{valign:'top'}));});
 footer(s,'三種做法使用相同的硬體與 reader；差別只在派工規則與控制器要掌握的資訊。');
}
// 8: Zone implementation
{
 const s=slide('Zone 怎麼實作：各管各的，但入口要協調','分區只管住「取件」；所有車最後都要擠進同一個 reader 入口。',
 'Zone 的實作需要三個元件。第一是分區表：N 台車平分 8 排，所以 N 必須整除 8。第二是各區的工作佇列：每台車只看自己區的 request，最舊的先搬。第三是共用區協調：不管怎麼分區，所有車都要經過接駁段和 reader 入口，這裡仍然要用預約或排隊，一次只放一台。模擬中的 Zone 就是這樣實作，共用路段和 Non-Zone 使用同一套預約規則，沒有假設 Zone 在 reader 前完全不會衝突。好處是決策簡單、區內不互卡；限制在後面第 17 頁以後會用數據展開：熱區只有一台能搬、N 要整除排數、壞一台整區讀不到。');
 [['01','分區表','N 台車平分 8 排；N 必須整除 8（1 / 2 / 4 / 8）'],
  ['02','各區工作佇列','每台車只看自己區的 request，最舊的先搬'],
  ['03','共用區協調','接駁段與 reader 入口仍要預約或排隊，一次只放一台']].forEach((v,i)=>{
  const y=2.15+i*1.45; box(s,.7,y,7.3,1.25,C.pale);
  text(s,v[0],.92,y+.18,.6,.3,16,C.zone,{bold:true});
  text(s,v[1],1.6,y+.16,6,.38,19,C.ink,{bold:true});
  text(s,v[2],1.6,y+.66,6.2,.4,14,C.muted);});
 box(s,8.35,2.15,4.3,2.05,'F6F8F6','C8D5CC');
 text(s,'好處',8.58,2.3,3.9,.3,15,C.zone,{bold:true});
 text(s,'決策簡單，不需要全域計算\n路線短，區內的車不會互相擋',8.58,2.72,3.9,1.2,14,C.ink,{valign:'top'});
 box(s,8.35,4.38,4.3,2.12,'FBF3E2');
 text(s,'限制',8.58,4.53,3.9,.3,15,'8A6416',{bold:true});
 text(s,'熱區只有一台能搬\nN 要整除排數，不能只加一台\n壞一台，整區暫時讀不到',8.58,4.95,3.9,1.4,14,C.ink,{valign:'top'});
 footer(s,'本模擬的 Zone 即依此實作；限制的數據見第 17 頁之後的「Zone 的適用邊界」。');
}
// 9: Non-Zone implementation
{
 const s=slide('Non-Zone 怎麼實作：派工、路段預約、限流','任何車都能搬任何玻璃，所以控制器要回答三個問題。',
 'Non-Zone 的控制器要回答三個問題。一、派哪台車：所有 request 放在同一個全域佇列，從空車中選預計最早把玻璃送到 reader 的那台；模擬目前的 Non-Zone FIFO 就是這樣做。二、走哪條路、何時出發：用路段預約表，每段路在時間軸上先訂位，有衝突就延後出發；進階做法是在一個小時間視窗內把幾台車一起規劃（例如 windowed CBS）。三、同時放幾台上路：前一頁看到車太多會塞車，所以共用區同時上路的車數要有上限 K，K 是可以調的參數，而不是把車賣掉。風險是每次派工都要評估「工作 × 車」的組合，車越多計算量越大；規則不好時車會跨區亂跑、互相擋路。');
 [['01','派哪台車？','全域工作佇列；選「預計最早送到 reader」的空車','目前模擬：FIFO + 最早送達'],
  ['02','走哪條路、何時出發？','路段預約表：每段路在時間軸上先訂位，衝突就延後出發','進階：小視窗內一起規劃（windowed CBS）'],
  ['03','同時放幾台上路？','共用區同時最多 K 台，其餘先在原地待命','呼應前頁：車太多會塞 → K 可調']].forEach((v,i)=>{
  const x=.7+i*4.1; box(s,x,2.15,3.85,3.3,i===2?'F2EDF7':C.pale);
  text(s,v[0],x+.22,2.3,.6,.3,16,i===2?C.local:C.zone,{bold:true});
  text(s,v[1],x+.22,2.7,3.4,.4,20,C.ink,{bold:true});
  text(s,v[2],x+.22,3.3,3.4,1.1,14,C.ink,{valign:'top'});
  text(s,v[3],x+.22,4.62,3.4,.6,12.5,C.muted,{valign:'top'});});
 box(s,.7,5.7,11.95,.85,'FBF3E2');
 text(s,'風險',.95,5.85,.8,.3,14,'8A6416',{bold:true});
 text(s,'每次派工都要評估「工作 × 車」的組合，車越多計算量越大；規則不好時，車會跨區亂跑、互相擋路。',1.75,5.82,10.7,.55,14,C.ink);
 footer(s,'01、02 為模擬目前的 Non-Zone 實作；03 限流尚未實作，是下一步要試的參數。');
}
// 10: hybrid ideas
{
 const s=slide('中間路線：四個想嘗試的做法','保留 Zone 的局部性，只在需要時借用彈性；每個做法都要能被量測驗證。',
 '四個中間做法。一、Work stealing：Project Silica 的既有做法，某區積壓超過門檻時，閒的鄰區車過來幫忙，並限制同時幫忙的車數；這是強基準，新方法要贏它才有意義。二、軟分區：派工分數等於預計送達時間加上跨區懲罰，懲罰很大時等於 Zone，懲罰為零時等於 Non-Zone，只用一個參數就能在光譜上連續移動，可以畫出取捨曲線。三、動態重劃區：每隔一段時間依各區積壓重新分配每台車負責的排數，處理熱區會移動的情況，難點是重劃時正在搬的車怎麼處理。四、限流：reader 共用區同時最多 K 台，直接對應前面車太多會塞的結果。二到四都是待驗證構想，還沒有本輪數據。');
 const hdr=['做法','怎麼做','想解決','風險 / 怎麼驗證'], xs=[.7,3.15,7.2,9.6], ws=[2.35,3.95,2.3,3.05];
 hdr.forEach((h,i)=>text(s,h,xs[i]+.15,2.1,ws[i],.3,13,C.muted,{bold:true}));
 [['① Work stealing','某區積壓超過門檻，閒的鄰區車來幫；限制幫手數','熱區人手不足','幫手跨區造成塞車\n看熱區 p99、跨區趟數'],
  ['② 軟分區','派工分數 = 預計送達時間 + 跨區懲罰；懲罰大 ≈ Zone，懲罰 0 ≈ Non-Zone','用一個參數在兩端之間連續調','懲罰值怎麼選\n掃懲罰值，畫取捨曲線'],
  ['③ 動態重劃區','每隔一段時間，依各區積壓重新分配排數','熱區會移動','重劃時正在搬的車怎麼辦\n看熱區移動時的 p99'],
  ['④ 限流','Reader 共用區同時最多 K 台，其餘在區內待命','車太多反而變慢','K 太小會讓 reader 缺料\n掃 K，看吞吐量']].forEach((r,j)=>{
  const y=2.5+j*1.03; box(s,.7,y,11.95,.93,j%2?'F6F8F6':C.pale,j%2?'C8D5CC':C.pale);
  r.forEach((v,i)=>text(s,v,xs[i]+.15,y+.1,ws[i]-.1,.75,i===0?15:12.5,i===0?(j===0?C.zone:C.local):C.ink,{bold:i===0,valign:'mid'}));});
 footer(s,'① 是 Project Silica 的既有做法，作為強基準；②–④ 為待驗證構想，尚無本輪數據。');
}
// 9: problem framing
{
 const s=slide('搬運與讀取的時間接不上','Reader 讀一片很快，但下一片玻璃還在路上；reader 空等的時間就是浪費的讀取能力。',
 `前面看到 shuttle 服務一片玻璃約 ${shuttleS.toFixed(0)} 秒，reader 只要 ${readerS.toFixed(0)} 秒，所以要多台 shuttle 平行供料。但多台 shuttle 的抵達時間不規則：有時同時到、有時一段時間都沒有車到。沒有暫存位置時，早到的 shuttle 只能載著玻璃等 reader，晚到時 reader 只能空等。想法是在 reader 前面留一小塊位置，讓下一批玻璃先就位，把搬運時間藏在讀取時間後面。Buffer 只能吸收時間差，不能補足長期不足的搬運吞吐量，也不會縮短實體搬運距離。`);
 const x0=2.75, tw=9.85, rd=readerS/shuttleS*3.2;
 text(s,'沒有暫存',.7,2.3,1.9,.5,18,C.fifo,{bold:true});
 text(s,'有 Buffer',.7,3.45,1.9,.5,18,C.zone,{bold:true});
 s.addShape(pptx.ShapeType.line,{x:x0,y:3.18,w:tw,h:0,line:{color:'BBC8C0',width:1}});
 s.addShape(pptx.ShapeType.line,{x:x0,y:4.33,w:tw,h:0,line:{color:'BBC8C0',width:1}});
 [1.35,.55,1.75,.35,1.1].reduce((x,gap,i)=>{
  box(s,x,2.3,rd,.55,C.local); text(s,'讀取',x,2.42,rd,.3,13,C.white,{align:'center'});
  if(x+rd+gap<=x0+tw){box(s,x+rd+.04,2.3,gap-.08,.55,'F3E6D8','D9B48C'); if(gap>.9)text(s,'等玻璃',x+rd,2.42,gap,.3,13,C.fifo,{align:'center'});}
  return x+rd+gap;
 },x0);
 for(let x=x0;x+rd<=x0+tw;x+=rd+.06){box(s,x,3.45,rd,.55,C.local);text(s,'讀取',x,3.57,rd,.3,13,C.white,{align:'center'});}
 text(s,'下一片已在 reader 前就位，讀取可以接續',x0,4.08,tw,.22,12,C.muted);
 [['問題','Reader 空等','多台 shuttle 抵達不規則，\n晚到時 reader 沒有玻璃可讀。',C.fifo],
  ['想法','先把玻璃放到 reader 旁','在 reader 前面留少量位置，\n把搬運藏在讀取時間後面。',C.zone],
  ['邊界','不是加快搬運','Buffer 吸收時間差，\n不能補足長期不足的供料。',C.local]].forEach((v,i)=>{
  const x=.7+i*4.1; box(s,x,4.65,3.85,1.9);
  text(s,v[0],x+.22,4.8,1.2,.3,15,v[3],{bold:true});
  text(s,v[1],x+.22,5.15,3.4,.4,20,C.ink,{bold:true});
  text(s,v[2],x+.22,5.68,3.4,.7,14,C.muted);
 });
 footer(s,'示意圖：時間軸長度為概念示意，非模擬數據。Reader 一片約 11 s（load+mount 2 s、read 8 s、unload 1 s）。');
}
// 9b: architecture
{
 const s=slide('Prefetch Buffer 架構：在 Reader 前方劃出待讀區','不加新硬體：reader 前面的一段 rack slots 由軟體劃為 buffer，shuttle 先把待讀玻璃搬過來。',
 '圖為示意：一個 partition 有 8 條 rack，每條 80 個 slot；圖中畫 N=4 台 shuttle，每台在 Zone 下負責 2 條相鄰 rack，但可以在多條 rack 間移動。Reader 在 partition 右下角，reader 前方 rack 的最後幾個 slot 由軟體劃為 prefetch buffer：黃色是已預取、等待讀取的玻璃，白色是空位。Request 已知時，shuttle 先把玻璃搬進 buffer，reader 讀完目前這片就直接讀下一片。讀完的玻璃仍要送回原 slot。模擬中 buffer 以 reader 前的 B 個 slots 建模，實體位置做了抽象；接下來的實驗固定 N=8，比較 B=0/8/16。');
 fitImage(s,path.join(root,'docs/diagrams/partition-prefetch-architecture-slide.png'),.55,2.05,9.05,4.65,1540/812);
 [['Rack + Shuttle','8 條 rack × 80 slots；\n每台 shuttle 可跨多條 rack 搬運',C.zone,C.pale],
  ['Prefetch buffer','reader 前方的 rack slots，\n由軟體劃定、不加硬體','8A6416','FBF3E2'],
  ['Reader','每個 partition 一台，\n從 buffer 依序讀取',C.local,'F2EDF7']].forEach((v,i)=>{
  const y=2.1+i*1.55; box(s,9.85,y,2.85,1.35,v[3]);
  text(s,v[0],10.05,y+.15,2.5,.35,17,v[2],{bold:true});
  text(s,v[1],10.05,y+.58,2.5,.6,12.5,C.muted);
 });
 footer(s,'示意圖畫 N=4、2×8 buffer slots；後續實驗固定 N=8，比較 B=0 / 8 / 16。');
}
// 7
{
 const s=slide('N=8 Prefetch：先看 p99 是否下降','只改 B=0 / 8 / 16，固定同一個 partition、8 台 shuttle 與 1 個 reader。',
 '這張圖來自 results/partition-feeder-prefetch-n8。X是prefetch buffer slots，Y是每個run的p99 latency平均。B=8符合一片/一台shuttle的主要設計點；B=16是額外容量敏感度。');
 fitImage(s,path.join(prefetchDir,'fig1_p99_uniform.png'),.72,1.95,12,4.7,2000/840);
 footer(s,'X：Prefetch slots (N=8) · Y：mean per-run p99 latency (minutes) · uniform / hotspot 分開。');
}
// 8
{
 const s=slide('Prefetch hit：玻璃真的提早到位了嗎？','B>0 的收益應該先出現在 handoff overlap，再反映在 p99 與 throughput。',
 'prefetch hit是handoff早於該片reader start的比例；lead是平均提前秒數；route motion是實體fetch/delivery/return路段時間，不包含traffic wait。這張圖來自N=8、read=8s、uniform。');
 fitImage(s,path.join(prefetchDir,'fig2_prefetch_diagnostics.png'),.72,1.95,12,4.7,2000/950);
 footer(s,'左：prefetch hit fraction · 中：lead time · 右：route motion / request；B不會讓physical distance消失。');
}
// 9
{
 const s=slide('B=16 仍有收益，但很快出現遞減','Prefetch capacity beyond N=8 is a sensitivity point, not the main design target.',
 'B=8與B=16都在N=8的同一partition。B=16有時提升lead time，但throughput與p99的額外改善很小；Non-Zone hotspot甚至不改善。這支持有限prefetch window的動機，不支持無限buffer。');
 fitImage(s,path.join(prefetchDir,'fig3_throughput.png'),.72,2.0,12,4.5,2000/960);
 footer(s,'X：Prefetch slots 0 / 8 / 16 · Y：read completions / min · read time與pattern分開保留在CSV。');
}
// 10
{
 const s=slide('加入到達時間後，再檢查一次','E4｜配對 Poisson requests；到達率固定，不為各方法分別調整。',
 'E4 N4 L32 read8，rate=.6/11 req/s。Rate是standalone reader ceiling的60%，不是實際transport系統capacity的60%。在較慢policy可能overload，有限episode p99不是steady-state。Synthetic arrivals，不是Azure trace。');
 ['uniform','hotspot'].forEach((pattern,i)=>{text(s,pattern,.85+i*6.3,2.1,5.7,.35,20,C.zone,{bold:true});bars(s,[0,4].map(b=>({name:`B=${b}`,labels:['Zone','Non-Zone FIFO'],values:['zone','nonzone_fifo'].map(p=>one({experiment:'E4',pattern,policy:p,buffer_slots:b}).p99_s_mean/60)})),.65+i*6.3,2.6,6.1,3.45,[C.fifo,C.zone]);});
 footer(s,'Y：各 run p99 的平均（分鐘）；N=4、同一 reader。自然 trace 與穩態驗證仍待後續進行。');
}
// Next-step story: where Zone's assumptions break (reads results/partition-feeder-prefetch-n8).
const pfRows=fs.readFileSync(path.join(prefetchDir,'aggregate.csv'),'utf8').trim().split('\n');
const pfHead=pfRows[0].split(',');
const pf=pfRows.slice(1).map(l=>Object.fromEntries(l.split(',').map((v,j)=>[pfHead[j],isNaN(Number(v))?v:Number(v)])));
const pfAt=(pattern,read,policy,b)=>{const r=pf.find(r=>r.pattern===pattern&&r.read_s===read&&r.policy===policy&&r.buffer_slots===b);if(!r)throw new Error(`No prefetch cell ${pattern}/${read}/${policy}/${b}`);return r;};
const perReq=(r,k)=>r[k]/r.requests_mean;
const ZU=pfAt('uniform',8,'zone',0), NU=pfAt('uniform',8,'nonzone_fifo',0);
const ZH=[0,8,16].map(b=>pfAt('hotspot',8,'zone',b)), NH=[0,8,16].map(b=>pfAt('hotspot',8,'nonzone_fifo',b));
const NEXT='下一步 / ZONE 的適用邊界';
{
 const s=slide('下一步：Zone 為什麼不一定好？','用一個比喻把故事串起來：先承認 Zone 的優點，再找出它沒想到的地方。',
 '這一段是下一輪研究的故事線，不是已完成的結論。比喻：reader 是只有一個出餐窗口的餐廳，shuttle 是外送員，prefetch buffer 是門口的暫存台。Zone 是每位外送員只搬自己負責那幾排貨架；Non-Zone 是誰有空誰去搬。故事分五步：一、平均時 Zone 很好；二、它隱含了四個假設；三、需求不均時 buffer 救不了 Zone；四、除了負載不均，還有幾個不直觀的問題；五、Non-Zone 有彈性但會塞車，因此需要會看 buffer 狀態的 Non-Zone 調度。',NEXT);
 const acts=[['01','平均時 Zone 很好','路線短、車不互卡；先承認它的優點'],['02','它偷偷假設了四件事','需求平均、不隨時間變、車都可用、一次讀一片'],['03','Buffer 救不了人手不均','暫存台吸收時間差，補不了單一 owner 的不足'],['04','負載以外的問題','距離、回程、buffer 位置、讀取順序、短時擁擠、故障'],['05','Non-Zone 也要付代價','共享會塞車 →需要會看 buffer 的調度']];
 acts.forEach((v,i)=>{const x=.7+i*2.42,last=i===4;box(s,x,2.2,2.25,2.95,last?'F2EDF7':C.pale);
  text(s,v[0],x+.18,2.38,.6,.3,16,last?C.local:C.zone,{bold:true});
  text(s,v[1],x+.18,2.82,1.95,.75,17,C.ink,{bold:true,valign:'top'});
  text(s,v[2],x+.18,3.85,1.95,.95,13,C.muted,{valign:'top'});
  if(i<4)arrow(s,x+2.27,3.55,.13,'BBC8C0');});
 box(s,.7,5.45,11.95,1.05,'F6F8F6','C8D5CC');
 text(s,'比喻',.95,5.6,.8,.3,14,C.fifo,{bold:true});
 text(s,'Reader＝只有一個出餐窗口的餐廳；Shuttle＝外送員；Prefetch buffer＝門口的暫存台。\nZone＝每位外送員只搬自己那幾排貨架；Non-Zone＝誰有空誰去搬。',1.85,5.55,10.6,.85,14,C.ink);
 footer(s,'故事線為研究構想；第 2–4 步的部分機制已有本輪數據，其餘列為待驗證假設。');
}
{
 const s=slide('Zone 偷偷假設了四件事','均勻需求下 Zone 確實比較好；但這個優點建立在幾個不一定成立的前提上。',
 `左側數據：N=8、read=8 s、B=0、uniform。Zone 每個 request 的路段移動約 ${perReq(ZU,'route_motion_s_mean').toFixed(0)} 秒、路段等待約 ${perReq(ZU,'traffic_wait_s_mean').toFixed(0)} 秒；Non-Zone FIFO 分別約 ${perReq(NU,'route_motion_s_mean').toFixed(0)} 與 ${perReq(NU,'traffic_wait_s_mean').toFixed(0)} 秒。所以平均時 Zone 的局部性是真的。右側四個假設：需求平均、需求不隨時間變、每台車都可用、一次只讀一片。Silica 論文提到 shuttle 故障可能讓 storage racks 被隔開，平台不可用時要用 cross-platter network coding 讀同一 platter-set 的其他平台，這讓第三、四個假設在真實系統中會被打破。`,NEXT);
 box(s,.7,2.1,4.55,4.4,C.pale);
 text(s,'均勻需求（N=8、read=8 s、B=0）',.92,2.28,4.1,.3,14,C.muted);
 [['路段移動 / request',perReq(ZU,'route_motion_s_mean'),perReq(NU,'route_motion_s_mean')],['路段等待 / request',perReq(ZU,'traffic_wait_s_mean'),perReq(NU,'traffic_wait_s_mean')]].forEach((v,i)=>{const y=2.8+i*1.75;
  text(s,v[0],.92,y,4,.3,15,C.ink,{bold:true});
  text(s,`Zone ${v[1].toFixed(0)} s`,.92,y+.45,2,.55,24,C.zone,{bold:true});
  text(s,`Non-Zone ${v[2].toFixed(0)} s`,2.95,y+.5,2.2,.5,17,C.fifo);});
 [['每一區的需求一樣多','熱門資料集中 →\n一位 owner 忙翻，其他人閒著'],['需求不隨時間改變','熱區會移動 →\n要重新劃區，否則一直不均'],['每台 shuttle 都可用','一台故障 →\n整區玻璃暫時讀不到'],['一個 request 只讀一片','降級讀取要讀多片 →\n完成時間看最慢的那一區']].forEach((v,i)=>{
  const x=5.6+(i%2)*3.57,y=2.1+Math.floor(i/2)*2.25; box(s,x,y,3.4,2.05,'F6F8F6','C8D5CC');
  text(s,'假設',x+.2,y+.17,1,.25,12,C.muted);
  text(s,v[0],x+.2,y+.47,3.05,.4,17,C.ink,{bold:true});
  text(s,v[1],x+.2,y+1.05,3.05,.8,13,C.fifo,{valign:'top'});});
 footer(s,'假設 3、4 依據：Project Silica SOSP 2023（shuttle 故障造成 rack 隔開；cross-platter network coding）。');
}
{
 const s=slide('Buffer 救得了時間差，救不了人手不均','75% requests 集中在 rows 0/1：只有熱區 owner 能搬，buffer 加大也補不了。',
 `數據：results/partition-feeder-prefetch-n8，hotspot、N=8、read=8 s。Zone 的 buffer 從 8 格加到 16 格，玻璃平均提前時間從 ${ZH[1].prefetch_lead_mean_s_mean.toFixed(0)} 秒增加到 ${ZH[2].prefetch_lead_mean_s_mean.toFixed(0)} 秒，但 prefetch hit 只從 ${(100*ZH[1].prefetch_hit_fraction_mean).toFixed(0)}% 變為 ${(100*ZH[2].prefetch_hit_fraction_mean).toFixed(0)}%，throughput 幾乎不變。解讀：多出來的 slot 被冷區提早送來的玻璃占住，熱區玻璃仍然卡在單一 owner。受限閒置（restricted idle）是 shuttle 閒著、但剩下的工作都不屬於它的時間；hotspot 下每個 request 約 ${perReq(ZH[1],'restricted_idle_s_mean').toFixed(0)} shuttle-s，uniform 只有約 ${perReq(ZU,'restricted_idle_s_mean').toFixed(0)}。「buffer 被冷區玻璃占住」是推論，需要下一輪的 buffer 組成指標直接量測。`,NEXT);
 bars(s,[{name:'Zone',labels:['B=0','B=8','B=16'],values:ZH.map(r=>r.throughput_req_s_mean*60)},{name:'Non-Zone FIFO',labels:['B=0','B=8','B=16'],values:NH.map(r=>r.throughput_req_s_mean*60)}],.6,2.05,7.7,4.45,[C.zone,C.fifo],null);
 [[`提前 ${ZH[1].prefetch_lead_mean_s_mean.toFixed(0)} → ${ZH[2].prefetch_lead_mean_s_mean.toFixed(0)} s`,'Zone 的 buffer 8 → 16 格：\n玻璃更早到，throughput 幾乎不變',C.pale,C.zone],
  [`Hit 只有 ${(100*ZH[2].prefetch_hit_fraction_mean).toFixed(0)}%`,'一半以上的玻璃仍然\n在 reader 要讀時還沒到','FBF3E2','8A6416'],
  [`閒著不能幫 ${perReq(ZH[1],'restricted_idle_s_mean').toFixed(0)} s`,`每 request 的受限閒置（shuttle-s）\nuniform 時只有 ${perReq(ZU,'restricted_idle_s_mean').toFixed(0)} s`,'F2EDF7',C.local]].forEach((v,i)=>{
  const y=2.1+i*1.5; box(s,8.7,y,3.95,1.32,v[2]);
  text(s,v[0],8.9,y+.14,3.6,.42,20,v[3],{bold:true});
  text(s,v[1],8.9,y+.62,3.6,.6,12.5,C.muted,{valign:'top'});});
 footer(s,'Y：read completions / min；hotspot、N=8、read=8 s、5 seeds 平均。Buffer 吸收時間差，不能補足長期不足的供料。');
}
// Zone blind spots: one overview, then one slide per issue (diagram left, explanation right).
const ZC=['4F7CAC','3F9E8F','8A6BBF','C2577A'], ZL=['E6EEF7','E3F3F0','EFEAF7','F8E7ED'];
function ar(s,x1,y1,x2,y2,color,dash=false,width=1.75){
 s.addShape(pptx.ShapeType.line,{x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.max(Math.abs(x2-x1),.001),h:Math.max(Math.abs(y2-y1),.001),
  flipH:x2<x1,flipV:y2<y1,line:{color,width,dashType:dash?'dash':'solid',endArrowType:'triangle'}});
}
function sh(s,x,y,c,label){box(s,x,y,.38,.36,c,'263238');text(s,label,x,y,.38,.36,10,C.white,{bold:true,align:'center'});}
function mini(s,x,y,w,h,o={}){
 const rh=h/4, rackW=w-1.25, n=16, tick=k=>x+.65+k*((rackW-.75)/n);
 for(let i=0;i<4;i++){
  const ry=y+i*rh+rh*.18, rH=rh*.64, dim=o.dim===i;
  box(s,x+.55,ry,rackW-.55,rH,dim?'E6E6E6':ZL[i],'B8C4C9');
  text(s,`Rack ${i}`,x,ry,.52,rH,10,C.muted);
  for(let k=0;k<n;k++){const buf=i===3&&k>=n-3;
   s.addShape(pptx.ShapeType.rect,{x:tick(k),y:ry+.08,w:.06,h:rH-.16,fill:{color:dim?'CFCFCF':buf?(k%2?'F2C766':'FFFFFF'):'BFD9E4'},line:{color:buf?'D9A441':dim?'B5B5B5':'7FA7B8',width:.5}});}
 }
 s.addShape(pptx.ShapeType.rect,{x:tick(n-3)-.06,y:y+3*rh+rh*.12,w:tick(n-1)-tick(n-3)+.18,h:rh*.76,fill:{color:'FFFFFF',transparency:100},line:{color:'D9A441',width:1.5,dashType:'dash'}});
 box(s,x+rackW+.2,y+3*rh+rh*.08,.95,rh*.84,'E3F0F3','2B819B');
 text(s,'Reader',x+rackW+.2,y+3*rh+rh*.08,.95,rh*.84,11,'2B819B',{bold:true,align:'center'});
 return {row:i=>y+i*rh+rh/2, tick, x1:x+rackW, rx:x+rackW+.2, ry:y+3*rh+rh/2, rh};
}
function explain(s,zone,real,nz,verify){
 const rowsX=[['Zone 以為',zone,C.zone,C.pale,.95],['實際會發生',real,C.fifo,'F8EFE6',1.45],['Non-Zone 怎麼處理',nz,C.local,'F2EDF7',1.15]];
 let y=2.1;
 rowsX.forEach(v=>{box(s,7.35,y,5.3,v[4],v[3]);text(s,v[0],7.55,y+.12,4.9,.28,13,v[2],{bold:true});text(s,v[1],7.55,y+.45,4.9,v[4]-.55,12.5,C.ink,{valign:'top'});y+=v[4]+.12;});
 box(s,.7,6.0,11.95,.6,'F6F8F6','C8D5CC');
 text(s,'怎麼驗證',.9,6.0,1.1,.6,13,C.zone,{bold:true});
 text(s,verify,2.05,6.0,10.4,.6,12.5,C.muted);
}
const ISSUES=[['距離不平均','需求平均，遠區仍然天生較慢'],['先到先讀 = 近的先讀','FIFO buffer 讓近區一直插隊'],['Buffer 落在某一區','最擠的地方沒有分區保護'],['空車回程與停車位置','只能回自己區，不能順路'],['Buffer 前排成車隊','加了 buffer，Zone 的車卻沒少等'],['短時間的擁擠','長期平均均勻，短期一直有熱點'],['車不可用','故障、充電、磨損，整區停擺']];
const blind=(n,title,sub,notes)=>slide(title,sub,notes,`ZONE 沒考慮到的事 / 0${n}`);
{
 const s=slide('負載不均以外，Zone 還沒考慮到的七件事','就算總需求完全平均，這些問題也可能發生；接下來一頁講一件。',
 '這一頁是目錄。七件事都來自同一個前提：每台車只看自己那一區。第五件已有本輪 E3 數據，其他是待驗證的假設，接下來每頁會說明 Zone 以為什麼、實際會發生什麼、Non-Zone 怎麼處理，以及怎麼驗證。',NEXT);
 ISSUES.forEach((v,i)=>{const x=.7+(i%4)*3.03,y=2.1+Math.floor(i/4)*2.1; box(s,x,y,2.85,1.9,i===4?'FBF3E2':C.pale);
  text(s,String(i+1).padStart(2,'0'),x+.2,y+.17,.6,.3,15,C.zone,{bold:true});
  text(s,v[0],x+.2,y+.55,2.5,.4,17,C.ink,{bold:true});
  text(s,v[1],x+.2,y+1.1,2.5,.6,13,C.muted,{valign:'top'});});
 box(s,.7+3*3.03,4.2,2.85,1.9,'F2EDF7');
 text(s,'共同點',9.99,4.37,2.5,.3,15,C.local,{bold:true});
 text(s,'每台車只看自己那一區：整個 partition 的狀態，沒有人在看',9.99,4.75,2.5,1.1,15,C.ink,{bold:true,valign:'top'});
 footer(s,'第 05 件已有本輪數據（E3）；其餘為待驗證假設，下一輪實驗會逐一量測。');
}
{
 const s=blind(1,'距離不平均：需求平均，遠區仍然較慢','每一趟都要送到 reader；離 reader 越遠的區，owner 每趟來回越久。',
 'Zone 以為需求平均就等於每台車的工作量一樣。但工作量是次數乘以每趟時間：每片玻璃都要送到 reader，遠區 owner 每趟要多跨好幾排，來回時間較長，所以遠區的供料速率天生較慢，遠區資料的等待時間會比較長。Non-Zone 可以讓剛好在附近的空車去接，遠區的工作不必全部由同一台車承擔。驗證方式：uniform 負載下，依 rack 分組比較 p99，並計算每台 owner 的忙碌率。這是待驗證假設。');
 const m=mini(s,.7,2.1,6.3,3.75);
 sh(s,m.tick(4),m.row(0)-.18,ZC[0],'S1'); sh(s,m.tick(9),m.row(3)-.18,ZC[3],'S4');
 ar(s,m.tick(4)+.42,m.row(0),m.x1+.12,m.row(0),ZC[0],false,2);
 ar(s,m.x1+.12,m.row(0),m.x1+.12,m.ry-.2,ZC[0],false,2);
 ar(s,m.x1+.12,m.ry-.2,m.rx,m.ry-.2,ZC[0],false,2);
 ar(s,m.tick(9)+.42,m.row(3)+.08,m.rx,m.row(3)+.08,ZC[3],false,2);
 text(s,'遠區：每趟要跨 3 排才到 reader',1.4,m.row(0)+.3,4,.25,12,ZC[0],{bold:true});
 text(s,'近區：幾步就到',m.tick(9)-1.6,m.row(3)-.05,1.5,.25,12,ZC[3],{bold:true});
 explain(s,'需求平均，每台車的工作量就一樣','工作量 = 次數 × 每趟時間。次數一樣，但遠區每趟都比較長：遠區 owner 供料較慢，遠區資料的等待天生較長','剛好在附近的空車就可以去接；遠區的工作不必全靠同一台車','uniform 負載下，依 rack 分組比較 p99；計算每台 owner 的忙碌率');
 footer(s,'待驗證假設。示意圖以 4 條 rack 簡化；實際模型為 8 rows、reader 接在 row 3。');
}
{
 const s=blind(2,'先到先讀 = 近的先讀','Buffer 依「送到的順序」讀取，不是依「請求的順序」。',
 'Zone 以為 buffer 先進先出很公平。但 FIFO 的「先」是玻璃送到 buffer 的時間，不是使用者發出請求的時間。近區的車來回快，總是比較早送到，因此一直排在前面；遠區的請求就算最早發出，也可能最後才被讀，尾端延遲被放大。Non-Zone 可以優先派車去搬等最久的那一片，最急的工作不會被綁在某一台忙碌的車上。驗證方式：計算請求順序與讀取順序之間的逆序數，並比較各區 p99。這是待驗證假設。');
 const chip=(x,y,t,c)=>{box(s,x,y,.85,.55,c,'263238');text(s,t,x,y,.85,.55,14,C.white,{bold:true,align:'center'});};
 text(s,'請求發出順序',.75,2.55,1.7,.4,15,C.ink,{bold:true});
 text(s,'實際讀取順序',.75,4.25,1.7,.4,15,C.ink,{bold:true});
 ['遠1','近1','近2','近3'].forEach((t,k)=>chip(2.6+k*1.05,2.47,t,t[0]==='遠'?ZC[0]:ZC[3]));
 ['近1','近2','近3','遠1'].forEach((t,k)=>chip(2.6+k*1.05,4.17,t,t[0]==='遠'?ZC[0]:ZC[3]));
 ar(s,3.03,3.05,5.75,4.12,C.red,true,2);
 text(s,'最早發出，最後才讀',4.45,3.3,2.3,.3,13,C.red,{bold:true});
 text(s,'近區的車來回快，總是先把玻璃送到 buffer',.75,5.15,6.2,.3,13,C.muted);
 explain(s,'Buffer 先進先出，對大家都公平','「先」是送到的時間，不是請求的時間。近區送得快，一直排在前面；遠區請求就算最早發出，也可能最後才讀','優先派車去搬等最久的那一片；最急的工作不會被綁在某一台忙碌的車上','計算請求順序與讀取順序的逆序數；比較各區 p99');
 footer(s,'待驗證假設。與 01 疊加：距離差讓遠區送得慢，FIFO 再把這個差距放大成讀取順序。');
}
{
 const s=blind(3,'Buffer 落在某一區：最擠的地方沒有分區保護','Buffer 是 reader 前方的 rack slots，一定屬於某一區；所有車都要進那一區交貨。',
 'Zone 的賣點是各區互不干擾。但照我們的架構，prefetch buffer 是 reader 前方的 rack slots，必然落在某一區裡，圖中是 S4 的 Rack 3。每一台車都要開進 S4 的地盤交貨，所以整個 partition 最擁擠的地方剛好沒有分區保護，而 S4 自己的取件工作還會被其他車擋住。Non-Zone 本來就假設路段是共用的，從一開始就把 reader 前的交通納入調度。驗證方式：比較 buffer 所在區與其他區的路段等待，並改變 buffer 位置看敏感度。這是待驗證假設。');
 const m=mini(s,.7,2.1,6.3,3.75);
 const tx=m.tick(13)+.05, ty=m.row(3)-m.rh*.32;
 [[0,5],[1,9],[2,3]].forEach(([i,k])=>{sh(s,m.tick(k),m.row(i)-.18,ZC[i],`S${i+1}`);ar(s,m.tick(k)+.4,m.row(i)+.1,tx,ty,ZC[i],true,1.75);});
 sh(s,m.tick(8),m.row(3)-.18,ZC[3],'S4');
 text(s,'S4：自己的工作被擋',m.tick(5)-.2,m.row(3)+.22,2.2,.25,12,C.red,{bold:true});
 text(s,'所有車都要進 S4 的區域交貨',m.x1+.15,m.row(2)-.3,1.2,.75,11,'8A6416',{bold:true,valign:'top'});
 explain(s,'各區互不干擾','Buffer 一定落在某一區（圖中是 S4）。所有車都要進去交貨：最擠的地方剛好沒有分區保護，S4 自己的工作還會被擋','本來就假設路段共用，從一開始就把 reader 前的交通納入調度','比較 buffer 所在區與其他區的路段等待；改變 buffer 位置看敏感度');
 footer(s,'待驗證假設。目前模擬把 buffer 抽象為 reader 前的 B 個 slots，需要加入實體位置才能量測。');
}
{
 const s=blind(4,'空車回程與停車位置','Zone 的車送完只能空車回自己區；讀完的玻璃也只能由原 owner 送回。',
 'Zone 以為只在自己區裡跑，路線最短。但每一趟都一定要到 reader：送完之後，車只能空車回自己的區；讀完的玻璃也只能由原本的 owner 送回去。閒置時，車也只能停在自己區，可能離 reader 很遠。Non-Zone 送完可以順路帶一片讀完的玻璃回附近的 rack，再接附近的下一單；閒置的車也可以停在 reader 附近待命。驗證方式：統計空車行駛距離比例，以及歸還造成的額外趟數。這是待驗證假設。');
 const m=mini(s,.7,2.1,6.3,3.75);
 ar(s,m.rx,m.ry-.32,m.tick(3),m.row(0)+.05,'8C979C',true,2);
 ar(s,m.rx+.15,m.ry-.38,m.tick(11),m.row(2)+.02,'3F8E80',false,2.25);
 const lx=m.x1+.15;
 text(s,'灰虛線 Zone：\n送完，空車回 rack 0',lx,m.row(0)-.3,1.25,.6,10.5,'6B777C',{bold:true,valign:'top'});
 text(s,'綠線 Non-Zone：\n順路帶讀完的玻璃回 rack 2，接附近的下一單',lx,m.row(1)-.4,1.25,.95,10.5,'3F8E80',{bold:true,valign:'top'});
 box(s,lx,m.row(2)-.12,.36,.32,'3F8E80','263238');text(s,'P',lx,m.row(2)-.12,.36,.32,11,C.white,{bold:true,align:'center'});
 text(s,'閒置時停在\nreader 附近',lx+.42,m.row(2)-.18,.9,.45,10,'3F8E80',{valign:'top'});
 explain(s,'只在自己區裡跑，路線最短','每趟都要到 reader。送完只能空車回自己區，讀完的玻璃也只能由原 owner 送回；閒置時只能停在自己區，可能離 reader 很遠','送完順路帶一片讀完的玻璃回去，接附近的下一單；閒置的車可以停在 reader 附近待命','統計空車行駛距離比例，以及歸還造成的額外趟數');
 footer(s,'待驗證假設。目前模型的歸還策略固定為 return-first；Non-Zone 的順路歸還需要另外實作。');
}
{
 const e3=p=>sort(get({experiment:'E3',pattern:'uniform',policy:p,shuttles:8,read_s:8,length_m:32}),'buffer_slots');
 const z=e3('zone'), f=e3('nonzone_fifo'), dw=r=>r.delivery_wait_s_mean/r.requests_mean;
 const s=blind(5,'Buffer 前排成車隊：加了 buffer，Zone 的車卻沒少等','E3｜同樣加 buffer，Non-Zone 的等交付幾乎歸零，Zone 卻沒有減少。',
 `數據：E3，uniform、N=8、32 m、read=8 s。等交付時間是 shuttle 抵達 reader 端後等待交貨的時間，除以 request 數。Non-Zone FIFO 從 B=0 的 ${dw(f[0]).toFixed(1)} 秒降到 B=4 的 ${dw(f[f.length-1]).toFixed(1)} 秒；Zone 從 ${dw(z[0]).toFixed(1)} 秒變成 ${dw(z[z.length-1]).toFixed(1)} 秒，沒有減少。一個可能的解釋是：Zone 的各台車各自決定何時出發，常常同時抵達，在 buffer 前排成車隊；Non-Zone 由中央指派，抵達時間比較分散。這是已觀察到、但原因未確定的現象，需要記錄抵達時間分布與排隊長度才能確認。`);
 text(s,'Shuttle 等交付時間 / request（s）',.75,2.05,6,.3,14,C.zone,{bold:true});
 bars(s,[{name:'Zone',labels:z.map(r=>`B=${r.buffer_slots}`),values:z.map(dw)},{name:'Non-Zone FIFO',labels:f.map(r=>`B=${r.buffer_slots}`),values:f.map(dw)}],.6,2.4,6.5,3.45,[C.zone,C.fifo]);
 explain(s,'加了 buffer，車就不用在 reader 前等',`Non-Zone 等交付從 ${dw(f[0]).toFixed(0)} s 降到 ${dw(f[f.length-1]).toFixed(1)} s；Zone 從 ${dw(z[0]).toFixed(0)} s 變 ${dw(z[z.length-1]).toFixed(0)} s，沒有減少。各台車各自出發，可能同時抵達、在 buffer 前排隊`,'由中央指派，可以錯開抵達時間；buffer 快滿時不急著出發','記錄抵達時間分布與 buffer 前排隊長度，確認是否為「同時抵達」造成');
 footer(s,'E3：uniform、N=8、32 m、read=8 s、5 seeds 平均。已觀察到的現象；原因尚未確定。');
}
{
 const s=blind(6,'短時間的擁擠：長期平均均勻，短期一直有熱點','真實請求常成串出現；排隊發生在幾分鐘內，不是長期平均。',
 'Zone 以為長期平均是均勻的，所以每一區都一樣忙。但真實的請求常常成串出現，例如同一個檔案、同一個使用者的連續讀取，幾分鐘之內就集中在同一排。分區是依長期平均設計的，排隊卻發生在短時間內：每個時段都有一區忙翻、其他區閒著。Non-Zone 在每個當下把閒著的車派去最忙的地方，不需要長期平均成立。驗證方式：總體均勻、但連續 k 個請求落在同一排，k 從 1 掃到 32。這是待驗證假設。');
 const base=5.35, sc=.85, groups=[['時段 1',[3,.6,.5,.4]],['時段 2',[.5,.4,2.8,.7]],['時段 3',[.6,2.6,.5,.7]],['整體平均',[1.05,1.2,1.15,.95]]];
 groups.forEach((g,gi)=>{const gx=.95+gi*1.55+(gi===3?.35:0);
  g[1].forEach((v,k)=>s.addShape(pptx.ShapeType.rect,{x:gx+k*.3,y:base-v*sc,w:.25,h:v*sc,fill:{color:ZC[k]},line:{color:ZC[k]}}));
  text(s,g[0],gx-.1,base+.1,1.4,.3,13,gi===3?C.ink:C.muted,{bold:gi===3,align:'center'});});
 s.addShape(pptx.ShapeType.line,{x:5.45,y:2.6,w:0,h:2.9,line:{color:'BBC8C0',width:1,dashType:'dash'}});
 text(s,'各區工作量：S1  S2  S3  S4',.95,2.15,4,.3,13,C.muted);
 text(s,'平均看起來很均勻',5.6,2.55,1.6,.5,12,C.zone,{bold:true});
 explain(s,'長期平均均勻，每一區都一樣忙','請求常成串（同一檔案、同一使用者），幾分鐘內集中在同一排。分區依長期平均設計，排隊卻發生在短時間內','每個當下把閒著的車派去最忙的地方，不需要長期平均成立','總體均勻、但連續 k 個請求落在同一排；k 從 1 掃到 32，比較 p99 與受限閒置');
 footer(s,'待驗證假設。示意圖為概念數字，非模擬數據。');
}
{
 const s=blind(7,'車不可用：故障、充電、磨損，整區停擺','熱區 owner 跑最多趟：最常充電、磨損最快；它不在，整區就讀不到。',
 'Zone 以為每台車隨時可用。但 Project Silica 的 shuttle 是用電池的，熱區 owner 跑最多趟，最常需要充電、磨損也最快。每次它不在，不管是故障、充電還是維修，它負責的那一區就暫時讀不到。Silica 論文提到 shuttle 故障可能讓 storage racks 被隔開；平台不可用時，系統要讀同一 platter-set 的其他平台，用 cross-platter network coding 還原，原本讀一片變成要讀好幾片。Non-Zone 少一台只是少一份人力，其他車分攤；工作分散，充電與磨損也比較平均。驗證方式：讓一台車停機 T 分鐘，或加入週期性充電，比較掉速與受影響的 request 數。');
 const m=mini(s,.7,2.1,6.3,3.0,{dim:1});
 [[0,5],[2,10],[3,7]].forEach(([i,k])=>sh(s,m.tick(k),m.row(i)-.18,ZC[i],`S${i+1}`));
 sh(s,m.tick(4),m.row(1)-.18,'9AA0A3','S2'); text(s,'✕',m.tick(4)+.35,m.row(1)-.3,.3,.3,16,C.red,{bold:true});
 text(s,'這一區暫時讀不到',m.tick(7),m.row(1)-.13,2.2,.26,12,C.red,{bold:true});
 ['故障','充電（電池）','維修 / 磨損'].forEach((t,k)=>{box(s,.75+k*1.6,5.3,1.45,.45,'F6F8F6','C8D5CC');text(s,t,.75+k*1.6,5.3,1.45,.45,12,C.ink,{align:'center'});});
 text(s,'→ 降級讀取：改讀同組好幾片',5.6,5.3,1.7,.45,11,C.red,{bold:true});
 explain(s,'每台車隨時可用','Shuttle 用電池。熱區 owner 跑最多，最常充電、磨損最快；它一不在，整區就讀不到。Silica 要改讀同組其他平台來還原，一片變好幾片','少一台只是少一份人力，其他車分攤；工作分散，充電與磨損也較平均','一台停機 T 分鐘，或加入週期性充電；比較掉速與受影響的 request 數');
 footer(s,'依據：Project Silica SOSP 2023（battery-powered shuttles；shuttle 故障造成 rack 隔開；cross-platter network coding）。');
}
{
 const s=slide('Non-Zone 也有代價：單純共享會塞車','同一個 hotspot 場景，Non-Zone FIFO 加上 buffer 反而稍微變慢。',
 `數據：hotspot、N=8、read=8 s。Non-Zone FIFO 的 throughput 從 B=0 的 ${(NH[0].throughput_req_s_mean*60).toFixed(2)} 降到 B=8 的 ${(NH[1].throughput_req_s_mean*60).toFixed(2)} req/min，每個 request 的路段等待從 ${perReq(NH[0],'traffic_wait_s_mean').toFixed(0)} 秒增加到 ${perReq(NH[1],'traffic_wait_s_mean').toFixed(0)} 秒。推測：有 buffer 後 shuttle 交貨就被釋放，同時上路的車變多，交通更擁擠；這個因果還沒有獨立驗證。這一頁的重點是：Zone 的問題是結構性的，加 buffer 修不好；Non-Zone 的問題是調度上的，有機會用方法修好。這就是下一步方法的位置。`,NEXT);
 bars(s,[{name:'Throughput (req/min)',labels:['B=0','B=8','B=16'],values:NH.map(r=>r.throughput_req_s_mean*60)}],.6,2.35,3.9,3.9,[C.fifo],null);
 bars(s,[{name:'Traffic wait / request (s)',labels:['B=0','B=8','B=16'],values:NH.map(r=>perReq(r,'traffic_wait_s_mean'))}],4.6,2.35,3.9,3.9,['93AD9C'],null);
 text(s,'Throughput（req/min）',.85,2.05,3.5,.3,14,C.fifo,{bold:true});
 text(s,'路段等待 / request（s）',4.85,2.05,3.5,.3,14,C.zone,{bold:true});
 box(s,8.85,2.1,3.8,4.4,'F2EDF7');
 text(s,'兩種問題不一樣',9.08,2.3,3.4,.35,16,C.local,{bold:true});
 text(s,'Zone：結構性問題',9.08,2.85,3.4,.35,16,C.ink,{bold:true});
 text(s,'人手被分區綁住，\n加 buffer 也修不好',9.08,3.25,3.4,.6,13,C.muted,{valign:'top'});
 text(s,'Non-Zone：調度問題',9.08,4.0,3.4,.35,16,C.ink,{bold:true});
 text(s,'會看 buffer 哪格快空、\n哪片最急、控制同時上路的車數\n→ 有機會修好',9.08,4.4,3.4,.95,13,C.muted,{valign:'top'});
 text(s,'→ 下一步方法',9.08,5.7,3.4,.35,16,C.local,{bold:true});
 footer(s,'hotspot、N=8、read=8 s、5 seeds 平均。B=8 與 B=16 結果相同，代表 buffer 容量不是限制因素。');
}
{
 const s=slide('下一輪實驗：畫出 Zone 的適用邊界','不只挑 Zone 輸的格子：每個實驗都掃參數，讓「Zone 贏 → Zone 輸」的交叉點出現在圖上。',
 '實驗順序依成本與證據強度排列。一、熱區比例從 25%（均勻）掃到 90%，找 Zone 與 Non-Zone 的交叉點；只要把 make_requests 的 0.75 參數化。二、新增 buffer 組成指標：reader 空等時，buffer 裡有幾片別區的玻璃；並記錄各區 p99。三、距離公平性：uniform 下比較遠區與近區 p99。四、短時擁擠：總體均勻，但連續 k 個 request 落在同一排。五、shuttle 故障：一台停機 T 分鐘。六、最後才是 buffer-aware Non-Zone 方法，與 Zone、Zone + work stealing 強基準比較。所有設定先登記再跑，負向結果保留。',NEXT);
 const exps=[['1','熱區要多集中，Zone 才開始輸？','熱區比例 25% → 90%','交叉點'],['2','Buffer 被什麼占住？','B=0/8/16 × 熱區比例','別區玻璃占比、各區 p99'],['3','需求平均時，遠區吃虧嗎？','uniform，依 rack 分組','遠區 vs 近區 p99'],['4','短時間擁擠的影響','連續 k 個 request 同一排','p99、受限閒置'],['5','有一台故障會怎樣？','N=8，一台停機 T 分鐘','掉速、受影響 request'],['6','Buffer-aware Non-Zone','對 Zone、Zone + stealing','p99、throughput、塞車']];
 text(s,'#',.85,2.12,.3,.3,13,C.muted,{bold:true});text(s,'要回答的問題',1.3,2.12,4,.3,13,C.muted,{bold:true});text(s,'改變什麼',5.6,2.12,3.3,.3,13,C.muted,{bold:true});text(s,'看什麼',9.2,2.12,3.3,.3,13,C.muted,{bold:true});
 exps.forEach((v,i)=>{const y=2.5+i*.66; if(i%2===0)box(s,.7,y,11.95,.6,'F1F5F2');
  text(s,v[0],.85,y+.15,.3,.3,15,i===5?C.local:C.zone,{bold:true});
  text(s,v[1],1.3,y+.15,4.2,.3,15,C.ink,{bold:true});
  text(s,v[2],5.6,y+.15,3.5,.3,14,C.muted);
  text(s,v[3],9.2,y+.15,3.4,.3,14,C.muted);});
 footer(s,'1、2 成本最低（改參數與加指標）；5 有 Silica 論文依據；6 需要 Zone + work stealing 強基準，避免只打弱對手。');
}
// 11
{
 const s=slide('三個設計，對應三種不同的等待','共享有場景差異；Buffer 有正負結果。本輪未證明增加 Shuttle 會使整體更慢。',
 '本輪完成motivation characterization，不能稱paper-ready實驗、實機validate或新方法。每個設計點後接它需要觀察的metric，不用片面utilization下結論。');
 item(s,'01','搬運供料能力','Shuttle 數量與內部分工\n→ Reader 是否缺料？',.7,2.35);
 item(s,'02','多車協作方式','自由服務與路段競爭\n→ 收益是否抵過交通成本？',4.8,2.35);
 item(s,'03','有限交接空間','提早放下玻璃\n→ 等待是否真的減少？',8.9,2.35);
 text(s,'共同動機：讓搬運、交付與讀取配合，而不是各自追求局部最優。',.95,5.35,11.5,.75,23,C.zone,{bold:true});
 footer(s,'Return 固定、Reader 單一；暫不展開跨 partition sharing、cache 或預測 prefetch。');
}
// 12
{
 const s=slide('下一步方法：先補上決策需要的資訊','使用簡單資料結構；每一項資訊都要能對應一個已觀察的損失。',
 '這是下一步研究構想，不是本輪已驗證方法。待服務玻璃queue記錄位置/等待時間；shuttle狀態表與routecalendar提供可用時間；bufferreader表提供slot與expectedfree。不需要先引入大規模MAPF oracle或複雜ML。未來要與earliest-delivery及lookahead強基準比較。');
 const blocks=[['玻璃需求佇列','位置 · 等待時間 · 待讀工作量'],['Shuttle 狀態表','位置 · 可用時間 · 路段預約'],['Buffer / Reader 狀態','剩餘 slots · 預計釋放時間']];
 blocks.forEach((v,i)=>{box(s,.8,2.2+i*1.12,6.4,.87);text(s,v[0],1.03,2.36+i*1.12,2.7,.3,18,C.zone,{bold:true});text(s,v[1],3.83,2.37+i*1.12,3.1,.3,14,C.muted);});
 arrow(s,7.5,3.6,.7);box(s,8.55,2.68,3.95,2.4,'F2EDF7');text(s,'選哪片？\n由誰搬？\n何時交付？',8.93,3.05,3.15,1.6,25,C.local,{bold:true});
 footer(s,'方法假設：預計抵達時間與 reader/slot 可用時間一起考慮；是否有效，仍需獨立 ablation。');
}
// 13
{
 const s=slide('目前能說什麼，還需要補什麼？','把研究證據與模型假設分開，才有可信的論文動機。',
 '目前實驗可以說明所定義的model內三類mechanism。不能證明真實大型glasslibrary效能，或實際碰撞安全。模型驗證主要是resource互斥與conservation。reader isolatedinput+8docks/output都是explicit hardware assumption。真實workload、更長episode、warmup和moreseeds仍需補充。');
 item(s,'已有','可重現的機制觀察','同一 partition、配對工作\n固定硬體下的調度與 buffer 比較',.7,2.35);
 item(s,'待補','架構與參數校準','Endpoint / junction 幾何\n真實服務時間與工作負載',4.8,2.35);
 item(s,'再做','Glass-aware 方法','先辨認主要損失\n再以同硬體、強基準檢驗',8.9,2.35);
 footer(s,'所有參數與負向結果保留；不為配合預期故事修改或挑選實驗數字。');
}
// 14
{
 const s=slide('附錄：硬體、交通與服務假設','固定成本與幾何，必須和圖表一起閱讀。',
 '完整資料experiments/partition-feeder-story/README.md。Silica§7.1支持約0.5s定位與約3s crabbing量級；2m/s與2m/s²、1spickplacehandoffunload、2sloadmount等均為controlled assumptions。每row80slot共640；length16/32/64，singlepartitiononerdr。所有policy使用sameexclusiveblocks。', 'APPENDIX / MODEL');
 const facts=[['儲存 / 讀取','8 rack rows × 80 slots；1 reader'],['Shuttle / Prefetch','配比實驗 N=1~32；E2 N=2/4/8；Prefetch N=8、B=0/8/16'],['水平 / 跨層','2 m/s、2 m/s²；connector 3 s/段'],['交接 / 讀取','Handoff 1 s；load+mount 2 s；read 2/8/24 s'],['交通 / 等待','分段互斥預約；固定有限離軌 docking'],['歸還 / 輸出','8 output slots；return-first，完整計入歸還']];
 facts.forEach((v,i)=>{if(i%2===0)box(s,.8,2.1+i*.61,11.7,.56,'F1F5F2');text(s,v[0],1,2.2+i*.61,2.5,.29,17,C.zone,{bold:true});text(s,v[1],3.9,2.2+i*.61,8.1,.29,17);});
 footer(s,'部分機械量級參考 Project Silica §7.1；本模型並非原論文完整硬體重建或實機校準。');
}
// 15
{
 const s=slide('附錄：證據檔案與重現入口','每一張實驗圖都由同一份 aggregate 資料建立，PPT 圖表可編輯。',
 `Source paper: https://www.microsoft.com/en-us/research/wp-content/uploads/2023/09/ProjectSilica-SOSP23.pdf\nMain config: experiments/partition-feeder-story/full.json\nPrefetch config: experiments/partition-feeder-story/prefetch-n8.json\nPrefetch run: .venv/bin/python scripts/run_prefetch_n8.py --config experiments/partition-feeder-story/prefetch-n8.json\nDeck: node scripts/build_partition_feeder_story.js\nRuns: results/partition-feeder-prefetch-n8/runs.csv\nAggregate: results/partition-feeder-prefetch-n8/aggregate.csv\nExact effective configs/source hashes: run_configs.json and summary.json\nAll means are over ${input.summary.config.seeds.length} synthetic seeds. SD is in CSV and standalone figures.`, 'APPENDIX / REPRODUCIBILITY');
 item(s,'DATA','逐次結果與設定','runs.csv / aggregate.csv\nrun_configs.json / summary.json',.7,2.35);
 item(s,'AUDIT','可追查的服務過程','requests / jobs / timeline / rail\n因果、容量與互斥檢查',4.8,2.35);
 item(s,'SOURCE','程式與圖表產生器','partition_feeder_study.py\nbuild_partition_feeder_story.js',8.9,2.35);
 text(s,'下一輪討論：先確認架構假設，再決定最值得最佳化的等待。',.95,5.5,11.5,.7,23,C.zone,{bold:true});
 footer(s,'完整解讀與命令：results/partition-feeder-story/ANALYSIS_ZH.md');
}

// 16
{
 const s=slide('附錄：相同硬體，調度方式會改變供料效率','E2｜先看均勻需求：共享是否值得支付額外移動與交通成本？',
 'E2uniform：N2/4/8、32m、read8、B4。Policy zone/fifo/lookahead由相同geometry與resource rules比較。Lookahead是16個候選加120秒aging的簡單基準，不宣稱新方法。曲線來自full matrix，不挑seed。','APPENDIX / E2 調度比較');
 line(s,Object.keys(labels).map(p=>({name:labels[p],rows:sort(get({experiment:'E2',pattern:'uniform',policy:p}),'shuttles'),color:colors[p]})),'throughput_req_s_mean','shuttles',.75,2.12,8.0,4.25,60);
 item(s,'觀察','看完成，不只看忙碌','車在移動或等待路段，\n都不等於正在產生讀取成果。',9.15,2.65,3.45);
 footer(s,'Y：Read completions / min；X：Shuttles / reader。32 m · read=8 s · B=4 · 均值，SD 保留在 CSV。');
}
// 17
{
 const s=slide('附錄：工作集中時，固定分區的代價也會浮現','E2｜75% requests 位於兩條 rack rows；測試忙閒不均的控制場景。',
 '此hotspot是人為診斷場景，非Azure實測分布；Zone的row0/1在N4由同一owner負責，在N8由兩owner負責。N變化也會改變hotspot對owner的集中程度，不能把所有差異只歸因機器人數量。需與uniform同時解讀。','APPENDIX / E2 調度比較');
 line(s,Object.keys(labels).map(p=>({name:labels[p],rows:sort(get({experiment:'E2',pattern:'hotspot',policy:p}),'shuttles'),color:colors[p]})),'throughput_req_s_mean','shuttles',.75,2.12,8.0,4.25,60);
 item(s,'取捨','共享的合理動機','閒置能力是否值得跨區支援？\n取決於收益能否超過協調成本。',9.15,2.65,3.45);
 footer(s,'與前頁硬體與讀取時間相同；只改 address 分布。此場景證明機制，不代表真實頻率。');
}
// 18
{
 const s=slide('附錄：增加 Shuttle，也可能增加協調負擔','E2｜路段等待與 controller 的候選評估量，必須和吞吐量一起看。',
 '數據E2uniform。Traffic wait是所有shuttle累計等待除requests，不是使用者latency。Candidate evaluations是對request-shuttle pair評估次數，不是硬體clock cycles或real controller latency。若吞吐量未下降，不能把更多trafficwait誇大成more robots always worse。','APPENDIX / E2 調度比較');
 ['traffic_wait_s_mean','pair_evaluations_mean'].forEach((metric,i)=>{const groups=Object.keys(labels).map(p=>({name:labels[p],rows:sort(get({experiment:'E2',pattern:'uniform',policy:p}),'shuttles').map(r=>({...r,normalized:r[metric]/r.requests_mean})),color:colors[p]}));text(s,i?'候選配對評估 / request':'路段等待 shuttle-s / request',.85+i*6.3,2.1,5.9,.35,18,C.zone,{bold:true});line(s,groups,'normalized','shuttles',.65+i*6.3,2.55,6.1,3.65);});
 footer(s,'Zone 減少 eligible pair，不代表省去共用入口的交通管理；controller 指標為模擬器工作量。');
}

async function main(){
 const out=path.join(root,'results/presentations');
 fs.mkdirSync(out,{recursive:true});
 const filename=path.join(out,'glint_partition_feeder_story_zh.pptx');
 await pptx.writeFile({fileName:filename});
 fs.writeFileSync(path.join(resultDir,'STORYLINE_ZH.md'),'# 簡報故事線與講者備註\n\n'+slideNotes.map((s,i)=>`## ${i+1}. ${s.title}\n\n${s.notes}\n`).join('\n'));
 console.log(`${slideNotes.length} slides: ${filename}`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
