# DESIGN.md

> Visual design system for the daily portfolio brief.
> Anyone modifying anything under `src/render/` **must read this first**.
> See `src/render/_design_reference{,_postclose}.html` for the canonical visual
> reference — **as of 2026-08-05 they are rendered snapshots of `brief.html.j2`**
> (sample brief + demo legal config), not hand-authored. Regenerate them after any
> visual change:
>
> ```bash
> .venv/bin/python scripts/make_design_reference.py
> ```
>
> The sample portfolio in that script is fictional on purpose — the reference files
> are committed, and a real holdings list is personal financial information.

---

## 1. 设计哲学 / Design Thesis

这份日报的视觉语言取自 **Arknights《孤星》(Lone Trail)** 的工业制图美学，并非装饰性引用 —— 它对应一组真实的产品决策：

| 隐喻 | 产品对应 |
|---|---|
| 太空舱发回地面的工程日志 | 每天 09:00 ET 推送的 Pre-market Radar brief |
| 被追踪的星体 / 天体 | 每个 ticker |
| 环境遥测（温度、辐射、压力） | 宏观数据（DGS2 / DGS10 / DXY / VIX） |
| 雷达扫描出的信号 | Top Signals（通过 relevance gate 的事件） |
| 异常告警 | Asset Impact 里的 `Watch` / `Alert` 状态 |
| 任务编号 ARC-XX | 每日报告编号（DAY N / FYXX） |

> **2026-06-12 重定位**：产品从 "Portfolio Log"（组合复盘）改为 **"Pre-market Radar"**
> （盘前情报压缩器）。视觉系统（色板、字体、留白、signal orb）完全保留；变的是
> **章节结构、标题、组件**。详见 §5.2 / §6 / §11 changelog。

**核心 mood：克制的工程档案。冷静、稀疏、有秩序、单点强调。**

不是 sci-fi HUD、不是赛博朋克、不是 Bloomberg Terminal。是 **NASA 早期任务手册 + 日式极简工程美学**。

---

## 2. 反例清单 / What NOT to Do

> 这一节前置，因为"科幻日报"这个 brief 极易让设计退化到下面这些默认值。改任何东西前先自检不要走进这些坑。

| ❌ 错误方向 | 为什么错 |
|---|---|
| 黑底 + 青色霓虹 + 满屏方括号 | 这是 AI 默认的 "sci-fi HUD"，跟孤星完全不是一回事 |
| 多色强调（青 + 橙 + 红 + 绿） | 孤星只用**一种**暖橙作为强调色，其他都是黑白灰 |
| 满屏边框 / 分割线 / 装饰性几何 | 孤星的层级靠**留白**建立，不靠边框 |
| 强烈的发光 / glow / shadow 效果 | 这是游戏 UI，不是印刷品 |
| 双语标签滥用（每个 section 都"中文 / ENGLISH"） | 中文应作为**克制的副标**，不是装饰元素 |
| 数据用 emoji 或符号（🟢🔴⚠️）作为状态指示 | 用 typography 和单一橙色就够了 |
| 卡片边框 + 圆角 + 阴影组合 | 这是 SaaS dashboard，不是工程档案 |
| 渐变色背景 / 渐变文字 | 孤星全程纯色 |
| 居中对齐所有内容 | 孤星大量使用左对齐 + 不对称布局 |

**判断标准**：如果你的设计能直接套到一个 generic "AI dashboard demo" 上而不显得突兀，那就走错方向了。

---

## 3. 色彩 Tokens / Color System

**全部色彩共 11 个 token。任何不在此列的颜色都不应该出现。**

```css
:root {
  /* Paper — backgrounds */
  --paper:       #F4F2EC;   /* Primary background. Warm off-white, like architecture paper. */
  --paper-2:     #EDEAE2;   /* Subtle secondary background (rarely used). */

  /* Ink — text */
  --ink:         #0A0908;   /* Primary text, headings, key data. */
  --ink-2:       #595550;   /* Secondary text, labels, meta info. */
  --ink-3:       #918C83;   /* Tertiary text, captions, dimmed labels. */

  /* Rules — dividers */
  --rule:        #D6D2C8;   /* Section dividers, primary hairlines. */
  --rule-soft:   #E5E1D6;   /* Within-section dividers, asset card separators. */

  /* Amber — the one accent */
  --amber:       #C8732C;   /* The ONLY accent color. Use with restraint. */
  --amber-deep:  #8E4F1B;   /* Hover / pressed state of amber (rarely used). */
  --amber-soft:  rgba(200, 115, 44, 0.08);  /* Background tint for amber regions. */
}
```

### 3.1 Amber 的使用守则

`--amber` 是这个设计里**唯一的视觉武器**。用对了一击必杀，用滥了整篇报告失效。

**Amber 可以用在**：
- 一句话 lede 里的 1–2 个关键数字（如 `+18% MTM`）
- Telemetry 的 "flag" delta（DGS2 突破、VIX regime shift 这种）
- Asset state 的 `Watch` 状态指示
- Anomaly 编号 `A · 01`
- Deep Scan 的 tag（`INTACT` / `REPRICED` 等）
- Catalysts 的 `HIGH` / `CRIT` 优先级
- 右上角 signal orb 的 illumination 部分
- `Signal: AMBER` 状态徽章

**Amber 不应该用在**：
- 普通段落正文里的"强调"（这种地方应该用 `font-weight: 500` + 同色 `--ink`）
- 区块背景大面积填充
- 章节标题
- 章节编号（`01` / `02` ...，那是 `--ink-3`）

