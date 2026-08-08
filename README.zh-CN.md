# Pre-market Radar 盘前雷达

> [English](README.md) · **中文**

一份关于你实际持有的美股的每日简报。它抓取隔夜新闻、宏观数据、价格和即将到来的
催化剂,写成一份可扫读的中文摘要。每个交易日两份:开盘前一份,收盘后一份。

不是投资建议。它做的是过滤而不是叠加:大部分新闻会被放进「已过滤」区并附一句理由,
只有通过相关性检查的内容才进主报告。

单用户,跑在笔记本上,没有数据库。

---

## 两份报告

| | 盘前 | 盘后 |
|---|---|---|
| 投递 | 09:00 ET | 约 17:00 ET |
| 覆盖 | 上一交易日收盘 → 今早(另带 5 个 session 的上下文) | 当日交易时段 + 盘后 |
| 回答 | 今天盘面大概率在交易什么 | 实际发生了什么,晨报对了吗 |
| 标志章节 | `01 Portfolio Read` 跨持仓合成 | `01 Scorecard` 给晨报的判断打分 |

盘后报告会从磁盘读当天的盘前简报,对每条预期打分:命中 / 落空 / 中性 / 待续。
如果磁盘上没有当天的晨报,它会留空,而不是编造晨报说过什么。

---

## 运行

```bash
source .venv/bin/activate

# 按 ET 时钟决定跑哪份,只写 output/,不发信
python -m src.main

# 同上,并发送(收件人取 .env 的 EMAIL_TO,或指定地址)
python -m src.main --send
python -m src.main --email someone@example.com

# 显式指定报告类型和日期
python -m src.main --report postclose --date 2026-08-06

# 迭代时复用已缓存的阶段
python -m src.main --skip-collect                    # 复用当天已抓的原始数据
python -m src.main --skip-collect --skip-per-asset   # 只跑合成 + 渲染
```

跑哪份报告由 ET 时钟决定(`src/timeutil.py::resolve_report`),不看机器本地时区:
06:00–16:00 ET 是当日盘前,16:01–23:59 是当日盘后,00:00–05:59 是前一日盘后。

产出:

```
output/YYYY-MM-DD.TYPE.email.html   MJML 构建,实际发出去的就是它
output/intermediate/                raw_*.json、per_asset_*.json、brief_*.json
```

`output/` 下全部 gitignored,可以重新生成。

---

## 排程(macOS)

```bash
./scripts/scheduler.sh install     # 写 plist 并加载
./scripts/scheduler.sh status      # 是否已加载 + 发送记录
./scripts/scheduler.sh log         # tail autorun 日志
./scripts/scheduler.sh uninstall
```

launchd 每 5 分钟调一次 `python -m src.autorun`。这个入口不试图在 08:30 精确触发,
而是问「当前 ET 时间该发哪份报告」和「这份发过了吗」,只有确实该发才跑 pipeline。
笔记本上的四个问题因此自然解决:

| 问题 | 如何处理 |
|---|---|
| 美国夏令时 | 窗口按 ET 判定,不需要一年改两次 |
| 睡眠 | launchd 在唤醒后补触发错过的 interval,报告随之补发 |
| 网络抖动 | 失败的运行不会写 `sent`,下个 tick 重试(6 次后发告警邮件) |
| 市场假日 | 查实时数据而不是日历文件:盘后要求 `last_session_date() == 报告日期`,盘前读 Yahoo 的 `marketState` |

`fcntl` 文件锁防止两个 tick 重叠,45 分钟的 `SIGALRM` 超时把卡住的 socket 变成
一次普通的可重试失败,而不是永久持锁。`output/state/autorun.json` 记录已发送内容,
这是防止重复发信的唯一机制。

**目前不工作**:直接调用时一切正常(`launchctl kickstart` → exit 0),但 launchd
不会自己拉起它。`RunAtLoad` 和 `StartInterval` 都停在
`pended nondemand spawn = speculative`,`runs = 0`。电池节流、`ProcessType`、
`launchctl enable` 都已排除。最可能是 macOS 的后台项目授权
(系统设置 → 通用 → 登录项与扩展)。

---

## 报告结构

章节结构固定,模型只填内容。正文简体中文,章节标题和 mono 标签保持英文。

**盘前**

| # | 章节 | 内容 |
|---|---|---|
| 00 | Market Pulse 脉象 | bias、≤3 个主题、关键问题、信心 |
| 01 | Portfolio Read 持仓合成 | 整体姿态、2–3 组跨持仓联动、二阶传导、命门、盯盘清单 |
| 02 | Telemetry 遥测 | 2 年/10 年期美债收益率、美元指数、VIX(最多 2 个 amber 标记) |
| 03 | Top Signals 信号 | ≤5 条排序条目,每条标 `source · freshness · impact` |
| 04 | Asset Impact 标的 | 价格表,然后每个持仓的 News / Impact / Watch / Confidence |
| 05 | Event Watch 事件 | 未来 72 小时内 ≤5 个催化剂 |
| 06 | Filtered 已过滤 | 检查过但丢弃的内容,每条一句理由 |
| 07 | Source Quality 来源 | 来源等级计数、报告信心、说明 |

