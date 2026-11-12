#!/usr/bin/env python3
"""把方案里的俯视图画出来：这个空间里有什么、人怎么走、几个机位各在哪、朝哪拍。两种出法。

  python3 scripts/topview.py <方案.plan.md> --chat [--clip 2] [--out 图.svg]
  python3 scripts/topview.py <方案.plan.md> [--out 页面.html] [--standalone]

--chat   对话里直接出的那一张图，默认用这种。打印一张 SVG，原样交给对话里的画图工具。
         不加 --clip 画全场；加了只画那一条用到的机位和那一条里的走位。
         这张图用的是画图工具自带的字和颜色，单独存成文件打开是没有颜色的。
不加     一页能按拍看的俯视图，重点的戏、复杂的场景或用户点名时用。存在方案旁边：<场>.topview.html，
         存好以后打印路径。有 Artifact 工具就把它发布出去，给用户链接；同一个路径再发布就是更新。
         没有 Artifact 工具时加 --standalone，生成能直接用浏览器打开的完整网页。

两种图都按方案第 4、5 段的坐标画，和 check.py 算左右用的是同一份数据。

图上有什么：
  固定的东西  一个方框，名字写在里面
  灯         画在它的位置上，旁边是名字
  人         开场站在哪（实心圆，旁边是名字），后来走到哪（虚线圈，旁边写第几拍到哪），箭头是走位，短线是脸朝哪。一个人一种颜色
  机位       小方块，里面是机位的字母；从它张开的一小片越窄焦段越长；单人镜的机位有一条点线连到它拍的那个人。机位不超过 3 个时旁边写它拍什么
  机位在动   分镜表机位栏写「A→B」的镜头：一条从 A 到 B 的虚线，旁边写镜号
  离场       站位表里姿态以「离场」开头的那一行：一条指向出口的箭头
"""
import argparse
import html
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check  # noqa: E402

S, M = 60, 50                       # 页面：一格多少像素；四周留白
CW = 680                            # 对话里那张图的宽度：画图工具按这个宽度 1:1 显示
ARC_WORDS = ('环绕', '绕', '弧')     # 运镜里有这些词，机位移动的那条线画成弧

CSS = """
/* 只有一张俯视图，可以按拍看；单栏，窄屏照样读 */
:root {
  --bg: #f3f5f8; --panel: #ffffff; --ink: #1a2330; --muted: #5a6677; --line: #cfd6e1; --grid: #e4e9f0; --lamp: #a9700a;
  --c1: #2a62c9; --c2: #c2501a; --c3: #1c8757; --c4: #8a3fb3; --c5: #b6316a; --c6: #0c7c90; --c7: #96650a; --c8: #5a4ac2;
  --font: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #11151b; --panel: #19202a; --ink: #e5eaf2; --muted: #98a4b6; --line: #303a48; --grid: #212a36; --lamp: #f0c060;
    --c1: #7ea9ff; --c2: #ff9a66; --c3: #62d39a; --c4: #d48bf2; --c5: #f582ae; --c6: #5fd3e6; --c7: #f2c066; --c8: #ada0ff;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #11151b; --panel: #19202a; --ink: #e5eaf2; --muted: #98a4b6; --line: #303a48; --grid: #212a36; --lamp: #f0c060;
  --c1: #7ea9ff; --c2: #ff9a66; --c3: #62d39a; --c4: #d48bf2; --c5: #f582ae; --c6: #5fd3e6; --c7: #f2c066; --c8: #ada0ff;
  color-scheme: dark;
}
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font); font-size: 15px; line-height: 1.6; }
.wrap { max-width: 980px; margin: 0 auto; padding-block: 28px 56px; padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); display: flex; flex-direction: column; gap: 24px; }
header h1 { margin: 0; font-size: 26px; line-height: 1.25; letter-spacing: .01em; text-wrap: balance; }
header p { margin: 6px 0 0; color: var(--muted); }
section { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
figure { margin: 0; display: flex; flex-direction: column; gap: 10px; }
figcaption, .note { color: var(--muted); font-size: 13px; margin: 0; }
.scroll { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; }
.scroll svg { display: block; width: 100%; height: auto; }
.picks { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.picks button { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); cursor: pointer; }
.picks button[aria-pressed="true"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.picks button:focus-visible { outline: 2px solid var(--c1); outline-offset: 2px; }
#beat-note { min-height: 1.6em; }
/* 图里的线和字 */
svg text { font-family: var(--font); fill: var(--ink); }
.lbl, .sub, .lamptxt { paint-order: stroke; stroke: var(--panel); stroke-width: 3.5px; stroke-linejoin: round; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { fill: var(--muted); font-size: 12px; }
.fx { fill: var(--bg); stroke: var(--line); stroke-width: 1.5; }
.fxbar { stroke: var(--line); stroke-width: 12; stroke-linecap: round; fill: none; }
.lbl { font-size: 12px; }
.sub { font-size: 11px; fill: var(--muted); }
.lamp { stroke: var(--lamp); stroke-width: 2; fill: var(--panel); }
.lamptxt { fill: var(--lamp); font-size: 12px; }
.pt { fill: none; stroke: var(--muted); stroke-width: 1.2; stroke-dasharray: 2 3; }
.who { fill: var(--ink); stroke: var(--panel); stroke-width: 2; }
.ghost { fill: var(--panel); stroke: var(--ink); stroke-width: 1.5; }
.ini { fill: var(--bg); font-size: 12px; font-weight: 700; }
.ghost + .ini, .ini.g { fill: var(--ink); }
.face { stroke: var(--ink); stroke-width: 2.5; stroke-linecap: round; }
.mv { stroke: var(--ink); stroke-width: 1.5; stroke-dasharray: 5 4; fill: none; }
.mvh { fill: var(--ink); }
.cone { fill-opacity: .1; stroke-width: 1.5; stroke-linejoin: round; }
.body { stroke: var(--panel); stroke-width: 1.5; }
.camtxt { fill: var(--bg); font-family: var(--mono); font-size: 12px; font-weight: 700; }
.dim { opacity: .18; }
.k1 { fill: var(--c1); stroke: var(--c1); } .k2 { fill: var(--c2); stroke: var(--c2); }
.k3 { fill: var(--c3); stroke: var(--c3); } .k4 { fill: var(--c4); stroke: var(--c4); }
.k5 { fill: var(--c5); stroke: var(--c5); } .k6 { fill: var(--c6); stroke: var(--c6); }
.k7 { fill: var(--c7); stroke: var(--c7); } .k8 { fill: var(--c8); stroke: var(--c8); }
.cm { fill: none; stroke-width: 2; stroke-dasharray: 7 5; stroke-linecap: round; }
@media (max-width: 560px) { header h1 { font-size: 21px; } }
"""