**密度准则**：单页面里 amber 的视觉占比应该 **≤ 3%**。如果一眼扫过去你看到很多橙色，说明用滥了。

### 3.2 涨跌色处理（重要）

这个产品故意**不用红绿涨跌色**：

- 涨跌都用 `--ink`（默认深色文字）
- 仅在叙事中需要"积极信号"时用 `--amber-deep`
- 真正的负面突破时用 `--ink` 加重 `font-weight: 500`

理由：孤星色板里不存在红绿。强行加入红绿会破坏整体气质。涨跌信号让数字本身和正负号说话。

---

## 4. 字体 / Typography

### 4.1 字体栈

```css
--font-display: 'Inter Tight', -apple-system, BlinkMacSystemFont, sans-serif;
--font-body:    'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
--font-mono:    'JetBrains Mono', 'SF Mono', Menlo, monospace;
--font-cjk:     'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
```

加载（通过 Google Fonts）：
```html
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

### 4.2 字号 Scale

| 用途 | 字体 | 字号 | 字重 | letter-spacing | 备注 |
|---|---|---|---|---|---|
| Hero title (`Portfolio Log`) | display | 64px | 700 | -0.045em | 唯一允许的超大字号 |
| Section title | display | 22px | 600 | -0.02em | |
| Lede paragraph | display | 18px | 400 | -0.012em | head-lede |
| Telemetry value | display | 30px | 500 | -0.025em | |
| Body text | body | 15px | 400 | normal | 1.7 line-height |
| Asset body | body | 14px | 400 | normal | 1.6 line-height |
| Asset ticker | mono | 17px | 500 | 0.02em | |
| Mono data | mono | 11–14px | 400–500 | varies | 价格、变化、时间戳 |
| Section number (`01`) | mono | 11px | 400 | 0.1em | --ink-3 |
| Eyebrow label (telemetry key, asset role) | mono | 9–10px | 400 | 0.18–0.22em | UPPERCASE |
| CJK subtitle (孤星 etc) | cjk | 14px | 400 | 0.05em | --ink-3，作为副标 |

### 4.3 字体使用守则

- **display 字体**：所有标题和"陈述性"文本（lede、telemetry value）。**永远不用于数据本身**。
- **mono 字体**：所有数字、ticker、时间戳、ID、编号、eyebrow label。**这是工程档案的核心质感来源**。
- **body 字体**：所有正文叙述（signal narrative、asset body、anomaly text、scan body）。
- **CJK 字体**：仅用于章节副标（如 `Telemetry 遥测`），字号比英文小、颜色比英文淡。**不要在正文里中英混排**。

### 4.4 Letter-spacing 的特殊处理

- **大标题 negative tracking**（-0.04em 左右）：让 `Portfolio Log` 紧凑、有印刷感
- **小号 mono uppercase 正 tracking**（0.18–0.22em）：让 `DGS2`、`MACRO TELEMETRY` 这种 eyebrow label 有"工程标签"质感
- 正文 body 字体保持 normal

---

## 5. Layout 规范

### 5.1 容器

```css
.sheet {
  max-width: 720px;    /* 单栏，邮件友好 */
  margin: 0 auto;
}

