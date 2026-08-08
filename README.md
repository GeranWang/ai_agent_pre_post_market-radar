# Pre-market Radar

> **English** · [中文](README.zh-CN.md)

A daily brief about the US stocks you actually hold. It pulls overnight news,
macro data, prices, and upcoming catalysts, then writes one scannable Chinese
summary. Two per weekday: one before the open, one after the close.

Not investment advice. It filters rather than adds: most news is pushed into a
"filtered" section with a one-line reason, and only what passes a relevance
check for your specific tickers makes it into the main report.

Single-user, runs on a laptop, no database.

---

## The two reports

| | Pre-market | Post-close |
|---|---|---|
| Delivered | 09:00 ET | ~17:00 ET |
| Covers | last close → this morning (plus 5 sessions of context) | today's session + after-hours |
| Asks | what is today's tape likely to trade? | what happened, and was the morning right? |
| Signature section | `01 Portfolio Read`, cross-holding synthesis | `01 Scorecard`, grades the morning's calls |

The post-close report reads that same day's pre-market brief off disk and scores
each expectation 命中 / 落空 / 中性 / 待续. If the morning brief isn't on disk it
leaves the scorecard empty rather than inventing what the morning said.

---

## Running it

```bash
source .venv/bin/activate

# Run whichever report the ET clock calls for; write to output/, don't send
python -m src.main

# Same, but email it (EMAIL_TO from .env, or any address)
python -m src.main --send
python -m src.main --email someone@example.com

# Pick the report and date explicitly
python -m src.main --report postclose --date 2026-08-06

# Reuse cached stages while iterating
python -m src.main --skip-collect                    # reuse today's raw data
python -m src.main --skip-collect --skip-per-asset   # only synthesis + render
```

Which report runs comes from the ET clock (`src/timeutil.py::resolve_report`),
not the machine's local timezone: 06:00–16:00 ET gives today's pre-market,
16:01–23:59 gives today's post-close, and 00:00–05:59 gives yesterday's post-close.

Output:

```
output/YYYY-MM-DD.TYPE.email.html   the MJML build, which is what gets mailed
output/intermediate/                raw_*.json, per_asset_*.json, brief_*.json
```

Everything under `output/` is gitignored and can be regenerated.

---

## Scheduling (macOS)

```bash
./scripts/scheduler.sh install     # write the plist and load it
./scripts/scheduler.sh status      # loaded? what has been sent?
./scripts/scheduler.sh log         # tail the autorun log
./scripts/scheduler.sh uninstall
```

launchd calls `python -m src.autorun` every 5 minutes. That entry point doesn't
try to fire at exactly 08:30. It asks which report is due at the current ET time
and whether it has already gone out, and runs the pipeline only if something is
actually due. Four laptop problems fall out of that:

| Problem | How it's handled |
|---|---|
| US daylight saving | Windows are in ET, so nothing needs editing twice a year |
| Sleep | launchd fires a missed interval on wake, so the report catches up |
| Flaky network | A failed run never records `sent`, so the next tick retries (6 attempts, then an alert email) |
| Market holidays | Checked against live data, not a calendar file: post-close needs `last_session_date() == report_date`, pre-market reads Yahoo's `marketState` |

An `fcntl` lock keeps two ticks from overlapping, and a 45-minute `SIGALRM`
deadline turns a stuck socket into a normal retryable failure instead of a lock
held forever. `output/state/autorun.json` records what has been sent; it's the
only thing preventing duplicate emails.

**Not currently working**: the agent runs fine when invoked directly
(`launchctl kickstart` → exit 0), but launchd never spawns it on its own.
`RunAtLoad` and `StartInterval` both stay at `pended nondemand spawn = speculative`
with `runs = 0`. Battery throttling, `ProcessType`, and `launchctl enable` have been
ruled out. Most likely macOS background-item approval (System Settings → General →
Login Items & Extensions).

---

## Report structure

The section layout is fixed and the model only fills in content. Prose is in
Simplified Chinese; section headings and the mono labels stay English.

**Pre-market**

| # | Section | Contents |
|---|---|---|
| 00 | Market Pulse 脉象 | bias, ≤3 themes, the key question, confidence |
| 01 | Portfolio Read 持仓合成 | posture, 2–3 cross-holding interactions, second-order chain, 命门, watch list |
| 02 | Telemetry 遥测 | 2Y/10Y Treasury, DXY, VIX (at most 2 amber flags) |
| 03 | Top Signals 信号 | ≤5 ranked items, each labelled `source · freshness · impact` |
| 04 | Asset Impact 标的 | price table, then News / Impact / Watch / Confidence per holding |
| 05 | Event Watch 事件 | ≤5 catalysts in the next 72h |
| 06 | Filtered 已过滤 | what was checked and dropped, one clause each |
| 07 | Source Quality 来源 | source-tier counts, report confidence, caveat |

