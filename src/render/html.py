"""Web/archive HTML render.

Not part of the daily delivery path — the mailer sends the MJML build. This is
the renderer behind `src/render/_design_reference*.html`, the canonical visual
reference that DESIGN.md §11 requires regenerating after any visual change.
"""
from pathlib import Path

from src.render.context import OUTPUT_DIR, render_template


def render_html(brief, owner: str = "", legal: dict | None = None) -> Path:
    content = render_template("brief.html.j2", brief, owner, legal)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{brief.date}.{brief.report_type}.html"
    out_path.write_text(content)
    return out_path
