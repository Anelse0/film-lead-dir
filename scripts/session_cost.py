#!/usr/bin/env python3
"""量一次会话花在哪里。读 Claude Code 的会话记录（.jsonl），只读，不改任何东西。

  python3 scripts/session_cost.py <session.jsonl> [<more.jsonl>…]
  python3 scripts/session_cost.py --latest 3 [--project-dir ~/.claude/projects/<slug>]

每个会话打印：
  调用        按 message id 去重的 API 调用数；output token；缓存读取 token；平均和峰值上下文
  用户几轮    用户自己说了几次话（不算工具结果和系统提示）
  输出构成    正文、工具输入（Write 的文件内容等）、思考 各多少字符
  规则文读取  Read 了哪些 skill 文件几次、多少字；cat / sed / grep 查 skill 文件的次数
  脚本        check / measure_clip / emotion_library 各跑几次；其中两次之间没有任何改动的重复跑有几次
  整篇重写    04_plan / 06_prompts / 07_log 下的文件被 Write 了几次、共多少字（Edit 另计）

用途：改了 skill 以后，拿下一场戏的会话和上一场比；验收时量"到第一条成片前用户说了几轮"。
"""
import collections
import json
import os
import re
import sys
from pathlib import Path

SCRIPTS = ('check', 'measure_clip', 'emotion_library')
ARTIFACT_DIRS = ('04_plan', '06_prompts', '07_log')


def project_dir(default=None):
    if default:
        return Path(default).expanduser()
    slug = str(Path.cwd().resolve()).replace('/', '-')
    return Path.home() / '.claude' / 'projects' / slug


def measure(path):
    calls = {}
    ctx = []
    text = think = tool_input = 0
    reads = collections.Counter()
    read_chars = collections.Counter()
    lookups = 0
    scripts = collections.Counter()
    seq = []
    writes = collections.Counter()
    write_chars = collections.Counter()
    edits = collections.Counter()
    pending = {}
    compactions = 0
    user_turns = 0
    first = last = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get('isCompactSummary'):
                compactions += 1
            ts = m.get('timestamp')
            if ts:
                first = first or ts
                last = ts
            msg = m.get('message') or {}
            role = msg.get('role')
            content = msg.get('content')
            if role == 'assistant':
                mid = msg.get('id')
                u = msg.get('usage') or {}
                if mid and mid not in calls and u:
                    calls[mid] = u
                    ctx.append(u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('input_tokens', 0))
                if not isinstance(content, list):
                    continue
                for b in content:
                    kind = b.get('type')
                    if kind == 'text':
                        text += len(b.get('text', ''))
                    elif kind == 'thinking':
                        think += len(b.get('thinking', ''))
                    elif kind == 'tool_use':
                        inp = b.get('input') or {}
                        tool_input += len(json.dumps(inp, ensure_ascii=False))
                        name = b.get('name')
                        if name == 'Read':
                            fp = inp.get('file_path', '')
                            if re.search(r'/film-(?:director|lead-dir)[^/]*/', fp):
                                key = re.sub(r'^.*/film-(?:director|lead-dir)[^/]*/', '', fp)
                                reads[key] += 1
                                pending[b.get('id')] = key
                        elif name == 'Bash':
                            cmd = inp.get('command', '')
                            found = set(re.findall(r'(' + '|'.join(SCRIPTS) + r')\.py', cmd))
                            if found:
                                for s in found:
                                    scripts[s] += 1
                                seq.append('script')
                            elif re.search(r'/film-(?:director|lead-dir)[^/]*/', cmd) and re.search(r'\b(cat|sed|head|grep|awk)\b', cmd):
                                lookups += 1
                            elif re.search(r'write_text|>\s*\S+\.md|sed -i|perl .*-i', cmd):
                                seq.append('edit')
                        elif name in ('Write', 'Edit'):
                            fp = inp.get('file_path', '')
                            seq.append('edit')
                            if any(d in fp for d in ARTIFACT_DIRS):
                                base = os.path.basename(fp)
                                if name == 'Write':
                                    writes[base] += 1
                                    write_chars[base] += len(inp.get('content', ''))
                                else:
                                    edits[base] += 1
            elif role == 'user' and isinstance(content, str):
                if content.strip() and not content.lstrip().startswith('<') and not m.get('isMeta') and not m.get('isCompactSummary'):
                    user_turns += 1
            elif role == 'user' and isinstance(content, list):
                said = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
                if any(t.strip() and not t.lstrip().startswith('<') for t in said) and not m.get('isMeta') and not m.get('isCompactSummary'):
                    user_turns += 1
                for b in content:
                    if b.get('type') == 'tool_result' and b.get('tool_use_id') in pending:
                        c = b.get('content')
                        size = sum(len(x.get('text', '')) for x in c if isinstance(x, dict)) if isinstance(c, list) else len(c or '')
                        read_chars[pending.pop(b['tool_use_id'])] += size
    reruns = 0
    last_script = -1
    last_edit = -1
    for i, k in enumerate(seq):
        if k == 'edit':
            last_edit = i
        elif k == 'script':
            if last_script >= 0 and last_edit < last_script:
                reruns += 1
            last_script = i
    out = sum(u.get('output_tokens', 0) for u in calls.values())
    cache_read = sum(u.get('cache_read_input_tokens', 0) for u in calls.values())
    return {
        'file': os.path.basename(path), 'first': first, 'last': last, 'calls': len(calls), 'output_tokens': out,
        'cache_read': cache_read, 'ctx_avg': int(sum(ctx) / len(ctx)) if ctx else 0, 'ctx_max': max(ctx) if ctx else 0,
        'compactions': compactions, 'user_turns': user_turns, 'text': text, 'think': think, 'tool_input': tool_input,
        'reads': reads, 'read_chars': read_chars, 'lookups': lookups, 'scripts': scripts, 'script_runs': sum(scripts.values()),
        'reruns': reruns, 'writes': writes, 'write_chars': write_chars, 'edits': edits,
    }