**Post-close**: `00 Close Pulse` · `01 Scorecard 复盘对账` · `02 Telemetry` ·
`03 Movers 今日异动` · `04 Asset Recap 标的复盘` · `05 After Hours & Tomorrow`,
then the same `06`/`07`.

What decides inclusion is relevance to your holdings, not how big the headline is.
A broad macro story only enters the main report if it explains today's tape for
these tickers. An SEC filing on a small-cap you hold outranks a large unrelated
headline. When the portfolio contains illiquid names, the prompt switches to a
small-cap mode that puts filings, dilution, FDA news, and cash runway ahead of macro.

---

## Configuration

`config/tickers.yaml` holds the tickers. It is gitignored (a holdings list is personal financial information), so start from the template: `cp config/tickers.example.yaml config/tickers.yaml`. List what you own and watch; the brief
works out each holding's role and sector itself. There is no fallback config file,
so a missing or misnamed file stops the run instead of quietly briefing you on
someone else's positions.

```yaml
owner: Your Name
holdings:
  - SPY
  - QQQ
watchlist:
  - NVDA
  - GOOGL
```

`.env` holds the keys (git-ignored):

```ini
LLM_PROVIDER=deepseek           # deepseek | kimi | anthropic
DEEPSEEK_API_KEY=...
# MOONSHOT_API_KEY=...          # if LLM_PROVIDER=kimi
# ANTHROPIC_API_KEY=sk-ant-...  # if LLM_PROVIDER=anthropic

FINNHUB_API_KEY=...             # company news + earnings
FRED_API_KEY=...                # optional, fills in released `actual` values
SEC_USER_AGENT=YourApp you@example.com   # SEC requires a contact in the UA

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587                   # 587 STARTTLS, 465 SSL
SMTP_USER=you@gmail.com
SMTP_PASS=<app-password>        # Gmail: turn on 2FA, then create an App Password
# EMAIL_FROM=you@gmail.com      # optional, defaults to SMTP_USER
EMAIL_TO=you@gmail.com          # default recipient for --send and the scheduler
```

Treasury yields, the economic calendar, and SEC EDGAR need no key.

---

## How it works

```
load config → collect → per-asset summaries → synthesize → render → deliver
```

1. `pipeline/collect.py` calls every source and writes `raw_*.json`. It looks back
   5 sessions for context but records the latest session in `RawMaterial.last_session`,
   which both prompts treat as a hard line: older news can add background, never a headline.
2. `pipeline/per_asset.py` makes one cheap LLM call per ticker for a structured
   summary plus freshness and source grading.
3. `pipeline/synthesize.py` (or `synthesize_postclose.py`) makes one call with all
   summaries, macro, and calendars, and returns a schema-validated brief. Shared
   pieces live in `pipeline/synth_shared.py`.
