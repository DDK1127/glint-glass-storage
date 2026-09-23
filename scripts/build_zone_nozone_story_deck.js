const pptxgen = require('pptxgenjs');
const path = require('path');

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'GLINT Research';
pptx.subject = 'Static Zone and Greedy No-Zone characterization';
pptx.title = 'Static Zones or Free Shuttle Mobility?';
pptx.company = 'GLINT';
pptx.lang = 'en-US';
pptx.theme = {
  headFontFace: 'Cambria',
  bodyFontFace: 'Calibri',
  lang: 'en-US',
};
pptx.defineSlideMaster({
  title: 'CONTENT',
  background: { color: 'F7F9FA' },
  objects: [
    { text: { text: 'GLINT  /  GLASS STORAGE SCHEDULING', options: { x: 0.62, y: 0.22, w: 4.5, h: 0.2, fontFace: 'Calibri', fontSize: 9, bold: true, color: '60727A', margin: 0, charSpacing: 1.1 } } },
    { text: { text: ' ', options: { x: 12.1, y: 7.12, w: 0.5, h: 0.16, fontFace: 'Calibri', fontSize: 8, color: '7B878D', margin: 0, align: 'right' } } },
  ],
  slideNumber: { x: 12.25, y: 7.08, w: 0.35, h: 0.18, fontFace: 'Calibri', fontSize: 8, color: '7B878D', align: 'right', margin: 0 },
});

const C = {
  ink: '263238', muted: '60727A', light: 'F7F9FA', white: 'FFFFFF',
  line: 'D7E0E4', static: '667580', nozone: '2B819B', orange: 'D9A441',
  green: '4F8B57', red: 'B95C55', paleBlue: 'E8F2F5', paleOrange: 'F7EDDB',
  paleGreen: 'E9F2EA', paleGray: 'EDF1F3',
};

const root = path.resolve(__dirname, '..');
const img = (relative) => path.join(root, relative);
const output = path.join(root, 'results', 'presentations', 'glint_zone_nozone_story_en.pptx');

function title(slide, text, subtitle) {
  slide.addText(text, { x: 0.65, y: 0.55, w: 12.0, h: 0.52, fontFace: 'Cambria', fontSize: 28, bold: true, color: C.ink, margin: 0, breakLine: false, fit: 'shrink' });
  if (subtitle) slide.addText(subtitle, { x: 0.67, y: 1.13, w: 11.8, h: 0.35, fontFace: 'Calibri', fontSize: 14, color: C.muted, margin: 0, fit: 'shrink' });
}

function label(slide, text, x, y, w, color = C.muted) {
  slide.addText(text, { x, y, w, h: 0.26, fontFace: 'Calibri', fontSize: 10, bold: true, color, margin: 0, charSpacing: 0.8, fit: 'shrink' });
}

function panel(slide, x, y, w, h, fill = C.white, line = C.line) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.06, fill: { color: fill }, line: { color: line, width: 1 } });
}

function arrow(slide, x, y, w, color = C.muted) {
  slide.addShape(pptx.ShapeType.chevron, { x, y, w, h: 0.32, fill: { color }, line: { color }, transparency: 5 });
}

function fitImage(slide, file, x, y, w, h, ratio) {
  let iw = w;
  let ih = iw / ratio;
  if (ih > h) { ih = h; iw = ih * ratio; }
  slide.addImage({ path: file, x: x + (w - iw) / 2, y: y + (h - ih) / 2, w: iw, h: ih });
}

function bulletList(slide, items, x, y, w, h, size = 17, color = C.ink) {
  const runs = [];
  items.forEach((item, index) => runs.push({ text: item, options: { bullet: { indent: size }, breakLine: index < items.length - 1, paraSpaceAfterPt: 10 } }));
  slide.addText(runs, { x, y, w, h, fontFace: 'Calibri', fontSize: size, color, margin: 0.06, breakLine: false, valign: 'mid', fit: 'shrink' });
}

