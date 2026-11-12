# -*- coding: utf-8 -*-
"""measure_clip.py 和 session_cost.py 的测试。要 ffmpeg 的那几条，没装就跳过。"""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import measure_clip  # noqa: E402
import session_cost  # noqa: E402

HAS_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))

PROMPT = """# synth clip01 · Prompt v2

- 方案：无
- 接上一条：无

---

【分镜时间线】
镜头1（0-2秒）：近景。
镜头2（2-5秒）：硬切。A 用英语、随口地说：{One two three four five six seven eight nine.}
镜头3（5-7秒）：硬切。全景。
"""


class Pure(unittest.TestCase):
    def test_match_cuts(self):
        pairs, extra = measure_clip.match_cuts([2, 5, 9], [2.1, 4.8, 6.0])
        self.assertEqual(pairs, [(2, 2.1), (5, 4.8), (9, None)])
        self.assertEqual(extra, [6.0])

    def test_nearest_cut_wins(self):
        pairs, extra = measure_clip.match_cuts([5], [4.4, 5.1])
        self.assertEqual(pairs, [(5, 5.1)])
        self.assertEqual(extra, [4.4])

    def test_summary(self):
        r = {'pairs': [(2, 2.1), (5, None)], 'extra': [6.0], 'cuts': [2.1, 6.0],
             'sound': {'active': 3.0, 'longest': 2.0}, 'rate': {'words': 3.0, 'chars': None},
             'profile': [{'no': 1, 'still': True, 'flat': None}, {'no': 2, 'still': False, 'flat': True}]}
        self.assertEqual(measure_clip.summary(r), '切点 1/2 对上，最大差 0.1 秒，多切 1 处；有声 3 秒，最长静音 2 秒；语速不低于 3 词/秒；静的镜 1；平的切点 1→2')


@unittest.skipUnless(HAS_FFMPEG, '没有 ffmpeg')
class WithVideo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / 'synth.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y',
                        '-f', 'lavfi', '-i', 'color=c=red:s=360x480:d=2:r=24',
                        '-f', 'lavfi', '-i', 'testsrc=s=360x480:d=3:r=24',
                        '-f', 'lavfi', '-i', 'color=c=blue:s=360x480:d=2:r=24',
                        '-f', 'lavfi', '-i', 'sine=f=440:d=3',
                        '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];[3:a]adelay=2000|2000,apad=whole_dur=7[a]',
                        '-map', '[v]', '-map', '[a]', '-t', '7', '-pix_fmt', 'yuv420p', str(cls.video)], check=True)
        cls.prompt = cls.tmp / 'synth-clip01.prompt.md'
        cls.prompt.write_text(PROMPT, encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_cuts_and_sound(self):
        r = measure_clip.measure(self.video, no_frames=True)
        self.assertAlmostEqual(r['duration'], 7.0, delta=0.1)
        self.assertEqual(len(r['cuts']), 2)
        self.assertAlmostEqual(r['cuts'][0], 2.0, delta=0.15)
        self.assertAlmostEqual(r['cuts'][1], 5.0, delta=0.15)
        self.assertAlmostEqual(r['sound']['active'], 3.0, delta=0.3)
        self.assertAlmostEqual(r['sound']['lead'], 2.0, delta=0.2)
        self.assertAlmostEqual(r['sound']['trail'], 2.0, delta=0.2)

    def test_against_prompt(self):
        r = measure_clip.measure(self.video, prompt=self.prompt, no_frames=True)
        self.assertEqual([d is not None for _, d in r['pairs']], [True, True])
        self.assertEqual(r['extra'], [])
        self.assertEqual(r['declared']['words'], 9)
        self.assertAlmostEqual(r['rate']['words'], 3.0, delta=0.4)
        self.assertIn('切点 2/2 对上', r['summary'])

    def test_frames_sheet_and_last_frame(self):
        out = self.tmp / 'frames'
        last = self.tmp / 'last.png'
        r = measure_clip.measure(self.video, prompt=self.prompt, frames=out, last_frame=last)
        self.assertEqual(len(r['frames']), 3)
        self.assertTrue(Path(r['sheet']).is_file())
        self.assertTrue(last.is_file())

    def test_cli_report(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = measure_clip.main([str(self.video), '--prompt', str(self.prompt), '--no-frames'])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        for token in ('对 Prompt（clip01 v2，3 镜）', '镜 2  声明 2-5', '语速：9 词', '摘要：'):
            self.assertIn(token, text)

    def test_missing_file(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(measure_clip.main([str(self.tmp / 'nope.mp4')]), 2)


class SessionCost(unittest.TestCase):
    def test_counts(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            log = tmp / 's.jsonl'
            rows = [
                {'timestamp': 't1', 'message': {'role': 'user', 'content': '开始'}},
                {'timestamp': 't2', 'message': {'role': 'assistant', 'id': 'm1', 'usage': {'output_tokens': 10, 'input_tokens': 5},
                                                'content': [{'type': 'text', 'text': '好'},
                                                            {'type': 'tool_use', 'id': 'u1', 'name': 'Read',
                                                             'input': {'file_path': '/x/skills/film-director/references/qa.md'}},
                                                            {'type': 'tool_use', 'id': 'u2', 'name': 'Bash',
                                                             'input': {'command': 'python3 scripts/check.py dock1 a.plan.md'}},
                                                            {'type': 'tool_use', 'id': 'u3', 'name': 'Write',
                                                             'input': {'file_path': '/p/04_plan/a.plan.md', 'content': 'abc'}}]}},
                {'timestamp': 't3', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'u1', 'content': 'x' * 40}]}},
                {'timestamp': 't4', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '<system-reminder>x</system-reminder>'}]}},
            ]
            log.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
            r = session_cost.measure(log)
            self.assertEqual(r['calls'], 1)
            self.assertEqual(r['user_turns'], 1)
            self.assertEqual(dict(r['reads']), {'references/qa.md': 1})
            self.assertEqual(r['read_chars']['references/qa.md'], 40)
            self.assertEqual(dict(r['scripts']), {'check': 1})
            self.assertEqual(dict(r['writes']), {'a.plan.md': 1})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
