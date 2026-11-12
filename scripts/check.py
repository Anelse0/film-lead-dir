#!/usr/bin/env python3
"""film-lead-dir 的检查。结果只有过和不过。

  python3 scripts/check.py dock1  <方案.plan.md>     第一次停靠前：解释、定调
  python3 scripts/check.py dock2  <方案.plan.md>     第二次停靠前：表演
  python3 scripts/check.py dock3  <方案.plan.md>     第三次停靠前：空间、镜头
  python3 scripts/check.py prompt <Prompt.prompt.md> [--plan 方案]            交 Prompt 前
  python3 scripts/check.py qa     <Prompt.prompt.md> [--plan 方案] [--log 场记录]  QA 记完以后
  python3 scripts/check.py map    <方案.plan.md>     只打印俯视图

后面的时机会把前面的也查一遍。退出码：0 过；1 不过；2 用法或文件有问题。
格式以 templates/ 的三份模板为准；每一项查什么，见 references/ 里对应那一步的文件。
"""
import argparse
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / 'references' / 'current-style.md'
PREF_NAME = '导演偏好.md'
RATE_EN, RATE_ZH = 3.5, 4.0
MAX_CLIP, MAX_CHARS = 30, 15000
LONG_CELL, LONG_RECORD = 120, 80
IN_VIEW = 50                      # 偏离镜头正前方多少度以内算在画里
SECTIONS = {1: '解释', 2: '定调', 3: '表演', 4: '空间', 5: '镜头'}
PROMPT_SECTIONS = ['素材绑定', '总述', '画面基调', '起始状态', '分镜时间线', '贯穿要求']
QA_NAMES = ['台词', '说法和声音', '空间', '动作', '衔接', '表演', '节奏', '写法']
MUSIC_WORDS = ['音乐', '背景音乐', 'BGM', '配乐', '器乐', '旋律', '铺底音']
KINDS = ('固定物', '灯', '点')
LENSES = {'广角': 35, '中长焦': 15, '中焦': 24, '长焦': 10}     # 焦段 → 画面横向一半的张角（度），只用来粗筛
TIGHT = ('近景', '特写', '大特写')
ASKED_ONLY = ('低角度', '仰拍', '顶视', '倾斜', '荷兰角', '固定机位')   # 用户点名才用


# ---------- 读文件 ----------

def read(path):
    return Path(path).read_text(encoding='utf-8')


PLACEHOLDER = re.compile(r'^\[[^\]]*\]$')


def empty(s):
    """没填：空的，或者还是模板里的方括号。"""
    s = (s or '').strip()
    return not s or bool(PLACEHOLDER.match(s))


def none(s):
    return (s or '').strip() in ('', '无', '—', '-', '－', '－－')


def split_cells(line):
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    return [c.strip() for c in line.split('|')]


def first_table(text):
    """文本里的第一张 Markdown 表：(表头, [行字典])。"""
    block = []
    for line in (text or '').splitlines():
        if line.strip().startswith('|'):
            block.append(line)
        elif block:
            break
    if len(block) < 2:
        return [], []
    head = split_cells(block[0])
    rows = []
    for line in block[2:]:
        cells = split_cells(line)
        cells += [''] * (len(head) - len(cells))
        if any(cells):
            rows.append(dict(zip(head, cells)))
    return head, rows


def get(row, key):
    """按栏名取格子：先找同名的栏，再找栏名里含这个词的。"""
    if key in row:
        return row[key].strip()
    for k, v in row.items():
        if key in k:
            return v.strip()
    return ''


def field(text, name):
    m = re.search(r'^- *' + re.escape(name) + r' *[：:][ \t]*(.*)$', text or '', re.M)
    return m.group(1).strip() if m else None


def subfields(text, name):
    """`- 名字：` 下面缩进的 `- 甲：乙` 几行。"""
    m = re.search(r'^- *' + re.escape(name) + r' *[：:].*\n((?:[ \t]+- .*(?:\n|$))*)', text or '', re.M)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r'\s*- *([^：:]+?) *[：:] *(.*)$', line)
            if mm:
                out[mm.group(1).strip()] = mm.group(2).strip()
    return out


def h3split(body):
    out, name, buf = {}, '', []
    for line in body.splitlines():
        m = re.match(r'###\s+(.+?)\s*$', line)
        if m:
            out[name] = '\n'.join(buf)
            name, buf = m.group(1), []
        else:
            buf.append(line)
    out[name] = '\n'.join(buf)
    return out


def ints(text):
    return [int(x) for x in re.findall(r'\d+', text or '')]


def num(text):
    m = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*$', text or '')
    return float(m.group(1)) if m else None


def fmt(x):
    return ('%.1f' % (x + 1e-9)).rstrip('0').rstrip('.')


def span(text):
    """坐标格：一个数，或一段「2~8」（墙、幕布这类宽的东西）。返回 (中点, 起, 止)。"""
    m = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*[~～]\s*(-?\d+(?:\.\d+)?)\s*$', text or '')
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return (a + b) / 2, a, b
    v = num(text)
    return v, v, v


def half_up(x):
    return int(math.floor(x + 0.5))


def names_in(text):
    return [n.strip() for n in re.split(r'[、,，和]', text or '') if n.strip()]


# ---------- 词数和秒数 ----------

CJK = re.compile(r'[一-鿿]')
WORD = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")


def count(text):
    """(英文词数, 中文字数)。缩写、带连字符的算一个词。"""
    text = text or ''
    return len(WORD.findall(CJK.sub(' ', text))), len(CJK.findall(text))


def seconds(text, rates, own=None):
    en, zh = count(text)
    r_en, r_zh = rates
    if own:
        if en >= zh:
            r_en = own
        else:
            r_zh = own
    return round(en / r_en + zh / r_zh + 1e-9, 1)


# ---------- 禁写词 ----------