body {
  padding: 80px 24px 120px;   /* 大上下留白是核心 */
}
```

Mobile breakpoint：`@media (max-width: 640px)`，padding 收紧到 `40px 18px 80px`。

### 5.2 Section 结构

每个 section 严格遵守：

```
┌─────────────────────────────────────────┐
│  [section-head: 编号 + 标题 + meta]      │
│  ─────────────────────────────────       │  (margin-bottom: 32px)
│                                          │
│      [section-body, padding-left: 64px] │  <- 主体缩进，呼应章节编号
│      [content...]                        │
│                                          │
└─────────────────────────────────────────┘  (padding-bottom: 64px)
```

关键尺寸：
- Section 之间的间距：**靠 `padding-bottom: 64px` 撑开，不用 border**
- 章节编号到标题的列宽：**40px**
- 主体内容相对页面左缘的缩进：**64px**（mobile 下取消）

### 5.2.1 章节结构（locked — Pre-market Radar）

固定 8 段，编号 `00`–`07`。改动任何一段必须先改本节。

| 编号 | 标题 | CN 副标 | 内容 |
|---|---|---|---|
| 00 | Market Pulse | 脉象 | bias + ≤3 themes + key question + confidence（30 秒读完） |
| 01 | Portfolio Read | 持仓合成 | **跨持仓合成（本报告核心）**：净姿态 + 2–3 条成对互动 + 可选二阶链 + 命门变量 + ≤4 组合级盯盘 |
| 02 | Telemetry | 遥测 | 3–6 个宏观读数（默认 DGS2/DGS10/DXY/VIX），≤2 flag |
| 03 | Top Signals | 信号 | ≤5 条，rank + affected + why + compact label + confidence |
| 04 | Asset Impact | 标的 | 常驻快照价格表 + **默认折叠的**逐标的卡（news / impact / watch / confidence，点开看详情） |
| 05 | Event Watch | 事件 | ≤5 个催化剂：time / event / affected / why / priority |
| 06 | Filtered | 已过滤 | 默认折叠；数量 + 每条一句过滤理由 |
| 07 | Source Quality | 来源 | 单行：official/tier-1/secondary/inference 计数 + report confidence |

> **2026-08-04 重排**：新增 **01 Portfolio Read（持仓合成）** 作为核心段，紧随 30 秒速读之后；
> 旧的 `Watch After Open`（盯盘）**并入 Portfolio Read 的组合级 `watch`**（不再独立成段）；
> `Asset Impact` 的逐标的卡片改为**默认折叠**（快照价格表仍常驻）。Telemetry/Top Signals 顺延。
> 产品核心从"逐标的罗列"转向"把持仓当一个组合来读"——见 §6.1.6。
>
> （更早）Header 标题从 `Portfolio Log` 改为 **`Pre-market Radar`**；旧 `Anomalies`/`Deep Scan`
> 已并入 `Top Signals`/`Asset Impact`。

### 5.2.2 章节结构（locked — Post-close Radar 收盘总结，2026-08-06 新增）

盘后报告是**向后复盘**版，共用孤星视觉系统（色板/字体/留白/合规页脚）与 Telemetry 组件，
但章节不同。三套模板按 `brief.report_type == 'postclose'` 分支渲染（`schemas/postclose.py`）。

| 编号 | 标题 | CN 副标 | 内容 |
|---|---|---|---|
| 00 | Close Pulse | 收盘脉象 | 今日如何收尾：bias + ≤3 themes + takeaway + confidence（30 秒读完） |
| 01 | Scorecard | 复盘对账 | **核心**：晨报的命门/watch/信号 逐条对当日实际打分（verdict ∈ 命中/落空/中性/待续）；无晨报则一行 `无当日晨报可对比` |
| 02 | Telemetry | 遥测 | 收盘读数（DGS2/DGS10/DXY/VIX + 当日变动），≤2 flag |
| 03 | Movers | 今日异动 | ≤5 持仓最大涨跌 + 一句原因 |
| 04 | Asset Recap | 标的复盘 | 每标的：What（今日实际）/ Read（含义）/ Watch（明日变量）/ Conf |
| 05 | After Hours & Tomorrow | 盘后·明日 | 盘后异动陈述 + 明日 72h 催化剂 |
| 06 | Filtered | 已过滤 | 折叠（web）/ 单行计数（email·md） |
| 07 | Source Quality | 来源 | 单行计数 + report confidence |

> Header：标题 `Post-close Radar`、时间戳 `16:00 ET · 收盘后`、副标 `N assets · N movers · N 对账`。
> `Scorecard` 里 `落空`（晨报判断错了）的 verdict 徽章可上 amber（诚实标错的一处强调）；其余 verdict 用 `--ink-2`。
> 组件规范见 §6.9。

### 5.3 留白原则

**这个设计的精髓是留白，不是密度。**

- Section 之间：64px
- Section header 到 body：32px
- 段落之间：16px
- Asset card 之间：24px padding + 1px hairline（`--rule-soft`）

**判断标准**：如果你想"再加一些内容把空白填满"，停下来。空白是设计本身。

---

## 6. 组件规范

### 6.1 Header

```
ARC-09 · 2026.06.10 · 09:00 ET · DAY 162 / FY26    [mono, 10px, --ink-2]

Pre-market                                           [display, 64px, 700]
Radar                                                [display, 64px, 700]
Five assets · Four signals · Three events           [display, 14px, 500]
                                                            ┌──────┐
                                                            │ ORB  │  <- SVG, 80×80
                                                            └──────┘
                                                            SIGNAL
                                                            AMBER
```

> Header 不再带 lede 段落 —— 30 秒速读的职责交给 `00 Market Pulse`。副标三段计数
> （assets · signals · events）由模板从列表长度推导，不写死。

**Signal Orb**（右上角的 SVG）是整份报告的 **signature element**，必须保留。SVG 源码见 `_design_reference.html`，参数化以下变量：

- 行星 illumination 区域颜色：根据 signal state 切换
  - `NOMINAL` → 不发光（无 fill），轨道弧为 `--ink-3`
  - `AMBER` → `--amber` fill on illuminated hemisphere
  - `RED` → 暂未启用，保留扩展位

### 6.1.5 Market Pulse (Section 00)

30 秒速读区。**无卡片、无边框**，靠 typography 层级。

```
BIAS   Mixed / Event-driven                       [eyebrow mono + display 18px]

01  Inflation pressure vs. rate rally             [themes: mono 11px num + body]
02  Semiconductor flow risk
03  Gold safe-haven confirmation test

KEY QUESTION                                       [eyebrow mono 9px --ink-3]
Is the market treating lower yields as the dominant
signal, or does inflation reprice risk after the open?   [display 18px]

CONFIDENCE  Medium                                 [eyebrow mono + --ink-2]
```

- `bias` 值用 display 18px；themes 编号用 mono `--ink-3`，正文 body。
- `key_question` 是这一段唯一的"重点"，用 display 18px，但**不上 amber**（它是问题不是结论）。`key_question` 只放那一个未决问题，不混入数据质量警告。
- amber 仅可点在 `confidence` 的值或某个 theme 的关键词上，且非必须。
- **caveat（2026-06-14 新增，可选）**：低信心/数据有局限时，在 `confidence` 下方挂一行 `.pulse-caveat`（12.5px `--ink-2`，顶部 hairline 分隔，max-width 34em），一句克制提示。`market_pulse.caveat=""` 时整行省略。不上 amber。

### 6.1.6 Portfolio Read (Section 01) — 持仓合成

**这是报告的核心段**，把持仓当作**一个组合**来读，而非逐标的罗列。**无卡片、无边框**，靠 typography 层级。四个部分：

```
NET POSTURE                                        [eyebrow mono 9px --ink-3]
多数持仓吃 AI 资本开支 / 利率这条线，只有那只小盘股是特异项。   [display 18px]

