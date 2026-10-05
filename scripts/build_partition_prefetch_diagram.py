from pathlib import Path

W, H = 1600, 1000
o = []
a = o.append
a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
a('<title>Single-partition prefetch buffer architecture</title>')
a('''<defs>
<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#51636B"/></marker>
<marker id="go" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#3F8E80"/></marker>
<style>
text { font-family: "PingFang TC","Noto Sans TC","Heiti TC",Arial,sans-serif; fill:#263238; }
.title { font-size:32px; font-weight:700; }
.subtitle { font-size:17px; fill:#60727A; }
.section { font-size:19px; font-weight:700; }
.label { font-size:15px; font-weight:700; }
.small { font-size:13px; fill:#60727A; }
.tiny { font-size:12px; fill:#60727A; }
.flow { fill:none; stroke:#51636B; stroke-width:3; marker-end:url(#arrow); }
.route { fill:none; stroke:#3F8E80; stroke-width:3; stroke-dasharray:5 5; marker-end:url(#go); }
</style></defs>''')
a(f'<rect width="{W}" height="{H}" fill="#F6F8FA"/>')
a('<text x="60" y="62" class="title">單一 Partition 架構：多台 Shuttle + Rack 上的 Prefetch Buffer + 單一 Reader</text>')
a('<text x="62" y="94" class="subtitle">Shuttle 在 rack 上移動搬運玻璃；reader 前方的一段 rack slots 由軟體劃為 prefetch buffer，先把待讀玻璃搬到 reader 旁邊。</text>')

# hierarchy strip
a('<rect x="40" y="116" width="1520" height="84" rx="10" fill="#FFFFFF"/>')
a('<text x="62" y="150" class="label">空間分割</text><text x="62" y="172" class="tiny">參考 Project Silica</text>')
hier = [("Glass Library", "整座儲存庫"), ("Partition × P", "本研究：聚焦 1 個"), ("Rack × 8", "shuttle 沿 rack 移動"),
        ("Slots × 80 / rack", "每格存放一片玻璃"), ("Glass platter", "讀完放回原位")]
x = 190
for i, (t, s) in enumerate(hier):
    fill, stroke = ("#E7EEF6", "#4F7CAC") if i == 1 else ("#EDF1F3", "#9AA8AE")
    a(f'<rect x="{x}" y="128" width="236" height="60" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{2 if i == 1 else 1.2}"/>')
    a(f'<text x="{x + 118}" y="154" class="label" text-anchor="middle">{t}</text>')
    a(f'<text x="{x + 118}" y="175" class="tiny" text-anchor="middle">{s}</text>')
    if i < len(hier) - 1:
        a(f'<path d="M{x + 242} 158 H{x + 266}" class="flow"/>')
    x += 274

# main panel
a('<rect x="40" y="216" width="1520" height="694" rx="10" fill="#FFFFFF"/>')
a('<text x="62" y="250" class="section">放大：一個 Partition（8 條 rack、N=4 台 shuttle、1 台 reader）</text>')

colors = ["#4F7CAC", "#3F9E8F", "#8A6BBF", "#C2577A"]
light = ["#E6EEF7", "#E3F3F0", "#EFEAF7", "#F8E7ED"]
RX0, RX1 = 150, 1290
SLOTS, PITCH = 80, 14
BUF_SLOTS = 8                      # last slots of rack 6/7 reserved as buffer
row_y = lambda i: 278 + i * 76
RH = 56
slot_x = lambda k: RX0 + 12 + k * PITCH
staged = {(6, 73), (6, 75), (6, 76), (7, 72), (7, 74), (7, 77)}

for i in range(8):
    y = row_y(i); z = i // 2
    a(f'<rect x="{RX0}" y="{y}" width="{RX1 - RX0}" height="{RH}" rx="6" fill="{light[z]}" stroke="#9AA8AE" stroke-width="1.2"/>')
    a(f'<line x1="{RX0 + 8}" y1="{y + RH - 7}" x2="{RX1 - 8}" y2="{y + RH - 7}" stroke="#7A8990" stroke-width="2"/>')
    a(f'<text x="138" y="{y + 34}" class="label" text-anchor="end">Rack {i}</text>')
    for k in range(SLOTS):
        px = slot_x(k)
        if i >= 6 and k >= SLOTS - BUF_SLOTS:
            if (i, k) in staged:
                a(f'<rect x="{px}" y="{y + 9}" width="7" height="{RH - 22}" rx="1.5" fill="#F2C766" stroke="#B9862A" stroke-width="0.9"/>')
            else:
                a(f'<rect x="{px}" y="{y + 9}" width="7" height="{RH - 22}" rx="1.5" fill="#FFFFFF" stroke="#D9A441" stroke-width="0.9" stroke-dasharray="2 1.5"/>')
        else:
            a(f'<rect x="{px}" y="{y + 9}" width="7" height="{RH - 22}" rx="1.5" fill="#BFD9E4" stroke="#7FA7B8" stroke-width="0.8"/>')

for z in range(4):
    y0, y1 = row_y(2 * z) + 4, row_y(2 * z + 1) + RH - 4
    a(f'<rect x="54" y="{y0}" width="8" height="{y1 - y0}" rx="4" fill="{colors[z]}"/>')
    a(f'<text x="70" y="{(y0 + y1) / 2 + 5}" class="tiny" style="fill:{colors[z]};font-weight:700">S{z + 1}</text>')

