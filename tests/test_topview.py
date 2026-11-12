# -*- coding: utf-8 -*-
"""topview.py 的测试：对话里那一张图、能按拍看的页面、机位在动的镜头、人物离场。"""
import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check  # noqa: E402
import topview  # noqa: E402

FIX = ROOT / 'tests' / 'fixtures' / 'demo'
MOVE = ('| 02 | 3 | 11-16 | D | Mia、Jack | 中景 | 轻微手持｜跟 Jack｜Jack 从车门边 → 朝 Mia 走半步 |',
        '| 02 | 3 | 11-16 | E→D | Mia、Jack | 中景 | 缓慢环绕｜绕着 Mia｜Mia 的近景 → 拉开成双人中景 |')
EXIT_POINT = ('| 车门边 | 点 | 6.5 | 5.5 | 驾驶座车门外 |',
              '| 车门边 | 点 | 6.5 | 5.5 | 驾驶座车门外 |\n| 出口 | 点 | 8.5 | 9.5 | 卷帘门画右一头，通到街上 |')
MIA_4 = '| 4 | Mia | 车头 | 画面中间偏左的车头前 | 往后靠在车头上，两手抱在胸前 | 看 Jack | 抹布搭在肩上 | 同上 |'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIX, self.tmp / 'demo')
        self.plan = self.tmp / 'demo' / '04_plan' / 'demo-s01.plan.md'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def change(self, old, new):
        s = self.plan.read_text(encoding='utf-8')
        self.assertEqual(s.count(old), 1, old)
        self.plan.write_text(s.replace(old, new), encoding='utf-8')

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = topview.main([str(self.plan)] + list(args))
        return code, buf.getvalue()

    def chat(self, *args):
        code, out = self.run_main('--chat', *args)
        self.assertEqual(code, 0, out)
        return out

    def page(self, *args):
        out = self.tmp / 'page.html'
        code, printed = self.run_main('--out', str(out), *args)
        self.assertEqual(code, 0, printed)
        return out.read_text(encoding='utf-8')


