// Install outside the repository and expose with NODE_PATH to keep the Python
// experiment package free of presentation-only dependencies.
// npm install --prefix /tmp/glint-pptx-runtime pptxgenjs
// NODE_PATH=/tmp/glint-pptx-runtime/node_modules node scripts/build_capacity_zoning_discussion_pptx.js
const pptxgen = require("pptxgenjs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(
  ROOT,
  "results/capacity-scalability/glint_capacity_zoning_discussion.pptx"
);
const FIG_THROUGHPUT = path.join(
  ROOT,
  "results/capacity-scalability/figures/fig1_capacity_scaling_performance.png"
);
const FIG_BREAKDOWN = path.join(
  ROOT,
  "results/capacity-scalability/figures/fig3_time_breakdown.png"
);

const C = {
  night: "111B22",
  ink: "16232C",
  muted: "5F707C",
  faint: "8796A1",
  line: "D8E1E6",
  pale: "F4F7F8",
  white: "FFFFFF",
  cyan: "218C99",
  cyanPale: "DCEFF1",
  blue: "3979A8",
  bluePale: "E4EEF5",
  orange: "D96C35",
  orangePale: "F8E6DC",
  green: "4C9560",
  greenPale: "E2F0E5",
  red: "C64F55",
  redPale: "F7E3E4",
  gray: "7F8A94",
};

let pptx;

function addTitle(slide, title, kicker, dark = false) {
  slide.addText(kicker.toUpperCase(), {
    x: 0.68,
    y: 0.35,
    w: 4.9,
    h: 0.22,
    fontFace: "Calibri",
    fontSize: 10,
    bold: true,
    charSpacing: 1.1,
    color: dark ? "7AD1D8" : C.cyan,
    margin: 0,
  });
  slide.addText(title, {
    x: 0.68,
    y: 0.70,
    w: 11.85,
    h: 0.72,
    fontFace: "Cambria",
    fontSize: 30,
    bold: true,
    color: dark ? C.white : C.ink,
    margin: 0,
    fit: "shrink",
  });
}

function addFooter(slide, page, text, dark = false) {
  slide.addText(text, {
    x: 0.68,
    y: 7.03,
    w: 10.9,
    h: 0.20,
    fontFace: "Calibri",
    fontSize: 8.5,
    color: dark ? "94A8B3" : C.faint,
    margin: 0,
    fit: "shrink",
  });
  slide.addText(String(page).padStart(2, "0"), {
    x: 12.17,
    y: 7.03,
    w: 0.45,
    h: 0.20,
    fontFace: "Calibri",
    fontSize: 8.5,
    color: dark ? "94A8B3" : C.faint,
    align: "right",
    margin: 0,
  });
}

function addBullet(slide, text, x, y, w, opts = {}) {
  slide.addText(text, {
    x,
    y,
    w,
    h: opts.h || 0.48,
    fontFace: "Calibri",
    fontSize: opts.fontSize || 18,
    color: opts.color || C.ink,
    bold: opts.bold || false,
    margin: 0,
    bullet: { indent: 18 },
    hanging: 4,
    breakLine: false,
    fit: "shrink",
  });
}

function addTag(slide, text, x, y, tone, pale) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w: 1.95,
    h: 0.34,
    rectRadius: 0.03,
    fill: { color: pale },
    line: { color: tone, width: 0.8 },
  });
  slide.addText(text.toUpperCase(), {
    x: x + 0.10,
    y: y + 0.09,
    w: 1.75,
    h: 0.15,
    fontFace: "Calibri",
    fontSize: 8.5,
    bold: true,
    color: tone,
    align: "center",
    margin: 0,
    fit: "shrink",
  });
}

function addArrow(slide, x, y, w, color = C.gray) {
  slide.addShape(pptx.ShapeType.chevron, {
    x,
    y,
    w,
    h: 0.30,
    fill: { color },
    line: { color },
  });
}

function addDrive(slide, x, y, label) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w: 1.12,
    h: 1.34,
    rectRadius: 0.04,
    fill: { color: C.bluePale },
    line: { color: C.blue, width: 1.1 },
  });
  slide.addShape(pptx.ShapeType.ellipse, {
    x: x + 0.38,
    y: y + 0.23,
    w: 0.36,
    h: 0.36,
    fill: { color: C.blue },
    line: { color: C.blue },
  });
  slide.addText(label, {
    x: x + 0.12,
    y: y + 0.83,
    w: 0.88,
    h: 0.25,
    fontFace: "Calibri",
    fontSize: 11,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
}

function addPlatter(slide, x, y, w = 0.34, h = 0.90) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.025,
    fill: { color: C.cyanPale, transparency: 8 },
    line: { color: C.cyan, width: 0.9 },
  });
}

function contain(imagePath, x, y, w, h, ratio) {
  const boxRatio = w / h;
  if (ratio > boxRatio) {
    const hh = w / ratio;
    return { path: imagePath, x, y: y + (h - hh) / 2, w, h: hh };
  }
  const ww = h * ratio;
  return { path: imagePath, x: x + (w - ww) / 2, y, w: ww, h };
}

function addSource(slide, text) {
  slide.addText(text, {
    x: 8.15,
    y: 6.72,
    w: 4.40,
    h: 0.20,
    fontFace: "Calibri",
    fontSize: 7.5,
    color: C.faint,
    align: "right",
    margin: 0,
    fit: "shrink",
  });
}