HEDGE FAILURE   GLD · MU                            [kind eyebrow mono + holdings mono --ink-3]
实际利率上行同时压黄金与成长股，GLD 今天不再对冲 MU 的回撤。    [body 15px]

SHARED DRIVER   SPY · GOOGL · MU
利率上行同时压三只的成长估值……

RIPPLE                                             [eyebrow mono 9px --ink-3，可选]
内存涨价 → 亚马逊 / 谷歌 capex 成本 → 二者利润率 → 拖累 SPY。   [body 15px]

SWING                                              [eyebrow mono 9px --amber 可点]
命门：10 年期美债能否守 4.75%——一个变量定整本书的方向。         [display 18px]

WATCH                                              [eyebrow mono 9px --ink-3]
01  ……                                            [组合级盯盘 ≤4 条，编号 mono + body]
02  ……
```

- `interactions` 每条渲染成**一行流动文本**（2026-08-05 去碎片化）：`kind`（mono eyebrow，四类
  `SHARED DRIVER` / `HEDGE FAILURE` / `CONCENTRATION` / `DIVERGENCE`）+ 点名持仓（mono `--ink-3`）
  作为**行内前缀**，紧接机制正文（body）——**不再拆成"eyebrow 行 + 正文行"两块**。目的：Portfolio
  Read 读起来连贯，不被一堆小标签切碎。`posture` / `ripple` 同样是流动段落（posture 无 eyebrow 作
  引导句，ripple 以行内 `RIPPLE` 前缀），只有 `swing`（命门，行内 amber 前缀）与 `watch`（盯盘列表）
  保留强调。**kind 与 holdings 是元信息，不上 amber。**
- `swing`（命门）是这一段的重点，display 18px；amber **仅可点在 `swing` 一处**（或其关键数字），
  呼应它"决定全书方向的那一个变量"的地位。这是本段唯一允许的 amber。
- `ripple` 可选，`portfolio_read.ripple=""` 时整行省略。
- `watch` 是**组合级**盯盘（≤4 条，编号列表），与 §6.4 卡片里的逐标的 `watch` 不重复。
- **反例**：把这段写成逐 ticker 小结、或不点名 ≥2 只持仓的泛泛宏观评论——那是退化，不许。

### 6.2 Telemetry

四列等宽 grid（3–6 个读数，>4 时换行），**无背景色无边框**，仅顶部 hairline `--rule`。

```
DGS2                  DGS10                 DXY                   VIX
────                  ─────                 ───                   ───
4.82%                 4.41%                 105.8                 18.2     [display 30px]
+3bp · breakout       +5bp                  +0.4%                 +1.1     [mono 10px]
[--amber]             [--ink-2]             [--ink-2]             [--amber]
```

**关键约束**：四个 delta 里，**最多 2 个**可以是 `flag` 状态（`--amber`）。如果某天三个都该标 flag，说明你 over-flagging，重新挑选。

**Telemetry note（2026-06-14 新增）**：`flag=true` 的读数下方可挂一行 ≤25 字中文解读（`.tel-note`，12px / `--ink-2`），把裸读数翻成"对持仓意味着什么"。`flag=false` 的读数不带 note，保持裸读数。note **不上 amber**——它是解读文字不是强调。目的:让不熟悉宏观指标的产品用户也能读懂 flag 读数。

### 6.2.5 Compact Label

Top Signal 的质量标签，渲染成**一行点分隔文本**，绝不堆方括号：

```
Official · New · High impact          [mono 10px, --ink-3]
```

- 三段：`source` · `freshness` · `impact`，用 ` · ` 连接。
- 整行 `--ink-3`，**不上 amber**（标签是元信息，不是信号本身）。
- 禁止 `[NEW][A][High][conf 0.9]` 这类堆叠 —— 这会让报告变重。

### 6.3 Top Signals (Section 03)

> **默认收起（2026-08-04）**：Portfolio Read 已承载"今天哪几件事重要"，Top Signals 降为参考层。
> **网页版**折进 `<details>`；**邮件/Markdown** 无法折叠，改为**一行一条**（`rank · signal — affected · label`，
> 去掉 `why` 段）。下方展开结构是网页展开态 / 旧全展示态的规格。

每条信号一个 block，block 之间 `border-top: 1px solid --rule-soft`。

```
1   PPI hotter than expected                      [rank mono --amber · signal display]
    QQQ / GLD / SGOV                               [affected mono 10px --ink-3]
    Keeps inflation pressure alive while rates fall.   [why, body 14px]
    Official · New · High impact   ·   Conf High   [label + confidence, mono 10px]
```

- `rank` 数字是这一段唯一的 amber 点（mono，`--amber`）。
- `affected` 用 mono eyebrow（uppercase tracking）。
- ≤5 条。少而强，不要凑数。

### 6.4 Asset Impact (Section 04)

Section 04 顶部先放一张**紧凑盘前快照表**（Ticker / State / Price / Chg %），让用户一眼扫到价格，再往下列卡片。表用 `.snapshot`：无 box border、仅表头 hairline `--rule`、行间 `--rule-soft`；**涨跌不用红绿**——Chg% 上涨用 `--amber-deep`、下跌/持平用 `--ink`、无数据用 `--ink-3`。

**逐标的卡片默认折叠（2026-08-04）**：重排后核心叙事在 §6.1.6 Portfolio Read，逐标的卡片降级为
**参考层**。HTML 版把卡片区包进 `<details>`（复用 Filtered 的折叠交互：mono summary + hairline +
三角箭头，summary 写 "逐标的详情 / N assets"），**快照价格表仍常驻可见、不折叠**。Markdown 与
邮件（MJML）版不支持折叠，照 Filtered 的先例**平铺**（DESIGN §7 / §8）。

每个标的/分组一张卡，卡片之间 `border-top: 1px solid --rule-soft`。
**不要 box border / 圆角 / 背景色。** 三行结构：

```
MU     Watch                                 823.03    —
       Thematic · AI memory                  [mono]    [mono]

