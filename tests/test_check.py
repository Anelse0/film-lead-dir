# -*- coding: utf-8 -*-
"""check.py 的测试：拿一场能过的假方案，一处一处改坏，看拦不拦得住。

  python3 -m unittest discover -s tests
"""
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check  # noqa: E402

FIX = ROOT / 'tests' / 'fixtures' / 'demo'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dir = self.tmp / 'demo'
        shutil.copytree(FIX, self.dir)
        self.plan = self.dir / '04_plan' / 'demo-s01.plan.md'
        self.prompt = self.dir / '06_prompts' / 'demo-s01-clip01.prompt.md'
        self.log = self.dir / '07_log' / 'demo-s01.log.md'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def change(self, path, old, new, count=1):
        s = path.read_text(encoding='utf-8')
        self.assertEqual(s.count(old), count, '假方案里要改的那句找到 %d 处：%s' % (s.count(old), old))
        path.write_text(s.replace(old, new), encoding='utf-8')

    def run_check(self, when, path=None):
        target = path or (self.plan if when.startswith('dock') or when == 'map' else self.prompt)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check.main([when, str(target)])
        return code, buf.getvalue()

    def bad(self, when, fragment):
        code, out = self.run_check(when)
        self.assertEqual(code, 1, out)
        self.assertIn(fragment, out)
        return out

    def ok(self, when):
        code, out = self.run_check(when)
        self.assertEqual(code, 0, out)
        self.assertIn('· 过', out.splitlines()[0])
        return out


class Passing(Base):
    def test_five_moments_pass(self):
        for when in ('dock1', 'dock2', 'dock3', 'prompt', 'qa'):
            self.ok(when)

    def test_map_prints(self):
        code, out = self.run_check('map')
        self.assertEqual(code, 0)
        for token in ('俯视图', 'CA', 'P3', '==', '门灯'):
            self.assertIn(token, out)

    def test_dock3_prints_what_prompt_needs(self):
        out = self.ok('dock3')
        self.assertIn('clip01 镜 1 · 机位 A｜从画左到画右：Mia、Jack', out)
        self.assertIn('亮的是远离镜头的半边', out)
        self.assertIn('8 句里，4 句给说话的人，3 句同框，1 句给了听的人或环境', out)
        self.assertIn('条数：2 条（20 秒、16 秒）。最少 2 条', out)

    def test_unfilled_template_fails(self):
        code, out = self.run_check('dock3', ROOT / 'templates' / 'scene-plan.md')
        self.assertEqual(code, 1)
        self.assertIn('「目的」没写', out)
        self.assertIn('「支点」要写第几拍', out)

    def test_missing_file(self):
        code, _ = self.run_check('dock1', self.dir / 'nope.md')
        self.assertEqual(code, 2)


class Counting(unittest.TestCase):
    def test_english_words(self):
        self.assertEqual(check.count("I'm still waiting on a part from the city."), (9, 0))
        self.assertEqual(check.count('World-class, isn’t it?'), (3, 0))

    def test_chinese_chars(self):
        self.assertEqual(check.count('我还在等一个零件。'), (0, 8))

    def test_seconds(self):
        self.assertEqual(check.seconds("I'm still waiting on a part from the city.", (3.5, 4.0)), 2.6)
        self.assertEqual(check.seconds("I'm still waiting on a part from the city.", (3.5, 4.0), 2.5), 3.6)
        self.assertEqual(check.seconds('我还在等一个零件。', (3.5, 4.0)), 2.0)

    def test_banned_list(self):
        cats = check.parse_banned(check.read(check.STYLE))
        self.assertEqual(sorted(cats), sorted(['光', '背景', '声音', '表演', '方位']))
        self.assertIn('亮点', cats['光'])
        self.assertIn('耸肩', cats['表演'])
        self.assertEqual(sum(len(v) for v in cats.values()), 50)
        for word, cat in (('眼睛里的亮光', '光'), ('大呼一口气', '表演'), ('东侧', '方位'), ('北面', '方位'), ('东南', '方位')):
            self.assertIn(word, cats[cat])