// 1. Title
{
  const s = pptx.addSlide();
  s.background = { color: C.ink };
  s.addText('STATIC ZONES OR\nFREE SHUTTLE MOBILITY?', { x: 0.72, y: 0.86, w: 7.3, h: 1.8, fontFace: 'Cambria', fontSize: 34, bold: true, color: C.white, margin: 0, breakLine: false, fit: 'shrink' });
  s.addText('Characterizing isolation, locality, and coordination in scalable glass storage', { x: 0.75, y: 2.92, w: 7.0, h: 0.7, fontFace: 'Calibri', fontSize: 18, color: 'C6D6DC', margin: 0, fit: 'shrink' });
  for (let i = 0; i < 8; i++) {
    const side = i < 4 ? 0 : 1;
    const row = i % 4;
    s.addShape(pptx.ShapeType.rect, { x: 8.55 + side * 1.75, y: 0.92 + row * 1.23, w: 1.45, h: 0.86, fill: { color: row === 1 && side === 0 ? C.orange : (side ? C.nozone : C.static), transparency: row === 1 && side === 0 ? 0 : 18 }, line: { color: 'D4E0E4', transparency: 55 } });
    s.addText(`Z${i}`, { x: 8.55 + side * 1.75, y: 1.18 + row * 1.23, w: 1.45, h: 0.2, fontFace: 'Calibri', fontSize: 12, bold: true, color: C.white, align: 'center', margin: 0 });
  }
  s.addText('Research discussion', { x: 0.75, y: 6.65, w: 2.4, h: 0.25, fontFace: 'Calibri', fontSize: 11, color: '9FB3BB', margin: 0 });
}

// 2. Capacity scalability
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'Capacity Scales, Active Resources Do Not', 'More passive media increases transport work without adding service bandwidth.');
  label(s, 'CAPACITY', 0.75, 1.68, 2.0);
  const counts = [4, 8, 14];
  counts.forEach((count, col) => {
    const x = 0.85 + col * 2.35;
    for (let i = 0; i < count; i++) {
      s.addShape(pptx.ShapeType.rect, { x: x + (i % 4) * 0.34, y: 2.15 + Math.floor(i / 4) * 0.42, w: 0.25, h: 0.32, fill: { color: '9FD0D9', transparency: 8 }, line: { color: C.nozone, transparency: 35 } });
    }
    s.addText(['Small', 'Medium', 'Large'][col], { x, y: 4.02, w: 1.45, h: 0.3, fontSize: 13, color: C.muted, align: 'center', margin: 0 });
  });
  arrow(s, 7.6, 2.62, 0.65, C.orange);
  panel(s, 8.5, 1.7, 3.85, 3.3, C.white);
  s.addText('FIXED ACTIVE RESOURCES', { x: 8.85, y: 2.02, w: 3.1, h: 0.3, fontSize: 12, bold: true, color: C.muted, align: 'center', margin: 0 });
  s.addText('8', { x: 8.85, y: 2.55, w: 1.3, h: 0.8, fontFace: 'Cambria', fontSize: 44, bold: true, color: C.static, align: 'center', margin: 0 });
  s.addText('SHUTTLES', { x: 8.85, y: 3.35, w: 1.3, h: 0.3, fontSize: 11, bold: true, color: C.muted, align: 'center', margin: 0 });
  s.addText('8', { x: 10.65, y: 2.55, w: 1.3, h: 0.8, fontFace: 'Cambria', fontSize: 44, bold: true, color: C.orange, align: 'center', margin: 0 });
  s.addText('READERS', { x: 10.65, y: 3.35, w: 1.3, h: 0.3, fontSize: 11, bold: true, color: C.muted, align: 'center', margin: 0 });
  s.addText('Question: can fixed transport and read resources preserve performance as the library grows?', { x: 1.15, y: 5.55, w: 11.0, h: 0.6, fontFace: 'Cambria', fontSize: 21, italic: true, color: C.ink, align: 'center', margin: 0.02, fit: 'shrink' });
}