def parse_banned(text):
    m = re.search(r'^## *禁写词[^\n]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    cats = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r'\s*- *([^：:\s]{1,8}) *[：:](.+)$', line)
            if mm:
                cats[mm.group(1)] = [w.strip() for w in re.split(r'[、,，]', mm.group(2)) if w.strip()]
    return cats


def find_up(start, name):
    d = Path(start).resolve()
    for _ in range(8):
        if (d / name).is_file():
            return d / name
        if d.parent == d:
            break
        d = d.parent
    return None


def banned_for(path):
    cats = parse_banned(read(STYLE)) if STYLE.is_file() else {}
    pref = find_up(Path(path).parent, PREF_NAME)
    if pref:
        cats.update(parse_banned(read(pref)))
    return cats


def scan_banned(text, cats, allow):
    hits = []
    for cat, words in cats.items():
        for w in words:
            if w in allow:
                continue
            if w in text:
                hits.append((cat, w))
    return hits


# ---------- 方案 ----------

class Plan:
    def __init__(self, path):
        self.path = Path(path)
        text = read(path)
        parts = re.split(r'^(?=## )', text, flags=re.M)
        self.head = parts[0]
        self.sec = {}
        for part in parts[1:]:
            title, _, body = part.partition('\n')
            m = re.match(r'##\s+([1-5])\s+(\S+?)(?:\s*·\s*(.*?))?\s*$', title)
            if not m:
                continue
            body = re.split(r'^---\s*\n+怎么填', body, maxsplit=1, flags=re.M)[0]
            self.sec[int(m.group(1))] = {'status': (m.group(3) or '').strip(), 'body': body, 'h3': h3split(body)}
        m = re.search(r'^- *版本 *[：:] *v(\d+)', self.head, re.M)
        self.version = int(m.group(1)) if m else None
        allow = field(self.head, '放行') or ''
        self.allow = [] if none(allow) else [re.split(r'[（(]', a)[0].strip() for a in re.split(r'[；;]', allow) if a.strip()]
        self._parse()

    def h3(self, n, name):
        h3 = self.sec.get(n, {}).get('h3', {})
        if name in h3:
            return h3[name]
        for key, text in h3.items():
            if key and (name in key or key in name):
                return text
        return ''

    def top(self, n):
        return self.sec.get(n, {}).get('h3', {}).get('', '')

    def rows(self, n, name):
        return first_table(self.h3(n, name))[1]

    def _parse(self):
        self.cast = list(subfields(self.top(1), '人物状态'))
        self.beats = []
        for r in self.rows(1, '节拍'):
            b = ints(get(r, '拍'))
            self.beats.append({'拍': b[0] if b else None, '内容': get(r, '内容'), '想要': get(r, '想要'),
                               '在场': names_in(get(r, '在场'))})
        sound = self.h3(2, '声音')
        en = re.search(r'(\d+(?:\.\d+)?)\s*词\s*/\s*秒', sound)
        zh = re.search(r'(\d+(?:\.\d+)?)\s*字\s*/\s*秒', sound)
        self.rates = (float(en.group(1)) if en else RATE_EN, float(zh.group(1)) if zh else RATE_ZH)
        self.rate_given = bool(en or zh)
        self.music_none = none(field(sound, '音乐') or '无')
        self.lines = []
        for r in self.rows(1, '台词'):
            n, b = ints(get(r, '句')), ints(get(r, '拍'))
            own = num(get(r, '语速'))
            text = get(r, '台词')
            self.lines.append({'句': n[0] if n else None, '拍': b[0] if b else None, '说话人': get(r, '说话人'),
                               '台词': text, '词数': get(r, '词数'), '秒数': get(r, '秒数'),
                               '算词数': sum(count(text)), '算秒数': seconds(text, self.rates, own)})
        self.line = {l['句']: l for l in self.lines if l['句'] is not None}
        self.refs = [{'图': get(r, '图'), '主体': get(r, '主体'), '用于': get(r, '用于'), '不采用': get(r, '不采用')}
                     for r in self.rows(2, '参考图')]
        m = re.search(r'^缺 *[：:] *(.*)$', self.h3(2, '参考图'), re.M)
        self.missing = m.group(1).strip() if m else ''
        self.arcs = self.rows(3, '情绪线')
        self.perf = []
        for r in self.rows(3, '表演表'):
            b = ints(get(r, '拍'))
            raw = get(r, '句')
            kind, covers = 'none', set()
            if re.match(r'^\d+$', raw):
                kind, covers = 'say', {int(raw)}
            elif raw.startswith('听'):
                kind = 'listen'
                for a, z in re.findall(r'(\d+)\s*[–\-—~～至到]\s*(\d+)', raw):
                    covers |= set(range(int(a), int(z) + 1))
                covers |= set(ints(re.sub(r'(\d+)\s*[–\-—~～至到]\s*(\d+)', ' ', raw)))
            self.perf.append({'拍': b[0] if b else None, '人物': get(r, '人物'), '句': raw, 'kind': kind, 'covers': covers,
                              '情绪': get(r, '情绪'), '动作': get(r, '动作'), '表情': get(r, '表情'),
                              '说法': get(r, '台词怎么说'), '触发': get(r, '触发')})
        # 空间
        self.things = {}
        for r in self.rows(4, '俯视图'):
            name = get(r, '名字')
            if name:
                x, x0, x1 = span(get(r, 'x'))
                y, y0, y1 = span(get(r, 'y'))
                ends = [(x0, y0), (x1, y1)] if x is not None and y is not None else []
                self.things[name] = {'类': get(r, '类'), 'x': x, 'y': y, 'ends': ends, '说明': get(r, '说明')}
        self.views = []
        for m in re.finditer(r'(@\S+?)\s*在\s*[（(]\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*[)）]\s*看向\s*([^\s，。；;]+)',
                             self.sec.get(4, {}).get('body', '')):
            self.views.append({'图': m.group(1), 'xy': (float(m.group(2)), float(m.group(3))), '看向': m.group(4)})
        self.blocking = []
        for r in self.rows(4, '站位'):
            raw = get(r, '拍')
            b = 0 if raw.startswith('起') else (ints(raw)[0] if ints(raw) else None)
            self.blocking.append({'拍': raw, 'beat': b, '人物': get(r, '人物'), '点': get(r, '点'), '位置': get(r, '位置'),
                                  '姿态': get(r, '姿态'), '朝向': get(r, '脸朝'), '手里': get(r, '手里'), '主光': get(r, '主光'),
                                  '离场': '离场' in get(r, '姿态')})
        self.people = list(dict.fromkeys(self.cast + [r['人物'] for r in self.blocking if r['人物']]))
        # 镜头
        self.cuts = [{'之后': ints(get(r, '在哪拍')), '理由': get(r, '理由'), '接缝': get(r, '接缝'), '怎么接': get(r, '怎么接')}
                     for r in self.rows(5, '切点')]
        self.cams = {}
        for r in self.rows(5, '机位'):
            name = re.sub(r'^机位\s*', '', get(r, '机位')).strip()
            if name:
                self.cams[name] = {'x': num(get(r, 'x')), 'y': num(get(r, 'y')), '看向': get(r, '看向'), '高度': get(r, '高度'),
                                   '焦段': get(r, '焦段'), '在哪': get(r, '在哪'), '拍什么': get(r, '拍什么'), '备注': get(r, '备注')}
        self.shots = []
        for r in self.rows(5, '分镜'):
            t = re.match(r'^\s*(\d+)\s*[-–—]\s*(\d+)\s*(?:秒|s)?\s*$', get(r, '时间'))
            c, s = ints(get(r, 'clip')), ints(get(r, '镜'))
            pairs = []
            for item in names_in(get(r, '表演表的行')):
                if none(item):
                    continue
                m = re.match(r'^(\d+)\s*-\s*(.+)$', item)
                pairs.append((int(m.group(1)), m.group(2).strip()) if m else (None, item))
            self.shots.append({'clip': c[0] if c else None, '镜': s[0] if s else None, '时间': get(r, '时间'),
                               'a': int(t.group(1)) if t else None, 'b': int(t.group(2)) if t else None,
                               '机位': [re.sub(r'^机位\s*', '', x).strip() for x in re.split(r'→|->', get(r, '机位')) if x.strip()],
                               '给谁': names_in(get(r, '画面给谁')), '景别': get(r, '景别'),
                               '运镜': get(r, '运镜'), '接法': get(r, '接法'), '画面': get(r, '画面与声音'),
                               '行': pairs, '句': ints(get(r, '句'))})
        body5 = self.sec.get(5, {}).get('body', '')
        self.clip_reason = field(body5, '条数理由') or ''

    # --- 取数 ---

    def clips(self):
        return sorted({s['clip'] for s in self.shots if s['clip'] is not None})

    def lens(self, cam):
        """机位的焦段：(名字, 半张角)。认不出返回 (None, None)。"""
        text = self.cams.get(cam, {}).get('焦段', '')
        for name in ('中长焦', '广角', '中焦', '长焦'):
            if name in text:
                return name, LENSES[name]
        return None, None

    def clip_shots(self, clip):
        return [s for s in self.shots if s['clip'] == clip]

    def shot_beats(self, shot, prev=0):
        beats = [b for b, _ in shot['行'] if b is not None]
        beats += [self.line[n]['拍'] for n in shot['句'] if n in self.line and self.line[n]['拍'] is not None]
        return (min(beats), max(beats)) if beats else (prev, prev)

    def state(self, person, beat):
        """这个人在这一拍的那一行站位。还没进场、或者已经离场（姿态里写了「离场」的那一拍之后），返回 None。"""
        rows = [r for r in self.blocking if r['人物'] == person and r['beat'] is not None and r['beat'] <= beat]
        if not rows or (rows[-1]['离场'] and rows[-1]['beat'] < beat):
            return None
        return rows[-1]

    def lamp_of(self, row):
        cell = row['主光']
        if cell.startswith('同上'):
            mine = [r for r in self.blocking if r['人物'] == row['人物']]
            i = mine.index(row)
            return self.lamp_of(mine[i - 1]) if i > 0 else None
        lamps = sorted((n for n, t in self.things.items() if t['类'] == '灯' and n in cell), key=len, reverse=True)
        return lamps[0] if lamps else None

    def xy(self, name, beat, cam_xy=None):
        name = (name or '').strip()
        t = self.things.get(name)
        if t and t['x'] is not None and t['y'] is not None:
            return (t['x'], t['y'])
        if name in self.people:
            st = self.state(name, beat)
            return self.xy(st['点'], beat) if st and st['点'] in self.things else None
        m = re.match(r'^[（(]?\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*[)）]?$', name)
        if m:
            return (float(m.group(1)), float(m.group(2)))
        if name == '镜头':
            return cam_xy
        return None

    def gaze(self, text):
        """从"脸朝哪、看谁"里认出看的是谁或什么。认不出返回 None。"""
        known = sorted(set(self.things) | set(self.people) | {'镜头'}, key=len, reverse=True)
        for kw in ('看', '朝'):
            i = text.find(kw)
            while i != -1:
                rest = text[i + 1:i + 14]
                best = None
                for n in known:
                    j = rest.find(n)
                    if j != -1 and (best is None or j < best[0]):
                        best = (j, n)
                if best:
                    return best[1]
                i = text.find(kw, i + 1)
        return None


# ---------- 俯视图的几何 ----------

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def unit(v):
    d = math.hypot(v[0], v[1])
    return (v[0] / d, v[1] / d) if d else (0.0, 0.0)


def between(a, b):
    a, b = unit(a), unit(b)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b)))))


def view(cam, look, p):
    """p 在这个机位的画面里：横向角度（正 = 画右）和纵深（> 0 在镜头前）。"""
    f = unit(sub(look, cam))
    r = (f[1], -f[0])
    d = sub(p, cam)
    return math.degrees(math.atan2(dot(d, r), dot(d, f))), dot(d, f)


def face_of(p, gaze, cam):
    a = between(sub(gaze, p), sub(cam, p))
    return '正脸' if a <= 20 else '3/4 侧脸' if a <= 65 else '侧脸' if a <= 110 else '背对'


def light_of(p, gaze, cam, look, lamp):
    """主光从哪来，亮的是哪半边。"""
    g = sub(gaze, p)
    a = between(g, sub(lamp, p))
    where = '正前方' if a < 20 else '侧前方' if a <= 80 else '正侧面' if a <= 100 else '背后'
    sl, sc = cross(g, sub(lamp, p)), cross(g, sub(cam, p))
    if where == '背后':
        return where, '背光'
    if between(g, sub(cam, p)) < 8 or abs(sc) < 1e-9:
        return where, '画右半边' if view(cam, look, lamp)[0] > view(cam, look, p)[0] else '画左半边'
    if where == '正前方' or abs(sl) < 1e-9:
        return where, '两边差不多'
    return where, '远离镜头的半边' if (sl > 0) != (sc > 0) else '靠近镜头的半边'


def side_word(angle):
    return '画左' if angle < -8 else '画右' if angle > 8 else '中间'