NEWS    三星利润创纪录、称 AI 内存紧缺或延长；MU 七月跌约29%、周四反弹约18%。
IMPACT  同业验证内存稀缺 → 美光定价权与 HBM 需求预期改善；但深跌后技术反弹遇阻。
WATCH   守住 823 前收上方；破 850 则反弹确认，跌破 800 则抛压未止。   Conf Medium
```

- `NEWS` / `IMPACT` / `WATCH` 是 mono eyebrow（9px, uppercase, `--ink-3`），右侧是 body 正文。
- `Watch` 状态：state label 前加 5px amber dot。`Alert`：`--ink` + weight 500。State 仅三档。
- 无直接新闻时 `NEWS` 写："No direct overnight news. Relevance from sector / macro context."
- `confidence` 放在 WATCH 行右端，mono `--ink-2`。
- 标的多时按 exposure group 合并成一张卡（ticker 位写组名，如 `Semiconductors`）。

**内容标准（密度优先，不是长度优先 — 2026-08-02 / synthesize Day4-v7)**：
卡片是 Asset Impact 的信息主体，不能敷衍。视觉仍是三行、每字段 1–2 句，但每句必须有信息，
五张卡合计仍要 10 分钟内读完。三行各自的硬标准：
- `NEWS`：写清发生了什么，**带关键数字/主体**；ETF 写主题/成分股层面读数。无直接消息时说明相关性
  具体来自哪条板块/宏观线索，不只写"无消息"。极端且仅二手来源的数字（如"较高点腰斩"）加一句归因
  （"据二手报道、未获证实"）。
- `IMPACT`：**必须给出传导链** —— 点名消息经由什么机制影响该持仓（二阶联系，如
  "内存涨价 → 美光定价权 → AI 资本开支需求"）。给一个清晰方向判断；**禁止**"方向不明 / 影响有限 /
  整体承压"这类空话收尾。只有真有双向拉锯才写两面。
- `WATCH`：一个**具体可观测**的确认变量，必须带**价位/数据阈值 + 往哪走意味着什么**。**禁止**
  "观察 XX 走势 / 留意板块方向 / 无独立盯盘变量"这类泛泛话；即使标的清淡，也要给出它实际跟随的
  那个变量与触发位。
- `state` / `signal_state` 校准：卡片出现 `Watch`/`Alert`，或 telemetry 有 flag、或有 High 信号时，
  Section header 的 `signal_state` 至少为 `AMBER`（详见 synthesize.md signal_state 硬规则）。

### 6.5 Watch After Open — 已并入 Portfolio Read（2026-08-04 移除）

**此段不再独立存在。** 组合级盯盘要点迁到 §6.1.6 Portfolio Read 的 `watch`（≤4 条、陈述句、
带阈值+含义、信息非建议）；逐标的盯盘在 §6.4 卡片的 `WATCH` 行。schema 的 `watch_after_open`
字段已删。保留本小节仅作历史指引，避免有人再按旧结构渲染。

### 6.6 Event Watch (Section 05)

4 列 grid：`[time] [affected] [event · why] [priority]`，≤5 行。

```
06.12 · 10:00   MACRO   UoM inflation expectations · tests GLD real-rate read   HIGH
06.12 · 16:00   QQQ     Semi peer earnings · flow read-through                  MED
```

- 时间格式严格 `MM.DD · HH:MM`，按时间正序。
- Priority 三档：`LOW` (--ink-3) / `MED` (--ink-2) / `HIGH` (--amber)。
- 弱相关事件不进这里，进 Filtered。

### 6.7 Source Quality (Section 07) + Footer

> **网页版默认收起（2026-08-04）**：折进 `<details>`（summary 显示 report confidence）；
> **邮件/Markdown** 保留为单行页脚（本就极简、且是透明度标注，值得可见）。

Source Quality 是**单行**计数，绝不展开成 audit 段落：

```
SOURCE QUALITY   3 official · 4 tier-1 · 2 secondary · 3 inference   ·   Report confidence Medium
```

- 整行 mono `--ink-3`，唯一可上 amber 的是 `Report confidence` 的值（且仅当 Low / High 时点一下）。
- 可选 limitation 一句，另起一行 `--ink-3` italic，无则省略。

Footer 紧随其后，极简两列对齐，顶部 `--rule` hairline：

```
END · ARC-09                          Finnhub · SEC EDGAR · US Treasury · Yahoo Finance
```

> 数据源串已去掉 FRED（2026-06-11 起 Treasury CSV 取代 FRED）。

**合规页脚（2026-08-05 新增，必备件）**：`END · ARC` 行之下挂一段克制的合规文本，全部
`--ink-3` 小字、body/mono，不上 amber、不破坏留白。**三格式一致**，A 类始终显示：
1. **免责声明**（body 11px `--ink-2`）：一句"仅供参考与教育用途，非投资建议…DYOR，风险自负"，
   可选 `完整条款` 链接。
2. **AI + 数据披露**（body 11px `--ink-3`）：一句"由 AI 基于第三方数据自动生成，可能有误/延迟，
   数据按现状提供不保证准确…覆盖你本人配置的持仓"，可选 `方法论` 链接。
3. **版权行**（mono 9px `--ink-3`）：`© {year} {holder} · 保留所有权利`，可选 contact。
- **B 类（CAN-SPAM，多用户必备）**：`退订 Unsubscribe` 链接 + 实体邮寄地址——**仅当 config 提供
  `legal.unsubscribe_url` / `legal.postal_address` 时才渲染**，单收件人模式自动省略。
- 变量位（`copyright_holder` / `year` / `contact` / `terms_url` / `methodology_url` /
  `unsubscribe_url` / `postal_address`）来自 `config.legal`，经 `render/context.py::_legal`
  注入，**不硬编码**；静态免责措辞在模板里（产品级 boilerplate，非数据）。

### 6.8 Data Sources（折叠）

Source Quality 之后、Footer 之前，放一个**默认折叠**的数据源明细，复用 Filtered 的
`<details>` 交互（mono summary + hairline，三角箭头）。列出每个数据源「提供什么」：

```
▶ 数据源 / DATA SOURCES
   Finnhub        — 公司新闻 + 财报日历
   ForexFactory   — 经济日历（预期 / 前值）
   SEC EDGAR      — 8-K / Form 4 / 10-Q 备案
   US Treasury    — 国债收益率（DGS2 / DGS10）
   Yahoo Finance  — 盘前价格 + DXY + VIX