// 3. Initial motivation
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'Initial Motivation: The Slowest Zone Sets the Tail', 'Static ownership creates independent queues that cannot share shuttle capacity.');
  const lengths = [5.2, 3.2, 4.1, 2.6, 3.7, 2.9, 3.5, 2.4];
  lengths.forEach((len, i) => {
    const y = 1.7 + i * 0.56;
    s.addText(`Zone ${i}`, { x: 0.78, y: y + 0.04, w: 0.72, h: 0.22, fontSize: 10, color: C.muted, margin: 0, align: 'right' });
    s.addShape(pptx.ShapeType.rect, { x: 1.68, y, w: len, h: 0.3, fill: { color: i === 0 ? C.orange : C.static, transparency: i === 0 ? 0 : 8 }, line: { color: i === 0 ? C.orange : C.static } });
    if (len < 5.2) s.addShape(pptx.ShapeType.rect, { x: 1.68 + len, y, w: 5.2 - len, h: 0.3, fill: { color: C.paleGray }, line: { color: C.paleGray } });
  });
  s.addShape(pptx.ShapeType.line, { x: 6.88, y: 1.52, w: 0, h: 4.65, line: { color: C.orange, width: 2, dash: 'dash' } });
  s.addText('BATCH\nCOMPLETES', { x: 6.35, y: 6.0, w: 1.1, h: 0.5, fontSize: 10, bold: true, color: C.orange, align: 'center', margin: 0 });
  panel(s, 8.05, 1.75, 4.3, 3.95, C.white);
  s.addText('Potential cost', { x: 8.45, y: 2.12, w: 3.5, h: 0.4, fontFace: 'Cambria', fontSize: 22, bold: true, color: C.ink, margin: 0 });
  bulletList(s, ['Queued requests remain in one zone', 'Other shuttles finish early', 'Idle capacity cannot help the tail'], 8.45, 2.75, 3.45, 2.1, 17);
  s.addText('Stranded service capacity', { x: 8.45, y: 5.05, w: 3.35, h: 0.35, fontSize: 17, bold: true, color: C.red, margin: 0 });
}

// 4. Hypotheses
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'What Did We Want to Test?', 'Does shared mobility convert idle capacity into lower tail latency?');
  panel(s, 0.9, 1.75, 5.55, 3.9, C.paleGreen, 'C9DEC9');
  label(s, 'HYPOTHESIS 1', 1.3, 2.12, 1.6, C.green);
  s.addText('No-Zone reduces\nidle shuttle capacity.', { x: 1.3, y: 2.62, w: 4.65, h: 1.15, fontFace: 'Cambria', fontSize: 25, bold: true, color: C.ink, margin: 0, fit: 'shrink' });
  s.addText('All shuttles draw work from a shared pool.', { x: 1.3, y: 4.3, w: 4.35, h: 0.6, fontSize: 16, color: C.muted, margin: 0 });
  panel(s, 6.85, 1.75, 5.55, 3.9, C.paleBlue, 'C9DDE4');
  label(s, 'HYPOTHESIS 2', 7.25, 2.12, 1.6, C.nozone);
  s.addText('Lower idle capacity\nreduces tail latency.', { x: 7.25, y: 2.62, w: 4.65, h: 1.15, fontFace: 'Cambria', fontSize: 25, bold: true, color: C.ink, margin: 0, fit: 'shrink' });
  s.addText('More active shuttles should drain work sooner.', { x: 7.25, y: 4.3, w: 4.35, h: 0.6, fontSize: 16, color: C.muted, margin: 0 });
  arrow(s, 6.34, 3.35, 0.55, C.muted);
}

// 5. Baselines
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'Two Baselines', 'The comparison isolates fixed ownership versus shared movement.');
  panel(s, 0.75, 1.55, 5.85, 4.95, C.white);
  s.addText('STATIC ZONE', { x: 1.15, y: 1.92, w: 2.2, h: 0.35, fontSize: 16, bold: true, color: C.static, margin: 0 });
  for (let i = 0; i < 4; i++) {
    s.addShape(pptx.ShapeType.rect, { x: 1.15, y: 2.55 + i * 0.72, w: 2.35, h: 0.48, fill: { color: C.paleGray }, line: { color: C.static } });
    s.addText(`Zone ${i}  →  Shuttle ${i}`, { x: 1.35, y: 2.69 + i * 0.72, w: 1.95, h: 0.18, fontSize: 11, color: C.ink, margin: 0, align: 'center' });
  }
  bulletList(s, ['Fixed owner', 'Fixed reader', 'Local movement', 'Conflict-free abstraction'], 3.85, 2.42, 2.2, 2.9, 16);
  panel(s, 6.85, 1.55, 5.7, 4.95, C.white);
  s.addText('GREEDY NO-ZONE', { x: 7.25, y: 1.92, w: 2.6, h: 0.35, fontSize: 16, bold: true, color: C.nozone, margin: 0 });
  const flow = ['Oldest task', ' Unreal idle shuttle', 'Nearest reader', 'Reserve route'];
  flow[1] = 'Nearest idle shuttle';
  flow.forEach((text, i) => {
    s.addShape(pptx.ShapeType.roundRect, { x: 7.25, y: 2.5 + i * 0.82, w: 2.2, h: 0.48, rectRadius: 0.04, fill: { color: i === 3 ? C.paleOrange : C.paleBlue }, line: { color: i === 3 ? C.orange : C.nozone } });
    s.addText(text, { x: 7.45, y: 2.64 + i * 0.82, w: 1.8, h: 0.18, fontSize: 11, color: C.ink, align: 'center', margin: 0 });
    if (i < 3) arrow(s, 8.08, 3.03 + i * 0.82, 0.46, C.muted);
  });
  s.addText('Shared work pool', { x: 10.05, y: 2.55, w: 1.85, h: 0.3, fontSize: 16, bold: true, color: C.nozone, margin: 0 });
  s.addText('Freedom is useful only when scheduling converts it into productive work.', { x: 10.05, y: 3.13, w: 1.9, h: 1.65, fontSize: 15, color: C.muted, margin: 0, fit: 'shrink' });
}