def shot_geometry(plan, shot, prev_beat=0):
    """一镜里看得见的人和东西，按机位算。算不了的原因放在 'why'。"""
    out = {'镜': shot['镜'], 'clip': shot['clip'], 'people': {}, 'things': [], 'order': [], 'behind': [], 'why': None,
           'cam': shot['机位'][-1] if shot['机位'] else None, 'view': None}
    cam = plan.cams.get(out['cam']) if out['cam'] else None
    b0, b1 = plan.shot_beats(shot, prev_beat)
    out['beats'] = (b0, b1)
    if not cam or cam['x'] is None or cam['y'] is None:
        out['why'] = '机位没有坐标'
        return out
    c = (cam['x'], cam['y'])
    look = plan.xy(cam['看向'], b1)
    if not look or look == c:
        out['why'] = '机位的「看向」认不出来'
        return out
    out['c'], out['look'] = c, look
    for v in plan.views:
        vlook = plan.xy(v['看向'], b1)
        if vlook:
            a = between(sub(look, c), sub(vlook, v['xy']))
            out['view'] = (v['图'], '同侧' if a <= 60 else '侧面' if a <= 120 else '反打')
            break
    seen = []
    for person in plan.people:
        st = plan.state(person, b1)
        if not st:
            continue
        p = plan.xy(st['点'], b1)
        if not p:
            continue
        ang, depth = view(c, look, p)
        info = {'angle': ang, 'depth': depth, 'in': depth > 0 and abs(ang) <= IN_VIEW, '点': st['点'], 'row': st,
                'face': None, 'light': None, 'lamp': None, 'moved': False}
        early = plan.state(person, b0)
        info['moved'] = bool(early and early['点'] != st['点'])
        target = plan.gaze(st['朝向'])
        g = plan.xy(target, b1, c) if target else None
        if target in plan.people and not g:
            info['gone'] = target                                      # 他看的人这时候不在场，脸和光算不了
        if g and g != p:
            info['face'] = face_of(p, g, c)
            lamp = plan.lamp_of(st)
            lxy = plan.xy(lamp, b1) if lamp else None
            if lxy:
                info['lamp'] = lamp
                info['light'] = light_of(p, g, c, look, lxy)
        out['people'][person] = info
        if info['in']:
            seen.append((ang, person))
    out['order'] = [n for _, n in sorted(seen)]
    far = max([out['people'][n]['depth'] for n in shot['给谁'] if n in out['people']] or [0])
    for name, t in plan.things.items():
        if t['类'] == '点' or t['x'] is None or t['y'] is None:
            continue
        (ax, ay), (bx, by) = t['ends']
        pts = [(ax + (bx - ax) * k / 4.0, ay + (by - ay) * k / 4.0) for k in range(5)]
        seen_pts = [view(c, look, q) for q in pts]
        ang, depth = view(c, look, (t['x'], t['y']))
        if any(d > 0 and abs(a) <= IN_VIEW for a, d in seen_pts):
            out['things'].append((ang, name))
            if t['类'] == '固定物' and any(d > far and abs(a) <= 25 for a, d in seen_pts):
                out['behind'].append(name)
    out['things'] = [n for _, n in sorted(out['things'])]
    return out


def all_geometry(plan):
    geo, prev = [], 0
    for shot in plan.shots:
        g = shot_geometry(plan, shot, prev)
        prev = g['beats'][1]
        geo.append(g)
    return geo


def render_map(plan):
    """字符画的俯视图：一格两个字符。"""
    items = []
    counters = {'固定物': 0, '灯': 0, '点': 0}
    letter = {'固定物': 'F', '灯': 'L', '点': 'P'}
    digits = '123456789abcdefghijklmnopqrstuvwxyz'
    for name, t in plan.things.items():
        if t['x'] is None or t['y'] is None or t['类'] not in letter:
            continue
        i = counters[t['类']]
        counters[t['类']] += 1
        items.append((letter[t['类']] + digits[i % len(digits)], name, t['x'], t['y'], t['类']))
    for name, c in plan.cams.items():
        if c['x'] is not None and c['y'] is not None:
            items.append(('C' + name[:1], '机位 ' + name + '，看向 ' + c['看向'], c['x'], c['y'], '机位'))
    for i, v in enumerate(plan.views):
        items.append(('V' + digits[i], '场景图 ' + v['图'] + ' 的视角，看向 ' + v['看向'], v['xy'][0], v['xy'][1], '图'))
    if not items:
        return '俯视图还没有坐标。'
    xs = [i[2] for i in items] + [q[0] for t in plan.things.values() for q in t.get('ends', [])]
    ys = [i[3] for i in items] + [q[1] for t in plan.things.values() for q in t.get('ends', [])]
    x0, x1 = math.floor(min(xs)), math.ceil(max(xs))
    y0, y1 = math.floor(min(ys)), math.ceil(max(ys))
    grid, same = {}, []
    for code, name, x, y, _ in items:
        key = (half_up(x), half_up(y))
        if key in grid:
            same.append((code, grid[key]))
        else:
            grid[key] = code
    for name, t in plan.things.items():
        if t.get('ends') and t['ends'][0] != t['ends'][1]:
            (ax, ay), (bx, by) = t['ends']
            steps = int(max(abs(bx - ax), abs(by - ay)) * 2) + 1
            for k in range(steps + 1):
                key = (half_up(ax + (bx - ax) * k / steps), half_up(ay + (by - ay) * k / steps))
                grid.setdefault(key, '==')
    lines = ['俯视图（按场景图的视角：左边是画左，上边是远处）', '']
    for y in range(y1, y0 - 1, -1):
        lines.append('%4d  ' % y + ' '.join(grid.get((x, y), ' .') for x in range(x0, x1 + 1)))
    lines.append('      ' + ' '.join('%2d' % x for x in range(x0, x1 + 1)))
    lines.append('')
    who = {}
    for r in plan.blocking:
        if r['点']:
            who.setdefault(r['点'], []).append(r['人物'] + '（' + r['拍'] + '）')
    for code, name, x, y, kind in items:
        extra = '：' + '、'.join(who[name]) if kind == '点' and name in who else ''
        lines.append('  %s  %s（%s，%s）%s%s' % (code, name, fmt(x), fmt(y), '  [' + kind + ']' if kind in ('灯',) else '', extra))
    for code, other in same:
        lines.append('  %s 和 %s 在同一格，图上只画了 %s' % (code, other, other))
    if any(t.get('ends') and t['ends'][0] != t['ends'][1] for t in plan.things.values()):
        lines.append('  == 是宽的东西占的那一段')
    return '\n'.join(lines)


# ---------- 报告 ----------

class Report:
    def __init__(self, name):
        self.name = name
        self.bad, self.ask, self.hint, self.info = [], [], [], []

    def out(self):
        if self.bad:
            head = '%s · 不过（%d 处）' % (self.name, len(self.bad))
        elif self.ask:
            head = '%s · 只差要用户给的 %d 项' % (self.name, len(self.ask))
        else:
            head = '%s · 过' % self.name
        lines = [head]
        lines += ['✗ ' + b for b in self.bad]
        if self.ask:
            lines += ['要用户给：'] + ['- ' + a for a in self.ask]
        if self.hint:
            lines += ['提示（不拦）：'] + ['- ' + h for h in self.hint]
        if self.info:
            lines += [''] + self.info
        return '\n'.join(lines)

    def code(self):
        return 1 if self.bad or self.ask else 0


def scan_section(plan, n, cats, rep):
    body = plan.sec.get(n, {}).get('body', '')
    for cat, w in scan_banned(body, cats, plan.allow):
        rep.bad.append('第 %d 段有禁写词「%s」（%s）' % (n, w, cat))


def long_cells(plan, n, names, rep):
    for name in names:
        for r in plan.rows(n, name):
            for k, v in r.items():
                if len(v) > LONG_CELL:
                    rep.hint.append('%s里「%s」一格有 %d 字，考虑拆行：%s…' % (name, k, len(v), v[:16]))


# ---------- 第一次停靠 ----------

def check_dock1(plan, rep, cats):
    for n in (1, 2):
        if n not in plan.sec:
            rep.bad.append('方案里没有第 %d 段（%s）' % (n, SECTIONS[n]))
    if rep.bad:
        return
    top = plan.top(1)
    for name in ('目的', '谁的戏', '支点'):
        if empty(field(top, name)):
            rep.bad.append('第 1 段的「%s」没写' % name)
    if not plan.cast:
        rep.bad.append('「人物状态」下面一个人也没有')
    for person, st in subfields(top, '人物状态').items():
        if empty(st):
            rep.bad.append('%s 的人物状态没写' % person)
    beat_ids = [b['拍'] for b in plan.beats]
    if not plan.beats:
        rep.bad.append('节拍表是空的')
    for b in plan.beats:
        if b['拍'] is None:
            rep.bad.append('节拍表有一行没有编号')
            continue
        for k, label in (('内容', '内容'), ('想要', '谁想要什么')):
            if empty(b[k]):
                rep.bad.append('第 %s 拍的「%s」没写' % (b['拍'], label))
        if not b['在场'] or all(empty(x) for x in b['在场']):
            rep.bad.append('第 %s 拍没写谁在场' % b['拍'])
        for who in b['在场']:
            if not empty(who) and who not in plan.cast:
                rep.bad.append('第 %s 拍在场的 %s 不在「人物状态」里' % (b['拍'], who))
    pivot = ints(field(top, '支点') or '')
    if not pivot:
        rep.bad.append('「支点」要写第几拍')
    elif pivot[0] not in beat_ids:
        rep.bad.append('支点写的第 %d 拍不在节拍表里' % pivot[0])
    if not plan.lines:
        rep.hint.append('台词清单是空的。这场没有台词就不用管')
    seen = set()
    for l in plan.lines:
        tag = '句 %s' % l['句']
        if l['句'] is None:
            rep.bad.append('台词清单有一行没有句号')
            continue
        if l['句'] in seen:
            rep.bad.append('%s 出现了两次' % tag)
        seen.add(l['句'])
        if l['拍'] not in beat_ids:
            rep.bad.append('%s 没有归到节拍表里的某一拍' % tag)
        if empty(l['说话人']):
            rep.bad.append('%s 没写说话人' % tag)
        elif l['说话人'] not in plan.cast:
            rep.bad.append('%s 的说话人 %s 不在「人物状态」里' % (tag, l['说话人']))
        if empty(l['台词']):
            rep.bad.append('%s 的台词是空的' % tag)
            continue
        if num(l['词数']) != l['算词数']:
            rep.bad.append('%s 的词数应为 %d（表里是「%s」）' % (tag, l['算词数'], l['词数']))
        written = num(l['秒数'])
        if written is None or abs(written - l['算秒数']) > 0.05:
            rep.bad.append('%s 的秒数应为 %s（表里是「%s」）' % (tag, fmt(l['算秒数']), l['秒数']))
    total = round(sum(l['算秒数'] for l in plan.lines) + 1e-9, 1)
    m = re.search(r'^合计 *[：:] *(\d+) *句[，,] *([\d.]+) *秒', plan.h3(1, '台词'), re.M)
    if plan.lines and (not m or int(m.group(1)) != len(plan.lines) or abs(float(m.group(2)) - total) > 0.05):
        rep.bad.append('台词清单下面的合计应为「合计：%d 句，%s 秒。」' % (len(plan.lines), fmt(total)))
    # 参考图
    if not plan.refs:
        rep.bad.append('参考图清单是空的')
    for r in plan.refs:
        if empty(r['图']) or empty(r['主体']) or empty(r['用于']):
            rep.bad.append('参考图清单有一行没填全（图、主体、用于）')
    for person in plan.cast:
        mine = [r for r in plan.refs if r['主体'] == person]
        if any('无图' in r['用于'] for r in mine):
            continue
        for need in ('脸', '服装'):
            if not any(need in r['用于'] for r in mine):
                rep.ask.append('%s 没有%s的参考图' % (person, need))
    if not none(plan.missing) and not empty(plan.missing):
        rep.ask.append('缺：' + plan.missing)
    tone = plan.h3(2, '画面基调')
    for name in ('灯和人', '身后'):
        if empty(field(tone, name)):
            rep.bad.append('画面基调的「%s」没写' % name)
    sound = plan.h3(2, '声音')
    for name in ('远近', '动作声', '音乐'):
        if empty(field(sound, name)):
            rep.bad.append('声音的「%s」没写' % name)
    voices = subfields(sound, '音色')
    for person in {l['说话人'] for l in plan.lines if l['说话人'] in plan.cast}:
        if empty(voices.get(person)):
            rep.bad.append('声音里没有 %s 的音色' % person)
    if not plan.rate_given:
        rep.hint.append('声音里没写语速，按英文 %s 词/秒、中文 %s 字/秒算' % (fmt(RATE_EN), fmt(RATE_ZH)))
    scan_section(plan, 2, cats, rep)
    rep.info.append('台词 %d 句，共 %s 秒（英文 %s 词/秒，中文 %s 字/秒）' % (len(plan.lines), fmt(total), fmt(plan.rates[0]), fmt(plan.rates[1])))