```

- 复用 `.fil-list` / `.fil-item` 样式（来源名 `--ink-2`，说明 `--ink-3` italic），不引入新强调色。
- 与 §07 Source Quality（按等级计数）职责不同：这里是**实际数据管道清单**，那里是来源质量评估。
- **Markdown 版**：DESIGN §7 禁止在 md 内嵌 HTML，故 md 用普通「数据源」小节列表（不可折叠），HTML 版才是真折叠。

---

## 7. Markdown 版本的适配

`brief.md.j2` 没有 CSS，需要用 **纯文本秩序** 还原"工程档案"质感：

### 原则

1. **大量空行模拟留白**（section 之间空 2 行）
2. **章节编号保留**（`## 01 · Telemetry 遥测`）
3. **mono 数据靠 markdown 表格 + 代码块对齐**
4. **强调用粗体替代橙色**（`**+18% MTM**`），但**仅限关键数字**
5. **避免 emoji / 装饰符号**
6. **可用 Unicode 分隔符**：`·` `—` `─` 这类，慎用 `─────` 长横线（容易过载）

### 示例片段

```markdown
ARC-09 · 2026.06.10 · 09:00 ET · DAY 162 / FY26

# Pre-market Radar

Five assets · Four signals · Three events

Signal: **AMBER**


## 00 · Market Pulse 脉象

**Bias** — Mixed / Event-driven

1. Inflation pressure vs. rate rally
2. Semiconductor flow risk
3. Gold safe-haven confirmation test

**Key question** — Is the market treating lower yields as the dominant
signal, or does inflation reprice risk after the open?

Confidence: **Medium**


## 01 · Telemetry 遥测

| Indicator | Value | Delta          |
|-----------|-------|----------------|
| DGS2      | 4.82% | +3bp breakout  |
| DGS10     | 4.41% | +5bp           |
| DXY       | 105.8 | +0.4%          |
| VIX       | 18.2  | +1.1 regime    |


## 02 · Top Signals 信号

**1 · PPI hotter than expected** — QQQ / GLD / SGOV
Keeps inflation pressure alive while rates fall.
*Official · New · High impact · Conf High*
```

**绝对禁止**：
- 在 markdown 里嵌入 HTML / inline style
- 用 emoji 作状态符号
- 大段使用引用块（`>`）

---

## 8. Email 适配清单

`brief.html.j2` 渲染输出需要在邮件客户端能用。已知坑：

| CSS 特性 | Gmail | Outlook (desktop) | Apple Mail | 处理方式 |
|---|---|---|---|---|
| Google Fonts `@import` | ✓ | ✗ | ✓ | 必须提供系统字体 fallback |
| CSS Grid | ✓ | ✗ (2007–2019) | ✓ | 用 `<table>` fallback 包一层，或 progressive enhancement |
| Flexbox | ✓ partial | ✗ partial | ✓ | 简单 flex 可用，复杂的退回 table |
| CSS variables (`var()`) | ✓ | ✗ partial | ✓ | **必须把 var 值在最终输出时 inline 化** |
| `<svg>` inline | ✓ | ✗ partial | ✓ | Signal orb 应该有 PNG fallback |
| `border-radius` | ✓ | ✗ partial | ✓ | 本设计不用圆角，N/A |

**实现状态（2026-06-12，已落地）**：
1. `brief.html.j2` 保留为 web preview / archive；`render/html.py` 仍输出 `output/<date>.html`。
2. 邮件专用模板 `brief.mjml.j2`（Jinja → MJML）由 `render/mjml.py` 用 **mrml**（Rust 实现的
   MJML 引擎，pip 装、无需 Node）编译成 `output/<date>.email.html`。**mailer 发送的是这一版**。