// 6. Conflict handling
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'How Greedy No-Zone Handles Conflicts', 'Direct routes are delayed or detoured when shuttle trajectories overlap.');
  panel(s, 0.65, 1.52, 6.0, 4.95, C.white);
  label(s, 'HEAD-ON ENCOUNTER', 0.98, 1.82, 2.4, C.orange);
  fitImage(s, img('results/shuttle-yield-demo/fig2_head_on_explainer.png'), 0.9, 2.1, 5.5, 3.65, 2000 / 1120);
  s.addText('B changes rack; A waits until the original rack is clear.', { x: 1.1, y: 5.9, w: 5.0, h: 0.3, fontSize: 12, color: C.muted, align: 'center', margin: 0 });
  panel(s, 6.9, 1.52, 5.75, 4.95, C.white);
  label(s, 'SAME-DIRECTION CATCH-UP', 7.22, 1.82, 2.8, C.nozone);
  fitImage(s, img('results/shuttle-following-service/fig1_pickup_to_reader.png'), 7.2, 2.05, 5.15, 3.8, 2200 / 1600);
  s.addText('The following shuttle slows or waits to preserve clearance.', { x: 7.3, y: 5.9, w: 4.95, h: 0.3, fontSize: 12, color: C.muted, align: 'center', margin: 0 });
}

// 7. Setup
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'Trace-Driven Experiment', 'Both policies receive the same requests and physical placement.');
  const stats = [
    ['100,000', 'Azure blob requests', C.nozone], ['640', 'Virtual platters', C.orange],
    ['8 + 8', 'Shuttles and readers', C.static], ['10', 'Paired placement seeds', C.green],
  ];
  stats.forEach((entry, i) => {
    const x = 0.8 + (i % 2) * 3.0;
    const y = 1.65 + Math.floor(i / 2) * 1.72;
    panel(s, x, y, 2.65, 1.35, C.white);
    s.addText(entry[0], { x: x + 0.2, y: y + 0.2, w: 2.25, h: 0.55, fontFace: 'Cambria', fontSize: 30, bold: true, color: entry[2], align: 'center', margin: 0 });
    s.addText(entry[1], { x: x + 0.2, y: y + 0.83, w: 2.25, h: 0.28, fontSize: 12, color: C.muted, align: 'center', margin: 0 });
  });
  panel(s, 7.2, 1.65, 5.2, 3.95, C.white);
  label(s, 'PANEL-SIDE LENGTH', 7.6, 2.02, 2.2);
  const vals = ['4 m', '8 m', '16 m', '32 m', '64 m'];
  vals.forEach((v, i) => {
    const x = 7.58 + i * 0.91;
    s.addShape(pptx.ShapeType.ellipse, { x, y: 2.65, w: 0.62, h: 0.62, fill: { color: i === 4 ? C.orange : C.paleBlue }, line: { color: i === 4 ? C.orange : C.nozone } });
    s.addText(v, { x: x - 0.06, y: 2.85, w: 0.74, h: 0.18, fontSize: 10, bold: true, color: i === 4 ? C.white : C.ink, align: 'center', margin: 0 });
    if (i < 4) s.addShape(pptx.ShapeType.line, { x: x + 0.62, y: 2.96, w: 0.29, h: 0, line: { color: C.line, width: 2 } });
  });
  s.addText('Preserved from the raw trace', { x: 7.6, y: 3.7, w: 2.6, h: 0.28, fontSize: 13, bold: true, color: C.ink, margin: 0 });
  s.addText('Arrival time · request order · object identity · bytes', { x: 7.6, y: 4.12, w: 4.2, h: 0.5, fontSize: 14, color: C.muted, margin: 0 });
  s.addText('Physical glass locations are seeded synthetic mappings shared by both policies.', { x: 1.0, y: 6.15, w: 11.25, h: 0.38, fontSize: 13, italic: true, color: C.muted, align: 'center', margin: 0 });
}