JS = """
(function () {
  var notes = __NOTES__;
  var buttons = document.querySelectorAll('[data-pick]');
  function pick(beat) {
    buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-pick') === beat ? 'true' : 'false'); });
    document.querySelectorAll('[data-beat]').forEach(function (g) {
      if (g.getAttribute('data-beat') === beat) { g.removeAttribute('hidden'); } else { g.setAttribute('hidden', ''); }
    });
    document.querySelectorAll('[data-beats]').forEach(function (g) {
      var on = beat === 'all' || (' ' + g.getAttribute('data-beats') + ' ').indexOf(' ' + beat + ' ') !== -1;
      g.classList.toggle('dim', !on);
    });
    var note = document.getElementById('beat-note');
    if (note) { note.textContent = notes[beat] || ''; }
  }
  buttons.forEach(function (b) { b.addEventListener('click', function () { pick(b.getAttribute('data-pick')); }); });
})();
"""


def e(text):
    return html.escape(str(text), quote=True)


def scene_name(plan):
    m = re.search(r'^#\s+(.+?)\s*$', plan.head, re.M)
    name = m.group(1) if m else plan.path.stem
    return re.sub(r'\s*·\s*导演方案\s*$', '', name).strip()


def shot_tag(plan, shot, clip=None):
    """一镜叫什么：只有一条 clip 在图上时写「镜 2」，几条都在时写「clip02 镜 2」。"""
    if clip is None and len(plan.clips()) > 1:
        return 'clip%02d 镜 %s' % (shot['clip'] or 0, shot['镜'])
    return '镜 %s' % shot['镜']


def cam_note(plan, name):
    c = plan.cams[name]
    return '机位 %s：%s，%s｜%s' % (name, plan.lens(name)[0] or c['焦段'], c['高度'], c['拍什么'])


def move_curve(a, b, look, arc, gap):
    """机位从 a 移到 b 的那条线（屏幕坐标），两头各缩进 gap：返回 (起点, 控制点, 终点)。
    arc 为真时画成弧，往离被拍的人远的一侧鼓出去。"""
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    if d < 2 * gap + 6:
        return None
    c = (mx, my)
    if arc:
        nx, ny = -(b[1] - a[1]) / d, (b[0] - a[0]) / d
        if look and math.hypot(mx + nx - look[0], my + ny - look[1]) < math.hypot(mx - nx - look[0], my - ny - look[1]):
            nx, ny = -nx, -ny
        c = (mx + nx * d * 0.3, my + ny * d * 0.3)
    da, db = math.hypot(c[0] - a[0], c[1] - a[1]), math.hypot(c[0] - b[0], c[1] - b[1])
    start = (a[0] + (c[0] - a[0]) / da * gap, a[1] + (c[1] - a[1]) / da * gap)
    end = (b[0] + (c[0] - b[0]) / db * gap, b[1] + (c[1] - b[1]) / db * gap)
    return start, c, end


def curve_mid(start, c, end):
    return (0.25 * start[0] + 0.5 * c[0] + 0.25 * end[0], 0.25 * start[1] + 0.5 * c[1] + 0.25 * end[1])


def camera_moves(plan, geo, clip=None):
    """机位在动的镜头：[(镜, 从哪个机位, 到哪个机位, 是不是弧, 这一镜的拍)]。"""
    out = []
    for shot, g in zip(plan.shots, geo):
        if clip is not None and shot['clip'] != clip:
            continue
        for a, b in zip(shot['机位'], shot['机位'][1:]):
            if a != b:
                out.append((shot, a, b, any(w in shot['运镜'] for w in ARC_WORDS), g['beats']))
    return out


# ---------- 页面 ----------

class Canvas:
    def __init__(self, xs, ys):
        self.x0, self.x1 = math.floor(min(xs) - 0.8), math.ceil(max(xs) + 0.8)
        self.y0, self.y1 = math.floor(min(ys) - 0.8), math.ceil(max(ys) + 0.8)
        self.w = (self.x1 - self.x0) * S + 2 * M
        self.h = (self.y1 - self.y0) * S + 2 * M

    def X(self, x):
        return round(M + (x - self.x0) * S, 1)

    def Y(self, y):
        return round(M + (self.y1 - y) * S, 1)

    def P(self, p):
        return self.X(p[0]), self.Y(p[1])


def cone_points(c, look, half, length):
    theta = math.atan2(look[1] - c[1], look[0] - c[0])
    pts = [c]
    for k in range(7):
        a = theta - math.radians(half) + math.radians(2 * half) * k / 6.0
        pts.append((c[0] + length * math.cos(a), c[1] + length * math.sin(a)))
    return pts


def arrow(cv, a, b, gap=16, end_gap=None):
    """从 a 到 b 的虚线箭头（屏幕坐标里两头各缩一点）。"""
    ax, ay = cv.P(a)
    bx, by = cv.P(b)
    end_gap = gap if end_gap is None else end_gap
    d = math.hypot(bx - ax, by - ay)
    if d < gap + end_gap + 6:
        return ''
    ux, uy = (bx - ax) / d, (by - ay) / d
    sx, sy, tx, ty = ax + ux * gap, ay + uy * gap, bx - ux * end_gap, by - uy * end_gap
    left = (tx - ux * 9 - uy * 4.5, ty - uy * 9 + ux * 4.5)
    right = (tx - ux * 9 + uy * 4.5, ty - uy * 9 - ux * 4.5)
    return ('<line class="mv" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
            '<polygon class="mvh" points="%.1f,%.1f %.1f,%.1f %.1f,%.1f"/>' % (sx, sy, tx - ux * 6, ty - uy * 6, tx, ty, left[0], left[1], right[0], right[1]))