# ---------- 第二次停靠 ----------

def check_dock2(plan, rep, cats):
    if 3 not in plan.sec:
        rep.bad.append('方案里没有第 3 段（表演）')
        return
    beat_ids = [b['拍'] for b in plan.beats]
    present = {b['拍']: [w for w in b['在场'] if w in plan.cast] for b in plan.beats}
    on_stage = {w for ws in present.values() for w in ws}
    arcs = {get(r, '人物'): r for r in plan.arcs}
    for person in plan.cast:
        if person not in on_stage:
            continue
        r = arcs.get(person)
        if not r:
            rep.bad.append('情绪线里没有 %s' % person)
            continue
        for key in ('起点', '走势', '到哪', '上限'):
            if empty(get(r, key)):
                rep.bad.append('%s 的情绪线没写「%s」' % (person, key))
    for i, r in enumerate(plan.perf, 1):
        tag = '表演表第 %d 行（%s-%s）' % (i, r['拍'], r['人物'])
        if r['拍'] not in beat_ids:
            rep.bad.append('%s 的拍不在节拍表里' % tag)
        if r['人物'] not in plan.cast:
            rep.bad.append('%s 的人物不在「人物状态」里' % tag)
        if r['kind'] == 'none' and not none(r['句']):
            rep.bad.append('%s 的「句」看不懂：%s。写句号、「听 3」「听 3–5」或「—」' % (tag, r['句']))
        if empty(r['情绪']):
            rep.bad.append('%s 没写情绪' % tag)
        if empty(r['动作']) and empty(r['表情']) and (r['kind'] != 'say' or empty(r['说法'])):
            rep.bad.append('%s 只有情绪，没有动作、表情或说法把它演出来' % tag)
        if re.search(r'转|从.+到', r['情绪']) and (empty(r['触发']) or none(r['触发'])):
            rep.bad.append('%s 的情绪有转折，没写触发点' % tag)
    for b in plan.beats:
        for who in present.get(b['拍'], []):
            if not any(r['拍'] == b['拍'] and r['人物'] == who for r in plan.perf):
                rep.bad.append('第 %s 拍在场的 %s 在表演表里没有行：每一拍，在场的每个人至少一行，写他在做什么' % (b['拍'], who))
    for l in plan.lines:
        n = l['句']
        say = [r for r in plan.perf if r['kind'] == 'say' and n in r['covers']]
        if len(say) != 1:
            rep.bad.append('句 %s 在表演表里应该恰好有一行说话的人，现在是 %d 行' % (n, len(say)))
            continue
        r = say[0]
        if r['人物'] != l['说话人']:
            rep.bad.append('句 %s 的说话人是 %s，表演表里写成了 %s' % (n, l['说话人'], r['人物']))
        if r['拍'] != l['拍']:
            rep.bad.append('句 %s 在台词清单里归第 %s 拍，表演表里写在第 %s 拍' % (n, l['拍'], r['拍']))
        for key, label in (('动作', '动作'), ('表情', '表情'), ('说法', '台词怎么说')):
            if empty(r[key]) or none(r[key]):
                rep.bad.append('句 %s（%s）的「%s」是空的' % (n, l['说话人'], label))
        if len(present.get(l['拍'], [])) <= 1:
            continue
        hear = [x for x in plan.perf if x['kind'] == 'listen' and n in x['covers'] and x['人物'] != l['说话人']]
        if not hear:
            rep.bad.append('句 %s 没有听的人的行（「句」写「听 %s」）' % (n, n))
            continue
        for x in hear:
            if (empty(x['动作']) or none(x['动作'])) and (empty(x['表情']) or none(x['表情'])):
                rep.bad.append('句 %s：%s 在听，但动作和表情都是空的' % (n, x['人物']))
            if empty(x['触发']) or none(x['触发']):
                rep.bad.append('句 %s：%s 的反应没写触发点' % (n, x['人物']))
    scan_section(plan, 3, cats, rep)
    long_cells(plan, 3, ['表演表', '情绪线'], rep)


# ---------- 第三次停靠 ----------