4. `render/` turns it into Markdown (the email's plain-text part), web HTML, and
   MJML-compiled email HTML.
5. `deliver/mailer.py` sends the MJML build over SMTP.

Some decisions worth knowing about:

- Every LLM output is Pydantic-validated, and a failure sends the error text back
  for a retry.
- Every stage writes its output to disk, so a quality problem can be traced to
  collection, summarization, or synthesis.
- Prices are injected from yfinance after synthesis. The model is never asked for
  one, so it can't make one up.
- Trading days, session boundaries, and holidays are read from live market data.
  There's no NYSE holiday table in the repo.
- Two LLM calls rather than one: pre-digested summaries work better than a single
  prompt full of raw headlines.

---

## Data sources

All free.

| Source | Provides | Module | Key |
|---|---|---|---|
| Finnhub | Company news, earnings calendar | `sources/finnhub.py` | Yes (free tier) |
| yfinance (ETF profile) | Fund category and top holdings | `sources/etf.py` | No |
| Source grading | News-tier classification, computed in preprocessing | `sources/source_grade.py` | No |
| ForexFactory (faireconomy XML) | Economic calendar: schedule, forecast, previous | `sources/forexfactory.py` | No |
| FRED | Released actuals for key US releases, plus latest official readings | `sources/fred.py` | Yes (free, optional) |
| US Treasury + yfinance | 2Y/10Y yields, DXY, VIX | `sources/macro.py` | No |
| yfinance | Pre-market and close quotes, `marketState` | `sources/yfinance_prices.py` | No |
| SEC EDGAR | 8-K, Form 4, 10-Q | `sources/sec_edgar.py` | No |
| DeepSeek / Kimi / Anthropic | The two LLM stages | `pipeline/llm.py` | Yes |

**ETF news.** Querying company news by an ETF's own symbol returns nothing useful,
since a fund has no earnings. `etf.py` reads each holding's category and top
constituents from yfinance, and `collect.py` merges the constituents' news into the
fund's pool, capped per holding so one mega-cap doesn't crowd out the rest. It follows
live holdings rather than a lookup table, so swapping in a different ETF just works.

**Source grading limits.** Finnhub's free tier only exposes the hosting platform
(Yahoo, SeekingAlpha), not the original wire, so most items are graded
`secondary_media` and unrecognized platforms fall back to `unknown`. Getting the real
wire would need a paid news API. The grading table is the one hardcoded lookup in the
repo, kept deliberately.

---

## Layout

```
News/
├── config/tickers.yaml          the tickers
├── scripts/scheduler.sh         launchd install / status / log
├── src/
│   ├── main.py                  pipeline entry + CLI
│   ├── autorun.py               scheduler tick: ET windows + sent ledger
│   ├── timeutil.py              UTC internally, ET for market semantics
│   ├── schemas/                 raw, per_asset, brief, postclose
│   ├── sources/                 finnhub, etf, source_grade, forexfactory, fred,
│   │                            macro, yfinance_prices, sec_edgar
│   ├── pipeline/                llm, collect, per_asset, synth_shared,
│   │                            synthesize, synthesize_postclose
│   ├── render/                  context + markdown/html/mjml + *.j2 templates
│   │   ├── DESIGN.md            visual design system, read before editing render/
│   │   └── _design_reference*.html
│   ├── deliver/mailer.py        SMTP send + alert mail
│   └── prompts/                 per_asset.md, synthesize.md, synthesize_postclose.md
└── output/                      gitignored: briefs, intermediate/, state/, logs/
```

---

## Visual design

The rendered brief follows a design system based on Arknights 《孤星》 (Lone Trail):
warm off-white background, one amber accent (`#C8732C`) kept under about 3% of the
visual area, mono typography, a lot of whitespace, no emoji, no card borders, no
second accent colour. Gains and losses are not coloured.

Read `src/render/DESIGN.md` and `_design_reference.html` before changing anything
under `src/render/`. The email template is compiled by `mrml` (a Rust MJML engine,
no Node) into table-based HTML; it drops the SVG orb and web fonts that mail clients
strip, and keeps the palette and structure.

---

## Known issues

### Collect takes about 17 minutes

Measured on 2026-08-07 with 5 tickers: collect 17m19s, per-asset 33s, synthesis
1m07s, send 9s, so 19 minutes end to end. Every source is fetched in a sequential
`for ticker` loop, roughly 40 HTTP round-trips at about 25 seconds each through an
overseas proxy.

That leaves no slack in the pre-market window. 08:30 ET is the earliest sensible
start, since the 8:30 economic releases have to be out, and it's also the latest
start that still makes 09:00. Parallelizing the independent fetches with a
`ThreadPoolExecutor` is the fix; until then a slow network means a late brief.

### Synthesis sometimes returns a list field as a string

Synthesis occasionally fails validation with `top_signals: Input should be a valid
list [input_value='[\n {\n ...`. Tool-use output is still token-by-token generation,
so the schema biases the model without enforcing a grammar, and a nested array can
come back as an escaped JSON string. When that string also overran `max_tokens` it
arrived truncated and unparseable.

`pipeline/synth_shared.py` handles it three ways: `coerce_json_strings()` parses
JSON-looking strings back into objects, `MAX_TOKENS = 16384` leaves room for the
roughly doubled payload, and `_repair_truncated_json()` recovers the complete leading
elements of an array that still got cut off.

Residual risk: the repair path can return a shorter brief (4 signals instead of 5)
that validates with no warning; truncated object fields aren't repaired and fall
through to a retry; and if all three attempts fail there's no brief that day and no
degraded fallback.

---

## Status

Working: both reports end to end through to SMTP delivery, the post-close scorecard,
the relevance gate, news tiering, small-cap mode, source grading, ETF constituent
news, the Lone Trail render, and the scheduler's decision logic.

Blocked: launchd doesn't auto-spawn the agent (see above).

Next: parallelize `collect`, then cross-day continuity so Market Pulse can say what
changed since yesterday.

---

## License

MIT — see [LICENSE](LICENSE).

This is a personal project published as-is. It produces market commentary for
your own reading; it is not investment advice, and the briefs it generates are
LLM-written summaries of third-party data that can be wrong.
