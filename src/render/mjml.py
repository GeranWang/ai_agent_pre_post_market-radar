"""Render the brief to email-safe HTML via MJML.

Jinja fills `brief.mjml.j2` → MJML markup → mrml compiles it to bulletproof,
inlined, table-based HTML that survives Gmail / Outlook. This is the version
the mailer sends; `brief.html.j2` stays the web/archive version.

mrml is a Rust MJML engine with Python bindings (pip install mrml) — no Node.
"""
from pathlib import Path

import mrml

from src.render.context import OUTPUT_DIR, render_template


def render_email_html(brief, owner: str = "", legal: dict | None = None) -> Path:
    """Compile the brief into email-safe HTML and write output/<date>.<type>.email.html."""
    mjml_markup = render_template("brief.mjml.j2", brief, owner, legal)
    out = mrml.to_html(mjml_markup)
    if getattr(out, "warnings", None):
        # MJML warnings are non-fatal (e.g. unknown attribute) — surface count only.
        print(f"[mjml] {len(out.warnings)} warning(s) during compile")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{brief.date}.{brief.report_type}.email.html"
    out_path.write_text(out.content, encoding="utf-8")
    return out_path