class Dock1(Base):
    def test_purpose_empty(self):
        self.change(self.plan, '- 目的：Jack 想从 Mia 手里拿回车；Mia 想让他多留一会儿', '- 目的：')
        self.bad('dock1', '「目的」没写')

    def test_pivot_not_a_beat(self):
        self.change(self.plan, '- 支点：第 3 拍', '- 支点：第 9 拍')
        self.bad('dock1', '支点写的第 9 拍不在节拍表里')

    def test_line_not_in_a_beat(self):
        self.change(self.plan, '| 3 | 2 | Mia | I', '| 3 | 9 | Mia | I')
        self.bad('dock1', '句 3 没有归到节拍表里的某一拍')

    def test_word_count_wrong(self):
        self.change(self.plan, 'from the city. | 9 | | 2.6 |', 'from the city. | 8 | | 2.6 |')
        self.bad('dock1', '句 3 的词数应为 9')

    def test_seconds_wrong(self):
        self.change(self.plan, 'from the city. | 9 | | 2.6 |', 'from the city. | 9 | | 3 |')
        self.bad('dock1', '句 3 的秒数应为 2.6')

    def test_own_pace_changes_seconds(self):
        self.change(self.plan, 'from the city. | 9 | | 2.6 |', 'from the city. | 9 | 2.5 | 2.6 |')
        self.bad('dock1', '句 3 的秒数应为 3.6')

    def test_total_wrong(self):
        self.change(self.plan, '合计：8 句，11.7 秒。', '合计：8 句，12 秒。')
        self.bad('dock1', '合计：8 句，11.7 秒。')

    def test_speaker_unknown(self):
        self.change(self.plan, '| 4 | 2 | Jack | You said', '| 4 | 2 | Sam | You said')
        self.bad('dock1', '句 4 的说话人 Sam 不在「人物状态」里')

    def test_missing_costume_image_is_an_ask(self):
        self.change(self.plan, '| @Jack-夹克 | Jack | 服装：棕色皮夹克，灰 T 恤，牛仔裤 | 白底 |\n', '')
        out = self.bad('dock1', 'Jack 没有服装的参考图')
        self.assertIn('只差要用户给的 1 项', out.splitlines()[0])

    def test_missing_line_is_an_ask(self):
        self.change(self.plan, '缺：无', '缺：门外街道的图')
        self.bad('dock1', '缺：门外街道的图')

    def test_person_without_image_can_be_text_only(self):
        self.change(self.plan, '| @Jack-基础形象 | Jack | 脸型、五官、发型 | 图里的衣服和背景 |\n', '| — | Jack | 无图，文字写 | — |\n')
        self.change(self.plan, '| @Jack-夹克 | Jack | 服装：棕色皮夹克，灰 T 恤，牛仔裤 | 白底 |\n', '')
        self.ok('dock1')

    def test_banned_word_in_look(self):
        self.change(self.plan, '- 身后：人物身后是半拉下来的灰色卷帘门，被门灯照亮', '- 身后：人物身后是半拉下来的灰色卷帘门，头上有顶光')
        self.bad('dock1', '禁写词「顶光」')

    def test_allow_list_lets_a_word_through(self):
        self.change(self.plan, '- 身后：人物身后是半拉下来的灰色卷帘门，被门灯照亮', '- 身后：人物身后是半拉下来的灰色卷帘门，头上有顶光')
        self.change(self.plan, '- 放行：无', '- 放行：顶光（用户 11-11："这场要顶光"）')
        self.ok('dock1')

    def test_project_preference_overrides_a_category(self):
        (self.tmp / '导演偏好.md').write_text('# 导演偏好\n\n## 禁写词\n\n- 光：霓虹\n', encoding='utf-8')
        self.change(self.plan, '- 身后：人物身后是半拉下来的灰色卷帘门，被门灯照亮', '- 身后：人物身后是卷帘门，头上有顶光，墙上有霓虹')
        out = self.bad('dock1', '禁写词「霓虹」')
        self.assertNotIn('顶光」', out)

    def test_voice_missing(self):
        self.change(self.plan, '  - Jack：三十多岁的男声，说话直\n', '')
        self.bad('dock1', '声音里没有 Jack 的音色')


class Dock2(Base):
    def test_listener_row_missing(self):
        self.change(self.plan, '| 2 | Jack | 听 3 | 不信 | 两手插进夹克口袋 | 头偏一下，眼睛眯一点 | — | 她说到 "a part" |\n', '')
        self.bad('dock2', '句 3 没有听的人的行')

    def test_speaker_expression_empty(self):
        self.change(self.plan, '| 眼睛往上抬一点，嘴角微微上扬 | 随口；说完停一下 |', '| | 随口；说完停一下 |')
        self.bad('dock2', '句 2（Mia）的「表情」是空的')

    def test_listener_without_trigger(self):
        self.change(self.plan, '| 头偏一下，眼睛眯一点 | — | 她说到 "a part" |', '| 头偏一下，眼睛眯一点 | — | |')
        self.bad('dock2', '句 3：Jack 的反应没写触发点')

    def test_arc_without_ceiling(self):
        self.change(self.plan, '| 不急了，等她说 | 最冲也只是话短，眉头松着，不提高声音 |', '| 不急了，等她说 | |')
        self.bad('dock2', 'Jack 的情绪线没写「上限」')

    def test_wrong_speaker_in_table(self):
        self.change(self.plan, '| 2 | Mia | 3 | 装正经 |', '| 2 | Jack | 3 | 装正经 |')
        self.bad('dock2', '句 3 的说话人是 Mia，表演表里写成了 Jack')

    def test_turn_without_trigger(self):
        self.change(self.plan, '| 慢一点；叫她名字前顿一拍 | 看到钥匙插在车上 |', '| 慢一点；叫她名字前顿一拍 | |')
        self.bad('dock2', '情绪有转折，没写触发点')

    def test_turn_written_as_from_to_needs_a_trigger(self):
        self.change(self.plan, '从不信转为明白', '从不信到明白')
        self.change(self.plan, '| 慢一点；叫她名字前顿一拍 | 看到钥匙插在车上 |', '| 慢一点；叫她名字前顿一拍 | — |')
        self.bad('dock2', '情绪有转折，没写触发点')

    def test_everyone_present_in_a_beat_has_a_row(self):
        self.change(self.plan, '  - Jack：赶时间，第三次来问车\n', '  - Jack：赶时间，第三次来问车\n  - Sam：店里的学徒，在后面干活\n')
        self.change(self.plan, '| Jack 想马上拿车；Mia 想拖一拖 | Mia、Jack |', '| Jack 想马上拿车；Mia 想拖一拖 | Mia、Jack、Sam |')
        self.bad('dock2', '第 1 拍在场的 Sam 在表演表里没有行')

    def test_banned_words_from_the_users_own_phrases(self):
        self.change(self.plan, '| 两手插进夹克口袋 |', '| 两手插进夹克口袋，大呼一口气 |')
        self.bad('dock2', '禁写词「大呼一口气」')

    def test_banned_word_in_performance(self):
        self.change(self.plan, '| 两手插进夹克口袋 |', '| 两手插进夹克口袋，耸肩 |')
        self.bad('dock2', '禁写词「耸肩」')

    def test_listen_ranges(self):
        self.change(self.plan, '| 2 | Jack | 听 3 |', '| 2 | Jack | 听 3–4 |')
        plan = check.Plan(self.plan)
        row = [r for r in plan.perf if r['句'] == '听 3–4'][0]
        self.assertEqual(row['covers'], {3, 4})

    def test_only_emotion_is_not_enough(self):
        self.change(self.plan, '| 2 | Mia | 听 4 | 被戳了一下，不接 | 低头把抹布叠起来 | 眼睛落下去，嘴角压住 | — | 他说 "Monday" |',
                    '| 2 | Mia | 听 4 | 被戳了一下，不接 | | | — | 他说 "Monday" |')
        self.bad('dock2', '只有情绪，没有动作、表情或说法把它演出来')


