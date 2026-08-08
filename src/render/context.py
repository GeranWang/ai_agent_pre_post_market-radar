"""Shared render plumbing — the Jinja environment plus the context values every
template needs, computed once.

Keeps generated_at / day_number / coverage / greeting consistent across the
Markdown, HTML, and MJML renders instead of each module recomputing them.
Everything here branches on report type where the two briefs genuinely differ:
the post-close brief is delivered in the evening and must not greet with 早安.
"""
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.timeutil import now_utc, to_et

TEMPLATE_DIR = Path(__file__).parent
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


def _coverage_window(date_str: str, post: bool) -> str:
    """Human, trust-building description of the content window the brief covers.

    Pre-market covers "previous close → this morning"; the start depends on the
    weekday (Monday reaches back to Friday's close, covering the weekend).
    Post-close covers the session that just ended plus after-hours. Holiday-
    adjacent days fall back to generic phrasing, in line with collect.py.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    wd = d.weekday()  # Mon=0 … Sun=6
    if post:
        return "覆盖 今日 09:30–16:00 ET 交易时段 + 盘后 · 投递 17:00 ET"
    if wd == 0:        # Monday
        start = "上周五 16:00 ET 收盘"
    elif 1 <= wd <= 4:  # Tue–Fri
        start = "昨日 16:00 ET 收盘"
    else:               # Sat/Sun — not a normal delivery day, generic fallback
        start = "上一交易日收盘"
    return f"覆盖 {start} → 今早 · 投递 09:00 ET"


_CN_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _greeting(date_str: str, owner: str, post: bool) -> str:
    """A warm, personal opening line. Composed here (not by the LLM) so it stays
    reliable and fluff-free. Tone shifts by weekday — and by report: the
    post-close brief lands in the evening, where "早安" would be absurd.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    wd = d.weekday()
    if post:
        if wd == 4:
            tail = "本周收官,周末好好休息。"
        elif wd >= 5:
            tail = "这是为你留存的一份收盘存档。"
        else:
            tail = "今天的盘已经走完了。"
        who = f"晚上好,{owner}。" if owner else "晚上好。"
        return f"{who}这是 {d.month} 月 {d.day} 日({_CN_WEEKDAY[wd]})的收盘总结 —— {tail}"

    if wd == 0:
        tail = "新的一周,愿开盘顺利。"
    elif wd == 4:
        tail = "本周最后一个交易日,稳健收官。"
    elif wd >= 5:
        tail = "周末好,这是为你留存的一份盘前存档。"
    else:
        tail = "祝你今天交易顺利。"
    who = f"早安,{owner}。" if owner else "早安。"
    return f"{who}这是 {d.month} 月 {d.day} 日({_CN_WEEKDAY[wd]})的盘前雷达 —— {tail}"


def _legal(date_str: str, legal_cfg: dict | None) -> dict:
    """Compliance / footer boilerplate. The *static* disclaimer prose lives in the
    templates (product-wide, not data); the *variable* bits (legal name, contact,
    URLs, postal address) come from config so nothing is hardcoded. B-class fields
    (unsubscribe_url, postal_address) render only when set — single-recipient mode
    omits them, multi-recipient sending fills them in.
    """
    d = {
        "product": "Pre-market Radar",
        "copyright_holder": "Pre-market Radar",
        "year": date_str[:4],
        "contact": "",          # support / feedback address
        "terms_url": "",        # full terms & disclaimer page
        "methodology_url": "",  # "how this is made" explainer
        "unsubscribe_url": "",  # CAN-SPAM: required once sending to others
        "postal_address": "",   # CAN-SPAM: sender's physical postal address
    }
    d.update({k: v for k, v in (legal_cfg or {}).items() if v})
    return d


def build_common_context(brief, owner: str = "", legal: dict | None = None) -> dict:
    """Values every template needs. `brief` is a DailyBrief or a PostCloseBrief —
    both carry `date` and `report_type`, which is all this needs."""
    now_et = to_et(now_utc())
    post = getattr(brief, "report_type", "premarket") == "postclose"
    return {
        "generated_at": now_et.strftime("%H:%M"),
        "day_number": datetime.strptime(brief.date, "%Y-%m-%d").timetuple().tm_yday,
        "coverage": _coverage_window(brief.date, post),
        "greeting": _greeting(brief.date, owner, post),
        "legal": _legal(brief.date, legal),
    }


def render_template(template_name: str, brief, owner: str = "",
                    legal: dict | None = None) -> str:
    """Fill one of the brief templates with the brief plus the common context.

    The single place a Jinja environment is built — the three output formats
    differ only in which template they name and what they do with the string.
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), keep_trailing_newline=True)
    return env.get_template(template_name).render(
        brief=brief, **build_common_context(brief, owner, legal))