**盘后**:`00 Close Pulse` · `01 Scorecard 复盘对账` · `02 Telemetry` ·
`03 Movers 今日异动` · `04 Asset Recap 标的复盘` · `05 After Hours & Tomorrow`,
后接相同的 `06`/`07`。

决定一条内容进不进主报告的是它与你持仓的相关性,不是标题有多大。一条宽泛的宏观新闻
只有在能解释这几个标的当天盘面时才进主报告;一份你持有的小盘股的 SEC 备案,
优先级高于一条很大但无关的头条。当组合里有低流动性标的时,prompt 会切到小盘股模式,
把备案、增发稀释、FDA 消息、现金 runway 排在宏观前面。

---

## 配置

`config/tickers.yaml` 放标的。它已被 gitignore(持仓属于个人财务信息),从模板开始:`cp config/tickers.example.yaml config/tickers.yaml`。只列你持有和关注的,简报会自己推断每个标的的角色和板块。
没有兜底配置文件,所以文件缺失或名字写错会直接停下来,而不是悄悄给你一份别人持仓的简报。

```yaml
owner: Your Name
holdings:
  - SPY
  - QQQ
watchlist:
  - NVDA
  - GOOGL
```

`.env` 放密钥(已 gitignore):

```ini
LLM_PROVIDER=deepseek           # deepseek | kimi | anthropic
DEEPSEEK_API_KEY=...
# MOONSHOT_API_KEY=...          # LLM_PROVIDER=kimi 时
# ANTHROPIC_API_KEY=sk-ant-...  # LLM_PROVIDER=anthropic 时

FINNHUB_API_KEY=...             # 公司新闻 + 财报日历
FRED_API_KEY=...                # 可选,补全已公布的 actual 值
SEC_USER_AGENT=YourApp you@example.com   # SEC 要求 UA 里带联系方式

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587                   # 587 STARTTLS,465 SSL
SMTP_USER=you@gmail.com
SMTP_PASS=<应用专用密码>          # Gmail:开 2FA,然后创建 App Password
# EMAIL_FROM=you@gmail.com      # 可选,默认等于 SMTP_USER
EMAIL_TO=you@gmail.com          # --send 和排程器的默认收件人
```

财政部收益率、经济日历、SEC EDGAR 不需要 key。

---

## 工作原理

```
读配置 → collect → 逐标的摘要 → 合成 → 渲染 → 投递
```

1. `pipeline/collect.py` 调用所有数据源并写 `raw_*.json`。它回看 5 个 session 取上下文,
   但把最新 session 记在 `RawMaterial.last_session` 里,两个 prompt 都把它当硬边界:
   旧新闻可以补脉络,不能当头条。
2. `pipeline/per_asset.py` 对每个标的做一次廉价的 LLM 调用,拿结构化摘要以及
   新鲜度和来源分级。
3. `pipeline/synthesize.py`(或 `synthesize_postclose.py`)用全部摘要、宏观和日历
   做一次调用,返回经 schema 校验的简报。公共部分在 `pipeline/synth_shared.py`。
4. `render/` 转成 Markdown(邮件的纯文本部分)、网页 HTML、以及 MJML 编译的邮件 HTML。
5. `deliver/mailer.py` 通过 SMTP 发送 MJML 构建版本。

几个值得知道的决定:

- 每个 LLM 输出都过 Pydantic 校验,失败时把错误文本发回去重试。
- 每个阶段都把输出写到磁盘,所以质量问题能定位到采集、摘要还是合成。
- 价格在合成之后从 yfinance 注入。模型从来不被要求提供价格,所以编不出来。
- 交易日、session 边界、假期都从实时市场数据读取,仓库里没有 NYSE 假期表。
- 用两次 LLM 调用而不是一次:预消化过的摘要比一个塞满原始标题的 prompt 效果好。

---

## 数据源

全部免费。

| 来源 | 提供 | 模块 | 需要 key |
|---|---|---|---|
| Finnhub | 公司新闻、财报日历 | `sources/finnhub.py` | 是(免费档) |
| yfinance(ETF 档案) | 基金分类和前十大持仓 | `sources/etf.py` | 否 |
| 来源分级 | 新闻等级判定,在预处理阶段算出 | `sources/source_grade.py` | 否 |
| ForexFactory(faireconomy XML) | 经济日历:日程、预期、前值 | `sources/forexfactory.py` | 否 |
| FRED | 关键美国数据的已公布 actual,以及最新官方读数 | `sources/fred.py` | 是(免费,可选) |
| 美国财政部 + yfinance | 2 年/10 年期收益率、美元指数、VIX | `sources/macro.py` | 否 |
| yfinance | 盘前和收盘报价、`marketState` | `sources/yfinance_prices.py` | 否 |
| SEC EDGAR | 8-K、Form 4、10-Q | `sources/sec_edgar.py` | 否 |
| DeepSeek / Kimi / Anthropic | 两个 LLM 阶段 | `pipeline/llm.py` | 是 |