class Dock3(Base):
    def test_point_not_on_map(self):
        self.change(self.plan, '| 3 | Jack | 车门边 | 画右的车门外 |', '| 3 | Jack | 车尾 | 画右的车门外 |')
        self.bad('dock3', '的「点」不在俯视图里')

    def test_key_light_not_a_lamp(self):
        self.change(self.plan, '| 靠门的那只手（画右那只）搭在铁链上 | 门灯 |', '| 靠门的那只手（画右那只）搭在铁链上 | 月光 |')
        self.bad('dock3', '主光不是俯视图里的灯：月光')

    def test_person_never_moves(self):
        self.change(self.plan, '| 3 | Jack | 车门边 | 画右的车门外 | 弯腰看车里，再直起身，靠着车门 | 看 Mia | 两手空着 | 门灯 |\n', '')
        self.bad('dock3', 'Jack 全场没有位置或姿态的变化')

    def test_times_not_contiguous(self):
        self.change(self.plan, '| 01 | 2 | 4-8 | C |', '| 01 | 2 | 5-8 | C |')
        self.bad('dock3', 'clip01 镜 2 从 5 秒开始，上一镜到 4 秒，没有首尾相接')

    def test_clip_too_long(self):
        self.change(self.plan, '| 01 | 4 | 16-20 | A |', '| 01 | 4 | 16-32 | A |')
        self.bad('dock3', 'clip01 有 32 秒，超过 30 秒')

    def test_line_in_two_shots(self):
        self.change(self.plan, '| 1-Mia、1-Jack、2-Mia、2-Jack | 2、3、4 |', '| 1-Mia、1-Jack、2-Mia、2-Jack | 1、2、3、4 |')
        self.bad('dock3', '句 1 应该恰好在一镜里，现在在 2 镜里')

    def test_line_in_no_shot(self):
        self.change(self.plan, '| 4-Jack、4-Mia | 8 |', '| 4-Jack、4-Mia | — |')
        self.bad('dock3', '句 8 应该恰好在一镜里，现在在 0 镜里')

    def test_lines_do_not_fit(self):
        self.change(self.plan, '| 01 | 3 | 8-16 | B |', '| 01 | 3 | 8-12 | B |')
        self.change(self.plan, '| 01 | 4 | 16-20 | A |', '| 01 | 4 | 12-20 | A |')
        self.bad('dock3', 'clip01 镜 3 装不下台词：台词 4.9 秒，这一镜 4 秒')

    def test_camera_move_needs_three_parts(self):
        self.change(self.plan, '轻微手持｜跟 Jack 上半身｜构图不变', '轻微手持，跟 Jack 上半身')
        self.bad('dock3', 'clip01 镜 2 的运镜要写三样')

    def test_unknown_performance_row(self):
        self.change(self.plan, '| 1-Jack、1-Mia | 1 |', '| 1-Jack、9-Mia | 1 |')
        self.bad('dock3', '表演表行「9-Mia」在表演表里没有')

    def test_cut_not_on_a_beat_boundary(self):
        self.change(self.plan, '| 3-Jack、3-Mia | 5、6 |', '| 3-Jack、3-Mia | 6 |')
        self.change(self.plan, '| 2-Mia、2-Jack | — |', '| 2-Mia、2-Jack | 5 |')
        self.bad('dock3', '句 5 属于第 3 拍，却排在 clip01 里：切点不在节拍边界上')

    def test_more_clips_than_needed_wants_a_reason(self):
        self.change(self.plan, '| 02 | 3 | 11-16 | D |', '| 03 | 1 | 0-5 | D |')
        self.bad('dock3', '共 36 秒，最少 2 条，现在 3 条')

    def test_unknown_camera(self):
        self.change(self.plan, '| 02 | 2 | 6-11 | E |', '| 02 | 2 | 6-11 | Z |')
        self.bad('dock3', 'clip02 镜 2 的机位 Z 不在机位表里')

    def test_camera_cannot_see_the_person(self):
        self.change(self.plan, '| E | 6 | 4 | Mia |', '| E | 6 | 4 | 卷帘门 |')
        self.bad('dock3', 'clip02 镜 2 的画面给 Mia，但机位 E 拍不到他')

    def test_back_to_camera_with_expression(self):
        self.change(self.plan, '| B | 5.5 | 6 | Mia |', '| B | 0 | 3 | Mia |')
        self.bad('dock3', 'Mia 背对机位 B，表演表里写的表情拍不到')

    def test_backlight(self):
        self.change(self.plan, '| 扳手放到工作台上，两手拿抹布擦手 | 门灯 |', '| 扳手放到工作台上，两手拿抹布擦手 | 工作灯 |')
        self.bad('dock3', 'Mia 的主光（工作灯）在他脑后，是背光')

    def test_backlight_allowed_when_user_asks(self):
        self.change(self.plan, '| 扳手放到工作台上，两手拿抹布擦手 | 门灯 |', '| 扳手放到工作台上，两手拿抹布擦手 | 工作灯 |')
        self.change(self.plan, '- 放行：无', '- 放行：背光（用户 11-11："Mia 这里要背光"）')
        out = self.ok('dock3')
        self.assertIn('主光工作灯在脑后（背光）', out)

    def test_crossing_the_line_needs_a_reason(self):
        self.change(self.plan, '| E | 6 | 4 | Mia | 和 Mia 的眼睛同高，平视 | 中长焦 | 车门前，贴着 Jack 的肩 | Mia 靠在车头上的近景，带 Jack 的肩 | |',
                    '| E | 6 | 4 | Mia | 和 Mia 的眼睛同高，平视 | 中长焦 | 车门前，贴着 Jack 的肩 | Mia 靠在车头上的近景，带 Jack 的肩 | |\n| F | 5.5 | 9 | 车 | 和两人的眼睛同高，平视 | 中焦 | 车后面，朝屋里拍 | 从车后看两人 | |')
        self.change(self.plan, '| 02 | 3 | 11-16 | D |', '| 02 | 3 | 11-16 | F |')
        self.bad('dock3', 'Jack 和 Mia 在机位 A')

    def test_crossing_the_line_with_a_reason(self):
        self.change(self.plan, '| E | 6 | 4 | Mia | 和 Mia 的眼睛同高，平视 | 中长焦 | 车门前，贴着 Jack 的肩 | Mia 靠在车头上的近景，带 Jack 的肩 | |',
                    '| E | 6 | 4 | Mia | 和 Mia 的眼睛同高，平视 | 中长焦 | 车门前，贴着 Jack 的肩 | Mia 靠在车头上的近景，带 Jack 的肩 | |\n| F | 5.5 | 9 | 车 | 和两人的眼睛同高，平视 | 中焦 | 车后面，朝屋里拍 | 从车后看两人 | 换边：最后一镜换到车后，两人的关系翻过来了 |')
        self.change(self.plan, '| 02 | 3 | 11-16 | D |', '| 02 | 3 | 11-16 | F |')
        code, out = self.run_check('dock3')
        self.assertNotIn('左右换了边', out)

    def test_wide_thing_counts_as_background(self):
        out = self.ok('dock3')
        self.assertIn('clip01 镜 2 · 机位 C｜从画左到画右：Jack；Jack 正脸', out)
        line = [l for l in out.splitlines() if 'clip01 镜 2' in l][0]
        self.assertIn('身后：卷帘门', line)

    def test_headings_may_end_with_the_word_table(self):
        self.change(self.plan, '### 站位\n', '### 站位表\n')
        self.change(self.plan, '### 机位\n', '### 机位表\n')
        self.ok('dock3')

    def test_empty_shot_needs_no_performance_rows(self):
        self.change(self.plan, '| 01 | 4 | 16-20 | A | Mia、Jack | 全景 |', '| 01 | 4 | 16-20 | A | 环境 | 全景 |')
        self.change(self.plan, '| 2-Mia、2-Jack | — |', '| — | — |')
        self.ok('dock3')

    def test_rule_inside_a_section_does_not_cut_it(self):
        self.change(self.plan, '### 站位\n', '---\n\n### 站位\n')
        self.ok('dock3')

    def test_camera_needs_height_and_lens(self):
        self.change(self.plan, '| B | 5.5 | 6 | Mia | 和 Mia 的眼睛同高，平视 | 中长焦 |', '| B | 5.5 | 6 | Mia | | 远摄 |')
        out = self.bad('dock3', '机位 B 的「高度」没写')
        self.assertIn('机位 B 的「焦段」要写 广角、中焦、中长焦 或 长焦', out)

    def test_low_angle_only_when_the_user_asks(self):
        self.change(self.plan, '| C | 4 | 5 | Jack | 和 Jack 的眼睛同高，平视 |', '| C | 4 | 5 | Jack | 低角度，机位在 Jack 腰的高度 |')
        self.bad('dock3', '机位 C 用了「低角度」：这是用户点名才用的')

    def test_low_angle_with_the_users_words(self):
        self.change(self.plan, '| C | 4 | 5 | Jack | 和 Jack 的眼睛同高，平视 | 中长焦 | 工作台和车之间 | Jack 的单人近景 | |',
                    '| C | 4 | 5 | Jack | 低角度，机位在 Jack 腰的高度 | 中长焦 | 工作台和车之间 | Jack 的单人近景 | 用户 11-11："Jack 进门这一下拍低一点" |')
        code, out = self.run_check('dock3')
        self.assertNotIn('用户点名才用', out)

    def test_one_high_angle_per_clip(self):
        self.change(self.plan, '| A | 5 | 0 | 车 | 和站着的人眼睛同高，平视 |', '| A | 5 | 0 | 车 | 略高于人，轻俯 |')
        self.bad('dock3', 'clip01 有 2 镜是俯拍（镜 1、4）：全条最多一处轻俯拍')
        self.change(self.plan, '- 放行：无', '- 放行：俯拍（用户："开头和结尾都俯一点"）')
        self.ok('dock3')

    def test_high_angle_the_user_asked_for_does_not_count(self):
        self.change(self.plan, '| B | 5.5 | 6 | Mia | 和 Mia 的眼睛同高，平视 |', '| B | 5.5 | 6 | Mia | 略高于 Mia 的眼睛，轻俯 |')
        self.change(self.plan, '| C | 4 | 5 | Jack | 和 Jack 的眼睛同高，平视 | 中长焦 | 工作台和车之间 | Jack 的单人近景 | |',
                    '| C | 4 | 5 | Jack | 略高于 Jack 的眼睛，轻俯 | 中长焦 | 工作台和车之间 | Jack 的单人近景 | 用户："这镜从上面看他" |')
        self.ok('dock3')

    def test_no_wide_lens_on_a_close_shot(self):
        self.change(self.plan, '| B | 5.5 | 6 | Mia | 和 Mia 的眼睛同高，平视 | 中长焦 |', '| B | 5.5 | 6 | Mia | 和 Mia 的眼睛同高，平视 | 广角 |')
        self.bad('dock3', 'clip01 镜 3 是近景，机位 B 却是广角')

    def test_long_lens_cannot_hold_two_people(self):
        self.change(self.plan, '| D | 5.5 | 2 | 车 | 和两人的眼睛同高，平视 | 中焦 |', '| D | 5.5 | 2 | 车 | 和两人的眼睛同高，平视 | 长焦 |')
        self.bad('dock3', '机位 D 是长焦，装不下Mia和Jack')

    def test_two_shots_in_a_row_must_differ(self):
        self.change(self.plan, '| 02 | 3 | 11-16 | D | Mia、Jack | 中景 |', '| 02 | 3 | 11-16 | E | Mia | 近景 |')
        self.bad('dock3', 'clip02 镜 2 和镜 3 的机位、景别、画面给谁都一样')

    def test_two_people_on_one_spot(self):
        self.change(self.plan, '| 3 | Jack | 车门边 | 画右的车门外 |', '| 3 | Jack | 车头 | 画右的车门外 |')
        self.bad('dock3', 'Jack、Mia 在同一拍（3）都写在「车头」这个点上')

    def test_three_overviews(self):
        out = self.ok('dock3')
        for token in ('机位：这个空间 5 个机位', 'A｜和场景图同一个位置｜和站着的人眼睛同高，平视，广角｜拍 全景，交代两人和车的位置｜用在 2 镜、共 8 秒',
                      '走位：', 'Jack：拍 1 门口（站） → 拍 3 车门边（弯腰看车里，再直起身，靠着车门）',
                      '画面：7 镜', '景别：近景 3 镜、全景 2 镜、中景 2 镜'):
            self.assertIn(token, out)

    def test_move_nobody_sees_is_a_hint(self):
        self.change(self.plan, '| 02 | 1 | 0-6 | D | Mia、Jack | 中景 |', '| 02 | 1 | 0-6 | D | 环境 | 中景 |')
        code, out = self.run_check('dock3')
        self.assertIn('Jack 在第 3 拍从门口走到车门边，但这一拍没有镜头给他', out)

    def test_someone_who_left_is_gone_from_later_shots(self):
        self.change(self.plan, '| 车门边 | 点 | 6.5 | 5.5 | 驾驶座车门外 |', '| 车门边 | 点 | 6.5 | 5.5 | 驾驶座车门外 |\n| 出口 | 点 | 8.5 | 9.5 | 卷帘门边 |')
        self.change(self.plan, '| 3 | Jack | 车门边 | 画右的车门外 | 弯腰看车里，再直起身，靠着车门 |', '| 3 | Jack | 出口 | 画右的卷帘门边 | 离场，往出口走 |')
        out = self.bad('dock3', 'clip02 镜 3 的画面给 Jack，但站位表里这时候没有他')
        self.assertIn('Mia 看的 Jack 这时候不在场（还没进来或已经离场）', out)
        self.assertNotIn('clip02 镜 1 的画面给 Jack，但站位表里', out)          # 走的那一拍他还在

    def test_several_people_can_leave_by_one_exit(self):
        self.change(self.plan, '| 车门边 | 点 | 6.5 | 5.5 | 驾驶座车门外 |', '| 车门边 | 点 | 6.5 | 5.5 | 驾驶座车门外 |\n| 出口 | 点 | 8.5 | 9.5 | 卷帘门边 |')
        row = '| 4 | Mia | 车头 | 画面中间偏左的车头前 | 往后靠在车头上，两手抱在胸前 | 看 Jack | 抹布搭在肩上 | 同上 |'
        self.change(self.plan, row, '| 4 | Mia | 出口 | 画右的卷帘门边 | 离场，往出口走 | 看 出口 | 抹布搭在肩上 | 同上 |\n'
                                    '| 4 | Jack | 出口 | 画右的卷帘门边 | 离场，跟着往出口走 | 看 出口 | 两手空着 | 门灯 |')
        code, out = self.run_check('dock3')
        self.assertNotIn('都写在「出口」这个点上', out)

    def test_scene_view_missing(self):
        self.change(self.plan, '- 场景图的视角：@garage 在 (5, 0) 看向 车\n', '')
        self.bad('dock3', '没写场景图的视角')