3. 邮件版的取舍（email 客户端限制）：
   - **字体退回系统栈**（Gmail 屏蔽 web font）：display→Helvetica/Arial，mono→Menlo/Consolas。
   - **放弃 SVG signal orb**（多数客户端剥离 inline SVG）：信号状态改用 `SIGNAL · AMBER`
     文字标签呈现(amber 仅点在 state 值上)。
   - **CSS Grid / flex / var() 全部不用**：mrml 输出纯 `<table>` + 内联样式;布局单栏 640px。
   - **Filtered 不可折叠**(email 不支持 `<details>`):改成普通小节(计数 + 列表)。
   - 色板/amber 克制/留白/编号章节/hairline 与 web 版一致;amber 仍 ≤3%。
4. 自检:编译产物应满足 `var(--` 不出现、`<table>` 大量存在、体积 < 102KB(Gmail 裁剪线)。

---

## 9. 迭代时的 Self-Check Checklist

每次改完 `src/render/` 下任何文件，回答以下五个问题。任何一个回答"不确定"或"否"，停下来重新看。

### Q1. Amber 用量是否 ≤ 3%？
扫一眼渲染输出，橙色占据的视觉面积应该是"点睛"级别。如果它变成"主色之一"，说明用滥了。

### Q2. 是否引入了反例清单（§2）里的任何元素？
特别警惕：青色、glow、多色 tag、强边框、emoji 状态符号、满屏方括号。

### Q3. 留白是否被填满了？
如果你给某个 section 加了内容是因为"觉得空"，撤回。**留白是设计本身**。

### Q4. 新增的 amber 强调是否"必要"？
每个 amber 应该承载真正的信号意义（关键数字、状态切换、优先级），不是装饰。问自己：拿掉这个 amber，读者会错过什么真实信息吗？如果不会，拿掉。

### Q5. 这个改动能直接放进 generic SaaS dashboard 而不显得突兀吗？
能 → 走错方向了，重做。
不能（这玩意儿一看就是"那份工程档案日报"）→ 走对了。

---

## 10. Token 速查表（开发用）

```css
/* Copy-paste tokens for new components */
:root {
  --paper: #F4F2EC;
  --paper-2: #EDEAE2;
  --ink: #0A0908;
  --ink-2: #595550;
  --ink-3: #918C83;
  --rule: #D6D2C8;
  --rule-soft: #E5E1D6;
  --amber: #C8732C;
  --amber-deep: #8E4F1B;
  --amber-soft: rgba(200, 115, 44, 0.08);

  --font-display: 'Inter Tight', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-body: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
  --font-cjk: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
}
```

---

## 11. 变更日志

