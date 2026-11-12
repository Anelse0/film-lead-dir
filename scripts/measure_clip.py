#!/usr/bin/env python3
"""量一条成片。要 ffmpeg 和 ffprobe。

  python3 scripts/measure_clip.py <成片> [--prompt Prompt.prompt.md] [--last-frame 末帧.png]
                                  [--frames 目录 | --no-frames] [--scene 0.3] [--silence -30] [--json]

量什么：
  切点和镜长    检出的切点；给了 --prompt 就和 Prompt 的镜头时间并排，标出多切、没切出来、差多少
  声音          有声几秒、开头结尾静音、最长静音在哪
  语速          Prompt 里台词的词数 ÷ 有声秒数。有声含动作声，所以这是语速的下限
  每镜一帧      存成 jpg，再拼成一张图，给 agent 自己看
  动没动        每镜开头和结尾的画面差多少。"静"是站着不动的线索
  变没变        相邻两镜的画面差多少。"平"是换了镜等于没换的线索
  末帧          --last-frame 存一张全尺寸的最后一帧，给下一条当参考图
  摘要          一行，抄进场记录的成片账

切点是估的：亮的开头慢摇可能算成一刀，两个很像的画面之间的硬切可能漏掉。差一两个算正常，要紧的地方看图。
声音只量有没有声，听不出语气。语气、音色、节奏以用户为准。
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GRAY_W, GRAY_H = 96, 54
FLAT_HIST, FLAT_EDGE = 0.12, 0.04      # 相邻两镜：直方图距离和边缘密度都小于这个，算"平"
STILL = 0.08                           # 镜内运动小于这个，算"静"
MATCH = 0.75                           # 检出的切点离声明的切点多少秒以内算对上


def run(cmd, binary=False):
    return subprocess.run(cmd, capture_output=True, text=not binary, check=False)


def duration(path):
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)])
    return float(out.stdout.strip())


def detect_cuts(path, threshold):
    out = run(['ffmpeg', '-hide_banner', '-i', str(path), '-vf', "select='gt(scene,%s)',showinfo" % threshold,
               '-an', '-f', 'null', '-'])
    times = [float(m) for m in re.findall(r'pts_time:\s*([0-9.]+)', out.stderr)]
    return [round(t, 2) for t in times if t > 0.2]


def detect_silences(path, db, total, min_len=0.3):
    out = run(['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'silencedetect=n=%sdB:d=%s' % (db, min_len),
               '-vn', '-f', 'null', '-'])
    if 'Output file does not contain any stream' in out.stderr or 'matches no streams' in out.stderr:
        return None
    starts = [float(m) for m in re.findall(r'silence_start:\s*(-?[0-9.]+)', out.stderr)]
    ends = [float(m) for m in re.findall(r'silence_end:\s*([0-9.]+)', out.stderr)]
    pairs = [(max(s, 0.0), e) for s, e in zip(starts, ends)]
    if len(starts) > len(ends):
        pairs.append((max(starts[-1], 0.0), total))
    return pairs


def has_audio(path):
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(path)])
    return bool(out.stdout.strip())


def match_cuts(declared, detected, tol=MATCH):
    """声明的切点各找一个最近的检出切点。返回 ([(声明, 检出或 None)], 多切的)。"""
    used, pairs = set(), []
    for t in declared:
        best = None
        for i, d in enumerate(detected):
            if i in used or abs(d - t) > tol:
                continue
            if best is None or abs(d - t) < abs(detected[best] - t):
                best = i
        if best is None:
            pairs.append((t, None))
        else:
            used.add(best)
            pairs.append((t, detected[best]))
    return pairs, [d for i, d in enumerate(detected) if i not in used]


def sound(path, total, db):
    if not has_audio(path):
        return None
    sil = detect_silences(path, db, total) or []
    silent = sum(e - s for s, e in sil)
    lead = sil[0][1] if sil and sil[0][0] <= 0.05 else 0.0
    trail = total - sil[-1][0] if sil and sil[-1][1] >= total - 0.05 else 0.0
    longest = max(sil, key=lambda p: p[1] - p[0]) if sil else (0.0, 0.0)
    return {'active': round(total - silent, 2), 'share': round((total - silent) / total, 3) if total else 0,
            'lead': round(lead, 2), 'trail': round(trail, 2),
            'longest': round(longest[1] - longest[0], 2), 'longest_at': round(longest[0], 2),
            'silences': [(round(s, 2), round(e, 2)) for s, e in sil]}


# ---------- 画面 ----------

def gray_frame(path, t):
    out = run(['ffmpeg', '-hide_banner', '-v', 'error', '-ss', '%.3f' % max(t, 0), '-i', str(path), '-frames:v', '1',
               '-vf', 'scale=%d:%d' % (GRAY_W, GRAY_H), '-pix_fmt', 'gray', '-f', 'rawvideo', '-'], binary=True)
    data = out.stdout
    return list(data[:GRAY_W * GRAY_H]) if len(data) >= GRAY_W * GRAY_H else None


def frame_stats(px):
    n = len(px)
    hist = [0] * 16
    for v in px:
        hist[v >> 4] += 1
    strong = 0
    for y in range(GRAY_H - 1):
        row = y * GRAY_W
        for x in range(GRAY_W - 1):
            i = row + x
            if abs(px[i] - px[i + 1]) + abs(px[i] - px[i + GRAY_W]) > 24:
                strong += 1
    return {'hist': [c / n for c in hist], 'edge': strong / ((GRAY_W - 1) * (GRAY_H - 1))}


def shot_profile(path, edges):
    """每镜：动没动；和上一镜比变没变。"""
    rows, prev, total = [], None, edges[-1]
    for i, (a, b) in enumerate(zip(edges, edges[1:]), 1):
        row = {'no': i, 'start': round(a, 2), 'end': round(b, 2), 'motion': None, 'still': None, 'flat': None}
        if b - a >= 0.6:
            first, last = gray_frame(path, a + 0.25), gray_frame(path, min(b - 0.25, total - 0.1))
            if first and last:
                row['motion'] = round(sum(abs(x - y) for x, y in zip(first, last)) / (len(first) * 255), 3)
                row['still'] = row['motion'] < STILL
        mid = gray_frame(path, min((a + b) / 2, max(total - 0.15, 0)))
        st = frame_stats(mid) if mid else None
        if st and prev:
            d_hist = 0.5 * sum(abs(x - y) for x, y in zip(prev['hist'], st['hist']))
            row['flat'] = d_hist < FLAT_HIST and abs(st['edge'] - prev['edge']) < FLAT_EDGE
        prev = st
        rows.append(row)
    return rows


def contact_sheet(path, edges, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem, total, frames = Path(path).stem, edges[-1], []
    can_label = 'drawtext' in run(['ffmpeg', '-hide_banner', '-filters']).stdout
    for i, (a, b) in enumerate(zip(edges, edges[1:]), 1):
        mid = min((a + b) / 2, max(total - 0.15, 0))
        target = out_dir / ('%s-shot%02d.jpg' % (stem, i))
        base = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', '%.3f' % mid, '-i', str(path), '-frames:v', '1']
        label = "drawtext=text='%d  %s-%ss':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6" % (i, fmt(a), fmt(b))
        done = can_label and run(base + ['-vf', 'scale=480:-2,' + label, '-q:v', '4', str(target)]).returncode == 0
        if not done or not target.exists():           # 没有 drawtext 或找不到字体：不标号，照样出图
            run(base + ['-vf', 'scale=480:-2', '-q:v', '4', str(target)])
        if target.exists():
            frames.append(target)
    sheet = None
    if frames:
        cols = len(frames) if len(frames) <= 4 else math.ceil(len(frames) / 2)
        rows = math.ceil(len(frames) / cols)
        listing = out_dir / (stem + '-frames.txt')
        listing.write_text(''.join("file '%s'\n" % f.resolve() for f in frames), encoding='utf-8')
        sheet = out_dir / (stem + '-sheet.jpg')
        run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
             '-vf', 'scale=360:480:force_original_aspect_ratio=decrease,pad=360:480:(ow-iw)/2:(oh-ih)/2,tile=%dx%d' % (cols, rows),
             '-frames:v', '1', '-q:v', '4', str(sheet)])
        if listing.exists():
            listing.unlink()
        if not sheet.exists():
            sheet = None
    return frames, sheet


def save_last_frame(path, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-sseof', '-0.3', '-i', str(path), '-update', '1', '-q:v', '1', str(target)])
    return target if target.exists() else None


# ---------- Prompt 这一边 ----------

def declared(prompt_path, plan_path=None):
    import check
    prompt = check.Prompt(prompt_path)
    shots = [(s['镜'], s['a'], s['b']) for s in prompt.shots]
    en = zh = 0
    for line in prompt.lines():
        e, z = check.count(line)
        en, zh = en + e, zh + z
    rates = None
    plan = plan_path or check.find_plan(prompt, None)
    if plan and Path(plan).is_file():
        rates = check.Plan(plan).rates
    return {'shots': shots, 'cuts': [b for _, _, b in shots[:-1]], 'words': en, 'chars': zh, 'rates': rates,
            'version': prompt.version, 'clip': prompt.clip}


# ---------- 汇总 ----------

def fmt(x):
    return ('%.1f' % (x + 1e-9)).rstrip('0').rstrip('.')


def measure(video, prompt=None, plan=None, scene=0.3, silence=-30, frames=None, no_frames=False, last_frame=None):
    video = Path(video)
    total = duration(video)
    cuts = detect_cuts(video, scene)
    r = {'file': str(video), 'duration': round(total, 2), 'cuts': cuts, 'sound': sound(video, total, silence),
         'declared': None, 'pairs': None, 'extra': None, 'rate': None, 'frames': [], 'sheet': None, 'last_frame': None}
    edges = [0.0] + cuts + [total]
    if prompt:
        d = declared(prompt, plan)
        r['declared'] = d
        r['pairs'], r['extra'] = match_cuts(d['cuts'], cuts)
        if d['shots']:
            edges = [0.0] + [min(float(t), total) for t in d['cuts']] + [total]
        if r['sound'] and r['sound']['active'] > 0 and (d['words'] or d['chars']):
            r['rate'] = {'words': round(d['words'] / r['sound']['active'], 2) if d['words'] else None,
                         'chars': round(d['chars'] / r['sound']['active'], 2) if d['chars'] else None}
    r['edges'] = [round(e, 2) for e in edges]
    r['profile'] = shot_profile(video, edges)
    if not no_frames:
        out_dir = Path(frames) if frames else video.with_name(video.stem + '_frames')
        got, sheet = contact_sheet(video, edges, out_dir)
        r['frames'], r['sheet'] = [str(f) for f in got], str(sheet) if sheet else None
    if last_frame:
        saved = save_last_frame(video, last_frame)
        r['last_frame'] = str(saved) if saved else None
    r['summary'] = summary(r)
    return r


def summary(r):
    bits = []
    if r['pairs'] is not None:
        hit = [(t, d) for t, d in r['pairs'] if d is not None]
        worst = max([abs(d - t) for t, d in hit] or [0])
        s = '切点 %d/%d 对上' % (len(hit), len(r['pairs']))
        if hit:
            s += '，最大差 %s 秒' % fmt(worst)
        if r['extra']:
            s += '，多切 %d 处' % len(r['extra'])
        bits.append(s)
    else:
        bits.append('检出 %d 个切点、%d 镜' % (len(r['cuts']), len(r['cuts']) + 1))
    if r['sound']:
        bits.append('有声 %s 秒，最长静音 %s 秒' % (fmt(r['sound']['active']), fmt(r['sound']['longest'])))
    else:
        bits.append('没有声音轨')
    if r['rate']:
        if r['rate']['words']:
            bits.append('语速不低于 %s 词/秒' % fmt(r['rate']['words']))
        if r['rate']['chars']:
            bits.append('语速不低于 %s 字/秒' % fmt(r['rate']['chars']))
    still = [str(p['no']) for p in r['profile'] if p['still']]
    flat = ['%d→%d' % (p['no'] - 1, p['no']) for p in r['profile'] if p['flat']]
    bits.append('静的镜 ' + ('、'.join(still) if still else '无'))
    bits.append('平的切点 ' + ('、'.join(flat) if flat else '无'))
    return '；'.join(bits)


def report(r):
    out = ['== %s：%s 秒' % (Path(r['file']).name, fmt(r['duration']))]
    lengths = [round(b - a, 2) for a, b in zip([0.0] + r['cuts'], r['cuts'] + [r['duration']])]
    out.append('切点：检出 %d 个（%s）→ %d 镜，镜长 %s' % (len(r['cuts']), '、'.join(fmt(c) for c in r['cuts']) or '无',
                                                 len(lengths), '、'.join(fmt(x) for x in lengths)))
    if r['declared']:
        d = r['declared']
        out.append('对 Prompt（clip%02d v%s，%d 镜）：' % (d['clip'] or 0, d['version'], len(d['shots'])))
        found = dict(r['pairs'])
        start = 0.0
        for i, (no, a, b) in enumerate(d['shots']):
            end = r['duration'] if i == len(d['shots']) - 1 else found.get(b)
            if end is None:
                out.append('  镜 %s  声明 %s-%s  实测 结尾这一刀没切出来' % (no, a, b))
            elif start is None:
                out.append('  镜 %s  声明 %s-%s  实测 ?-%s（开头那一刀没切出来）' % (no, a, b, fmt(end)))
            else:
                out.append('  镜 %s  声明 %s-%s  实测 %s-%s  差 %s 秒' % (no, a, b, fmt(start), fmt(end), fmt(abs(end - b))))
            start = end
        out.append('  多切：%s' % ('、'.join(fmt(x) + ' 秒' for x in r['extra']) if r['extra'] else '无'))
    s = r['sound']
    if s:
        out.append('声音：有声 %s 秒（%d%%）；开头静音 %s 秒，结尾静音 %s 秒；最长静音 %s 秒，在 %s 秒处' % (
            fmt(s['active']), round(s['share'] * 100), fmt(s['lead']), fmt(s['trail']), fmt(s['longest']), fmt(s['longest_at'])))
        out.append('静音段：%s' % ('、'.join('%s-%s' % (fmt(a), fmt(b)) for a, b in s['silences']) or '无'))
    else:
        out.append('声音：没有声音轨')
    if r['rate'] and r['declared']:
        d = r['declared']
        if r['rate']['words']:
            line = '语速：%d 词 ÷ 有声 %s 秒 ≈ %s 词/秒（下限）' % (d['words'], fmt(s['active']), fmt(r['rate']['words']))
            out.append(line + ('；方案 %s 词/秒' % fmt(d['rates'][0]) if d['rates'] else ''))
        if r['rate']['chars']:
            line = '语速：%d 字 ÷ 有声 %s 秒 ≈ %s 字/秒（下限）' % (d['chars'], fmt(s['active']), fmt(r['rate']['chars']))
            out.append(line + ('；方案 %s 字/秒' % fmt(d['rates'][1]) if d['rates'] else ''))
    src = '按 Prompt 的镜头时间' if r['declared'] and r['declared']['shots'] else '按检出的切点'
    out.append('每镜（%s）：' % src + '；'.join(
        '镜 %d %s%s' % (p['no'], '量不了' if p['still'] is None else ('静' if p['still'] else '动'),
                       '' if p['flat'] is None else ('，和上一镜比平' if p['flat'] else '，和上一镜比变')) for p in r['profile']))
    if r['frames']:
        out.append('抽帧 %d 张：%s' % (len(r['frames']), Path(r['frames'][0]).parent))
    if r['sheet']:
        out.append('拼图（按镜头顺序，从左到右、从上到下）：%s' % r['sheet'])
    if r['last_frame']:
        out.append('末帧：%s' % r['last_frame'])
    out.append('摘要：' + r['summary'])
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video')
    ap.add_argument('--prompt')
    ap.add_argument('--plan')
    ap.add_argument('--scene', type=float, default=0.3)
    ap.add_argument('--silence', type=float, default=-30)
    ap.add_argument('--frames')
    ap.add_argument('--no-frames', action='store_true')
    ap.add_argument('--last-frame')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
        print('要先装 ffmpeg 和 ffprobe')
        return 2
    if not Path(args.video).is_file():
        print('找不到成片：%s' % args.video)
        return 2
    r = measure(args.video, args.prompt, args.plan, args.scene, args.silence, args.frames, args.no_frames, args.last_frame)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str) if args.json else report(r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