class StyleInScript(Base):
    """现行写法里用户点名才用的手法，脚本每次查。"""

    def test_fixed_camera_in_a_shot_needs_the_user(self):
        self.change(self.plan, '| 01 | 4 | 16-20 | A | Mia、Jack | 全景 | 轻微手持｜跟 Mia｜构图不变 |',
                    '| 01 | 4 | 16-20 | A | Mia、Jack | 全景 | 固定｜跟 Mia｜构图不变 |')
        self.bad('dock3', 'clip01 镜 4 的运镜写了「固定」')
        self.change(self.plan, '- 放行：无', '- 放行：固定机位（用户："最后一镜锁住"）')
        self.ok('dock3')

    def test_fixed_camera_with_the_users_words_on_the_camera(self):
        self.change(self.plan, '| 01 | 2 | 4-8 | C | Jack | 近景 | 轻微手持｜跟 Jack 上半身｜构图不变 |',
                    '| 01 | 2 | 4-8 | C | Jack | 近景 | 固定｜跟 Jack 上半身｜构图不变 |')
        self.bad('dock3', 'clip01 镜 2 的运镜写了「固定」')
        self.change(self.plan, '| Jack 的单人近景 | |', '| Jack 的单人近景 | 用户："这镜锁住" |')
        self.ok('dock3')

    def test_one_high_angle_per_clip(self):
        self.change(self.plan, '| B | 5.5 | 6 | Mia | 和 Mia 的眼睛同高，平视 |', '| B | 5.5 | 6 | Mia | 略高于 Mia 的眼睛，轻俯 |')
        self.ok('dock3')
        self.change(self.plan, '| C | 4 | 5 | Jack | 和 Jack 的眼睛同高，平视 |', '| C | 4 | 5 | Jack | 略高于 Jack 的眼睛，轻俯 |')
        self.bad('dock3', 'clip01 有 2 镜是俯拍（镜 2、3）')

    def test_no_room_for_the_lines_says_what_to_do(self):
        self.change(self.plan, '| 01 | 2 | 4-8 | C |', '| 01 | 2 | 4-5 | C |')
        code, out = self.run_check('dock3')
        self.assertEqual(code, 1, out)
        self.assertIn('不改台词，不为了装下调快语速', out)