class Chat(Base):
    def test_one_svg_the_drawing_tool_can_take(self):
        svg = self.chat()
        self.assertTrue(svg.startswith('<svg width="100%" viewBox="0 0 680 '))
        self.assertTrue(svg.rstrip().endswith('</svg>'))
        self.assertEqual(svg.count('<svg'), 1)
        self.assertIn('role="img"><title>demo-s01 修车铺 俯视图</title><desc>', svg)
        self.assertIn('<marker id="arrow"', svg)
        for banned in ('<style', '<!--', '<table', 'font-size', '<script', 'http'):
            self.assertNotIn(banned, svg)
        for text in re.findall(r'<text[^>]*>', svg):                  # 每一行字都用画图工具自带的类
            self.assertRegex(text, r'class="(t|ts|th)"')

    def test_shows_the_space_the_people_and_every_camera(self):
        svg = self.chat()
        for token in ('>卷帘门<', '>工作台<', '>车<', '>门灯<', '>工作灯<', '>Mia<', '>Jack<', '>第 3 拍到车头<', '>第 3 拍到车门边<',
                      '>开场的位置<', '>后来走到的位置<', '>脸朝哪<', '>机位，张开的一片越窄焦段越长<', '>单人镜拍的是谁<',
                      '>画左<', '>画右<', '>远<', '>近（场景图是从这边拍的）<'):
            self.assertIn(token, svg)
        for cam in 'ABCDE':
            self.assertIn('<g><title>机位 %s：' % cam, svg)
        self.assertEqual(svg.count('<rect class="box"'), 3 + 5 + 1)     # 三样固定的东西、五个机位、图例里一个
        self.assertEqual(svg.count('<circle class="c-amber"'), 2)       # 两盏灯画在各自的位置上
        self.assertEqual(svg.count('stroke-dasharray="4 4"'), 2)        # 两个后来走到的位置
        self.assertNotIn('镜头里机位在动', svg)
        self.assertNotIn('>Mia 靠在车头上的近景<', svg)                 # 机位多，不在旁边写拍什么

    def test_each_person_has_a_colour(self):
        svg = self.chat()
        self.assertIn('<circle class="c-teal"', svg)                    # Mia
        self.assertIn('<circle class="c-purple"', svg)                  # Jack
        self.assertEqual(svg.count('stroke="#1D9E75" stroke-width="1.5" marker-end="url(#arrow)"'), 1)    # Mia 的走位
        self.assertEqual(svg.count('stroke="#7F77DD" stroke-width="1.5" marker-end="url(#arrow)"'), 1)    # Jack 的走位
        self.assertEqual(svg.count('class="c-teal"'), 1)
        self.assertEqual(svg.count('class="c-purple"'), 1)

    def test_a_dotted_line_runs_from_a_single_camera_to_its_subject(self):
        svg = self.chat()
        dots = re.findall(r'<line x1="(\d+)" y1="(\d+)" x2="(\d+)" y2="(\d+)" stroke="var\(--s\)" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="0 5"/>', svg)
        self.assertEqual(len(dots), 3 + 1)                              # B、C、E 是单人镜，各一条；图例里一条。A、D 拍两个人，不连
        jack = re.search(r'<circle class="c-purple" cx="(\d+)" cy="(\d+)"', svg)
        x2, y2 = int(dots[1][2]), int(dots[1][3])                       # 机位 C 拍的是第 1 拍站在门口的 Jack
        self.assertLess(((x2 - int(jack.group(1))) ** 2 + (y2 - int(jack.group(2))) ** 2) ** 0.5, 22)

    def test_camera_on_a_thing_gets_a_line_to_that_thing(self):
        self.change('| 01 | 4 | 16-20 | A | Mia、Jack | 全景 |', '| 01 | 4 | 16-20 | A | 环境 | 全景 |')
        self.change('| 01 | 1 | 0-4 | A | Mia、Jack | 全景 |', '| 01 | 1 | 0-4 | A | 环境 | 全景 |')
        svg = self.chat('--clip', '1')
        box = re.search(r'<rect class="box" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" rx="6" stroke-width="0.5"/>\n<text class="th"[^>]*>车<', svg)
        bx, by, bw, bh = [int(v) for v in box.groups()]
        dots = re.findall(r'<line x1="(\d+)" y1="(\d+)" x2="(\d+)" y2="(\d+)" stroke="var\(--s\)" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="0 5"/>', svg)
        self.assertTrue(any(bx - 8 <= int(d[2]) <= bx + bw + 8 and by - 8 <= int(d[3]) <= by + bh + 8 for d in dots))   # 停在车那个方框的边上

    def test_no_dotted_line_when_the_subject_is_right_there(self):
        self.assertIsNone(topview.to_box_edge((10, 10), (0, 0, 40, 40)))
        end = topview.to_box_edge((100, 20), (0, 0, 40, 40))
        self.assertAlmostEqual(end[0], 44, delta=0.6)
        self.assertAlmostEqual(end[1], 20, delta=0.6)

    def test_camera_cover_is_wider_for_a_wider_lens(self):
        svg = self.chat()
        wide = []
        for x, y, x1, y1, x2, y2 in re.findall(r'<path d="M(\d+) (\d+)L(\d+) (\d+)L(\d+) (\d+)Z" fill="var\(--s\)" fill-opacity="0.08"', svg):
            wide.append(((int(x1) - int(x2)) ** 2 + (int(y1) - int(y2)) ** 2) ** 0.5)
        self.assertEqual(len(wide), 5)                                  # 一个机位一片，按机位表的顺序
        self.assertGreater(wide[0], wide[3])                            # A 广角比 D 中焦宽
        self.assertGreater(wide[3], wide[1])                            # D 中焦比 B 中长焦宽

    def test_boxes_step_off_people_and_paths(self):
        box = topview.clear_of((0, 0, 40, 40), [(38, 20, 10)])
        self.assertLessEqual(box[2], 28)                                # 往左让开了
        self.assertEqual((box[1], box[3]), (0, 40))
        self.assertEqual(topview.clear_of((0, 0, 40, 40), [(100, 100, 10)]), (0, 0, 40, 40))

    def test_everything_stays_on_the_canvas(self):
        for args in ((), ('--clip', '1'), ('--clip', '2')):
            svg = self.chat(*args)
            height = int(re.search(r'viewBox="0 0 680 (\d+)"', svg).group(1))
            self.assertLessEqual(height, 760)
            for x in re.findall(r'\b(?:x|x1|x2|cx)="(-?\d+)"', svg):
                self.assertTrue(0 <= int(x) <= 680, x)
            for y in re.findall(r'\b(?:y|y1|y2|cy)="(-?\d+)"', svg):
                self.assertTrue(0 <= int(y) <= height, y)

    def test_one_clip_only(self):
        svg = self.chat('--clip', '2')
        self.assertIn('<title>demo-s01 修车铺 俯视图 clip02</title>', svg)
        self.assertEqual(svg.count('<g><title>机位 '), 2)               # 这一条只用了 D、E
        for cam in 'ABC':
            self.assertNotIn('<title>机位 %s：' % cam, svg)
        for token in ('>这一条开头的位置<', '>车边的双人中景<', '>Mia 靠在车头上的近景<'):   # 机位少，旁边写了拍什么
            self.assertIn(token, svg)

    def test_first_clip_has_no_later_moves(self):
        svg = self.chat('--clip', '1')
        self.assertNotIn('第 3 拍', svg)
        self.assertNotIn('后来走到的位置', svg)

    def test_camera_move_is_a_dashed_line_with_the_shot_number(self):
        self.change(*MOVE)
        svg = self.chat('--clip', '2')
        self.assertRegex(svg, r'<path d="M\d+ \d+Q\d+ \d+ \d+ \d+" fill="none" stroke="var\(--s\)" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url\(#arrow\)"/>')
        self.assertIn('>镜 3<', svg)
        self.assertIn('>镜头里机位在动<', svg)
        self.assertIn('>clip02 镜 3<', self.chat())                     # 全场那张要带上是哪一条

    def test_straight_move_when_the_camera_does_not_circle(self):
        self.change(MOVE[0], MOVE[1].replace('缓慢环绕｜绕着 Mia', '缓慢横移｜跟 Mia'))
        m = re.search(r'<path d="M(\d+) (\d+)Q(\d+) (\d+) (\d+) (\d+)" fill="none" stroke="var\(--s\)" stroke-width="1.5"', self.chat('--clip', '2'))
        x0, y0, cx, cy, x1, y1 = [int(v) for v in m.groups()]
        self.assertLessEqual(abs((x0 + x1) / 2.0 - cx), 1)              # 控制点就在中点上：是直线
        self.assertLessEqual(abs((y0 + y1) / 2.0 - cy), 1)

    def test_someone_leaving(self):
        self.change(*EXIT_POINT)
        self.change(MIA_4, MIA_4 + '\n| 4 | Jack | 出口 | 画右深处的卷帘门边 | 离场，往出口走 | 看 出口 | 两手空着 | 门灯 |')
        svg = self.chat()
        self.assertIn('>第 4 拍离场，往出口<', svg)
        self.assertEqual(svg.count('stroke-dasharray="4 4"'), 2)        # 出口那里不画人
        self.assertEqual(svg.count('stroke="#7F77DD" stroke-width="1.5" marker-end="url(#arrow)"'), 2)    # Jack 走了两段
        plan = check.Plan(self.plan)
        self.assertEqual(plan.state('Jack', 4)['点'], '出口')
        self.assertIsNone(plan.state('Jack', 5))
        self.assertIn('Jack 第 4 拍离场', self.page())

    def test_wrong_use(self):
        self.assertEqual(self.run_main('--clip', '2')[0], 2)            # --clip 要和 --chat 一起
        self.assertEqual(self.run_main('--chat', '--clip', '9')[0], 2)
        self.plan = self.tmp / 'none.plan.md'
        self.assertEqual(self.run_main('--chat')[0], 2)

    def test_can_save_to_a_file(self):
        out = self.tmp / 'a' / 'map.svg'
        code, printed = self.run_main('--chat', '--out', str(out))
        self.assertEqual(code, 0)
        self.assertEqual(printed.strip(), str(out))
        self.assertTrue(out.read_text(encoding='utf-8').startswith('<svg'))


