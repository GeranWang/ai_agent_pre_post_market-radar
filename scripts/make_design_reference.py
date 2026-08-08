"""Regenerate src/render/_design_reference{,_postclose}.html.

DESIGN.md treats those files as rendered snapshots of `brief.html.j2`, not
hand-written specs, so they have to be regenerated whenever the templates change
(DESIGN.md §11). This script is that step.

The sample portfolio here is fictional on purpose. The reference files are
committed, and a real holdings list is personal financial information.

    .venv/bin/python scripts/make_design_reference.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.render.context import render_template  # noqa: E402
from src.schemas.brief import (  # noqa: E402
    AssetImpact, DailyBrief, EventWatch, FilteredItem, Interaction, Label,
    MarketPulse, PortfolioRead, SourceQuality, TelemetryReading, TopSignal,
)
from src.schemas.postclose import (  # noqa: E402
    AssetRecap, ClosePulse, Mover, PostCloseBrief, ScorecardItem,
)

OUT_DIR = Path(__file__).parent.parent / "src/render"
DATE = "2026-03-11"
OWNER = "Sample Reader"

# Demo compliance config, so the reference shows the full legal footer including
# the B-class fields that single-recipient mode omits.
LEGAL = {
    "copyright_holder": "Pre-market Radar",
    "contact": "support@example.com",
    "terms_url": "https://example.com/terms",
    "methodology_url": "https://example.com/how-it-works",
    "unsubscribe_url": "https://example.com/unsubscribe",
    "postal_address": "123 Example St, City, ST 00000",
}

TELEMETRY = [
    TelemetryReading(key="DGS2", value="3.92", unit="%", delta="+4个基点", flag=False),
    TelemetryReading(key="DGS10", value="4.41", unit="%", delta="+9个基点", flag=True,
                     note="本周第三日上行,长端定价的是期限溢价而非加息预期。"),
    TelemetryReading(key="DXY", value="103.18", unit="", delta="+0.31%", flag=False),
    TelemetryReading(key="VIX", value="17.60", unit="", delta="+1.4", flag=False),
]

SOURCE_QUALITY = SourceQuality(
    official=2, tier1=1, secondary=6, inference=2, report_confidence="Medium",
    limitation="多数条目来自聚合平台,原始通讯社不可得;宏观数字取自官方发布。",
)


def premarket() -> DailyBrief:
    return DailyBrief(
        date=DATE,
        report_type="premarket",
        signal_state="AMBER",
        market_pulse=MarketPulse(
            bias="混合 / 利率驱动",
            themes=[
                "长端收益率续升,压制高久期资产估值",
                "云资本开支指引成为科技股分歧点",
                "美元走强,黄金与新兴市场同步承压",
            ],
            key_question="10年期美债收益率站上4.40%之后,科技股的估值折价会否从长久期扩散到现金流稳定的大市值?",
            confidence="Medium",
            caveat="盘前成交清淡,方向性结论待开盘后成交量确认。",
        ),
        portfolio_read=PortfolioRead(
            posture="组合整体偏防守:两只权益持仓共享同一个利率贴现因子,而唯一的对冲仓位今日与它们同向下跌。",
            interactions=[
                Interaction(
                    kind="Shared driver", holdings=["AAPL", "MSFT"],
                    note="两者同受长端收益率上行压制,分散度低于表面——共同承担的是同一个贴现率风险。",
                ),
                Interaction(
                    kind="Hedge failure", holdings=["TLT", "AAPL"],
                    note="长债本应在权益回撤时提供缓冲,但今日收益率上行使其与权益同向,对冲暂时失效。",
                ),
            ],
            ripple="若云资本开支指引下修,冲击会从MSFT经供应链传导至半导体,再回到以科技为主的宽基敞口。",
            swing="10年期美债收益率能否在4.45%之下企稳——这决定今天是估值调整还是趋势反转。",
            watch=[
                "长端收益率日内是否回落至4.35%下方",
                "美元指数走强是否延续,以及对海外营收占比高的持仓的影响",
                "科技板块成交量能否配合价格企稳",
            ],
        ),
        telemetry=TELEMETRY,
        top_signals=[
            TopSignal(
                rank=1, signal="10年期美债收益率升至4.41%,为三周高位", affected=["AAPL", "MSFT", "TLT"],
                why="长端利率是组合内三只持仓的共同贴现因子,直接压制估值并使债券对冲失效。",
                label=Label(freshness="NEW", source="Official", impact="High"), confidence="High",
            ),
            TopSignal(
                rank=2, signal="据隔夜报道,某大型云厂商下调下季度资本开支指引", affected=["MSFT", "NVDA"],
                why="资本开支是AI硬件需求的领先指标,指引下修会先反映在半导体订单预期上。",
                label=Label(freshness="NEW", source="Secondary", impact="Medium"), confidence="Medium",
            ),
            TopSignal(
                rank=3, signal="美元指数连续第四日走强", affected=["AAPL"],
                why="海外营收占比高的持仓面临汇兑逆风,通常在财报季前被重新定价。",
                label=Label(freshness="RECENT", source="Official", impact="Low"), confidence="Medium",
            ),
        ],
        assets=[
            AssetImpact(
                ticker="AAPL", role="核心权益敞口", state="Watch",
                price=224.15, change_pct=-0.62,
                news="无点名新闻;盘前随大盘走弱,美元走强构成汇兑逆风。",
                impact="长端收益率上行压制估值倍数;海外营收占比高,美元每走强1%对折算营收构成约0.4%的拖累。",
                watch="能否守住222附近的前低——跌破则回撤从估值调整变为趋势破位。",
                confidence="Medium", meta={"板块": "大市值科技", "敏感度": "利率 · 美元"},
            ),
            AssetImpact(
                ticker="MSFT", role="核心权益敞口", state="Alert",
                price=408.30, change_pct=-1.24,
                news="据隔夜报道,同业下调云业务资本开支指引,板块盘前普遍走弱。",
                impact="资本开支指引若确认下修,AI相关营收预期需重估;该风险经供应链二阶传导至半导体持仓。",
                watch="410的整数关口与开盘后半小时成交量;放量跌破意味着机构在减仓而非散户情绪。",
                confidence="Medium", meta={"板块": "软件 · 云", "敏感度": "AI资本开支"},
            ),
            AssetImpact(
                ticker="TLT", role="久期对冲", state="Watch",
                price=88.40, change_pct=-0.83,
                news="长端收益率续升,长债价格同步走低。",
                impact="今日与权益同向下跌,对冲功能暂时失效——组合的有效分散度低于配置时的假设。",
                watch="收益率若回落至4.35%下方,对冲关系可望恢复;否则组合实际是单因子暴露。",
                confidence="Medium", meta={"久期": "长", "敏感度": "期限溢价"},
            ),
        ],
        events=[
            EventWatch(time="今日 08:30 ET", event="美国消费者物价指数(2月)", affected="全组合",
                       why="核心通胀读数直接决定长端收益率的下一步方向。", priority="HIGH"),
            EventWatch(time="明日 14:00 ET", event="联邦公开市场委员会会议纪要", affected="TLT · 全组合",
                       why="纪要中对期限溢价的表述会影响长端定价。", priority="MED"),
            EventWatch(time="周四 盘后", event="NVDA 财报", affected="MSFT · NVDA",
                       why="AI资本开支链条的关键验证点。", priority="MED"),
        ],
        filtered=[
            FilteredItem(headline="某分析师上调科技板块目标价", reason="评级变动不改变基本面,且未点名持仓。"),
            FilteredItem(headline="欧洲央行维持利率不变", reason="符合预期,对美元与美债无增量影响。"),
            FilteredItem(headline="原油库存超预期增加", reason="组合无能源敞口,传导路径过长。"),
            FilteredItem(headline="社交平台流传的并购传闻", reason="来源为社交媒体,无二次确认,不进主报告。"),
        ],
        source_quality=SOURCE_QUALITY,
    )


def postclose() -> PostCloseBrief:
    return PostCloseBrief(
        date=DATE,
        report_type="postclose",
        signal_state="AMBER",
        close_pulse=ClosePulse(
            bias="估值调整,非趋势反转",
            themes=["长端收益率盘中见顶回落", "云资本开支担忧局部化", "美元强势延续"],
            takeaway="晨报担心的估值折价扩散没有发生:收益率回落后大市值科技收复大半跌幅,但对冲仓位全天未能发挥作用。",
            confidence="Medium",
        ),
        scorecard=[
            ScorecardItem(
                item="命门:10年期美债收益率能否在4.45%之下企稳",
                morning_view="站上4.45%将使估值调整转为趋势反转",
                actual="盘中触及4.44%后回落至4.38%收盘,未突破",
                verdict="命中",
            ),
            ScorecardItem(
                item="MSFT 410关口与开盘后成交量",
                morning_view="放量跌破意味着机构减仓",
                actual="跌破410但成交量低于20日均值,尾盘收复至411上方",
                verdict="落空",
            ),
            ScorecardItem(
                item="长债对冲能否恢复",
                morning_view="收益率回落至4.35%下方则对冲关系恢复",
                actual="收益率回落但未到4.35%,TLT全天与权益同向",
                verdict="待续",
            ),
        ],
        telemetry=[
            TelemetryReading(key="DGS2", value="3.89", unit="%", delta="+1个基点", flag=False),
            TelemetryReading(key="DGS10", value="4.38", unit="%", delta="+6个基点", flag=True,
                             note="盘中高点4.44%后回落,长端买盘在4.40%上方出现。"),
            TelemetryReading(key="DXY", value="103.34", unit="", delta="+0.47%", flag=False),
            TelemetryReading(key="VIX", value="16.90", unit="", delta="-0.7", flag=False),
        ],
        movers=[
            Mover(ticker="MSFT", change_pct=-0.31, note="盘前跌逾1%,收益率回落后尾盘收复大半。"),
            Mover(ticker="TLT", change_pct=-0.54, note="长端收益率全天高于昨收,对冲未生效。"),
            Mover(ticker="AAPL", change_pct=0.18, note="低开高走,美元逆风被估值修复抵消。"),
        ],
        assets=[
            AssetRecap(
                ticker="AAPL", role="核心权益敞口", state="Nominal",
                close_price=225.55, change_pct=0.18,
                what_happened="低开0.6%后全天走高,收盘小幅翻红,成交量接近均值。",
                read="晨报担心的222前低未被测试;美元逆风在没有点名新闻时不足以单独驱动价格。",
                watch="明日消费者物价指数读数——这是决定贴现率方向的下一个变量。",
                confidence="Medium", meta={"板块": "大市值科技"},
            ),
            AssetRecap(
                ticker="MSFT", role="核心权益敞口", state="Watch",
                close_price=411.20, change_pct=-0.31,
                what_happened="盘前因同业资本开支传闻低开,盘中跌破410,尾盘收复。全天成交量低于20日均值。",
                read="缩量下跌说明抛压来自情绪而非机构调仓,资本开支担忧暂时被视为局部事件。",
                watch="周四 NVDA 财报是这条链的验证点,指引比业绩更重要。",
                confidence="Medium", meta={"板块": "软件 · 云"},
            ),
            AssetRecap(
                ticker="TLT", role="久期对冲", state="Watch",
                close_price=88.02, change_pct=-0.54,
                what_happened="长端收益率全天高于昨收,长债价格同步走低。",
                read="连续第二日与权益同向,组合的有效分散度仍低于配置假设。",
                watch="收益率回到4.30%下方才是对冲关系恢复的确认信号。",
                confidence="Medium", meta={"久期": "长"},
            ),
        ],
        after_hours=[
            "某半导体厂商盘后公布财报,营收超预期但下季度指引偏保守,盘后跌约3%。",
            "两只大市值科技股盘后无重大公告,盘后成交清淡。",
        ],
        tomorrow=[
            EventWatch(time="明日 08:30 ET", event="美国消费者物价指数(2月)", affected="全组合",
                       why="核心通胀读数决定长端收益率方向,是组合当前的共同风险因子。", priority="HIGH"),
            EventWatch(time="明日 13:00 ET", event="10年期国债标售", affected="TLT",
                       why="投标倍数偏弱会直接推高长端收益率。", priority="MED"),
        ],
        filtered=[
            FilteredItem(headline="某分析师上调科技板块目标价", reason="评级变动不改变基本面。"),
            FilteredItem(headline="零售销售数据小幅超预期", reason="未引发利率或美元的可见反应。"),
        ],
        source_quality=SOURCE_QUALITY,
    )


def main() -> None:
    for brief, name in ((premarket(), "_design_reference.html"),
                        (postclose(), "_design_reference_postclose.html")):
        html = render_template("brief.html.j2", brief, owner=OWNER, legal=LEGAL)
        path = OUT_DIR / name
        path.write_text(html, encoding="utf-8")
        print(f"wrote {path.relative_to(Path(__file__).parent.parent)}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
