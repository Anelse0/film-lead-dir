# film-lead-dir 2.0.0

把一场台词锁定的戏做成 Seedance 2.5 参考生视频的 Prompt。先出每场一份导演方案，分三次给用户确认；再一条 clip 一条 clip 编 Prompt、做 QA；成片回来量、判层、改。

入口是 `SKILL.md`。这份只讲怎么装、有哪些文件、怎么跑检查和测试。

## 做什么，不做什么

- 做：导演方案（解释、定调、表演、空间、镜头）、Prompt、QA、成片回来以后的改稿。
- 不做：故事和剧本（那是 film-story）；视频编辑、延长、首尾帧、关键帧、宫格、白模、动作和运镜的参考视频、两段视频之间的无缝转场、文生视频、单张图片。

## 需要什么

- Python 3.9 以上，不用装别的包。
- 量成片要 `ffmpeg` 和 `ffprobe`。
- 对话里直接出俯视图，要对话里有画图工具；没有就用字符画，或出网页。

## 文件

| 文件 | 内容 |
|---|---|
| `SKILL.md` | 流程、三次停靠、听谁的、贯穿规则、每场的文件、检查、改动回到哪、协作、文件地图 |
| `references/current-style.md` | 现行写法和禁写词。每场都照它写 |
| `references/step-1-interpret.md` 到 `step-7-footage.md` | 七步各一份：做法、产出、过关 |
| `references/qa.md` | QA 八道：每道查什么、怎么记 |
| `references/phrase-ledger.md` | 写法账：一种写法，成片把它演成了什么 |
| `references/shot-vocabulary.md` | 景别、焦段、运镜、接法 |
| `references/principles.md` | 18 条原则，当检查问题用 |
| `references/seedance-2.5.md` | 官方要点，只留参考生视频 |
| `references/director-lenses.md` | 透镜库，参考 |
| `references/emotion-library.md`、`references/emotion-index.json`、`assets/emotion-library.json` | 情绪库和怎么查，参考 |
| `templates/scene-plan.md`、`templates/prompt.md`、`templates/scene-log.md` | 每场三个文件的模板 |
| `scripts/` | 见下面 |
| `tests/` | 测试，和一场能过全部检查的假方案（`tests/fixtures/demo`） |

## 脚本

路径相对本目录。每个脚本加 `-h` 看用法。

| 脚本 | 做什么 |
|---|---|
| `scripts/check.py` | 检查，结果只有过和不过。`dock1`、`dock2`、`dock3` 在三次停靠前跑，`prompt` 在交 Prompt 前，`qa` 在 QA 记完以后；`map` 打印字符画的俯视图 |
| `scripts/topview.py` | 画俯视图。`--chat` 打印一张 SVG，交给对话里的画图工具；不加就生成一页能按拍看的网页 |
| `scripts/measure_clip.py` | 量成片：切点、声音、语速下限，每镜抽一帧拼图，存末帧 |
| `scripts/emotion_library.py` | 查情绪库 |
| `scripts/session_cost.py` | 量一次会话花在哪，改了 skill 以后前后对比用 |

拿假方案试一遍：

```
python3 scripts/check.py dock3 tests/fixtures/demo/04_plan/demo-s01.plan.md
python3 scripts/check.py qa tests/fixtures/demo/06_prompts/demo-s01-clip01.prompt.md
python3 scripts/topview.py tests/fixtures/demo/04_plan/demo-s01.plan.md --chat
```

## 测试

```
python3 -m unittest discover -s tests
```

- 检查的测试：拿假方案一处一处改坏，看拦不拦得住。
- 量成片的测试要 ffmpeg，没装就跳过。

## 每个项目自己的要求

项目根目录放一份 `导演偏好.md`（可以没有）。它排在 `current-style.md` 前面：项目里写了的，按项目的来。里面也可以改禁写词，格式和 `current-style.md` 的「禁写词」一节相同。

## 和 1.x 的关系

- 前身是 film-director 1.15.1，在另一个仓库。2.0.0 是从空目录重写的，从这一版起改名 film-lead-dir，版本号接着往下排。
- 不认 1.x 的分镜卡和 QA 文件。用旧版做到一半的场，按原来的做法收尾，不迁移。
- 改了什么见 `CHANGELOG.md`。