def report(r):
    print('=' * 96)
    print(f"{r['file']}  {r['first']} → {r['last']}")
    print(f"  调用 {r['calls']}  output {r['output_tokens']:,} tok  缓存读取 {r['cache_read']:,} tok  上下文 平均 {r['ctx_avg']:,} / 峰值 {r['ctx_max']:,}  压缩 {r['compactions']} 次")
    print(f"  用户说了 {r['user_turns']} 轮")
    total = max(1, r['text'] + r['think'] + r['tool_input'])
    print(f"  输出构成（字符）正文 {r['text']:,} ({r['text'] / total:.0%})  工具输入 {r['tool_input']:,} ({r['tool_input'] / total:.0%})  思考 {r['think']:,} ({r['think'] / total:.0%})")
    print(f"  规则文 Read {sum(r['reads'].values())} 次 / {sum(r['read_chars'].values()):,} 字；cat / sed / grep 查 skill 文件 {r['lookups']} 次")
    for k, v in sorted(r['reads'].items(), key=lambda x: -r['read_chars'][x[0]])[:8]:
        print(f"      {v:2d}× {r['read_chars'][k]:7,}  {k}")
    print(f"  脚本 {r['script_runs']} 次（无改动重复 {r['reruns']}）：" + '，'.join(f'{k} {v}' for k, v in r['scripts'].most_common()))
    if r['writes']:
        print('  整篇 Write：' + '，'.join(f"{k} {v}×/{r['write_chars'][k]:,} 字" for k, v in r['writes'].most_common(6)))
    if r['edits']:
        print('  局部 Edit：' + '，'.join(f'{k} {v}×' for k, v in r['edits'].most_common(6)))


def main(argv):
    args = list(argv[1:])
    proj = None
    latest = None
    if '--project-dir' in args:
        i = args.index('--project-dir')
        proj = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if '--latest' in args:
        i = args.index('--latest')
        try:
            latest = int(args[i + 1])
        except (IndexError, ValueError):
            print('--latest 后面要跟数字', file=sys.stderr)
            return 2
        del args[i:i + 2]
    paths = [Path(a).expanduser() for a in args]
    if latest:
        d = project_dir(proj)
        if not d.is_dir():
            print(f'找不到会话目录 {d}（用 --project-dir 指定）', file=sys.stderr)
            return 2
        paths += sorted(d.glob('*.jsonl'), key=lambda p: p.stat().st_mtime)[-latest:]
    if not paths:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        print(__doc__.strip().splitlines()[3].strip(), file=sys.stderr)
        return 2
    for p in paths:
        if not p.is_file():
            print(f'不是文件：{p}', file=sys.stderr)
            return 2
        report(measure(p))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