def person(cv, name, p, gaze=None, ghost=False):
    x, y = cv.P(p)
    out = ''
    if gaze and gaze != p:
        d = math.hypot(gaze[0] - p[0], gaze[1] - p[1])
        ux, uy = (gaze[0] - p[0]) / d, -(gaze[1] - p[1]) / d
        out += '<line class="face" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (x + ux * 13, y + uy * 13, x + ux * 25, y + uy * 25)
    out += '<circle class="%s" cx="%s" cy="%s" r="13"/>' % ('ghost' if ghost else 'who', x, y)
    out += '<text class="ini%s" x="%s" y="%s" text-anchor="middle">%s</text>' % (' g' if ghost else '', x, y + 4.2, e(name[:1].upper()))
    if not ghost:
        out += '<text class="lbl" x="%s" y="%s" text-anchor="middle">%s</text>' % (x, y - 19, e(name))
    return out


def build_map(plan, geo):
    beats = [0] + [b['拍'] for b in plan.beats if b['拍'] is not None]
    cams = {}
    for name, c in plan.cams.items():
        if c['x'] is None or c['y'] is None:
            continue
        look, used = None, []
        for shot, g in zip(plan.shots, geo):
            if name in shot['机位']:
                used += list(range(g['beats'][0], g['beats'][1] + 1))
                if look is None and g.get('look') and g['cam'] == name:
                    look = g['look']
        look = look or plan.xy(c['看向'], beats[-1])
        cams[name] = {'xy': (c['x'], c['y']), 'look': look, 'beats': sorted(set(used)), 'half': plan.lens(name)[1] or 20}
    cones = {}
    for name, c in cams.items():
        if c['look'] and c['look'] != c['xy']:
            length = min(max(math.hypot(c['look'][0] - c['xy'][0], c['look'][1] - c['xy'][1]) * 0.6, 1.2), 2.4)
            cones[name] = cone_points(c['xy'], c['look'], c['half'], length)
    xs = [t['x'] for t in plan.things.values() if t['x'] is not None] + [q[0] for t in plan.things.values() for q in t['ends']]
    ys = [t['y'] for t in plan.things.values() if t['y'] is not None] + [q[1] for t in plan.things.values() for q in t['ends']]
    xs += [c['xy'][0] for c in cams.values()] + [v['xy'][0] for v in plan.views] + [p[0] for pts in cones.values() for p in pts]
    ys += [c['xy'][1] for c in cams.values()] + [v['xy'][1] for v in plan.views] + [p[1] for pts in cones.values() for p in pts]
    if not xs:
        return '<p class="note">俯视图还没有坐标。</p>', {}, beats
    cv = Canvas(xs, ys)
    o = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s" style="min-width:%dpx">' % (
        cv.w, cv.h, e('俯视图：%d 个机位各朝哪拍，人物怎么走' % len(cams)), min(cv.w, 560))]
    for x in range(cv.x0, cv.x1 + 1):
        o.append('<line class="grid" x1="%s" y1="%s" x2="%s" y2="%s"/>' % (cv.X(x), cv.Y(cv.y0), cv.X(x), cv.Y(cv.y1)))
    for y in range(cv.y0, cv.y1 + 1):
        o.append('<line class="grid" x1="%s" y1="%s" x2="%s" y2="%s"/>' % (cv.X(cv.x0), cv.Y(y), cv.X(cv.x1), cv.Y(y)))
    o.append('<text class="axis" x="%s" y="%s">画左</text>' % (M, cv.h - 16))
    o.append('<text class="axis" x="%s" y="%s" text-anchor="end">画右</text>' % (cv.w - M, cv.h - 16))
    o.append('<text class="axis" x="%s" y="%s" text-anchor="middle">远</text>' % (cv.w / 2, 24))
    o.append('<text class="axis" x="%s" y="%s" text-anchor="middle">近</text>' % (cv.w / 2, cv.h - 16))
    # 机位的扇形先画，垫在下面
    order = list(plan.cams)
    for name, pts in cones.items():
        k = order.index(name) % 8 + 1
        o.append('<g data-beats="%s"><polygon class="cone k%d" points="%s"/></g>' % (
            ' '.join(str(b) for b in cams[name]['beats']), k, ' '.join('%s,%s' % cv.P(p) for p in pts)))
    # 固定的东西、灯、点
    for name, t in plan.things.items():
        if t['x'] is None or t['y'] is None:
            continue
        x, y = cv.P((t['x'], t['y']))
        if t['类'] == '固定物':
            if t['ends'][0] != t['ends'][1]:
                (ax, ay), (bx, by) = cv.P(t['ends'][0]), cv.P(t['ends'][1])
                o.append('<line class="fxbar" x1="%s" y1="%s" x2="%s" y2="%s"/>' % (ax, ay, bx, by))
                o.append('<text class="lbl" x="%s" y="%s" text-anchor="middle">%s</text>' % (x, y - 12, e(name)))
            else:
                o.append('<rect class="fx" x="%s" y="%s" width="68" height="34" rx="7"/>' % (x - 34, y - 17))
                o.append('<text class="lbl" x="%s" y="%s" text-anchor="middle">%s</text>' % (x, y + 4, e(name)))
        elif t['类'] == '灯':
            rays = ''.join('<line class="lamp" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (
                x + 11 * math.cos(a), y + 11 * math.sin(a), x + 16 * math.cos(a), y + 16 * math.sin(a))
                for a in [math.radians(d) for d in range(0, 360, 45)])
            o.append('<circle class="lamp" cx="%s" cy="%s" r="7"/>%s' % (x, y, rays))
            o.append('<text class="lamptxt" x="%s" y="%s" text-anchor="middle">%s</text>' % (x, y + 30, e(name)))
        elif t['类'] == '点':
            o.append('<circle class="pt" cx="%s" cy="%s" r="17"/>' % (x, y))
            o.append('<text class="sub" x="%s" y="%s" text-anchor="middle">%s</text>' % (x, y + 31, e(name)))
    # 机位在动的镜头：从起点到终点的虚线
    for shot, a, b, arc, shot_beats in camera_moves(plan, geo):
        if a not in cams or b not in cams:
            continue
        line = move_curve(cv.P(cams[a]['xy']), cv.P(cams[b]['xy']), cv.P(cams[b]['look']) if cams[b]['look'] else None, arc, 18)
        if not line:
            continue
        (sx, sy), (cx, cy), (tx, ty) = line
        d = math.hypot(tx - cx, ty - cy) or 1.0
        ux, uy = (tx - cx) / d, (ty - cy) / d
        k = order.index(b) % 8 + 1
        mx, my = curve_mid(*line)
        o.append('<g data-beats="%s"><path class="cm k%d" d="M%.1f %.1f Q%.1f %.1f %.1f %.1f"/>'
                 '<polygon class="k%d" points="%.1f,%.1f %.1f,%.1f %.1f,%.1f"/>'
                 '<text class="sub" x="%.1f" y="%.1f" text-anchor="middle">%s</text></g>' % (
                     ' '.join(str(x) for x in range(shot_beats[0], shot_beats[1] + 1)), k, sx, sy, cx, cy, tx - ux * 6, ty - uy * 6,
                     k, tx, ty, tx - ux * 10 - uy * 5, ty - uy * 10 + ux * 5, tx - ux * 10 + uy * 5, ty - uy * 10 - ux * 5,
                     mx, my - 10, e(shot_tag(plan, shot))))
    # 人：全程、每一拍
    paths = check.moves(plan)
    full = ['<g data-beat="all">']
    for who, path in paths.items():
        spots, seen = [], []
        for raw, spot, pose, beat in path:
            if spot in plan.things and (not spots or spots[-1][1] != spot):
                spots.append((raw, spot, beat, '离场' in pose))
        for i, (raw, spot, beat, gone) in enumerate(spots):
            p = plan.xy(spot, 0)
            if not p:
                continue
            if i:
                q = plan.xy(spots[i - 1][1], 0)
                full.append(arrow(cv, q, p, end_gap=20 if gone else None))
                (qx, qy), (px, py) = cv.P(q), cv.P(p)
                d = math.hypot(px - qx, py - qy) or 1.0
                nx, ny = -(py - qy) / d, (px - qx) / d                  # 垂直于箭头的方向
                if ny > 0:
                    nx, ny = -nx, -ny                                   # 字放在箭头的上方一侧
                full.append('<text class="sub" x="%.1f" y="%.1f" text-anchor="middle">%s 第 %s 拍%s</text>' % (
                    (qx + px) / 2 + nx * 16, (qy + py) / 2 + ny * 16 + 4, e(who), e(raw), '离场' if gone else ''))
            if spot not in seen and not gone:
                st = plan.state(who, beat if beat is not None else 0)
                target = plan.gaze(st['朝向']) if st and i == 0 else None
                full.append(person(cv, who, p, plan.xy(target, beat or 0) if target else None, ghost=i > 0))
                seen.append(spot)
    full.append('</g>')
    o += full
    notes = {'all': '全程：实心是开场的位置，空心是后来走到的位置，虚线箭头是走位。'}
    for b in beats:
        o.append('<g data-beat="%s" hidden>' % b)
        for who in plan.people:
            st = plan.state(who, b)
            p = plan.xy(st['点'], b) if st else None
            if not p or st['离场']:
                continue
            target = plan.gaze(st['朝向'])
            o.append(person(cv, who, p, plan.xy(target, b) if target else None))
        o.append('</g>')
        info = next((x for x in plan.beats if x['拍'] == b), None)
        notes[str(b)] = '开场：每个人一开始在哪。' if b == 0 else '第 %s 拍：%s' % (b, info['内容'] if info else '')
    # 机位的机身最后画，压在上面
    for name, c in cams.items():
        k = order.index(name) % 8 + 1
        x, y = cv.P(c['xy'])
        o.append('<g data-beats="%s"><title>%s</title><rect class="body k%d" x="%s" y="%s" width="24" height="20" rx="5"/>'
                 '<text class="camtxt" x="%s" y="%s" text-anchor="middle">%s</text></g>' % (
                     ' '.join(str(b) for b in c['beats']), e(cam_note(plan, name)), k, x - 12, y - 10, x, y + 4.5, e(name)))
    o.append('</svg>')
    return '\n'.join(o), notes, beats