def check_dock3(plan, rep, cats):
    for n in (4, 5):
        if n not in plan.sec:
            rep.bad.append('方案里没有第 %d 段（%s）' % (n, SECTIONS[n]))
    if 4 not in plan.sec or 5 not in plan.sec:
        return
    beat_ids = [b['拍'] for b in plan.beats]
    # 俯视图
    if empty(field(plan.top(4), '轴线')):
        rep.bad.append('第 4 段的「轴线」没写')
    if not plan.things:
        rep.bad.append('俯视图是空的')
    for name, t in plan.things.items():
        if t['类'] not in KINDS:
            rep.bad.append('俯视图里 %s 的「类」要写 固定物、灯 或 点' % name)
        if t['x'] is None or t['y'] is None:
            rep.bad.append('俯视图里 %s 没有坐标' % name)
    lamps = [n for n, t in plan.things.items() if t['类'] == '灯']
    if any('场景' in r['用于'] for r in plan.refs) and not plan.views:
        rep.bad.append('第 4 段没写场景图的视角（「@图名 在 (5, 0) 看向 某某」）')
    for v in plan.views:
        if not plan.xy(v['看向'], 0):
            rep.bad.append('场景图 %s 的「看向」认不出来：%s' % (v['图'], v['看向']))
        if v['图'] not in [r['图'] for r in plan.refs]:
            rep.bad.append('场景图的视角写的 %s 不在参考图清单里' % v['图'])
    # 站位
    faces = {r['主体'] for r in plan.refs if '脸' in r['用于']}
    by_person = {}
    for r in plan.blocking:
        tag = '站位表（%s · %s）' % (r['拍'], r['人物'])
        if r['beat'] is None or (r['beat'] != 0 and r['beat'] not in beat_ids):
            rep.bad.append('%s 的拍要写「起」或节拍表里的拍' % tag)
        if empty(r['人物']):
            rep.bad.append('站位表有一行没写人物')
            continue
        by_person.setdefault(r['人物'], []).append(r)
        t = plan.things.get(r['点'])
        if not t or t['类'] != '点':
            rep.bad.append('%s 的「点」不在俯视图里（类要是"点"）：%s' % (tag, r['点'] or '空'))
        for key, label in (('位置', '位置'), ('姿态', '姿态'), ('朝向', '脸朝哪、看谁')):
            if empty(r[key]):
                rep.bad.append('%s 的「%s」没写' % (tag, label))
        if r['人物'] in faces:
            if not plan.lamp_of(r):
                rep.bad.append('%s 的主光不是俯视图里的灯：%s' % (tag, r['主光'] or '空'))
            if not empty(r['朝向']) and not plan.gaze(r['朝向']):
                rep.hint.append('%s 的「脸朝哪、看谁」里没有认得出的名字，这张脸的朝向和光算不了' % tag)
    spots = {}
    for r in plan.blocking:
        if r['beat'] is not None and r['点'] and not r['离场']:           # 出口不算站人的点，几个人可以从同一个出口走
            spots.setdefault((r['beat'], r['点']), set()).add(r['人物'])
    for (beat, spot), who in sorted(spots.items(), key=lambda kv: str(kv[0])):
        if len(who) > 1:
            rep.bad.append('站位表：%s 在同一拍（%s）都写在「%s」这个点上。一个点站一个人，再加一个点' % (
                '、'.join(sorted(who)), '起' if beat == 0 else beat, spot))
    for person in plan.cast:
        rows = by_person.get(person, [])
        if person not in faces:
            continue
        if not rows:
            rep.bad.append('站位表里没有 %s' % person)
        elif len({(r['点'], r['姿态']) for r in rows}) < 2:
            rep.bad.append('%s 全场没有位置或姿态的变化（站位表里要有至少两行不一样的）' % person)
    # 机位
    if not plan.cams:
        rep.bad.append('机位表是空的')
    for name, c in plan.cams.items():
        if c['x'] is None or c['y'] is None:
            rep.bad.append('机位 %s 没有坐标' % name)
        if empty(c['看向']):
            rep.bad.append('机位 %s 没写看向谁' % name)
        for key in ('在哪', '拍什么', '高度'):
            if empty(c[key]):
                rep.bad.append('机位 %s 的「%s」没写' % (name, key))
        if not plan.lens(name)[0]:
            rep.bad.append('机位 %s 的「焦段」要写 广角、中焦、中长焦 或 长焦' % name)
        for word in ASKED_ONLY:
            if word in c['高度'] + c['焦段'] + c['在哪'] and word not in plan.allow and '用户' not in c['备注']:
                rep.bad.append('机位 %s 用了「%s」：这是用户点名才用的。用户说过就在备注里写用户的原话，或写进方案开头的「放行」' % (name, word))
    used = {m for s in plan.shots for m in s['机位']}
    for name in plan.cams:
        if name not in used:
            rep.hint.append('机位 %s 没有镜头在用' % name)
    # 分镜
    if not plan.shots:
        rep.bad.append('分镜表是空的')
        return
    perf_keys = {(r['拍'], r['人物']) for r in plan.perf}
    where = {}
    for clip in plan.clips():
        shots = plan.clip_shots(clip)
        t = 0
        for s in shots:
            tag = 'clip%02d 镜 %s' % (clip, s['镜'])
            if s['a'] is None:
                rep.bad.append('%s 的时间要写成整数秒，如 0-5：%s' % (tag, s['时间'] or '空'))
                continue
            if s['a'] != t:
                rep.bad.append('%s 从 %d 秒开始，上一镜到 %d 秒，没有首尾相接' % (tag, s['a'], t))
            if s['b'] <= s['a']:
                rep.bad.append('%s 的时间不对：%s' % (tag, s['时间']))
            t = s['b']
            if not s['机位']:
                rep.bad.append('%s 没写机位' % tag)
            for m in s['机位']:
                if m not in plan.cams:
                    rep.bad.append('%s 的机位 %s 不在机位表里' % (tag, m))
            if not s['给谁']:
                rep.bad.append('%s 没写画面给谁' % tag)
            for key, label in (('景别', '景别'), ('接法', '接法'), ('画面', '画面与声音')):
                if empty(s[key]):
                    rep.bad.append('%s 的「%s」没写' % (tag, label))
            parts = [p.strip() for p in s['运镜'].split('｜')]
            if len(parts) != 3 or any(not p for p in parts):
                rep.bad.append('%s 的运镜要写三样，用「｜」隔开：方式｜跟谁｜起点 → 终点' % tag)
            elif '→' not in parts[2] and '不变' not in parts[2]:
                rep.bad.append('%s 的运镜第三样要写「起点 → 终点」或「构图不变」' % tag)
            if '固定' in parts[0] and not any('固定' in a for a in plan.allow) \
                    and not any('用户' in (plan.cams.get(m) or {}).get('备注', '') for m in s['机位']):
                rep.bad.append('%s 的运镜写了「%s」：固定机位是用户点名才用的，默认轻微手持。用户说过，就在这个机位的备注里写用户的原话，或写进方案开头的「放行」'
                               % (tag, parts[0]))
            if not s['行'] and any(w in plan.people for w in s['给谁']):
                rep.bad.append('%s 没写对应表演表的哪几行' % tag)
            for b, who in s['行']:
                if (b, who) not in perf_keys:
                    rep.bad.append('%s 写的表演表行「%s-%s」在表演表里没有' % (tag, b, who))
            need = 0.0
            for n in s['句']:
                if n not in plan.line:
                    rep.bad.append('%s 写的句 %d 不在台词清单里' % (tag, n))
                    continue
                where.setdefault(n, []).append(tag)
                need += plan.line[n]['算秒数']
            if need > (s['b'] - s['a']) + 1e-6:
                rep.bad.append('%s 装不下台词：台词 %s 秒，这一镜 %d 秒。加长这一镜，或把一句挪到相邻的镜；不改台词，不为了装下调快语速'
                               % (tag, fmt(need), s['b'] - s['a']))
        if t > MAX_CLIP:
            rep.bad.append('clip%02d 有 %d 秒，超过 %d 秒' % (clip, t, MAX_CLIP))
        high = [str(s['镜']) for s in shots
                if any('俯' in (plan.cams.get(m) or {}).get('高度', '') and '用户' not in (plan.cams.get(m) or {}).get('备注', '')
                       for m in s['机位'])]
        if len(high) > 1 and not any('俯' in a for a in plan.allow):
            rep.bad.append('clip%02d 有 %d 镜是俯拍（镜 %s）：全条最多一处轻俯拍。用户点名要的，在机位的备注里写用户的原话，或写进方案开头的「放行」'
                           % (clip, len(high), '、'.join(high)))
        for a, b in zip(shots, shots[1:]):
            if a['机位'] and a['机位'] == b['机位'] and a['景别'] == b['景别'] and sorted(a['给谁']) == sorted(b['给谁']):
                rep.bad.append('clip%02d 镜 %s 和镜 %s 的机位、景别、画面给谁都一样：相邻两镜至少换一样，或并成一镜' % (clip, a['镜'], b['镜']))
        for s in shots:
            for m in s['机位']:
                if plan.lens(m)[0] == '广角' and any(k in s['景别'] for k in TIGHT) and '广角' not in plan.allow:
                    rep.bad.append('clip%02d 镜 %s 是%s，机位 %s 却是广角：近景用中长焦，不用广角贴近脸' % (clip, s['镜'], s['景别'], m))
    for l in plan.lines:
        hits = where.get(l['句'], [])
        if len(hits) != 1:
            rep.bad.append('句 %s 应该恰好在一镜里，现在在 %d 镜里%s' % (l['句'], len(hits), '：' + '、'.join(hits) if hits else ''))
    # 切点
    clips = plan.clips()
    if len(plan.cuts) != max(len(clips) - 1, 0):
        rep.bad.append('切点表有 %d 行，分镜表有 %d 条 clip，应该差一' % (len(plan.cuts), len(clips)))
    bounds = []
    for i, c in enumerate(plan.cuts, 1):
        if not c['之后'] or c['之后'][0] not in beat_ids:
            rep.bad.append('切点 %d 的「在哪拍之后」要写节拍表里的拍' % i)
            continue
        bounds.append(c['之后'][0])
        for key, label in (('理由', '理由'), ('接缝', '接缝处每人的状态'), ('怎么接', '怎么接')):
            if empty(c[key]):
                rep.bad.append('切点 %d 的「%s」没写' % (i, label))
    if len(bounds) == len(clips) - 1 and bounds == sorted(bounds):
        edges = [0] + bounds + [10 ** 6]
        for k, clip in enumerate(clips):
            lo, hi = edges[k], edges[k + 1]
            for s in plan.clip_shots(clip):
                for n in s['句']:
                    b = plan.line.get(n, {}).get('拍')
                    if b is not None and not (lo < b <= hi):
                        rep.bad.append('句 %d 属于第 %d 拍，却排在 clip%02d 里：切点不在节拍边界上' % (n, b, clip))
    lengths = {clip: max([s['b'] or 0 for s in plan.clip_shots(clip)] or [0]) for clip in clips}
    total = sum(lengths.values())
    least = max(1, math.ceil(total / MAX_CLIP))
    if len(clips) > least and (empty(plan.clip_reason) or none(plan.clip_reason)):
        rep.bad.append('共 %d 秒，最少 %d 条，现在 %d 条：在「条数理由」里写为什么' % (total, least, len(clips)))
    # 几何
    geo = all_geometry(plan)
    check_geometry(plan, geo, rep)
    scan_section(plan, 4, cats, rep)
    scan_section(plan, 5, cats, rep)
    long_cells(plan, 4, ['站位'], rep)
    long_cells(plan, 5, ['分镜', '切点'], rep)
    # 打印
    rep.info.append('条数：%d 条（%s）。最少 %d 条' % (len(clips), '、'.join('%d 秒' % lengths[c] for c in clips), least))
    sp = picture_stats(plan, None)
    rep.info.append('画面给谁：%d 句里，%d 句给说话的人，%d 句同框，%d 句给了听的人或环境' % (sp['n'], sp['self'], sp['both'], sp['other']))
    for clip in clips:
        st = rhythm(plan, clip)
        rep.info.append('clip%02d：台词 %s 秒；没台词最长 %s 秒（%s）' % (clip, fmt(st['speech']), fmt(st['quiet']), st['quiet_at']))
    rep.info.append('')
    rep.info.extend(overview(plan, rep))
    rep.info.append('')
    rep.info.append('每一镜按俯视图算出来的（Prompt 里的左右和光照这个写）：')
    for g in geo:
        rep.info.append('  ' + describe(plan, g))
    rep.info.append('')
    rep.info.append(render_map(plan))


def check_geometry(plan, geo, rep):
    pairs = {}
    for shot, g in zip(plan.shots, geo):
        tag = 'clip%02d 镜 %s' % (shot['clip'] or 0, shot['镜'])
        if g['why']:
            if g['cam'] in plan.cams:
                rep.bad.append('%s 算不了左右：%s' % (tag, g['why']))
            continue
        rows = {who: r for r in plan.perf for b, who in shot['行'] if r['拍'] == b and r['人物'] == who}
        for person in shot['给谁']:
            info = g['people'].get(person)
            if person not in plan.people:
                continue
            if not info:
                rep.bad.append('%s 的画面给 %s，但站位表里这时候没有他' % (tag, person))
                continue
            if not info['in']:
                rep.bad.append('%s 的画面给 %s，但机位 %s 拍不到他（在%s）' % (
                    tag, person, g['cam'], '镜头身后' if info['depth'] <= 0 else '画外，偏了 %d 度' % abs(round(info['angle']))))
                continue
            perf_rows = [r for r in plan.perf for b, who in shot['行'] if who == person and r['拍'] == b and r['人物'] == who]
            if info['face'] == '背对' and any(not empty(r['表情']) and not none(r['表情']) for r in perf_rows):
                rep.bad.append('%s：%s 背对机位 %s，表演表里写的表情拍不到。换机位，或改他看的方向' % (tag, person, g['cam']))
            if info['light'] and info['light'][1] == '背光' and '背光' not in plan.allow:
                rep.bad.append('%s：%s 的主光（%s）在他脑后，是背光。换一盏灯做主光，或改他看的方向' % (tag, person, info['lamp']))
        for person, info in g['people'].items():
            if info['in'] and info.get('gone'):
                rep.bad.append('%s：%s 看的 %s 这时候不在场（还没进来或已经离场），脸的朝向和光算不了。把站位表的「脸朝哪、看谁」改成看一个点，比如出口' % (
                    tag, person, info['gone']))
        seen = [p for p in shot['给谁'] if p in g['people'] and g['people'][p]['in']]
        lens, half = plan.lens(g['cam'])
        if len(seen) > 1 and half:
            angles = [g['people'][p]['angle'] for p in seen]
            wide = max(angles) - min(angles)
            if wide > 2 * half + 6:
                rep.bad.append('%s：机位 %s 是%s，装不下%s（从机位看他们张开 %d 度）。换短一点的焦段、把机位拉远，或拆成单人镜' % (
                    tag, g['cam'], lens, '和'.join(seen), round(wide)))
        for i, a in enumerate(seen):
            for b in seen[i + 1:]:
                key = tuple(sorted((a, b)))
                left = key[0] if g['people'][key[0]]['angle'] < g['people'][key[1]]['angle'] else key[1]
                pairs.setdefault(key, []).append((g['cam'], left, tag))
    for key, seen in pairs.items():
        first_cam, first_left, first_tag = seen[0]
        for cam, left, tag in seen[1:]:
            if left != first_left and cam != first_cam:
                note = plan.cams.get(cam, {}).get('备注', '') + plan.cams.get(first_cam, {}).get('备注', '')
                if '换边' not in note:
                    rep.bad.append('%s 和 %s 在机位 %s（%s）和机位 %s（%s）里左右换了边。要换就在机位表的备注里写「换边」和理由' % (
                        key[0], key[1], first_cam, first_tag, cam, tag))
                break


