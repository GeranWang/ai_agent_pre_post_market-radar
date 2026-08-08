"""Markdown render — used as the email's plain-text alternative."""
from src.render.context import render_template


def render_markdown_text(brief, owner: str = "", legal: dict | None = None) -> str:
    """Render the brief to Markdown and return it as a string (no disk write)."""
    return render_template("brief.md.j2", brief, owner, legal)