def render(plan):
    geo = check.all_geometry(plan)
    name = scene_name(plan)
    svg, notes, beats = build_map(plan, geo)
    picks = '<button type="button" data-pick="all" aria-pressed="true">全程</button>' + ''.join(
        '<button type="button" data-pick="%s" aria-pressed="false">%s</button>' % (b, '开场' if b == 0 else '第 %s 拍' % b) for b in beats)
    js_notes = '{' + ', '.join('"%s": "%s"' % (k, v.replace('\\', '\\\\').replace('"', '\\"')) for k, v in notes.items()) + '}'
    return '\n'.join([
        '<title>%s 机位图</title>' % e(name),
        '<meta name="claude:viewport-fit-sides" content="cover">',
        '<style>%s</style>' % CSS,
        '<div class="wrap">',
        '<header><h1>%s · 机位图</h1><p>方案 v%s · %d 个机位 · %d 条 clip、%d 镜 · 按场景图的视角：左边是画左，上边是远处</p></header>' % (
            e(name), e(plan.version if plan.version is not None else '?'), len(plan.cams), len(plan.clips()), len(plan.shots)),
        '<section>',
        '<div class="picks" role="group" aria-label="按拍看">%s</div>' % picks,
        '<p class="note" id="beat-note">%s</p>' % e(notes.get('all', '')),
        '<figure><div class="scroll">%s</div>' % svg,
        '<figcaption>扇形是机位朝哪拍，宽窄是焦段；颜色一样的虚线是这个镜头里机位在动。圆是人，短线是脸朝的方向。虚线圈是人能待的点。</figcaption></figure>',
        '</section>',
        '<p class="note">这一页是脚本按方案画的，改方案以后重新生成。坐标是估的，只管左右、前后和谁挨着谁。机位、站位、分镜的表在方案里。</p>',
        '</div>',
        '<script>%s</script>' % JS.replace('__NOTES__', js_notes),
    ])