// 8. Result
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'Unexpected Result: Greedy No-Zone Is Slower', 'Shared mobility lowers idle capacity, but p99 request latency remains higher.');
  fitImage(s, img('results/zone-nozone-natural-arrivals-4-64/fig1_latency.png'), 0.62, 1.42, 12.1, 5.45, 2000 / 840);
}

// 9. Why
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'Why Is Greedy No-Zone Slower?', 'Each physical glass service becomes less efficient.');
  fitImage(s, img('results/zone-nozone-comparison-4-64/fig3_service_phase_breakdown.png'), 0.62, 1.42, 12.1, 5.42, 2000 / 919);
}

// 10. Tradeoff
{
  const s = pptx.addSlide('CONTENT');
  title(s, 'The Real Trade-off', 'Static pays in stranded capacity; No-Zone pays per service.');
  fitImage(s, img('results/zone-nozone-comparison-4-64/fig4_isolation_vs_coordination.png'), 0.62, 1.42, 12.1, 5.25, 2000 / 860);
  s.addText('Higher shuttle utilization does not imply higher productive throughput.', { x: 2.15, y: 6.6, w: 9.0, h: 0.32, fontFace: 'Cambria', fontSize: 18, bold: true, italic: true, color: C.ink, align: 'center', margin: 0 });
}

// 11. Refined motivation
{
  const s = pptx.addSlide();
  s.background = { color: C.ink };
  s.addText('REFINED RESEARCH MOTIVATION', { x: 0.75, y: 0.55, w: 5.8, h: 0.35, fontSize: 13, bold: true, color: '9FB3BB', charSpacing: 1.2, margin: 0 });
  s.addText('Recover stranded capacity without sacrificing locality and traffic isolation.', { x: 0.75, y: 1.18, w: 11.5, h: 1.0, fontFace: 'Cambria', fontSize: 30, bold: true, color: C.white, margin: 0, fit: 'shrink' });
  const directions = [
    ['1', 'Fair baseline', 'Allow the flexible scheduler to emulate Static Zone.'],
    ['2', 'Locality-aware assignment', 'Choose task, shuttle, and reader by expected completion.'],
    ['3', 'Bounded coordination', 'Plan only interacting shuttle paths in a short horizon.'],
    ['4', 'Feeder buffering', 'Overlap platter transport with reader service when starvation dominates.'],
  ];
  directions.forEach((d, i) => {
    const x = 0.78 + i * 3.08;
    s.addShape(pptx.ShapeType.roundRect, { x, y: 3.0, w: 2.72, h: 2.55, rectRadius: 0.05, fill: { color: i === 3 ? '37474F' : '314149' }, line: { color: i === 3 ? C.orange : '53666F', width: 1 } });
    s.addShape(pptx.ShapeType.ellipse, { x: x + 0.22, y: 3.25, w: 0.48, h: 0.48, fill: { color: i === 3 ? C.orange : C.nozone }, line: { color: i === 3 ? C.orange : C.nozone } });
    s.addText(d[0], { x: x + 0.22, y: 3.38, w: 0.48, h: 0.18, fontSize: 11, bold: true, color: C.white, align: 'center', margin: 0 });
    s.addText(d[1], { x: x + 0.22, y: 3.95, w: 2.25, h: 0.42, fontFace: 'Cambria', fontSize: 18, bold: true, color: C.white, margin: 0, fit: 'shrink' });
    s.addText(d[2], { x: x + 0.22, y: 4.55, w: 2.25, h: 0.68, fontSize: 13, color: 'C5D2D7', margin: 0, fit: 'shrink' });
  });
  s.addText('Zone provides more than collision avoidance: it also preserves movement locality.', { x: 1.1, y: 6.35, w: 11.1, h: 0.42, fontFace: 'Cambria', fontSize: 19, italic: true, color: 'DDE8EB', align: 'center', margin: 0 });
}

pptx.writeFile({ fileName: output });