# prefetch buffer region (software-defined)
bx0 = slot_x(SLOTS - BUF_SLOTS) - 7
bx1 = slot_x(SLOTS - 1) + 14
by0, by1 = row_y(6) - 6, row_y(7) + RH + 6
a(f'<rect x="{bx0}" y="{by0}" width="{bx1 - bx0}" height="{by1 - by0}" rx="8" fill="none" stroke="#D9A441" stroke-width="3.5" stroke-dasharray="9 5"/>')
cx = (bx0 + bx1) / 2
CX, CY = 1310, row_y(4) + 4
a(f'<rect x="{CX}" y="{CY}" width="230" height="64" rx="8" fill="#FFF8E8" stroke="#D9A441" stroke-width="1.5"/>')
a(f'<text x="{CX + 115}" y="{CY + 26}" text-anchor="middle" class="label" style="fill:#8A6416">Prefetch buffer</text>')
a(f'<text x="{CX + 115}" y="{CY + 48}" text-anchor="middle" class="tiny">reader 前方 rack slots，由軟體劃定</text>')
a(f'<path d="M{CX + 60} {CY + 66} L{bx1 - 10} {by0 - 4}" class="flow" style="stroke:#D9A441;stroke-width:2"/>')

def shuttle(x, y, c, name, carry=False):
    a(f'<rect x="{x}" y="{y}" width="48" height="{RH + 8}" rx="8" fill="{c}" stroke="#263238" stroke-width="1.5"/>')
    a(f'<text x="{x + 24}" y="{y + 18}" text-anchor="middle" style="fill:#fff;font-size:13px;font-weight:700">{name}</text>')
    if carry:
        a(f'<rect x="{x + 19}" y="{y + 25}" width="10" height="28" rx="2" fill="#BFD9E4" stroke="#fff" stroke-width="1.5"/>')
    a(f'<circle cx="{x + 12}" cy="{y + RH + 8}" r="4" fill="#263238"/><circle cx="{x + 36}" cy="{y + RH + 8}" r="4" fill="#263238"/>')

shuttle(420, row_y(0) - 4, colors[0], "S1")
shuttle(560, row_y(3) - 4, colors[1], "S2", True)
shuttle(760, row_y(5) - 4, colors[2], "S3")
shuttle(960, row_y(6) - 4, colors[3], "S4", True)

# S1: moves across racks within its zone
a(f'<path d="M476 {row_y(0) + 30} C 540 {row_y(0) + 50}, 540 {row_y(1) + 6}, 500 {row_y(1) + 26}" fill="none" stroke="{colors[0]}" stroke-width="2.5" stroke-dasharray="5 4" marker-end="url(#arrow)"/>')
a(f'<text x="550" y="{row_y(1) - 2}" class="tiny" style="fill:{colors[0]};font-weight:700">一台 shuttle 可跨多條 rack 移動</text>')
# S2: carries platter toward buffer
a(f'<path d="M614 {row_y(3) + 28} H{bx0 - 60} Q{bx0 - 30} {row_y(3) + 28} {bx0 - 30} {row_y(3) + 60} V{row_y(7) + 20} H{bx0 - 6}" class="route"/>')
# S4: into buffer
a(f'<path d="M1014 {row_y(6) + 28} H{bx0 - 6}" class="route"/>')

# reader at bottom-right
RDX, RDY = 1350, row_y(6) - 6
a(f'<rect x="{RDX}" y="{RDY}" width="170" height="{row_y(7) + RH + 6 - RDY}" rx="12" fill="#E3F0F3" stroke="#2B819B" stroke-width="2.5"/>')
a(f'<text x="{RDX + 85}" y="{RDY + 32}" class="label" text-anchor="middle" style="font-size:18px">Reader</text>')
a(f'<text x="{RDX + 85}" y="{RDY + 52}" class="tiny" text-anchor="middle">×1 / partition</text>')
a(f'<circle cx="{RDX + 85}" cy="{RDY + 84}" r="20" fill="none" stroke="#2B819B" stroke-width="2"/><circle cx="{RDX + 85}" cy="{RDY + 84}" r="6" fill="#2B819B"/>')
a(f'<text x="{RDX + 85}" y="{RDY + 128}" class="tiny" text-anchor="middle">load · read · unload</text>')
a(f'<path d="M{bx1 + 4} {(by0 + by1) / 2} H{RDX - 6}" class="flow"/>')

# legend
LY = row_y(7) + RH + 28
items = [("#BFD9E4", "#7FA7B8", "玻璃（home slot）"), ("#F2C766", "#B9862A", "已預取、待讀"), ("#FFFFFF", "#D9A441", "空的 buffer slot")]
lx = 150
for f, s, t in items:
    a(f'<rect x="{lx}" y="{LY - 14}" width="8" height="18" rx="1.5" fill="{f}" stroke="{s}"/>')
    a(f'<text x="{lx + 16}" y="{LY}" class="tiny">{t}</text>')
    lx += 160
a(f'<line x1="{lx + 10}" y1="{LY - 5}" x2="{lx + 50}" y2="{LY - 5}" class="route"/><text x="{lx + 58}" y="{LY}" class="tiny">shuttle 搬運</text>')
a(f'<text x="{lx + 180}" y="{LY}" class="tiny">左側色條 = Zone：每台 shuttle 負責 2 條相鄰 rack</text>')

a('<text x="62" y="950" class="small">讀取流程：request 到達 → shuttle 從 home slot 取出玻璃 → 放進 reader 前的 prefetch buffer slot → reader 讀取 → 送回原 slot</text>')
a('</svg>')
svg = '\n'.join(o)
diagrams = Path(__file__).resolve().parents[1] / 'docs/diagrams'
(diagrams / 'partition-prefetch-architecture.svg').write_text(svg)
# Slide variant: drop the title block (the slide supplies its own title).
first, rest = svg.split('\n', 1)
slide_head = '<svg xmlns="http://www.w3.org/2000/svg" width="1540" height="812" viewBox="30 106 1540 812">'
(diagrams / 'partition-prefetch-architecture-slide.svg').write_text(slide_head + '\n' + rest)