class Page(Base):
    def test_page_is_only_the_map(self):
        page = self.page()
        for token in ('<title>demo-s01 修车铺 机位图</title>', '5 个机位', 'data-pick="all"', 'data-beat="3"', '卷帘门', '门灯',
                      '<title>机位 B：中长焦，和 Mia 的眼睛同高，平视｜Mia 的单人近景</title>'):
            self.assertIn(token, page)
        self.assertEqual(page.count('<svg'), 1)
        self.assertNotIn('<table', page)                              # 机位、走位、分镜三张表不放在页面上

    def test_page_follows_the_artifact_contract(self):
        page = self.page()
        self.assertFalse(re.search(r'<!doctype|<html|<body', page, re.I))
        self.assertIn('<meta name="claude:viewport-fit-sides" content="cover">', page)
        self.assertIn('max(16px, env(safe-area-inset-left, 0px))', page)
        self.assertIn('max(16px, env(safe-area-inset-right, 0px))', page)
        self.assertIn('@media (prefers-color-scheme: dark)', page)
        self.assertIn(':root:not([data-theme="light"])', page)
        self.assertIn(':root[data-theme="dark"]', page)
        self.assertFalse(re.search(r'https?://', page))               # 不联网

    def test_standalone_page_opens_in_a_browser(self):
        page = self.page('--standalone')
        self.assertTrue(page.startswith('<!doctype html>'))
        self.assertIn('<meta charset="utf-8">', page)

    def test_camera_move_on_the_page(self):
        self.change(*MOVE)
        page = self.page()
        self.assertIn('<path class="cm k4" d="M', page)
        self.assertIn('>clip02 镜 3<', page)

    def test_default_file_sits_next_to_the_plan(self):
        code, printed = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(Path(printed.strip()), self.plan.with_name('demo-s01.topview.html'))


if __name__ == '__main__':
    unittest.main()