# ---------- 对话里直接出的那一张图 ----------

RAMPS = [('c-teal', '#1D9E75'), ('c-purple', '#7F77DD'), ('c-coral', '#D85A30'), ('c-pink', '#D4537E'),
         ('c-blue', '#378ADD'), ('c-green', '#639922')]      # 一个人一种颜色：圆和走位的箭头同色
GRAY = 'var(--s)'                                            # 机位拍的范围、朝向的短线、机位移动的虚线
LAMP = '#BA7517'                                             # 灯是琥珀色


def text_w(s, size):
    """估一行字有多宽：中文一个字比字号略宽，英文和数字约半个字号多一点。"""
    return sum(size * (1.08 if ord(ch) > 0x2E7F else 0.58) for ch in s)


def n(v):
    return '%d' % round(v)


def label(cls, x, y, s, anchor='middle'):
    return '<text class="%s" x="%s" y="%s"%s dominant-baseline="central">%s</text>' % (
        cls, n(x), n(y), '' if anchor == 'start' else ' text-anchor="%s"' % anchor, e(s))


class Board:
    """记着图上哪些地方已经有东西，给一行字找一个不压着别的东西的位置。"""

    def __init__(self, x0, y0, x1, y1):
        self.box, self.taken, self.low = (x0, y0, x1, y1), [], 0.0

    def block(self, x0, y0, x1, y1):
        self.taken.append((x0, y0, x1, y1))
        self.low = max(self.low, y1)

    def block_line(self, pts, pad=4):
        for a, b in zip(pts, pts[1:]):
            steps = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 8))
            for i in range(steps + 1):
                x, y = a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps
                self.block(x - pad, y - pad, x + pad, y + pad)

    def cost(self, box):
        hit = sum(max(0.0, min(box[2], t[2]) - max(box[0], t[0])) * max(0.0, min(box[3], t[3]) - max(box[1], t[1])) for t in self.taken)
        x0, y0, x1, y1 = self.box
        out = max(0.0, x0 - box[0]) + max(0.0, box[2] - x1) + max(0.0, y0 - box[1]) + max(0.0, box[3] - y1)
        return hit + out * 1000

    def place(self, anchors, w, h, r, order='rblu'):
        """给一行宽 w、高 h 的字找位置：在几个候选点的四边和四角试，先贴近、再远一圈，挑压得最少的。
        r 是候选点上那个东西的半径；order 是先试哪几边（u 上、b 下、r 右、l 左）。返回字的中心。"""
        best = None
        for far in (0, 12, 26):
            for x, y in anchors:
                g, k = r + 5 + far, r * 0.7 + 4 + far * 0.7
                side = {'u': (x, y - g - h / 2), 'b': (x, y + g + h / 2), 'r': (x + g + w / 2, y), 'l': (x - g - w / 2, y)}
                for cx, cy in [side[ch] for ch in order] + [(x + k + w / 2, y - k - h / 2), (x - k - w / 2, y - k - h / 2),
                                                           (x + k + w / 2, y + k + h / 2), (x - k - w / 2, y + k + h / 2)]:
                    box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                    c = self.cost(box) + far * 0.5
                    if best is None or c < best[0] - 1e-6:
                        best = (c, cx, cy, box)
        self.block(best[3][0] - 3, best[3][1] - 1, best[3][2] + 3, best[3][3] + 1)
        return best[1], best[2]


def walk(plan, who, lo, hi):
    """这个人在第 lo 拍之前站在哪，加上第 lo 到 hi 拍里换到的点。
    每一项是 [刚到这个点的那一行, 在这个点上最后的那一行]。"""
    rows = [r for r in plan.blocking if r['人物'] == who and r['beat'] is not None and plan.xy(r['点'], 0)]
    before = [r for r in rows if r['beat'] < lo]
    path = [[before[-1], before[-1]]] if before and not before[-1]['离场'] else []
    for r in rows:
        if lo <= r['beat'] <= hi:
            if path and path[-1][0]['点'] == r['点'] and not r['离场']:
                path[-1][1] = r
            else:
                path.append([r, r])
    return path


def segment(a, b, gap_a, gap_b):
    """从 a 到 b 的线段，两头各缩进一点；太短返回 None。"""
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    if d < gap_a + gap_b + 8:
        return None
    ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
    return (a[0] + ux * gap_a, a[1] + uy * gap_a), (b[0] - ux * gap_b, b[1] - uy * gap_b)


def to_box_edge(a, box, gap=4):
    """从 a 朝方框的中心走，停在方框边外 gap 的地方。a 在框里、或走不到，返回 None。"""
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    dx, dy = cx - a[0], cy - a[1]
    d = math.hypot(dx, dy)
    hits = []
    for t in ([(box[0] - a[0]) / dx, (box[2] - a[0]) / dx] if dx else []) + ([(box[1] - a[1]) / dy, (box[3] - a[1]) / dy] if dy else []):
        x, y = a[0] + dx * t, a[1] + dy * t
        if 0 < t <= 1 and box[0] - 0.5 <= x <= box[2] + 0.5 and box[1] - 0.5 <= y <= box[3] + 0.5:
            hits.append(t)
    if not hits or not d:
        return None
    t = max(0.0, min(hits) - gap / d)
    return a[0] + dx * t, a[1] + dy * t