def camera_use(plan):
    """每个机位用在哪几镜、共几秒。"""
    use = {name: {'shots': [], 'seconds': 0} for name in plan.cams}
    for s in plan.shots:
        if s['a'] is None:
            continue
        for m in s['机位']:
            if m in use:
                use[m]['shots'].append('clip%02d 镜 %s' % (s['clip'] or 0, s['镜']))
                use[m]['seconds'] += (s['b'] - s['a']) / float(len(s['机位']))
    return use


def moves(plan):
    """每个人的走位：[(拍, 点, 姿态)]，只留有变化的。"""
    out = {}
    for r in plan.blocking:
        if not r['人物']:
            continue
        path = out.setdefault(r['人物'], [])
        if not path or (path[-1][1], path[-1][2]) != (r['点'], r['姿态']):
            path.append((r['拍'], r['点'], r['姿态'], r['beat']))
    return out


def spread(plan):
    """画面分布：景别、机位、画面给谁各出现几镜。"""
    out = {'景别': {}, '机位': {}, '画面给谁': {}}
    for s in plan.shots:
        out['景别'][s['景别']] = out['景别'].get(s['景别'], 0) + 1
        for m in s['机位']:
            out['机位'][m] = out['机位'].get(m, 0) + 1
        who = '、'.join(s['给谁'])
        out['画面给谁'][who] = out['画面给谁'].get(who, 0) + 1
    return out


def overview(plan, rep=None):
    """三张总览：这个空间几个机位、各拍什么；每个人怎么走；画面有没有变化。"""
    lines = ['机位：这个空间 %d 个机位' % len(plan.cams)]
    use = camera_use(plan)
    for name, c in plan.cams.items():
        u = use[name]
        lines.append('  %s｜%s｜%s，%s｜拍 %s｜用在 %d 镜、共 %s 秒' % (
            name, c['在哪'], c['高度'], plan.lens(name)[0] or c['焦段'], c['拍什么'], len(u['shots']), fmt(u['seconds'])))
    lines.append('走位：')
    for person, path in moves(plan).items():
        lines.append('  %s：%s' % (person, ' → '.join('%s %s（%s）' % ('起' if b == 0 else '拍 %s' % raw, spot, pose) for raw, spot, pose, b in path)))
        if rep is not None:
            for (_, spot0, _, _), (raw, spot1, _, beat) in zip(path, path[1:]):
                if spot0 == spot1 or beat is None:
                    continue
                shown = [s for s in plan.shots if person in s['给谁'] and plan.shot_beats(s)[0] <= beat <= plan.shot_beats(s)[1]]
                if not shown:
                    rep.hint.append('%s 在第 %s 拍从%s走到%s，但这一拍没有镜头给他：观众看不到他怎么过去的' % (person, raw, spot0, spot1))
    sp = spread(plan)
    lines.append('画面：%d 镜' % len(plan.shots))
    for key in ('景别', '机位', '画面给谁'):
        lines.append('  %s：%s' % (key, '、'.join('%s %d 镜' % (k, v) for k, v in sorted(sp[key].items(), key=lambda kv: -kv[1]))))
    if rep is not None and len(plan.shots) >= 4 and len(sp['景别']) == 1:
        rep.hint.append('全场 %d 镜都是%s：画面容易单一，看看要不要换景别' % (len(plan.shots), list(sp['景别'])[0]))
    return lines


def describe(plan, g):
    tag = 'clip%02d 镜 %s · 机位 %s' % (g['clip'] or 0, g['镜'], g['cam'] or '？')
    if g['why']:
        return tag + '：' + g['why']
    bits = ['从画左到画右：' + ('、'.join(g['order']) or '没有人')]
    for person in g['order']:
        info = g['people'][person]
        if info['face']:
            s = '%s %s' % (person, info['face'])
            if info['light'] and info['light'][1] == '背光':
                s += '，主光%s在脑后（背光）' % info['lamp']
            elif info['light']:
                s += '，主光%s从%s来，亮的是%s' % (info['lamp'], info['light'][0], info['light'][1])
            bits.append(s)
        if info['moved']:
            bits.append('%s 这一镜里换了位置，左右按走完以后算' % person)
    if g['things']:
        bits.append('东西从左到右：' + '、'.join(g['things']))
    bits.append('身后：' + ('、'.join(g['behind']) if g['behind'] else '俯视图里没有登记'))
    if g['view']:
        bits.append('和 %s 的视角：%s' % g['view'] + ('（镜头身后的东西只留一句方向句）' if g['view'][1] == '反打' else ''))
    return tag + '｜' + '；'.join(bits)


def picture_stats(plan, clip):
    out = {'n': 0, 'self': 0, 'both': 0, 'other': 0}
    for s in plan.shots:
        if clip is not None and s['clip'] != clip:
            continue
        for n in s['句']:
            l = plan.line.get(n)
            if not l:
                continue
            out['n'] += 1
            if l['说话人'] in s['给谁'] and len(s['给谁']) == 1:
                out['self'] += 1
            elif l['说话人'] in s['给谁']:
                out['both'] += 1
            else:
                out['other'] += 1
    return out


def rhythm(plan, clip):
    """这条 clip 的节奏数字。"""
    shots = plan.clip_shots(clip)
    speech, quiet, quiet_at, run, run_from = 0.0, 0.0, '没有', 0, None
    for s in shots:
        if s['a'] is None:
            continue
        need = sum(plan.line[n]['算秒数'] for n in s['句'] if n in plan.line)
        speech += need
        length = s['b'] - s['a']
        if not s['句']:
            if run == 0:
                run_from = s['镜']
            run += length
            if run > quiet:
                quiet, quiet_at = run, '镜 %s' % run_from if run_from == s['镜'] else '镜 %s–%s' % (run_from, s['镜'])
        else:
            run = 0
            if length - need > quiet:
                quiet, quiet_at = length - need, '镜 %s 的余量' % s['镜']
    st = picture_stats(plan, clip)
    return {'speech': round(speech + 1e-9, 1), 'quiet': round(quiet + 1e-9, 1), 'quiet_at': quiet_at, 'off': st['both'] + st['other'],
            'n': st['n']}


def rhythm_sentence(st):
    return '台词 %s 秒；没台词最长 %s 秒；%d 句的画面给了听的人、双人或环境' % (fmt(st['speech']), fmt(st['quiet']), st['off'])


# ---------- Prompt ----------

class Prompt:
    def __init__(self, path):
        self.path = Path(path)
        text = read(path)
        parts = re.split(r'^---\s*$', text, flags=re.M)
        self.head = parts[0]
        self.body = parts[1].strip() if len(parts) > 1 else ''      # 两条线之间是正文；第二条线后面的不算
        t = re.search(r'clip\s*0*(\d+)\s*·\s*Prompt\s*v(\d+)', self.head)
        self.clip = int(t.group(1)) if t else None
        self.version = int(t.group(2)) if t else None
        self.plan_ref = field(self.head, '方案') or ''
        self.follow = field(self.head, '接上一条') or ''
        self.sections = {}
        self.order = []
        for m in re.finditer(r'^【([^】]+)】[ \t]*\n?(.*?)(?=^【[^】]+】|\Z)', self.body, re.M | re.S):
            self.sections[m.group(1)] = m.group(2).strip()
            self.order.append(m.group(1))
        self.shots = []
        timeline = self.sections.get('分镜时间线', '')
        for m in re.finditer(r'^镜头\s*(\d+)\s*[（(]\s*(\d+)\s*[-–—]\s*(\d+)\s*(?:秒|s)\s*[）)]\s*[：:](.*?)(?=^镜头\s*\d+\s*[（(]|\Z)', timeline, re.M | re.S):
            self.shots.append({'镜': int(m.group(1)), 'a': int(m.group(2)), 'b': int(m.group(3)), 'text': m.group(4).strip()})

    def lines(self, text=None):
        return [x.strip() for x in re.findall(r'\{([^{}]*)\}', self.sections.get('分镜时间线', '') if text is None else text)]

    def outside_braces(self):
        return re.sub(r'\{[^{}]*\}', '{}', self.body)


def find_plan(prompt, given):
    if given:
        return Path(given)
    name = re.split(r'\s+v\d+', prompt.plan_ref)[0].strip()
    here = prompt.path.resolve().parent
    for cand in (here / name, here.parent / '04_plan' / name):
        if name and cand.is_file():
            return cand
    plans = sorted((here.parent / '04_plan').glob('*.plan.md')) if (here.parent / '04_plan').is_dir() else []
    stem = re.sub(r'-clip\d+.*$', '', prompt.path.name)
    for p in plans:
        if p.name.startswith(stem):
            return p
    return None