class PromptChecks(Base):
    def test_listeners_keep_their_mouths_closed(self):
        self.change(self.prompt, '不说话的人自然合着嘴，只用眼神和表情回应。', '')
        self.bad('prompt', '【贯穿要求】要写一次「不说话的人自然合着嘴')

    def test_duration_in_the_head_matches_the_last_shot(self):
        self.change(self.prompt, '- 时长：20 秒', '- 时长：18 秒')
        self.bad('prompt', '参数段的「时长」要和分镜的末秒一样：分镜到 20 秒，参数段写的是 18 秒')
        self.change(self.prompt, '- 时长：18 秒 · ', '- ')
        self.bad('prompt', '参数段写的是 空')

    def test_line_not_verbatim(self):
        self.change(self.prompt, "{Tell me she's ready.}", '{Tell me she is ready.}')
        self.bad('prompt', '句 1 和方案不是逐字相同')

    def test_shot_time_differs(self):
        self.change(self.prompt, '镜头2（4-8秒）', '镜头2（4-9秒）')
        self.bad('prompt', '镜头和方案不一样')

    def test_banned_word(self):
        self.change(self.prompt, 'Jack 松开铁链，朝车的方向看一眼，再看 Mia。', 'Jack 松开铁链，耸肩，再看 Mia。')
        self.bad('prompt', '禁写词「耸肩」')

    def test_fast_in_how_to_say(self):
        self.change(self.prompt, '一边用英语、随口、眼睛往上抬一点', '一边用英语、很快地、眼睛往上抬一点')
        self.bad('prompt', '台词的说法里有"快"')

    def test_fast_in_action_is_fine(self):
        self.change(self.prompt, 'Mia 低头把抹布叠起来，眼睛落下去，嘴角压住。', 'Mia 很快低头把抹布叠起来，眼睛落下去，嘴角压住。')
        self.ok('prompt')

    def test_talking_about_the_line_afterwards(self):
        self.change(self.prompt, "{Tell me she's ready.} <皮夹克的摩擦声>", "{Tell me she's ready.} 说到最后一个词，他眼睛看向车。<皮夹克的摩擦声>")
        self.bad('prompt', '台词后面回头提了台词')

    def test_echoing_words_of_the_line(self):
        self.change(self.prompt, "{Tell me she's ready.} <皮夹克的摩擦声>", "{Tell me she's ready.} 他把 she's ready 说得很重。<皮夹克的摩擦声>")
        self.bad('prompt', '台词后面回头提了台词')

    def test_lead_in_of_the_next_line_is_fine(self):
        self.assertIn('最后三个词前顿一拍地说', self.prompt.read_text(encoding='utf-8'))
        self.ok('prompt')

    def test_summary_has_duration(self):
        self.change(self.prompt, '夜里的修车铺，Jack 又来问车修好没有', '20秒3:4竖屏，夜里的修车铺，Jack 又来问车修好没有')
        self.bad('prompt', '【总述】里不写时长、画幅、分辨率')

    def test_unknown_image(self):
        self.change(self.prompt, 'Jack 松开铁链，朝车的方向看一眼，再看 Mia。', 'Jack 松开铁链，朝 @old_car 看一眼，再看 Mia。')
        self.bad('prompt', '正文里用了 @old_car，【素材绑定】里没有它')

    def test_music_list_incomplete(self):
        self.change(self.prompt, '不要音乐、背景音乐、BGM、配乐、器乐、旋律与铺底音。', '不要音乐、背景音乐、BGM、配乐。')
        self.bad('prompt', '少了：器乐、旋律、铺底音')

    def test_wrong_number_of_lines(self):
        self.change(self.prompt, '除了写出的 4 句台词', '除了写出的 5 句台词')
        self.bad('prompt', '除了写出的 4 句台词，没有人说别的话')

    def test_subtitles_not_mentioned(self):
        self.change(self.prompt, '不要字幕。', '')
        self.bad('prompt', '要写不要字幕')

    def test_left_right_against_the_map(self):
        self.change(self.prompt, '晃动很小。Mia 在画左的工作台边，Jack 在画右深处的卷帘门下面。', '晃动很小。Mia 在画右的工作台边，Jack 在画左深处的卷帘门下面。')
        out = self.bad('prompt', '镜头 1：写的是 Mia 在画右，按俯视图算在画左（机位 A）')
        self.assertIn('写的是 Jack 在画左、Mia 在画右，按俯视图算正好反过来', out)

    def test_start_state_against_the_map(self):
        self.change(self.prompt, '穿 @Mia-工装）在画左的工作台边', '穿 @Mia-工装）在画右的工作台边')
        self.bad('prompt', '【起始状态】：写的是 Mia 在画右，按俯视图算在画左')

    def test_light_side_against_the_map(self):
        self.change(self.prompt, '正是她脸微微转向的那一边；她脸上远离镜头的那半边较亮，靠近镜头的那半边较暗；', '正是她脸微微转向的那一边；她脸上靠近镜头的那半边较亮，远离镜头的那半边较暗；')
        self.bad('prompt', '镜头 3 的光：Mia 写的是靠近镜头的半边亮，按俯视图算是远离镜头的半边亮')

    def test_plan_section_not_confirmed(self):
        self.change(self.plan, '## 3 表演 · 已确认 11-11', '## 3 表演 · 待确认')
        self.bad('prompt', '方案第 3 段（表演）还没确认')

    def test_no_dock_mode_counts_as_confirmed(self):
        self.change(self.plan, '## 3 表演 · 已确认 11-11', '## 3 表演 · 免停靠 11-11')
        self.ok('prompt')

    def test_follow_needs_checking_the_last_frame(self):
        self.change(self.prompt, '- 接上一条：无', '- 接上一条：#12 的末帧（@c00_end）')
        self.bad('prompt', '先拿成片的末帧对一遍')

    def test_follow_checked(self):
        self.change(self.prompt, '- 接上一条：无', '- 接上一条：#12 的末帧（@c00_end）；已对，一致')
        self.ok('prompt')

    def test_sections_out_of_order(self):
        s = self.prompt.read_text(encoding='utf-8')
        a, b = s.index('【总述】'), s.index('【画面基调】')
        c = s.index('【起始状态】')
        self.prompt.write_text(s[:a] + s[b:c] + s[a:b] + s[c:], encoding='utf-8')
        self.bad('prompt', '六段要齐、按这个顺序')

    def test_too_long(self):
        self.change(self.prompt, '不要字幕。', '不要字幕。' + '画面清晰。' * 2600)
        self.bad('prompt', '超过 15000')

    def test_people_in_order_of_first_appearance(self):
        s = self.prompt.read_text(encoding='utf-8')
        mia = s[s.index('@Mia-基础形象：'):s.index('@Jack-基础形象：')]
        jack = s[s.index('@Jack-基础形象：'):s.index('@garage：')]
        self.prompt.write_text(s.replace(mia + jack, jack + mia), encoding='utf-8')
        self.bad('prompt', '人物的顺序要按首次出场：Mia、Jack')

    def test_image_line_must_say_what_is_not_used(self):
        self.change(self.prompt, '深蓝连体工装，袖子卷到手肘；白底不采用。', '深蓝连体工装，袖子卷到手肘。')
        self.bad('prompt', '@Mia-工装 没写不采用什么')

    def test_text_after_second_rule_is_not_body(self):
        s = self.prompt.read_text(encoding='utf-8')
        self.prompt.write_text(s + '\n---\n\n怎么填：耸肩这种词不要写。\n', encoding='utf-8')
        self.ok('prompt')

    def test_ascii_brackets_in_shot_headers(self):
        s = self.prompt.read_text(encoding='utf-8')
        for old, new in (('镜头1（0-4秒）', '镜头1(0-4s)'), ('镜头2（4-8秒）', '镜头2(4-8s)')):
            self.assertEqual(s.count(old), 1)
            s = s.replace(old, new)
        self.prompt.write_text(s, encoding='utf-8')
        code, out = self.run_check('prompt')
        self.assertNotIn('镜头和方案不一样', out)

    def test_person_outside_the_frame_is_not_compared(self):
        self.change(self.prompt, 'Jack 在画面中间，看着画左外的 Mia。', 'Jack 在画面中间，Mia 在画左外，他看着她。')
        code, out = self.run_check('prompt')
        self.assertNotIn('按俯视图算', out)

    def test_missing_image_reaches_the_prompt_check(self):
        self.change(self.plan, '缺：无', '缺：门外街道的图')
        self.bad('prompt', '缺：门外街道的图')

    def test_shot_line_names_the_long_lens(self):
        self.change(self.prompt, '机位和 Jack 的眼睛同高，平视，中长焦，轻微手持', '机位和 Jack 的眼睛同高，平视，轻微手持')
        self.bad('prompt', '镜头 2 的镜头行要写出焦段「中长焦」（机位 C）')

    def test_shot_line_names_the_camera_height(self):
        self.change(self.prompt, '镜头1（0-4秒）：全景，平视，轻微手持', '镜头1（0-4秒）：全景，轻微手持')
        self.bad('prompt', '镜头 1 的镜头行要写机位高度')

    def test_plan_problems_block_the_prompt(self):
        self.change(self.plan, '| 01 | 2 | 4-8 | C |', '| 01 | 2 | 5-8 | C |')
        self.bad('prompt', '方案自己还有')