def lead(cam, seg):
    """引导线：从机位那一小片的外面，到 seg 的终点。终点就在跟前（那一片已经指到了）返回 None。"""
    end = seg[1] if seg else None
    d = math.hypot(end[0] - cam[0], end[1] - cam[1]) if end else 0
    if d < 48:
        return None
    return (cam[0] + (end[0] - cam[0]) / d * 38, cam[1] + (end[1] - cam[1]) / d * 38), end


def clear_of(box, spots, reach=64):
    """把一个方框从它压着的人、机位、走位线上挪开：往八个方向一点一点试，挪得最少的那个位置算数；
    挪到 reach 还让不开，就取压得最少的。方框只是个记号，位置差一点没关系。"""
    def hit(dx, dy):
        x0, y0, x1, y1 = box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy
        return sum(max(0.0, min(x1, px + r) - max(x0, px - r)) * max(0.0, min(y1, py + r) - max(y0, py - r)) for px, py, r in spots)

    best = (hit(0, 0), 0.0, 0.0)
    for step in range(4, reach + 1, 4):
        if best[0] <= 0:
            break
        for ux, uy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-0.7, -0.7), (0.7, -0.7), (-0.7, 0.7), (0.7, 0.7)):
            h = hit(ux * step, uy * step)
            if h < best[0] - 1e-6:
                best = (h, ux * step, uy * step)
            if h <= 0:
                break
    return box[0] + best[1], box[1] + best[2], box[2] + best[1], box[3] + best[2]