LANG = re.compile(r'用[一-鿿]{1,6}(?:语|文|话)')
BACK = re.compile(r'说到|说完这|这句话|这一句|最后[一二两三四五六几]?个?(?:词|字)|那个词|念到')
SUMMARY_PARAMS = re.compile(r'\d+\s*秒|\d+\s*s\b|\d+\s*[:：]\s*\d+|竖屏|横屏|竖幅|横幅|画幅|分辨率|\b(?:480|720|1080)\s*[pP]\b')


def side_claims(text, names):
    """从一段 Prompt 里找"某某在画左 / 画右的某某"这类明说的左右。返回 [(名字, '左'|'右')]。"""
    out = []
    alt = '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    if not alt:
        return out
    for m in re.finditer(r'画([左右])(?:边|侧)?(?:的|那位|那个)\s*(' + alt + r')', text):
        out.append((m.group(2), m.group(1)))
    for m in re.finditer(r'(' + alt + r')(?:（[^）]*）)?\s*(?:坐|站|停|靠|蹲|立)?在(?:画面(?:的)?)?画?([左右])(?![手肩脚腿眼耳])', text):
        out.append((m.group(1), m.group(2)))
    for m in re.finditer(r'画([左右])(?:边|侧)?(?:是|为)\s*(' + alt + r')', text):
        out.append((m.group(2), m.group(1)))
    return out


def light_claims(text, people):
    """从「光：」一行里找每个人说的是哪半边亮。同一个人两种说法都有就不算。"""
    out = {}
    marks = [(m.start(), m.group(1)) for m in re.finditer('(' + '|'.join(re.escape(p) for p in people) + r')\s*的主光', text)] if people else []
    for i, (pos, who) in enumerate(marks):
        seg = text[pos:marks[i + 1][0] if i + 1 < len(marks) else len(text)]
        far = bool(re.search(r'远离镜头的那?半边(?:脸)?(?:较|更)?亮', seg))
        near = bool(re.search(r'靠近镜头的那?半边(?:脸)?(?:较|更)?亮|光落(?:到|在)靠近镜头', seg))
        if far != near:
            out[who] = '远离镜头的半边' if far else '靠近镜头的半边'
    return out


def check_prompt(prompt, plan, rep, cats):
    if prompt.clip is None or prompt.version is None:
        rep.bad.append('第一行标题要写成「# 场号 clip01 · Prompt v1」')
        return None
    if not prompt.body:
        rep.bad.append('没有找到「---」下面的 Prompt 正文')
        return None
    for n in range(1, 6):
        st = plan.sec.get(n, {}).get('status', '')
        if not (st.startswith('已确认') or st.startswith('免停靠')):
            rep.bad.append('方案第 %d 段（%s）还没确认，状态是「%s」。五段都确认了才编 Prompt' % (n, SECTIONS[n], st or '空'))
    if plan.version is not None:
        v = re.search(r'v(\d+)', prompt.plan_ref)
        if not v:
            rep.bad.append('参数段的「方案」要写方案文件名和版本，如 xx.plan.md v3')
        elif int(v.group(1)) < plan.version:
            rep.hint.append('方案已经是 v%d，这份 Prompt 记的是 v%s。对过没有出入就把版本号改过来' % (plan.version, v.group(1)))
    if prompt.order != PROMPT_SECTIONS:
        rep.bad.append('六段要齐、按这个顺序：%s。现在是：%s' % ('、'.join('【%s】' % s for s in PROMPT_SECTIONS),
                                                    '、'.join('【%s】' % s for s in prompt.order) or '没有'))
        return None
    shots = plan.clip_shots(prompt.clip)
    if not shots:
        rep.bad.append('方案的分镜表里没有 clip%02d' % prompt.clip)
        return None
    # 镜头
    want = [(s['镜'], s['a'], s['b']) for s in shots]
    have = [(s['镜'], s['a'], s['b']) for s in prompt.shots]
    if want != have:
        rep.bad.append('镜头和方案不一样。方案：%s；Prompt：%s' % (
            '、'.join('镜%s %s-%s' % w for w in want), '、'.join('镜%s %s-%s' % h for h in have) or '没有认出镜头'))
    # 台词
    plan_lines = [(n, plan.line[n]['台词']) for s in shots for n in s['句'] if n in plan.line]
    got = prompt.lines()
    if [t for _, t in plan_lines] != got:
        for i, (n, t) in enumerate(plan_lines):
            if i >= len(got):
                rep.bad.append('句 %d 没有出现在 Prompt 里：%s' % (n, t))
            elif got[i] != t:
                rep.bad.append('句 %d 和方案不是逐字相同。方案：%s｜Prompt：%s' % (n, t, got[i]))
                break
        if len(got) > len(plan_lines):
            rep.bad.append('Prompt 里多出 %d 句方案里没有的台词' % (len(got) - len(plan_lines)))
    for s, ps in zip(shots, prompt.shots):
        if [plan.line[n]['台词'] for n in s['句'] if n in plan.line] != prompt.lines(ps['text']):
            rep.bad.append('镜头 %s 里的台词和分镜表的「句」对不上（一句不跨镜，按先后写在所属的镜头里）' % ps['镜'])
    # 写法
    for cat, w in scan_banned(prompt.outside_braces(), cats, plan.allow):
        rep.bad.append('有禁写词「%s」（%s）' % (w, cat))
    for ps in prompt.shots:
        text = ps['text']
        for m in re.finditer(r'\{[^{}]*\}', text):
            before = re.split(r'[。}]', text[:m.start()])[-1]
            lang = list(LANG.finditer(before))
            how = before[lang[-1].end():] if lang else before.split('，')[-1]
            if '快' in how:
                rep.bad.append('镜头 %s：台词的说法里有"快"，台词会挤成一团：%s' % (ps['镜'], how.strip()[-20:]))
            after = text[m.end():]
            nxt = after.find('{')
            if nxt != -1:
                after = after[:nxt]
                lead = list(LANG.finditer(after))
                after = after[:lead[-1].start()] if lead else after[:after.rfind('，') + 1]
            words = WORD.findall(m.group(0))
            back = BACK.search(after)
            echo = None
            for i in range(len(words) - 1):
                if re.search(r'\b' + re.escape(words[i]) + r'\W+' + re.escape(words[i + 1]) + r'\b', after, re.I):
                    echo = words[i] + ' ' + words[i + 1]
                    break
            zh = re.findall(r'[一-鿿]{4,}', m.group(0))
            for frag in zh:
                for i in range(len(frag) - 3):
                    if frag[i:i + 4] in after:
                        echo = frag[i:i + 4]
                        break
            if back or echo:
                rep.bad.append('镜头 %s：台词后面回头提了台词（%s）。说话人的表演写在台词前面，后面只接别人的反应' % (
                    ps['镜'], back.group(0) if back else echo))
    if len(prompt.body) > MAX_CHARS:
        rep.bad.append('正文 %d 字符，超过 %d。先删重复和复述，同机位的光写「同镜头 N」；还超就告诉用户' % (len(prompt.body), MAX_CHARS))
    # 素材
    bound = re.findall(r'^(@[^\s：:，。、；（）()]+)\s*[：:]\s*(.*)$', prompt.sections['素材绑定'], re.M)
    bound_names = [b[0] for b in bound]
    ref_names = {r['图'] for r in plan.refs}
    extra = re.findall(r'@[^\s：:，。、；（）()]+', prompt.follow)
    for name in sorted(set(re.findall(r'@[^\s：:，。、；（）()]+', prompt.outside_braces()))):
        if name not in bound_names:
            rep.bad.append('正文里用了 %s，【素材绑定】里没有它' % name)
        elif name not in ref_names and name not in extra:
            rep.bad.append('%s 不在方案的参考图清单里（上一条的末帧写在参数段的「接上一条」里）' % name)
    for name, text in bound:
        if len(text.strip()) < 6:
            rep.bad.append('【素材绑定】里 %s 没写用于什么' % name)
        ref = next((r for r in plan.refs if r['图'] == name), None)
        if ref and not none(ref['不采用']) and not empty(ref['不采用']) and not re.search(r'不采用|不参考|不照', text):
            rep.bad.append('【素材绑定】里 %s 没写不采用什么（方案里写的是：%s）' % (name, ref['不采用']))
    first_seen = []
    for s in shots:
        for who in s['给谁'] + [w for _, w in s['行']]:
            if who in plan.cast and who not in first_seen:
                first_seen.append(who)
    face_img = {r['主体']: r['图'] for r in reversed(plan.refs) if '脸' in r['用于']}
    seq = [bound_names.index(face_img[w]) for w in first_seen if w in face_img and face_img[w] in bound_names]
    if seq != sorted(seq):
        rep.bad.append('【素材绑定】里人物的顺序要按首次出场：%s' % '、'.join(first_seen))
    if SUMMARY_PARAMS.search(prompt.sections['总述']):
        rep.bad.append('【总述】里不写时长、画幅、分辨率：%s' % SUMMARY_PARAMS.search(prompt.sections['总述']).group(0))
    # 声音
    last = prompt.sections['贯穿要求']
    if plan.music_none:
        if not re.search(r'没有音乐|无音乐|不要音乐', prompt.sections['总述']):
            rep.bad.append('【总述】里要有无音乐的第一遍（如"没有音乐"）')
        lack = [w for w in MUSIC_WORDS if w not in last]
        if lack:
            rep.bad.append('【贯穿要求】里无音乐的说法没列全，少了：%s' % '、'.join(lack))
    m = re.search(r'除了写出的(?:这)?\s*(\d+)\s*句台词', last)
    if plan_lines and (not m or int(m.group(1)) != len(plan_lines)):
        rep.bad.append('【贯穿要求】要写「除了写出的 %d 句台词，没有人说别的话」' % len(plan_lines))
    if '字幕' not in last:
        rep.bad.append('【贯穿要求】里要写不要字幕')
    seen = {w for s in shots for w in s['给谁'] if w in plan.people}
    if plan_lines and len(seen) > 1 and not re.search(r'合着嘴|闭着嘴|闭口', last):
        rep.bad.append('【贯穿要求】要写一次「不说话的人自然合着嘴，只用眼神和表情回应」')
    dur = re.search(r'\d+', field(prompt.head, '时长') or '')
    if prompt.shots and (not dur or int(dur.group(0)) != prompt.shots[-1]['b']):
        rep.bad.append('参数段的「时长」要和分镜的末秒一样：分镜到 %d 秒，参数段写的是 %s'
                       % (prompt.shots[-1]['b'], dur.group(0) + ' 秒' if dur else '空'))
    if not none(prompt.follow) and not empty(prompt.follow) and '已对' not in prompt.follow:
        rep.bad.append('接上一条成片时，先拿成片的末帧对一遍站位和左右，在「接上一条」里写"已对"和结果')
    # 左右和光，对俯视图
    geo = {g['镜']: g for g in all_geometry(plan) if g['clip'] == prompt.clip}
    names = set(plan.people) | {n for n, t in plan.things.items() if t['类'] != '点'}
    by_no = {s['镜']: s for s in shots}
    for ps in prompt.shots:
        first = ps['text'].splitlines()[0] if ps['text'] else ''
        for m in (by_no.get(ps['镜']) or {}).get('机位', []):
            lens = plan.lens(m)[0]
            if lens in ('中长焦', '长焦') and lens not in first:
                rep.bad.append('镜头 %s 的镜头行要写出焦段「%s」（机位 %s）' % (ps['镜'], lens, m))
            height = plan.cams.get(m, {}).get('高度', '')
            if '俯' in height and '俯' not in first:
                rep.bad.append('镜头 %s 的镜头行要写出俯拍（机位 %s：%s）' % (ps['镜'], m, height))
            elif '俯' not in height and height and not re.search(r'平视|同高|同一高度', first):
                rep.bad.append('镜头 %s 的镜头行要写机位高度：和谁的眼睛同高、平视（机位 %s）' % (ps['镜'], m))
    for ps in prompt.shots:
        g = geo.get(ps['镜'])
        if not g or g['why']:
            continue
        check_sides(plan, g, ps['text'], '镜头 %s' % ps['镜'], names, rep)
        light_line = '\n'.join(l for l in ps['text'].splitlines() if l.strip().startswith('光：') or l.strip().startswith('光:'))
        for who, said in light_claims(light_line, plan.people).items():
            info = g['people'].get(who)
            if info and info['light'] and info['light'][1] in ('远离镜头的半边', '靠近镜头的半边') and info['light'][1] != said:
                rep.bad.append('镜头 %s 的光：%s 写的是%s亮，按俯视图算是%s亮（机位 %s，主光 %s）。改机位、改他看的方向，或照实写' % (
                    ps['镜'], who, said, info['light'][1], g['cam'], info['lamp']))
    if prompt.shots and prompt.shots[0]['镜'] in geo and not geo[prompt.shots[0]['镜']]['why']:
        check_sides(plan, geo[prompt.shots[0]['镜']], prompt.sections['起始状态'], '【起始状态】', names, rep, start=True)
    st = rhythm(plan, prompt.clip)
    rep.info.append('第 7 道抄这一句：' + rhythm_sentence(st))
    rep.info.append('没台词最长的那段在：' + st['quiet_at'])
    rep.info.append('第 8 道的字符数：%d' % len(prompt.body))
    return st