class QaChecks(Base):
    def test_a_pass_is_missing(self):
        self.change(self.log, '- 5 衔接 · 过 · 本场第一条；末态和切点表的接缝一样\n', '')
        self.bad('qa', 'QA 缺第 5 道（衔接）')

    def test_rhythm_numbers_must_match(self):
        self.change(self.log, '台词 6 秒；没台词最长 4 秒；1 句的画面给了', '台词 7 秒；没台词最长 4 秒；1 句的画面给了')
        self.bad('qa', 'QA 第 7 道的数字要从脚本抄：台词 6 秒；没台词最长 4 秒；1 句的画面给了听的人、双人或环境')

    def test_character_count_must_match(self):
        self.change(self.log, '- 8 写法 · 过 · 2486 字符', '- 8 写法 · 过 · 2400 字符')
        self.bad('qa', 'QA 第 8 道的字符数要从脚本抄')

    def test_qa_is_for_another_version(self):
        self.change(self.prompt, '# demo-s01 clip01 · Prompt v1', '# demo-s01 clip01 · Prompt v2')
        self.bad('qa', '场记录里的 QA 是 Prompt v1 的，现在的 Prompt 是 v2')

    def test_note_is_required(self):
        self.change(self.log, '- 3 空间 · 过 · 4 镜的左右和主光都和脚本算的一样', '- 3 空间 · 过')
        self.bad('qa', 'QA 第 3 道没写说明')

    def test_prompt_must_pass_first(self):
        self.change(self.prompt, '不要字幕。', '')
        self.bad('qa', 'Prompt 的检查还没过')

    def test_no_qa_section(self):
        self.change(self.log, '### clip01 · Prompt v1', '### clip02 · Prompt v1')
        self.bad('qa', '没有「### clip01 · Prompt v1」')