| 日期 | 变更 | 决策人 |
|---|---|---|
| 2026-06-10 | Initial design system established (Lone Trail aesthetic) | owner |
| 2026-06-12 | 产品重定位为 **Pre-market Radar**（盘前情报压缩器）。标题 `Portfolio Log`→`Pre-market Radar`；章节重构为 00–07（Market Pulse / Telemetry / Top Signals / Asset Impact / Watch After Open / Event Watch / Filtered / Source Quality）；新增 Market Pulse、Compact Label、Source Quality 组件；旧 Anomalies+Deep Scan 并入 Top Signals/Asset Impact。**色板/字体/留白/orb 全部保留。** | owner |
| 2026-06-12 | 正文中文化（chrome/英文标签保留）；§6.4 Asset Impact 顶部恢复盘前快照价格表 `.snapshot`；§6.8 新增**折叠式 Data Sources** 明细（复用 Filtered `<details>`）；watch_after_open 改陈述句、信息更密；prose 缩写首次出现注明中文全称。 | owner |
| 2026-06-12 | 落地**邮件版**：`brief.mjml.j2` + `render/mjml.py`（mrml 编译，无 Node），输出 `output/<date>.email.html`，mailer 改发此版。§8 更新实现状态与取舍（系统字体、去 orb、纯 table、Filtered 不折叠）。 | owner |
| 2026-06-15 | Header 顶部新增 **friendly greeting（个人时报问候）**：`.head-greeting`（display 15px `--ink-2`，max-width 30em），位于 mono ID 行之上。文案由 `render/context.py::_greeting` 按 owner 名 + 投递日 weekday **模板合成**（非 LLM 生成,避免废话/不可控），周一/周五/周末语气略有差异。owner 取自 `config/tickers.yaml::owner`。三套模板同步。 | owner |
| 2026-06-14 | **产品化排版批次（适度重构）**：① Header 新增 **coverage 信任行**（mono 10px `--ink-3`）——一行说明内容窗口"覆盖 上一交易日收盘 → 今早 · 投递 09:00 ET"，由 `render/context.py::_coverage_window` 按投递日 weekday 推导。② Market Pulse（§6.1.5）新增可选 **caveat 行**（`.pulse-caveat`，12.5px `--ink-2`，顶部 hairline 分隔）——仅低信心/数据有局限时出现，`key_question` 回归纯粹。③ **价格快照表方向改为单色 ↑/↓ 箭头**：移除原 `.chg.up` 的 `--amber-deep` 上色（违反 §3.2 涨跌不上色），改为 `--ink` + `--ink-3` 箭头 glyph，符号本身表达方向；同步修正 `.asset-change` 卡片内涨跌。④ 盘前未开盘（全部 `change_pct` 为 None）时表格下方加 **empty-state 说明**（`.snapshot-note`）。三套模板（html/md/mjml）同步。 | owner |
| 2026-08-02 | **§6.4 内容标准（非视觉变更）**：Asset Impact 卡片明确"密度优先、不敷衍"的三行内容硬标准——`IMPACT` 必须给二阶传导链、`WATCH` 必须带具体价位/数据阈值 + 含义，禁用"方向不明 / 观察 XX 走势 / 无独立盯盘变量"等空话；示例刷新为 MU（传导链 + 阈值）。同步 `signal_state` 校准（有 Watch/Alert 标的、telemetry flag 或 High 信号 ⇒ 至少 AMBER）。视觉结构/色板/留白不变；对应 `synthesize.md` Day4-v7。 | owner |
| 2026-08-06 | **新增 Post-close Radar（收盘总结）报告**（§5.2.2）：向后复盘版，共用孤星视觉系统 + Telemetry + 合规页脚，章节不同（00 收盘脉象 / 01 复盘对账 / 02 遥测 / 03 今日异动 / 04 标的复盘 / 05 盘后·明日 / 06 已过滤 / 07 来源）。三套模板按 `brief.report_type` 分支渲染（`{% if post %}`），premarket 无回归。核心是 **01 复盘对账**：把当日晨报的命门/watch/信号对实际打分（命中/落空/中性/待续），`落空` 徽章可上 amber。schema `schemas/postclose.py`；prompt `synthesize_postclose.md`。时间层改为 UTC 内部计算、ET 语义（`src/timeutil.py`），报告类型按 ET 时钟自动分派。 | owner |
| 2026-08-05 | **`_design_reference.html` 改为渲染快照**：过去手写、已严重滞后于模板。现在由 `brief.html.j2` 渲染一份代表性样本（+ demo legal config 展示完整合规页脚）生成——它成为模板的**快照/派生物**，不再是模板要去追的手写规范。工作流相应调整：DESIGN.md（规范）→ 改模板 → **重新生成**参考图（命令见本文件开头）。DESIGN.md 仍是唯一的规则源。 | owner |
| 2026-08-05 | **Portfolio Read 去碎片化 + 尾部收拢**：① §6.1.6 互动从"eyebrow 行 + 正文行两块"改为**一行流动文本**（`kind · holdings — note`），posture/ripple 也改流动段落，只留 `swing`（命门 amber）与 `watch` 强调——不再被一堆小标签切碎。② **邮件/Markdown**（无 `<details>`）把 **Filtered + Source Quality 收成单行摘要**（Filtered 只留计数"逐条见网页版"，Source 一行计数）；网页版仍是真折叠。三格式同步。 | owner |
| 2026-08-05 | **合规页脚（产品级必备件，非内容）**：`END · ARC` 行下新增合规文本——① 免责声明（非投资建议 / DYOR / 风险自负）② AI 生成 + 第三方数据 as-is 披露 ③ 版权行 `© {year} {holder}`。B 类（退订 + 实体地址）config 提供 `legal.*` 时才渲染（多用户 CAN-SPAM 用），单收件人省略。变量走 `config.legal` → `context._legal`，静态措辞在模板；三格式（html/md/mjml）一致。全 `--ink-3/2` 小字，不破坏留白。见 §6.7。 | owner |
| 2026-08-04 | **盘前减法（去冗余）**：加了合成层后，Top Signals/Asset 卡对同一事件重复叙述 → 减掉重复。**网页版**：Top Signals(03) 与 Source Quality(07) 收进 `<details>` 折叠（Asset 卡 / Filtered / 数据源已折叠）；扫读层 = 00 Market Pulse + 01 Portfolio Read + 02 Telemetry + 05 Event Watch。**邮件/Markdown**（无 `<details>`，见 §8）：Top Signals **压成一行一条**（rank · signal — affected · label，去掉 `why` 段——`why` 已在 Portfolio Read），Source Quality 保留单行页脚。三格式各自达到"盘前不冗长"。 | owner |
| 2026-08-04 | **章节重排（结构变更）**：新增 **01 Portfolio Read（持仓合成）** 作为核心段（§6.1.6）——净姿态 + 2–3 条成对跨持仓互动（`kind` ∈ SHARED DRIVER / HEDGE FAILURE / CONCENTRATION / DIVERGENCE，每条点名 ≥2 只 + 机制）+ 可选二阶链 + 命门（`swing`，本段唯一 amber）+ ≤4 组合级盯盘。旧 **Watch After Open 段移除**、内容并入 Portfolio Read 的 `watch`（§6.5 保留为历史指引）。**Asset Impact 逐标的卡片改默认折叠**（HTML `<details>`，快照表仍常驻；md/email 平铺）。段号顺延：Telemetry 02、Top Signals 03、Asset Impact 04。schema 去 `watch_after_open`、加 `portfolio_read`；对应 `synthesize.md` 新增 portfolio_read 段。色板/字体/留白/orb 不变。 | owner |
| 2026-11-05 | **模板转义（工程修复，非视觉变更）**：`brief.html.j2` / `brief.mjml.j2` 开启 Jinja autoescape（`render/context.py`），`brief.md.j2` 仍为纯文本不转义。起因：LLM 正文里的 `>` 紧挨中文时 mrml panic，整封邮件构建失败（2026-08-10、10-05 盘后复现）。约定：模板里的**可信常量**若含引号或标记，显式 `\|safe`（如 mjml 的字体栈）；brief 字段一律不加 `\|safe`。无特殊字符的 brief 渲染结果与修复前逐字节一致。 | owner |

> 任何后续设计变更必须同步更新本文件。代码与文档不一致时，**以本文件为准**，代码视为 bug。