def chat_svg(plan, geo, clip=None):
    """对话里直接出的那一张图。没有坐标时返回 None。"""
    pairs = [(s, g) for s, g in zip(plan.shots, geo) if clip is None or s['clip'] == clip]
    lo = min([g['beats'][0] for _, g in pairs] or [0]) if clip is not None else 0
    hi = max([g['beats'][1] for _, g in pairs] or [0]) if clip is not None else 10 ** 6
    cams = {}
    for name, c in plan.cams.items():
        if c['x'] is None or c['y'] is None:
            continue
        mine = [(s, g) for s, g in pairs if name in s['机位']]
        if clip is not None and not mine:
            continue
        looks = []                                          # 用这个机位的几镜里，它对着的那个人或东西各在哪
        for s, g in mine:
            if g.get('look') and g['cam'] == name and g['look'] not in looks:
                looks.append(g['look'])
        if not looks and plan.xy(c['看向'], hi):
            looks.append(plan.xy(c['看向'], hi))
        solo, anyone = [], False                            # 单人镜拍的那个人，当时站在哪个点
        for s, g in mine:
            who = [w for w in s['给谁'] if w in g['people']]
            anyone = anyone or bool(who)
            if g['cam'] == name and len(who) == 1 and plan.xy(g['people'][who[0]]['点'], 0) and (who[0], g['people'][who[0]]['点']) not in solo:
                solo.append((who[0], g['people'][who[0]]['点']))
        cams[name] = {'xy': (c['x'], c['y']), 'look': looks[0] if looks else None, 'half': plan.lens(name)[1] or 20,
                      'solo': solo, 'thing': None if anyone else c['看向'].strip()}
    known = {name: t for name, t in plan.things.items() if t['x'] is not None and t['y'] is not None}
    pts = [c['xy'] for c in cams.values()]              # 只框住画出来的东西：按条出的图比全场的紧
    for t in known.values():
        pts += [(t['x'], t['y'])] + list(t['ends'])
    if not pts:
        return None
    wx0, wx1 = min(p[0] for p in pts) - 0.7, max(p[0] for p in pts) + 0.7
    wy0, wy1 = min(p[1] for p in pts) - 0.7, max(p[1] for p in pts) + 0.7
    k = min(500.0 / (wx1 - wx0), 500.0 / (wy1 - wy0), 56.0)
    mw, mh = (wx1 - wx0) * k, (wy1 - wy0) * k
    left, top = (CW - mw) / 2.0, 34.0
    bottom = top + mh

    def P(p):
        return left + (p[0] - wx0) * k, top + (wy1 - p[1]) * k

    board = Board(8, top - 6, CW - 8, bottom + 4)
    under, lines, shapes, texts, late, drawn = [], [], [], [], [], {}
    color = {who: RAMPS[i % len(RAMPS)] for i, who in enumerate(plan.people)}
    paths = {who: walk(plan, who, lo, hi) for who in plan.people}
    paths = {who: p for who, p in paths.items() if p and not (len(p) == 1 and p[0][0]['离场'])}
    # 人站过的地方、走位的线、机位移动的线：先算出来，方框要让开它们
    stands, walks, moving, spots = [], [], [], []
    for who, path in paths.items():
        prev = None
        for i, (first, last) in enumerate(path):
            p = P(plan.xy(first['点'], 0))
            if prev is not None:
                seg = segment(prev, p, 16, 8 if first['离场'] else 18)
                if seg:
                    walks.append((who, seg, first))
            if not first['离场']:
                stands.append((who, p, first, last, i == 0))
                spots.append((p[0], p[1], 17))
            prev = p
    for name, c in cams.items():
        x, y = P(c['xy'])
        spots.append((x, y, 18))
    lamps = [(name, P((t['x'], t['y']))) for name, t in known.items() if t['类'] == '灯']
    spots += [(x, y, 14) for _, (x, y) in lamps]
    for shot, a, b, arc, _ in camera_moves(plan, geo, clip):
        if a in cams and b in cams:
            line = move_curve(P(cams[a]['xy']), P(cams[b]['xy']), P(cams[b]['look']) if cams[b]['look'] else None, arc, 17)
            if line:
                (sx, sy), (cx, cy), (tx, ty) = line
                curve = [((1 - u) ** 2 * sx + 2 * u * (1 - u) * cx + u * u * tx, (1 - u) ** 2 * sy + 2 * u * (1 - u) * cy + u * u * ty)
                         for u in [i / 8.0 for i in range(9)]]
                moving.append((shot_tag(plan, shot, clip), line, curve))
    for _, seg, _ in walks:
        steps = max(1, int(math.hypot(seg[1][0] - seg[0][0], seg[1][1] - seg[0][1]) / 8))
        spots += [(seg[0][0] + (seg[1][0] - seg[0][0]) * i / steps, seg[0][1] + (seg[1][1] - seg[0][1]) * i / steps, 6) for i in range(steps + 1)]
    for _, _, curve in moving:
        spots += [(x, y, 6) for x, y in curve]
    leads = []                                              # 引导线：单人镜的机位连到它拍的那个人
    for name, c in cams.items():
        for who, spot in c['solo']:
            line = lead(P(c['xy']), segment(P(c['xy']), P(plan.xy(spot, 0)), 0, 17))
            if line:
                leads.append(line)
                steps = max(1, int(math.hypot(line[1][0] - line[0][0], line[1][1] - line[0][1]) / 8))
                spots += [(line[0][0] + (line[1][0] - line[0][0]) * i / steps, line[0][1] + (line[1][1] - line[0][1]) * i / steps, 5) for i in range(steps + 1)]
    # 固定的东西：一个方框，名字在里面。压到人、机位、灯、走位线就挪开一点
    for name, t in known.items():
        if t['类'] != '固定物':
            continue
        w, h = text_w(name, 14) + 30, 32.0
        (ax, ay), (bx, by) = P(t['ends'][0]), P(t['ends'][1])
        if abs(ay - by) < 1:
            w = max(w, abs(bx - ax))                    # 宽的东西按它占的那一段画
        elif abs(ax - bx) < 1:
            h = max(h, abs(by - ay))
        x, y = P((t['x'], t['y']))
        x0, y0, x1, y1 = clear_of((x - w / 2, y - h / 2, x + w / 2, y + h / 2), spots)
        dx = max(0.0, 8 - x0) - max(0.0, x1 - (CW - 8))
        dy = max(0.0, top - 6 - y0)
        x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
        under.append('<rect class="box" x="%s" y="%s" width="%s" height="%s" rx="6" stroke-width="0.5"/>' % (n(x0), n(y0), n(x1 - x0), n(y1 - y0)))
        under.append(label('th', (x0 + x1) / 2, (y0 + y1) / 2, name))
        board.block(x0, y0, x1, y1)
        drawn[name] = (x0, y0, x1, y1)
    # 灯：画在它的位置上
    for name, (x, y) in lamps:
        rays = ''.join('M%s %sL%s %s' % (n(x + 8 * math.cos(a)), n(y + 8 * math.sin(a)), n(x + 11 * math.cos(a)), n(y + 11 * math.sin(a)))
                       for a in [math.radians(d) for d in range(0, 360, 45)])
        under.append('<circle class="c-amber" cx="%s" cy="%s" r="5" stroke-width="0.5"/><path d="%s" fill="none" stroke="%s" stroke-linecap="round"/>' % (
            n(x), n(y), rays, LAMP))
        board.block(x - 12, y - 12, x + 12, y + 12)
        late.append((name, [(x, y)], text_w(name, 12), 16, 11, 'ts', 'buRl'))
    # 机位拍的范围：从机位张开的一小片，宽窄是焦段。再用一条点线连到它对着的人或东西
    for name, c in cams.items():
        x, y = P(c['xy'])
        board.block(x - 14, y - 10, x + 14, y + 10)
        if c['look'] and c['look'] != c['xy']:
            th = math.atan2(c['look'][1] - c['xy'][1], c['look'][0] - c['xy'][0])
            e1, e2 = [(x + 34 * math.cos(th + sign * math.radians(c['half'])), y - 34 * math.sin(th + sign * math.radians(c['half']))) for sign in (-1, 1)]
            lines.append('<path d="M%s %sL%s %sL%s %sZ" fill="%s" fill-opacity="0.08" stroke="%s" stroke-opacity="0.3" stroke-width="0.5"/>' % (
                n(x), n(y), n(e1[0]), n(e1[1]), n(e2[0]), n(e2[1]), GRAY, GRAY))
            board.block_line([(x, y), e1, e2], 2)                   # 字尽量不压在这片的边上
        if c['thing'] in drawn:                                     # 不拍人的机位：连到它对着的那样东西
            line = lead((x, y), (None, to_box_edge((x, y), drawn[c['thing']])))
            if line:
                leads.append(line)
    for start, end in leads:
        lines.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="0 5"/>' % (
            n(start[0]), n(start[1]), n(end[0]), n(end[1]), GRAY))
        board.block_line([start, end], 2)
    # 机位在动的镜头
    for word, ((sx, sy), (cx, cy), (tx, ty)), curve in moving:
        lines.append('<path d="M%s %sQ%s %s %s %s" fill="none" stroke="%s" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#arrow)"/>' % (
            n(sx), n(sy), n(cx), n(cy), n(tx), n(ty), GRAY))
        board.block_line(curve)
    # 走位
    for who, seg, row in walks:
        lines.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1.5" marker-end="url(#arrow)"/>' % (
            n(seg[0][0]), n(seg[0][1]), n(seg[1][0]), n(seg[1][1]), color[who][1]))
        board.block_line(list(seg))
        if row['离场']:
            word = '第 %s 拍离场，往%s' % (row['拍'], row['点'])
            late.append((word, [seg[1], ((seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2)], text_w(word, 14), 18, 4, 't'))
    # 人和脸朝哪
    for who, p, first, last, opening in stands:
        board.block(p[0] - 13, p[1] - 13, p[0] + 13, p[1] + 13)
        target = plan.gaze(last['朝向'])
        g = plan.xy(target, last['beat']) if target else None
        if g and g != plan.xy(first['点'], 0):
            gx, gy = P(g)
            d = math.hypot(gx - p[0], gy - p[1]) or 1.0
            ux, uy = (gx - p[0]) / d, (gy - p[1]) / d
            f0, f1 = (p[0] + ux * 16, p[1] + uy * 16), (p[0] + ux * 27, p[1] + uy * 27)
            shapes.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1.5" stroke-linecap="round"/>' % (
                n(f0[0]), n(f0[1]), n(f1[0]), n(f1[1]), GRAY))
            board.block_line([f0, f1], 3)
        if opening:
            shapes.append('<circle class="%s" cx="%s" cy="%s" r="12" stroke-width="0.5"/>' % (color[who][0], n(p[0]), n(p[1])))
            late.insert(0, (who, [p], text_w(who, 14), 18, 12, 't'))
        else:
            shapes.append('<circle cx="%s" cy="%s" r="12" fill="none" stroke="%s" stroke-dasharray="4 4"/>' % (n(p[0]), n(p[1]), color[who][1]))
            word = '第 %s 拍到%s' % (first['拍'], first['点'])
            late.append((word, [p], text_w(word, 14), 18, 12, 't'))
    # 机位的方块
    for name, c in cams.items():
        x, y = P(c['xy'])
        shapes.append('<g><title>%s</title><rect class="box" x="%s" y="%s" width="26" height="18" rx="4" stroke-width="0.5"/>%s</g>' % (
            e(cam_note(plan, name)), n(x - 13), n(y - 9), label('th', x, y, name[:2])))
        if len(cams) <= 3:                                  # 机位少、图上有地方，就把它拍什么写在旁边
            word = re.split(r'[，,；;。]', plan.cams[name]['拍什么'])[0][:14]
            if word:
                late.append((word, [(x, y)], text_w(word, 14), 18, 13, 't'))
    for word, line, _ in moving:
        late.append((word, [curve_mid(*line)], text_w(word, 14), 18, 4, 't'))
    # 字最后放：先人名，再别的
    for item in late:
        word, anchors, w, h, r, cls = item[:6]
        cx, cy = board.place(anchors, w, h, r, *[o.lower() for o in item[6:]])
        texts.append(label(cls, cx, cy, word))
    # 四边写方向：按场景图的视角
    mid = left + mw / 2
    texts += [label('ts', mid, top - 18, '远'), label('ts', mid, bottom + 16, '近（场景图是从这边拍的）'),
              label('ts', left, bottom + 16, '画左', 'start'), label('ts', left + mw, bottom + 16, '画右', 'end')]
    # 图例
    items = [('<circle class="c-gray" cx="%s" cy="%s" r="6" stroke-width="0.5"/>', '这一条开头的位置' if clip is not None else '开场的位置')]
    if any(not opening for _, _, _, _, opening in stands):
        items.append(('<circle cx="%s" cy="%s" r="6" fill="none" stroke="' + GRAY + '" stroke-dasharray="3 3"/>', '后来走到的位置'))
    items.append(('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="' + GRAY + '" stroke-width="1.5" stroke-linecap="round"/>', '脸朝哪'))
    items.append(('<rect class="box" x="%s" y="%s" width="16" height="12" rx="3" stroke-width="0.5"/>', '机位，张开的一片越窄焦段越长'))
    if leads:
        items.append(('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="' + GRAY + '" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="0 5"/>', '单人镜拍的是谁'))
    if moving:
        items.append(('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="' + GRAY + '" stroke-width="1.5" stroke-dasharray="5 4"/>', '镜头里机位在动'))
    legend, x, y = [], 40.0, bottom + 46
    for glyph, word in items:
        w = (26 if glyph else 0) + text_w(word, 12)
        if x + w > CW - 40 and x > 40:
            x, y = 40.0, y + 22
        if glyph.startswith('<circle'):
            legend.append(glyph % (n(x + 8), n(y)))
        elif glyph.startswith('<rect'):
            legend.append(glyph % (n(x), n(y - 6)))
        elif glyph:
            legend.append(glyph % (n(x), n(y), n(x + 18), n(y)))
        legend.append(label('ts', x + (26 if glyph else 0), y, word, 'start'))
        x += w + 20
    title = '%s 俯视图%s' % (scene_name(plan), ' clip%02d' % clip if clip is not None else '')
    desc = '%d 个机位各在哪、朝哪拍；%s 的站位和走位。左边是画左，上边是远处。' % (len(cams), '、'.join(paths) or '人物')
    return '\n'.join(
        ['<svg width="100%%" viewBox="0 0 %d %s" role="img"><title>%s</title><desc>%s</desc>' % (CW, n(y + 26), e(title), e(desc)),
         '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
         '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>']
        + under + lines + shapes + texts + legend + ['</svg>'])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plan')
    ap.add_argument('--chat', action='store_true', help='只出一张 SVG，交给对话里的画图工具（默认用这种）')
    ap.add_argument('--clip', type=int, help='和 --chat 一起用：只画这一条 clip')
    ap.add_argument('--out')
    ap.add_argument('--standalone', action='store_true', help='页面做成完整网页，直接用浏览器打开（不发布成 Artifact 时用）')
    args = ap.parse_args(argv)
    path = Path(args.plan)
    if not path.is_file():
        print('找不到方案：%s' % path)
        return 2
    plan = check.Plan(path)
    if args.clip is not None and not args.chat:
        print('--clip 只和 --chat 一起用')
        return 2
    if args.chat:
        if args.clip is not None and args.clip not in plan.clips():
            print('方案里没有 clip%02d' % args.clip)
            return 2
        svg = chat_svg(plan, check.all_geometry(plan), args.clip)
        if svg is None:
            print('俯视图还没有坐标。')
            return 2
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(svg + '\n', encoding='utf-8')
            print(args.out)
        else:
            print(svg)
        return 0
    out = Path(args.out) if args.out else path.with_name(re.sub(r'\.plan\.md$', '', path.name) + '.topview.html')
    out.parent.mkdir(parents=True, exist_ok=True)
    page = render(plan)
    if args.standalone:
        page = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n'
                + page + '\n</body>\n</html>\n')
    out.write_text(page, encoding='utf-8')
    print(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