class Geometry(unittest.TestCase):
    def test_left_and_right(self):
        ang, depth = check.view((5, 0), (5, 9), (2.5, 5))
        self.assertLess(ang, -8)
        self.assertGreater(depth, 0)
        ang, _ = check.view((5, 10), (5, 0), (2.5, 5))      # 反打：同一个点到了画右
        self.assertGreater(ang, 8)

    def test_face(self):
        self.assertEqual(check.face_of((0, 0), (0, -5), (0.5, -5)), '正脸')
        self.assertEqual(check.face_of((0, 0), (0, -5), (4, -4)), '3/4 侧脸')
        self.assertEqual(check.face_of((0, 0), (0, -5), (5, 0)), '侧脸')
        self.assertEqual(check.face_of((0, 0), (0, -5), (0, 5)), '背对')

    def test_light(self):
        p, gaze, look = (0, 0), (0, -5), (0, 0)
        self.assertEqual(check.light_of(p, gaze, (3, -4), look, (-3, -4)), ('侧前方', '远离镜头的半边'))
        self.assertEqual(check.light_of(p, gaze, (3, -4), look, (4, -3)), ('侧前方', '靠近镜头的半边'))
        self.assertEqual(check.light_of(p, gaze, (3, -4), look, (0, 5))[1], '背光')

    def test_span(self):
        self.assertEqual(check.span('2~8'), (5.0, 2.0, 8.0))
        self.assertEqual(check.span('4.5'), (4.5, 4.5, 4.5))