function addLane(slide, x, y, w, tone) {
  slide.addShape(pptx.ShapeType.line, {
    x,
    y,
    w,
    h: 0,
    line: { color: tone, width: 2 },
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: x + 0.28,
    y: y - 0.12,
    w: 0.32,
    h: 0.24,
    rectRadius: 0.025,
    fill: { color: tone },
    line: { color: tone },
  });
}

async function build() {
  pptx = new pptxgen();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "GLINT Glass Storage Research";
  pptx.company = "GLINT";
  pptx.subject = "Capacity scalability and shuttle zoning in glass storage";
  pptx.title = "Capacity Scalability and the Operating Region of Shuttle Zoning";
  pptx.lang = "en-US";
  pptx.theme = {
    headFontFace: "Cambria",
    bodyFontFace: "Calibri",
    lang: "en-US",
  };

  // 1. Opening tension
  const s1 = pptx.addSlide();
  s1.background = { color: C.night };
  s1.addText("CAPACITY SCALABILITY IN GLASS STORAGE", {
    x: 0.72, y: 0.62, w: 5.6, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, charSpacing: 1.2,
    color: "78D0D8", margin: 0,
  });
  s1.addText("More glass does not mean\nmore service bandwidth", {
    x: 0.72, y: 1.20, w: 7.15, h: 1.55,
    fontFace: "Cambria", fontSize: 37, bold: true,
    color: C.white, margin: 0, fit: "shrink",
  });
  s1.addText("Passive capacity can grow while readers and shuttles remain fixed.", {
    x: 0.75, y: 3.05, w: 6.4, h: 0.64,
    fontFace: "Calibri", fontSize: 21, color: "C4D1D8",
    margin: 0, fit: "shrink",
  });
  s1.addText("DISK SCALE-OUT", {
    x: 8.05, y: 0.92, w: 2.2, h: 0.22,
    fontFace: "Calibri", fontSize: 10, bold: true, color: "AEBEC7", margin: 0,
  });
  addDrive(s1, 8.05, 1.28, "capacity + I/O");
  addDrive(s1, 9.42, 1.28, "capacity + I/O");
  addDrive(s1, 10.79, 1.28, "capacity + I/O");
  s1.addText("GLASS SCALE-OUT", {
    x: 8.05, y: 3.14, w: 2.2, h: 0.22,
    fontFace: "Calibri", fontSize: 10, bold: true, color: "78D0D8", margin: 0,
  });
  addPlatter(s1, 8.05, 3.58);
  addPlatter(s1, 8.50, 3.66);
  addPlatter(s1, 8.95, 3.58);
  addPlatter(s1, 9.40, 3.66);
  addPlatter(s1, 9.85, 3.58);
  addPlatter(s1, 10.30, 3.66);
  addArrow(s1, 10.92, 3.88, 0.48, C.orange);
  s1.addShape(pptx.ShapeType.ellipse, {
    x: 11.62, y: 3.70, w: 0.64, h: 0.64,
    fill: { color: C.orange }, line: { color: C.orange },
  });
  s1.addText("R", {
    x: 11.62, y: 3.89, w: 0.64, h: 0.20,
    fontFace: "Calibri", fontSize: 14, bold: true,
    color: C.white, align: "center", margin: 0,
  });
  s1.addText("more media", {
    x: 8.05, y: 4.82, w: 2.2, h: 0.26,
    fontFace: "Calibri", fontSize: 15, bold: true, color: "78D0D8", margin: 0,
  });
  s1.addText("same active service", {
    x: 10.18, y: 4.82, w: 2.08, h: 0.26,
    fontFace: "Calibri", fontSize: 15, bold: true, color: "F3A37D", align: "right", margin: 0,
  });
  s1.addShape(pptx.ShapeType.roundRect, {
    x: 8.05, y: 5.55, w: 4.22, h: 0.76,
    rectRadius: 0.04, fill: { color: "1C2C35" }, line: { color: "39505D", width: 0.8 },
  });
  s1.addText("Old intuition: capacity ↑ ⇒ throughput ↑\nGlass reality: capacity ↑, service resources unchanged", {
    x: 8.30, y: 5.72, w: 3.72, h: 0.40,
    fontFace: "Calibri", fontSize: 13.5, bold: true,
    color: C.white, margin: 0, fit: "shrink",
  });
  addFooter(s1, 1, "Opening claim: glass decouples passive capacity from active service resources.", true);
  s1.addNotes(`
這一頁不要重新介紹 Glass Library，而是直接推翻舊直覺。傳統 disk scale-out 雖然不一定線性成長，但新增裝置通常會帶來新的 I/O endpoint。Glass platter 是 passive media，新增容量不會自動增加 reader 或 shuttle。接下來要問的是：這種 capacity-service decoupling 會造成什麼效能結果？
  `);

  // 2. Fixed-resource framing
  const s2 = pptx.addSlide();
  s2.background = { color: C.white };
  addTitle(s2, "Scale passive capacity; hold active hardware fixed", "Research scope");
  s2.addShape(pptx.ShapeType.roundRect, {
    x: 0.72, y: 1.58, w: 5.65, h: 4.65,
    rectRadius: 0.05, fill: { color: C.cyanPale }, line: { color: C.cyan, width: 1 },
  });
  s2.addText("WHAT SCALES", {
    x: 1.08, y: 1.93, w: 2.0, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.cyan, margin: 0,
  });
  s2.addText("1× → 32×", {
    x: 1.08, y: 2.40, w: 3.8, h: 0.64,
    fontFace: "Cambria", fontSize: 35, bold: true, color: C.ink, margin: 0,
  });
  addBullet(s2, "Glass platters and storage slots", 1.08, 3.35, 4.5);
  addBullet(s2, "Storage-rack footprint", 1.08, 4.05, 4.5);
  addBullet(s2, "Physical access range", 1.08, 4.75, 4.5);
  s2.addShape(pptx.ShapeType.roundRect, {
    x: 6.85, y: 1.58, w: 5.65, h: 4.65,
    rectRadius: 0.05, fill: { color: C.orangePale }, line: { color: C.orange, width: 1 },
  });
  s2.addText("WHAT REMAINS FIXED", {
    x: 7.21, y: 1.93, w: 2.7, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.orange, margin: 0,
  });
  s2.addText("8 readers + 8 shuttles", {
    x: 7.21, y: 2.40, w: 4.5, h: 0.64,
    fontFace: "Cambria", fontSize: 30, bold: true, color: C.ink, margin: 0, fit: "shrink",
  });
  addBullet(s2, "Reader throughput", 7.21, 3.35, 4.5);
  addBullet(s2, "Logical and physical work", 7.21, 4.05, 4.5);
  addBullet(s2, "Hardware provisioning", 7.21, 4.75, 4.5);
  s2.addText("We do not optimize the reader/shuttle ratio in this study.", {
    x: 3.00, y: 6.47, w: 7.30, h: 0.32,
    fontFace: "Calibri", fontSize: 15, bold: true,
    color: C.muted, align: "center", margin: 0,
  });
  addFooter(s2, 2, "Goal: characterize performance degradation before proposing a movement-management design.");
  s2.addNotes(`
研究範圍先固定 active hardware。我們不是要找最佳 reader/shuttle 配比，也不是用增加硬體解決問題。唯一擴充的是 passive capacity、slots 與 physical range。這能讓後續 throughput degradation 明確歸因到容量擴張下的服務成本。
  `);

  // 3. Causal mechanism
  const s3 = pptx.addSlide();
  s3.background = { color: C.pale };
  addTitle(s3, "Capacity affects performance only when accesses span the enlarged library", "Causal mechanism");
  const stages = [
    { x: 0.78, title: "More capacity", body: "More available\nstorage locations", tone: C.cyan, pale: C.cyanPale },
    { x: 3.78, title: "Longer reach", body: "Requested platters\ncan be farther away", tone: C.blue, pale: C.bluePale },
    { x: 6.78, title: "More movement", body: "Fetch and return\ncycles get longer", tone: C.orange, pale: C.orangePale },
    { x: 9.78, title: "Lower throughput", body: "The same batch\ndrains later", tone: C.red, pale: C.redPale },
  ];
  stages.forEach((stage, index) => {
    s3.addShape(pptx.ShapeType.roundRect, {
      x: stage.x, y: 2.02, w: 2.35, h: 2.52,
      rectRadius: 0.04, fill: { color: stage.pale }, line: { color: stage.tone, width: 1 },
    });
    s3.addShape(pptx.ShapeType.ellipse, {
      x: stage.x + 0.90, y: 2.35, w: 0.54, h: 0.54,
      fill: { color: stage.tone }, line: { color: stage.tone },
    });
    s3.addText(String(index + 1), {
      x: stage.x + 0.90, y: 2.51, w: 0.54, h: 0.18,
      fontFace: "Calibri", fontSize: 12, bold: true,
      color: C.white, align: "center", margin: 0,
    });
    s3.addText(stage.title, {
      x: stage.x + 0.20, y: 3.10, w: 1.95, h: 0.34,
      fontFace: "Cambria", fontSize: 19, bold: true,
      color: C.ink, align: "center", margin: 0, fit: "shrink",
    });
    s3.addText(stage.body, {
      x: stage.x + 0.20, y: 3.60, w: 1.95, h: 0.58,
      fontFace: "Calibri", fontSize: 14, color: C.muted,
      align: "center", margin: 0, fit: "shrink",
    });
    if (index < 3) addArrow(s3, stage.x + 2.52, 3.10, 0.38, C.gray);
  });
  s3.addShape(pptx.ShapeType.roundRect, {
    x: 1.64, y: 5.25, w: 10.05, h: 0.86,
    rectRadius: 0.04, fill: { color: C.white }, line: { color: C.line, width: 0.9 },
  });
  s3.addText("Important condition", {
    x: 1.95, y: 5.51, w: 1.70, h: 0.24,
    fontFace: "Calibri", fontSize: 13, bold: true, color: C.orange, margin: 0,
  });
  s3.addText("If newly added capacity is cold and all requested platters remain nearby, capacity growth need not reduce throughput.", {
    x: 3.62, y: 5.42, w: 7.65, h: 0.40,
    fontFace: "Calibri", fontSize: 15, color: C.ink, margin: 0, fit: "shrink",
  });
  addFooter(s3, 3, "The pilot studies capacity-proportional physical access, not every possible placement or workload.");
  s3.addNotes(`
這一頁把 capacity 和 throughput 的因果條件講清楚。不是 platter count 本身讓 throughput 下降，而是 request 所觸及的 physical range 隨容量擴張。若新增容量完全是 cold data，結果可能不同。這個限制應該主動說明，避免把條件式 observation 說成普遍定律。
  `);

  // 4. Experiment setup
  const s4 = pptx.addSlide();
  s4.background = { color: C.white };
  addTitle(s4, "The pilot changes capacity while preserving the work", "Controlled experiment");
  addTag(s4, "Pilot simulation", 10.38, 0.38, C.green, C.greenPale);
  const rows = [
    ["Readers / shuttles", "8 / 8", "Fixed"],
    ["Physical platter tasks", "640", "Fixed"],
    ["Request size", "64 MiB", "Fixed"],
    ["Random seeds", "10 paired runs", "Fixed"],
    ["Capacity scale", "1×, 2×, 4×, 8×, 16×, 32×", "Scaled"],
  ];
  rows.forEach((row, index) => {
    const y = 1.62 + index * 0.83;
    s4.addShape(pptx.ShapeType.line, {
      x: 0.82, y: y + 0.64, w: 7.0, h: 0,
      line: { color: C.line, width: 0.7 },
    });
    s4.addText(row[0], {
      x: 0.84, y, w: 2.85, h: 0.34,
      fontFace: "Calibri", fontSize: 16, color: C.muted, margin: 0,
    });
    s4.addText(row[1], {
      x: 3.83, y, w: 3.05, h: 0.34,
      fontFace: "Calibri", fontSize: 16, bold: true, color: C.ink, margin: 0, fit: "shrink",
    });
    s4.addText(row[2].toUpperCase(), {
      x: 6.90, y: y + 0.01, w: 0.82, h: 0.22,
      fontFace: "Calibri", fontSize: 8.5, bold: true,
      color: row[2] === "Fixed" ? C.orange : C.cyan, align: "right", margin: 0,
    });
  });
  s4.addShape(pptx.ShapeType.roundRect, {
    x: 8.35, y: 1.62, w: 4.20, h: 4.62,
    rectRadius: 0.05, fill: { color: C.pale }, line: { color: C.line, width: 0.9 },
  });
  s4.addText("Model boundary", {
    x: 8.73, y: 1.98, w: 2.5, h: 0.32,
    fontFace: "Cambria", fontSize: 20, bold: true, color: C.ink, margin: 0,
  });
  addBullet(s4, "Direct fetch–read–return cycle", 8.73, 2.70, 3.15, { fontSize: 15 });
  addBullet(s4, "No prefetch or reader staging", 8.73, 3.42, 3.15, { fontSize: 15 });
  addBullet(s4, "No multi-shuttle collision model", 8.73, 4.14, 3.15, { fontSize: 15 });
  addBullet(s4, "Paired normalized locations", 8.73, 4.86, 3.15, { fontSize: 15 });
  s4.addText("Use this as mechanism evidence, not a production forecast.", {
    x: 8.73, y: 5.61, w: 3.20, h: 0.40,
    fontFace: "Calibri", fontSize: 13.5, bold: true, color: C.orange, margin: 0, fit: "shrink",
  });
  addFooter(s4, 4, "All capacity points use the same logical and physical work.");
  s4.addNotes(`
這頁是教授最容易檢查實驗是否公平的地方。所有 capacity points 都使用同樣的 640 個 tasks、相同 request size、相同 active resources 與 paired seeds。也要清楚說明目前沒有 prefetch、staging 與 collision，因此結果是 mechanism pilot，不代表真實 production Silica 的精確數字。
  `);

  // 5. Throughput result
  const s5 = pptx.addSlide();
  s5.background = { color: C.white };
  addTitle(s5, "The same batch loses throughput as the access range expands", "Observation 1");
  addTag(s5, "Measured result", 10.38, 0.38, C.green, C.greenPale);
  s5.addImage(contain(FIG_THROUGHPUT, 0.70, 1.47, 8.85, 4.95, 3060 / 1170));
  s5.addShape(pptx.ShapeType.roundRect, {
    x: 9.75, y: 1.67, w: 2.65, h: 1.32,
    rectRadius: 0.04, fill: { color: C.orangePale }, line: { color: C.orange, width: 1 },
  });
  s5.addText("35.3%", {
    x: 10.02, y: 1.95, w: 2.10, h: 0.50,
    fontFace: "Cambria", fontSize: 29, bold: true,
    color: C.orange, align: "center", margin: 0,
  });
  s5.addText("throughput retained at 32×", {
    x: 10.02, y: 2.48, w: 2.10, h: 0.24,
    fontFace: "Calibri", fontSize: 11, color: C.muted, align: "center", margin: 0,
  });
  addBullet(s5, "Request count and bytes are unchanged", 9.82, 3.45, 2.45, { fontSize: 15, h: 0.62 });
  addBullet(s5, "Reader and shuttle counts are unchanged", 9.82, 4.28, 2.45, { fontSize: 15, h: 0.62 });
  addBullet(s5, "Batch completion increases from 30.8 to 87.2 min", 9.82, 5.11, 2.45, { fontSize: 15, h: 0.72 });
  addFooter(s5, 5, "Result: capacity-proportional access turns the same work into a longer batch.");
  addSource(s5, "Source: GLINT capacity-scalability pilot, 10 paired seeds.");
  s5.addNotes(`
這一頁只講現象，不急著談 zone。相同 batch 在 32× capacity 只保留約 35.3% throughput。因為 requests 和硬體都固定，所以 throughput loss 必須來自每次 service cycle 的時間增加。下一頁再分解原因。
  `);

  // 6. Time breakdown
  const s6 = pptx.addSlide();
  s6.background = { color: C.white };
  addTitle(s6, "Movement—not reader work—is the growing component", "Observation 2");
  addTag(s6, "Measured result", 10.38, 0.38, C.green, C.greenPale);
  s6.addImage(contain(FIG_BREAKDOWN, 0.64, 1.43, 9.20, 5.15, 3060 / 1230));
  s6.addShape(pptx.ShapeType.roundRect, {
    x: 10.03, y: 1.70, w: 2.40, h: 4.57,
    rectRadius: 0.05, fill: { color: C.pale }, line: { color: C.line, width: 0.9 },
  });
  s6.addText("1× → 32×", {
    x: 10.35, y: 2.02, w: 1.76, h: 0.32,
    fontFace: "Calibri", fontSize: 14, bold: true, color: C.muted, align: "center", margin: 0,
  });
  s6.addText("Movement", {
    x: 10.35, y: 2.62, w: 1.76, h: 0.30,
    fontFace: "Calibri", fontSize: 13, color: C.blue, align: "center", margin: 0,
  });
  s6.addText("8.53 → 50.39 s", {
    x: 10.25, y: 3.00, w: 1.96, h: 0.40,
    fontFace: "Cambria", fontSize: 20, bold: true, color: C.blue, align: "center", margin: 0,
  });
  s6.addShape(pptx.ShapeType.line, {
    x: 10.40, y: 3.62, w: 1.66, h: 0, line: { color: C.line, width: 0.8 },
  });
  s6.addText("Reader total", {
    x: 10.35, y: 3.92, w: 1.76, h: 0.30,
    fontFace: "Calibri", fontSize: 13, color: C.orange, align: "center", margin: 0,
  });
  s6.addText("35.7% → 12.5%", {
    x: 10.25, y: 4.31, w: 1.96, h: 0.40,
    fontFace: "Cambria", fontSize: 20, bold: true, color: C.orange, align: "center", margin: 0,
  });
  s6.addText("The reader is not slower. More of every cycle is spent moving media.", {
    x: 10.31, y: 5.14, w: 1.84, h: 0.68,
    fontFace: "Calibri", fontSize: 13.5, bold: true,
    color: C.ink, align: "center", margin: 0, fit: "shrink",
  });
  addFooter(s6, 6, "Movement grows from 37.7% to 78.2% of the platter cycle.");
  addSource(s6, "Assumption: fixed 64 MiB request; read time varies with request size.");
  s6.addNotes(`
這張圖解釋 throughput loss。Reader read、load/unload 和 platter pick/place 都固定，只有 shuttle movement 從 8.53 秒增加到 50.39 秒。系統不是 reader 變慢，而是每個 cycle 花在 reader 的比例越來越低。這一步只帶出 movement management 重要，還不能直接推論 zone 必要。
  `);

  // 7. Long movement vs conflict
  const s7 = pptx.addSlide();
  s7.background = { color: C.pale };
  addTitle(s7, "Long movement does not automatically imply that zoning is needed", "Logical checkpoint");
  s7.addShape(pptx.ShapeType.roundRect, {
    x: 0.78, y: 1.72, w: 5.70, h: 4.55,
    rectRadius: 0.05, fill: { color: C.white }, line: { color: C.line, width: 0.9 },
  });
  s7.addText("LONG BUT CONFLICT-FREE", {
    x: 1.15, y: 2.08, w: 2.8, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.cyan, margin: 0,
  });
  addLane(s7, 1.20, 3.25, 4.70, C.cyan);
  s7.addText("Movement latency", {
    x: 1.20, y: 4.08, w: 4.70, h: 0.38,
    fontFace: "Cambria", fontSize: 22, bold: true, color: C.ink, align: "center", margin: 0,
  });
  s7.addText("One shuttle can travel far without blocking another shuttle.", {
    x: 1.35, y: 4.72, w: 4.40, h: 0.56,
    fontFace: "Calibri", fontSize: 16, color: C.muted, align: "center", margin: 0, fit: "shrink",
  });
  s7.addShape(pptx.ShapeType.roundRect, {
    x: 6.85, y: 1.72, w: 5.70, h: 4.55,
    rectRadius: 0.05, fill: { color: C.white }, line: { color: C.line, width: 0.9 },
  });
  s7.addText("OVERLAPPING PATHS", {
    x: 7.22, y: 2.08, w: 2.8, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.red, margin: 0,
  });
  addLane(s7, 7.35, 3.00, 4.55, C.red);
  addLane(s7, 7.35, 3.50, 4.55, C.orange);
  s7.addShape(pptx.ShapeType.ellipse, {
    x: 9.40, y: 3.04, w: 0.64, h: 0.64,
    fill: { color: C.red }, line: { color: C.red },
  });
  s7.addText("!", {
    x: 9.40, y: 3.21, w: 0.64, h: 0.20,
    fontFace: "Calibri", fontSize: 15, bold: true, color: C.white, align: "center", margin: 0,
  });
  s7.addText("Traffic congestion", {
    x: 7.35, y: 4.08, w: 4.55, h: 0.38,
    fontFace: "Cambria", fontSize: 22, bold: true, color: C.ink, align: "center", margin: 0,
  });
  s7.addText("Zoning addresses shuttle interactions—not physical distance by itself.", {
    x: 7.50, y: 4.72, w: 4.25, h: 0.56,
    fontFace: "Calibri", fontSize: 16, color: C.muted, align: "center", margin: 0, fit: "shrink",
  });
  addTag(s7, "Hypothesis", 5.69, 6.43, C.orange, C.orangePale);
  addFooter(s7, 7, "Next question: does scaling create enough shuttle interaction to justify spatial isolation?");
  s7.addNotes(`
這一頁防止邏輯跳躍。長距離 movement 只代表 latency 增加，不代表一定發生 congestion。Zone 解決的是多 shuttle 互相阻擋與 traffic-management complexity，而不是距離本身。因此下一步必須建立 collision-free traffic model，才能判斷 zone 是否真正有價值。
  `);

  // 8. Zone-effective scenario
  const s8 = pptx.addSlide();
  s8.background = { color: C.white };
  addTitle(s8, "Zoning is effective when traffic is dense and work is balanced", "Zone-beneficial scenario");
  addTag(s8, "Hypothesis", 10.38, 0.38, C.orange, C.orangePale);
  s8.addShape(pptx.ShapeType.roundRect, {
    x: 0.78, y: 1.58, w: 6.25, h: 4.88,
    rectRadius: 0.05, fill: { color: C.greenPale }, line: { color: C.green, width: 1 },
  });
  for (let i = 0; i < 4; i++) {
    const y = 1.92 + i * 1.05;
    s8.addShape(pptx.ShapeType.roundRect, {
      x: 1.15, y, w: 5.50, h: 0.77,
      rectRadius: 0.03, fill: { color: C.white }, line: { color: "B7D5BE", width: 0.7 },
    });
    addLane(s8, 1.48, y + 0.39, 4.76, C.green);
  }
  s8.addText("Independent traffic domains", {
    x: 1.48, y: 6.02, w: 4.76, h: 0.28,
    fontFace: "Calibri", fontSize: 14, bold: true, color: C.green, align: "center", margin: 0,
  });
  s8.addText("ZONE-FRIENDLY CONDITIONS", {
    x: 7.63, y: 1.76, w: 3.1, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.green, margin: 0,
  });
  addBullet(s8, "Many shuttles move concurrently", 7.63, 2.34, 4.15, { fontSize: 18 });
  addBullet(s8, "Paths compete for shared rails or readers", 7.63, 3.12, 4.15, { fontSize: 18, h: 0.60 });
  addBullet(s8, "Post-merge work is spatially balanced", 7.63, 4.02, 4.15, { fontSize: 18, h: 0.60 });
  addBullet(s8, "Predictable tail latency matters", 7.63, 4.92, 4.15, { fontSize: 18 });
  s8.addText("Expected benefit", {
    x: 7.63, y: 5.67, w: 1.65, h: 0.25,
    fontFace: "Calibri", fontSize: 12, bold: true, color: C.muted, margin: 0,
  });
  s8.addText("less blocking + simpler traffic control", {
    x: 9.11, y: 5.63, w: 2.75, h: 0.32,
    fontFace: "Calibri", fontSize: 14.5, bold: true, color: C.green, margin: 0, fit: "shrink",
  });
  addFooter(s8, 8, "Zone benefit comes from avoiding congestion while keeping all partitions useful.");
  addSource(s8, "Prior evidence: Project Silica, SOSP 2023, §7.5.");
  s8.addNotes(`
Zone 最適合的場景是 traffic 很密集，同時 workload 又能平均落在各區。這時 spatial isolation 能減少 blocking，且不會留下大量 idle resources。這是我們預期的 zone-beneficial region，但在目前 simulator 尚未有 collision model，所以先標成 hypothesis。
  `);

  // 9. Zone-harmful scenario
  const s9 = pptx.addSlide();
  s9.background = { color: C.pale };
  addTitle(s9, "Static zoning becomes costly when demand and boundaries diverge", "Zone-harmful scenario");
  addTag(s9, "Mechanism", 10.38, 0.38, C.orange, C.orangePale);
  s9.addText("POST-MERGE WORK BY ZONE", {
    x: 0.82, y: 1.58, w: 3.3, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.muted, margin: 0,
  });
  const heights = [3.55, 0.78, 0.74, 0.72, 0.68, 0.65, 0.62, 0.60];
  heights.forEach((height, index) => {
    const x = 0.92 + index * 0.70;
    s9.addShape(pptx.ShapeType.rect, {
      x, y: 5.74 - height, w: 0.46, h: height,
      fill: { color: index === 0 ? C.red : C.gray },
      line: { color: index === 0 ? C.red : C.gray },
    });
    s9.addText(`Z${index}`, {
      x: x - 0.02, y: 5.87, w: 0.50, h: 0.22,
      fontFace: "Calibri", fontSize: 10, color: C.muted, align: "center", margin: 0,
    });
  });
  s9.addShape(pptx.ShapeType.line, {
    x: 0.82, y: 5.74, w: 5.55, h: 0, line: { color: C.line, width: 1 },
  });
  s9.addText("one owner remains busy", {
    x: 0.88, y: 1.84, w: 1.95, h: 0.26,
    fontFace: "Calibri", fontSize: 12, bold: true, color: C.red, align: "center", margin: 0,
  });
  s9.addText("seven owners become idle", {
    x: 3.10, y: 4.62, w: 2.90, h: 0.26,
    fontFace: "Calibri", fontSize: 12, bold: true, color: C.gray, align: "center", margin: 0,
  });
  s9.addShape(pptx.ShapeType.roundRect, {
    x: 7.00, y: 1.58, w: 5.36, h: 4.74,
    rectRadius: 0.05, fill: { color: C.white }, line: { color: C.line, width: 0.9 },
  });
  s9.addText("ZONE-UNFRIENDLY CONDITIONS", {
    x: 7.42, y: 1.96, w: 3.45, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.red, margin: 0,
  });
  addBullet(s9, "Shuttle traffic is naturally sparse", 7.42, 2.56, 4.10, { fontSize: 17 });
  addBullet(s9, "Requests concentrate in a few zones", 7.42, 3.33, 4.10, { fontSize: 17 });
  addBullet(s9, "Hot regions move over time", 7.42, 4.10, 4.10, { fontSize: 17 });
  addBullet(s9, "Idle resources cannot help busy owners", 7.42, 4.87, 4.10, { fontSize: 17 });
  s9.addText("Expected cost: stranded capacity and a longer batch tail", {
    x: 7.42, y: 5.66, w: 4.10, h: 0.36,
    fontFace: "Calibri", fontSize: 14.5, bold: true, color: C.red, margin: 0, fit: "shrink",
  });
  addFooter(s9, 9, "Static ownership is useful only when its traffic benefit exceeds its resource-fragmentation cost.");
  s9.addNotes(`
Static zone 的代價是 ownership fragmentation。只要 request 分布和 boundary 不一致，一個 owner 可能持續忙碌，其他資源卻無法幫忙。這頁不要宣稱某一個 skew threshold 已經確定，只呈現我們已經理解的 causal mechanism，下一步再找 crossover。
  `);

  // 10. Opposing effects of capacity
  const s10 = pptx.addSlide();
  s10.background = { color: C.white };
  addTitle(s10, "Capacity growth can make zoning less necessary—or more necessary", "Unresolved relationship");
  addTag(s10, "Experiment needed", 10.18, 0.38, C.red, C.redPale);
  s10.addShape(pptx.ShapeType.roundRect, {
    x: 0.78, y: 1.72, w: 5.70, h: 4.64,
    rectRadius: 0.05, fill: { color: C.cyanPale }, line: { color: C.cyan, width: 1 },
  });
  s10.addText("SPATIAL DILUTION", {
    x: 1.18, y: 2.10, w: 2.5, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.cyan, margin: 0,
  });
  s10.addText("Larger area", {
    x: 1.18, y: 2.72, w: 4.85, h: 0.34,
    fontFace: "Cambria", fontSize: 22, bold: true, color: C.ink, align: "center", margin: 0,
  });
  s10.addText("↓", {
    x: 3.20, y: 3.20, w: 0.85, h: 0.45,
    fontFace: "Calibri", fontSize: 25, bold: true, color: C.cyan, align: "center", margin: 0,
  });
  s10.addText("Lower shuttle density", {
    x: 1.18, y: 3.83, w: 4.85, h: 0.34,
    fontFace: "Cambria", fontSize: 22, bold: true, color: C.ink, align: "center", margin: 0,
  });
  s10.addText("Zone may matter less", {
    x: 1.18, y: 5.32, w: 4.85, h: 0.36,
    fontFace: "Calibri", fontSize: 19, bold: true, color: C.cyan, align: "center", margin: 0,
  });
  s10.addShape(pptx.ShapeType.roundRect, {
    x: 6.85, y: 1.72, w: 5.70, h: 4.64,
    rectRadius: 0.05, fill: { color: C.orangePale }, line: { color: C.orange, width: 1 },
  });
  s10.addText("LONGER ROUTE OCCUPANCY", {
    x: 7.25, y: 2.10, w: 3.5, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: C.orange, margin: 0,
  });
  s10.addText("Longer trips", {
    x: 7.25, y: 2.72, w: 4.85, h: 0.34,
    fontFace: "Cambria", fontSize: 22, bold: true, color: C.ink, align: "center", margin: 0,
  });
  s10.addText("↓", {
    x: 9.27, y: 3.20, w: 0.85, h: 0.45,
    fontFace: "Calibri", fontSize: 25, bold: true, color: C.orange, align: "center", margin: 0,
  });
  s10.addText("Paths remain active longer", {
    x: 7.25, y: 3.83, w: 4.85, h: 0.34,
    fontFace: "Cambria", fontSize: 22, bold: true, color: C.ink, align: "center", margin: 0,
  });
  s10.addText("Zone may matter more", {
    x: 7.25, y: 5.32, w: 4.85, h: 0.36,
    fontFace: "Calibri", fontSize: 19, bold: true, color: C.orange, align: "center", margin: 0,
  });
  s10.addText("Which effect dominates under fixed readers and shuttles?", {
    x: 2.65, y: 6.55, w: 8.05, h: 0.32,
    fontFace: "Calibri", fontSize: 17, bold: true, color: C.ink, align: "center", margin: 0,
  });
  addFooter(s10, 10, "Capacity is an amplifier; traffic concurrency and spatial demand determine the zoning outcome.");
  s10.addNotes(`
這是 capacity 和 zone 的真正橋接。固定 shuttle 數量下，面積變大會降低空間密度，可能減少 encounters；但更長的 trips 也讓 rails 被占用更久，reader 入口的共同瓶頸仍存在。因此 capacity 越大到底越需要 zone 或越不需要，不能先假設，必須實驗量測。
  `);

  // 11. Alternative to permanent zoning
  const s11 = pptx.addSlide();
  s11.background = { color: C.night };
  addTitle(s11, "Prevent interaction—or coordinate it?", "Possible research direction", true);
  addTag(s11, "Open question", 10.28, 0.38, C.orange, C.orangePale);

  s11.addShape(pptx.ShapeType.roundRect, {
    x: 0.78, y: 1.62, w: 5.72, h: 4.40,
    rectRadius: 0.04, fill: { color: "192B33" }, line: { color: "45606B", width: 0.9 },
  });
  s11.addText("STATIC ZONING", {
    x: 1.15, y: 1.98, w: 2.20, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: "7AD1D8", margin: 0,
  });
  s11.addText("Prevent interaction", {
    x: 1.15, y: 2.38, w: 4.92, h: 0.42,
    fontFace: "Cambria", fontSize: 25, bold: true, color: C.white, margin: 0,
  });
  for (let i = 0; i < 3; i++) {
    const y = 3.08 + i * 0.73;
    s11.addShape(pptx.ShapeType.roundRect, {
      x: 1.15, y, w: 4.92, h: 0.53,
      rectRadius: 0.025, fill: { color: "223943" }, line: { color: "47626D", width: 0.6 },
    });
    s11.addShape(pptx.ShapeType.line, {
      x: 1.45, y: y + 0.27, w: 4.30, h: 0,
      line: { color: C.cyan, width: 1.6 },
    });
    s11.addShape(pptx.ShapeType.roundRect, {
      x: 1.66 + i * 1.15, y: y + 0.15, w: 0.28, h: 0.24,
      rectRadius: 0.02, fill: { color: C.cyan }, line: { color: C.cyan },
    });
  }
  s11.addText("Simple and predictable", {
    x: 1.15, y: 5.37, w: 2.35, h: 0.27,
    fontFace: "Calibri", fontSize: 14, bold: true, color: "7AD1D8", margin: 0,
  });
  s11.addText("but idle resources cannot cross boundaries", {
    x: 3.45, y: 5.37, w: 2.62, h: 0.27,
    fontFace: "Calibri", fontSize: 13.5, color: "AFC0C9", align: "right", margin: 0, fit: "shrink",
  });

  s11.addShape(pptx.ShapeType.roundRect, {
    x: 6.84, y: 1.62, w: 5.72, h: 4.40,
    rectRadius: 0.04, fill: { color: "2A241F" }, line: { color: "76513E", width: 0.9 },
  });
  s11.addText("CONTROLLER COORDINATION", {
    x: 7.21, y: 1.98, w: 3.20, h: 0.24,
    fontFace: "Calibri", fontSize: 11, bold: true, color: "F3A37D", margin: 0,
  });
  s11.addText("Coordinate interaction", {
    x: 7.21, y: 2.38, w: 4.92, h: 0.42,
    fontFace: "Cambria", fontSize: 25, bold: true, color: C.white, margin: 0,
  });
  addLane(s11, 7.45, 3.35, 4.28, C.orange);
  addLane(s11, 7.45, 4.12, 4.28, C.red);
  s11.addShape(pptx.ShapeType.ellipse, {
    x: 9.50, y: 3.48, w: 0.60, h: 0.60,
    fill: { color: "382B24" }, line: { color: C.orange, width: 1.2 },
  });
  s11.addText("✓", {
    x: 9.50, y: 3.65, w: 0.60, h: 0.20,
    fontFace: "Calibri", fontSize: 14, bold: true, color: "F3A37D", align: "center", margin: 0,
  });
  s11.addText("Allow movement when paths do not conflict", {
    x: 7.48, y: 4.72, w: 4.38, h: 0.34,
    fontFace: "Calibri", fontSize: 15, bold: true, color: "F3A37D", align: "center", margin: 0,
  });
  s11.addText("More flexible", {
    x: 7.21, y: 5.37, w: 1.55, h: 0.27,
    fontFace: "Calibri", fontSize: 14, bold: true, color: "F3A37D", margin: 0,
  });
  s11.addText("but online scheduling has a cost", {
    x: 9.15, y: 5.37, w: 2.98, h: 0.27,
    fontFace: "Calibri", fontSize: 13.5, color: "C7B8B0", align: "right", margin: 0, fit: "shrink",
  });

  s11.addShape(pptx.ShapeType.roundRect, {
    x: 1.18, y: 6.28, w: 10.98, h: 0.65,
    rectRadius: 0.035, fill: { color: "20343D" }, line: { color: "55717C", width: 0.8 },
  });
  s11.addText("Can we keep movement conflict-free without permanent shuttle ownership?", {
    x: 1.48, y: 6.47, w: 10.38, h: 0.27,
    fontFace: "Cambria", fontSize: 18, bold: true, color: C.white, align: "center", margin: 0, fit: "shrink",
  });
  addFooter(s11, 11, "Research direction: preserve conflict avoidance while recovering resource flexibility.", true);
  s11.addNotes(`
這一頁提出一個新的研究方向。Static zone 是用永久限制移動來避免 shuttle interaction，優點是簡單、可預測，缺點是空閒資源不能跨區幫忙。另一個方向是讓 controller 只在路徑真正衝突時進行協調，沒有衝突時仍允許跨區服務。這不代表 controller 一定更好，因為即時 scheduling 也有計算與 traffic overhead。我們真正要問的是：能否在維持 conflict-free movement 的同時，避免 permanent ownership restriction？
  `);

  await pptx.writeFile({ fileName: OUT });
}

build().catch((error) => {
  console.error(error);
  process.exit(1);
});