**ETF 新闻**。用 ETF 自己的代码查公司新闻查不到有用的东西,因为基金没有财报。
`etf.py` 从 yfinance 读每个持仓的分类和主要成分股,`collect.py` 把成分股的新闻并进
基金的新闻池,并限制每个成分股的条数,免得一只巨头把其他的挤掉。它跟随的是实时持仓
而不是查找表,所以换成别的 ETF 也能直接工作。

**来源分级的局限**。Finnhub 免费档只暴露托管平台(Yahoo、SeekingAlpha),
拿不到原始通讯社,所以大多数条目被判为 `secondary_media`,不认识的平台落到 `unknown`。
要拿到真正的信源需要付费新闻 API。这张分级表是仓库里唯一的硬编码查找表,是有意保留的。

---

## 目录

```
News/
├── config/tickers.yaml          标的配置
├── scripts/scheduler.sh         launchd 安装 / 状态 / 日志
├── src/
│   ├── main.py                  pipeline 入口 + CLI
│   ├── autorun.py               排程 tick:ET 窗口 + 发送账本
│   ├── timeutil.py              内部 UTC,市场语义用 ET
│   ├── schemas/                 raw、per_asset、brief、postclose
│   ├── sources/                 finnhub、etf、source_grade、forexfactory、fred、
│   │                            macro、yfinance_prices、sec_edgar
│   ├── pipeline/                llm、collect、per_asset、synth_shared、
│   │                            synthesize、synthesize_postclose
│   ├── render/                  context + markdown/html/mjml + *.j2 模板
│   │   ├── DESIGN.md            视觉设计系统,改 render/ 前先读
│   │   └── _design_reference*.html
│   ├── deliver/mailer.py        SMTP 发送 + 告警邮件
│   └── prompts/                 per_asset.md、synthesize.md、synthesize_postclose.md
└── output/                      gitignored:简报、intermediate/、state/、logs/
```

---

## 视觉设计

渲染后的简报遵循一套基于明日方舟《孤星》的设计系统:暖调米白背景,单一琥珀色强调
(`#C8732C`,控制在视觉面积 3% 以内),等宽字体,大量留白,无 emoji,无卡片边框,
无第二强调色。涨跌不着色。

改 `src/render/` 下任何东西之前,先读 `src/render/DESIGN.md` 和 `_design_reference.html`。
邮件模板由 `mrml`(Rust 写的 MJML 引擎,不需要 Node)编译成表格化 HTML;
它去掉了邮件客户端会剥离的 SVG 信号球和网络字体,保留配色和结构。

---

## 已知问题

### collect 耗时约 17 分钟

2026-08-07 实测,5 个标的:collect 17m19s、per-asset 33s、合成 1m07s、发信 9s,
端到端 19 分钟。所有数据源都在顺序 `for ticker` 循环里,大约 40 次 HTTP 往返,
经代理出海每次约 25 秒。

这让盘前窗口没有任何余量。08:30 ET 是最早合理的启动时间,因为 8:30 的经济数据
必须已经发布;它同时也是还能赶上 09:00 的最晚启动时间。修法是用 `ThreadPoolExecutor`
并行化那些互相独立的抓取;在那之前,网络慢就意味着简报迟到。

### 合成阶段偶尔把列表字段返回成字符串

合成偶尔会校验失败:`top_signals: Input should be a valid list [input_value='[\n {\n ...`。
工具调用的输出本质上仍是逐 token 生成,schema 只是偏置而不是语法约束,
所以嵌套数组可能变成转义的 JSON 字符串。当这个字符串又超出 `max_tokens` 时,
它会被截断,彻底无法解析。

`pipeline/synth_shared.py` 从三个方向处理:`coerce_json_strings()` 把看起来像 JSON 的
字符串解析回对象;`MAX_TOKENS = 16384` 给约两倍的载荷留出空间;
`_repair_truncated_json()` 抢救出仍被截断的数组里完整的前缀元素。

残留风险:抢救路径可能返回一份更短的简报(5 条信号只剩 4 条)且通过校验、没有任何提示;
被截断的对象字段不在抢救范围内,只能走重试;三次尝试都失败时当天没有简报,
也没有降级兜底。

---

## 状态

可用:两份报告端到端直到 SMTP 投递、盘后复盘对账、相关性闸门、新闻分层、
小盘股模式、来源分级、ETF 成分股新闻、孤星风格渲染、排程器的判定逻辑。

受阻:launchd 不会自动拉起 agent(见上)。

下一步:并行化 `collect`,然后做跨日连续性,让 Market Pulse 能说出较昨日有什么变化。

---

## 许可

MIT —— 见 [LICENSE](LICENSE)。

这是一个个人项目,按现状发布。它生成的是供你自己阅读的市场评述,不构成投资建议;
简报内容由大模型基于第三方数据写成,可能出错。