class EmotionLibrary(unittest.TestCase):
    def test_library_loads(self):
        import emotion_library
        entries = emotion_library.load_library()
        self.assertEqual(len(entries), 25)
        self.assertEqual(entries[19]['name'], 'Sadness')


class SkillFiles(unittest.TestCase):
    def test_skill_md_is_short(self):
        self.assertLessEqual(len((ROOT / 'SKILL.md').read_text(encoding='utf-8')), 6000)

    def test_files_named_in_skill_md_exist(self):
        import re
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        for name in set(re.findall(r'`((?:references|templates|scripts)/[\w\-.]+\.(?:md|py))`', text)):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_files_named_anywhere_exist(self):
        """SKILL.md、README、references、templates 里写在反引号里的文件名，都要真的在。"""
        import re
        places = [ROOT / 'SKILL.md', ROOT / 'README.md'] + sorted((ROOT / 'references').glob('*.md')) + sorted((ROOT / 'templates').glob('*.md'))
        dirs = ('', 'references', 'scripts', 'templates', 'assets', 'tests')
        project = re.compile(r'[<\[*一-鿿]|^0\d_|^demo|导演偏好')            # 每场的文件、项目里的文件，不是 skill 的
        for path in places:
            for name in set(re.findall(r'`([^`\s]+\.(?:md|py|json))`', path.read_text(encoding='utf-8'))):
                if project.search(name):
                    continue
                self.assertTrue(any((ROOT / d / name).is_file() for d in dirs), '%s 提到 %s，没有这个文件' % (path.name, name))

    def test_version_file(self):
        self.assertEqual((ROOT / 'VERSION').read_text(encoding='utf-8').strip(), '2.0.0')
        self.assertIn('## 2.0.0', (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'))
        self.assertIn('# film-lead-dir 2.0.0', (ROOT / 'SKILL.md').read_text(encoding='utf-8'))

    def test_every_footage_number_cited_is_in_the_ledger(self):
        import re
        ledger = (ROOT / 'references' / 'phrase-ledger.md').read_text(encoding='utf-8')
        ledger = '\n'.join(line for line in ledger.splitlines() if line.startswith('| '))      # 只认表里的行，开头的说明不算
        known = set()
        for a, b in re.findall(r'#(\d+)[–-]#(\d+)', ledger):
            known |= set(range(int(a), int(b) + 1))
        known |= {int(n) for n in re.findall(r'#(\d+)', ledger)}
        for path in sorted((ROOT / 'references').glob('*.md')):
            if path.name in ('phrase-ledger.md', 'qa.md'):          # qa.md 里的编号是格式示例
                continue
            text = re.sub(r'^- #\d+ ·.*$', '', path.read_text(encoding='utf-8'), flags=re.M)     # 成片账一行的格式示例
            for n in re.findall(r'#(\d+)', text):
                self.assertIn(int(n), known, '%s 引了 #%s，写法账里没有这条' % (path.name, n))

    def test_templates_have_no_banned_words(self):
        cats = check.parse_banned(check.read(check.STYLE))
        for name in ('prompt.md', 'scene-plan.md', 'scene-log.md'):
            text = (ROOT / 'templates' / name).read_text(encoding='utf-8').split('怎么填')[0]
            self.assertEqual(check.scan_banned(text, cats, []), [], name)


if __name__ == '__main__':
    unittest.main()