def check_sides(plan, g, text, tag, names, rep, start=False):
    def angle_of(name):
        if name in g['people']:
            info = g['people'][name]
            if start:
                first = plan.state(name, g['beats'][0])
                p = plan.xy(first['点'], g['beats'][0]) if first else None
                return view(g['c'], g['look'], p)[0] if p else None
            return None if info['moved'] or not info['in'] else info['angle']
        t = plan.things.get(name)
        if t and t['x'] is not None:
            ang, depth = view(g['c'], g['look'], (t['x'], t['y']))
            return ang if depth > 0 else None
        return None

    claims = {}
    for sentence in re.split(r'[。；;\n]', re.sub(r'\{[^{}]*\}', '', text)):
        for name, side in side_claims(sentence, names):
            claims.setdefault(name, set()).add(side)
    solid = {n: next(iter(s)) for n, s in claims.items() if len(s) == 1}
    for name, side in solid.items():
        ang = angle_of(name)
        if ang is None:
            continue
        if (side == '左' and ang > 10) or (side == '右' and ang < -10):
            rep.bad.append('%s：写的是 %s 在画%s，按俯视图算在画%s（机位 %s）' % (tag, name, side, '右' if ang > 0 else '左', g['cam']))
    lefts = [n for n, s in solid.items() if s == '左' and angle_of(n) is not None]
    rights = [n for n, s in solid.items() if s == '右' and angle_of(n) is not None]
    for a in lefts:
        for b in rights:
            if angle_of(a) > angle_of(b) + 3:
                rep.bad.append('%s：写的是 %s 在画左、%s 在画右，按俯视图算正好反过来（机位 %s）' % (tag, a, b, g['cam']))


# ---------- QA ----------

def find_log(prompt, plan_path, given):
    if given:
        return Path(given)
    here = prompt.path.resolve().parent
    stem = re.sub(r'\.plan\.md$', '', Path(plan_path).name)
    for cand in (here.parent / '07_log' / (stem + '.log.md'), here / (stem + '.log.md')):
        if cand.is_file():
            return cand
    return None


def check_qa(prompt, plan, log_path, rep, st):
    text = read(log_path)
    m = re.search(r'^###\s*clip\s*0*%d\s*·\s*Prompt\s*v(\d+)\s*$(.*?)(?=^##|\Z)' % prompt.clip, text, re.M | re.S)
    if not m:
        rep.bad.append('场记录的「QA」里没有「### clip%02d · Prompt v%d」' % (prompt.clip, prompt.version))
        return
    if int(m.group(1)) != prompt.version:
        rep.bad.append('场记录里的 QA 是 Prompt v%s 的，现在的 Prompt 是 v%d。QA 要重做' % (m.group(1), prompt.version))
        return
    rows = {}
    for line in m.group(2).splitlines():
        mm = re.match(r'^-\s*(\d)\s*(\S+?)\s*·\s*(过|改了)\s*(?:·\s*(.*))?$', line.strip())
        if mm:
            rows[int(mm.group(1))] = (mm.group(2), mm.group(3), (mm.group(4) or '').strip(), line.strip())
    for i, name in enumerate(QA_NAMES, 1):
        if i not in rows:
            rep.bad.append('QA 缺第 %d 道（%s）。一道一行：- %d %s · 过或改了 · 说明' % (i, name, i, name))
            continue
        got_name, verdict, note, line = rows[i]
        if got_name != name:
            rep.bad.append('QA 第 %d 道的名字应该是「%s」，现在是「%s」' % (i, name, got_name))
        if empty(note) or len(note) < 2:
            rep.bad.append('QA 第 %d 道没写说明。"过"写查到了什么，"改了"写改了什么' % i)
        if len(line) > LONG_RECORD:
            rep.hint.append('QA 第 %d 道有 %d 字，超过 %d 字' % (i, len(line), LONG_RECORD))
    if 7 in rows and st:
        note = rows[7][2]
        a = re.search(r'台词\s*([\d.]+)\s*秒', note)
        b = re.search(r'没台词最长\s*([\d.]+)\s*秒', note)
        c = re.search(r'(\d+)\s*句的画面给了', note)
        ok = (a and b and c and abs(float(a.group(1)) - st['speech']) < 0.05 and abs(float(b.group(1)) - st['quiet']) < 0.05
              and int(c.group(1)) == st['off'])
        if not ok:
            rep.bad.append('QA 第 7 道的数字要从脚本抄：' + rhythm_sentence(st))
    if 8 in rows:
        n = ints(rows[8][2])
        if not n or n[0] != len(prompt.body):
            rep.bad.append('QA 第 8 道的字符数要从脚本抄：%d 字符' % len(prompt.body))


# ---------- 入口 ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('when', choices=['dock1', 'dock2', 'dock3', 'prompt', 'qa', 'map'])
    ap.add_argument('file')
    ap.add_argument('--plan')
    ap.add_argument('--log')
    args = ap.parse_args(argv)
    path = Path(args.file)
    if not path.is_file():
        print('找不到文件：%s' % path)
        return 2
    if args.when in ('dock1', 'dock2', 'dock3', 'map'):
        plan = Plan(path)
        if args.when == 'map':
            print(render_map(plan))
            return 0
        rep = Report(args.when)
        cats = banned_for(path)
        check_dock1(plan, rep, cats)
        if args.when in ('dock2', 'dock3'):
            check_dock2(plan, rep, cats)
        if args.when == 'dock3':
            check_dock3(plan, rep, cats)
        print(rep.out())
        return rep.code()
    prompt = Prompt(path)
    plan_path = find_plan(prompt, args.plan)
    if not plan_path or not Path(plan_path).is_file():
        print('找不到方案。在参数段的「方案」里写文件名，或用 --plan 指定')
        return 2
    plan = Plan(plan_path)
    cats = banned_for(plan_path)
    rep = Report(args.when)
    upstream = Report('dock3')
    check_dock1(plan, upstream, cats)
    check_dock2(plan, upstream, cats)
    check_dock3(plan, upstream, cats)
    if upstream.bad:
        rep.bad.append('方案自己还有 %d 处没过，先跑 dock3 改完：%s' % (len(upstream.bad), upstream.bad[0]))
    rep.ask.extend(upstream.ask)
    st = check_prompt(prompt, plan, rep, cats)
    if args.when == 'qa':
        log_path = find_log(prompt, plan_path, args.log)
        if not log_path or not Path(log_path).is_file():
            print('找不到场记录。用 --log 指定')
            return 2
        if rep.bad:
            rep.bad.insert(0, 'Prompt 的检查还没过，先跑 prompt 改完再记 QA')
        else:
            check_qa(prompt, plan, log_path, rep, st)
    print(rep.out())
    return rep.code()


if __name__ == '__main__':
    sys.exit(main())
