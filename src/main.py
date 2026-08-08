import json
import sys
from datetime import date as _date
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from src.deliver.mailer import EmailConfigError, send_brief_email
from src.pipeline.collect import collect_all
from src.pipeline.per_asset import run_per_asset
from src.pipeline.synthesize import run_synthesize
from src.render.markdown import render_markdown_text
from src.render.mjml import render_email_html
from src.schemas.per_asset import PerAssetSummary
from src.schemas.raw import RawMaterial
from src.timeutil import POSTCLOSE, resolve_report

console = Console()


ROOT = Path(__file__).parent.parent
INTERMEDIATE = ROOT / "output/intermediate"


def _find_intermediate(prefix: str, report_type: str, date) -> Path | None:
    """Locate a cached intermediate for --skip modes. Prefers the exact
    {prefix}_{type}_{date}.json, then the most recent {prefix}_{type}_*.json,
    then legacy untyped {prefix}_*.json (treated as premarket)."""
    d = date.isoformat() if hasattr(date, "isoformat") else str(date)
    exact = INTERMEDIATE / f"{prefix}_{report_type}_{d}.json"
    if exact.exists():
        return exact
    typed = sorted(INTERMEDIATE.glob(f"{prefix}_{report_type}_*.json"), reverse=True)
    if typed:
        return typed[0]
    legacy = sorted(INTERMEDIATE.glob(f"{prefix}_*.json"), reverse=True)
    # exclude already-typed names from the legacy glob
    legacy = [p for p in legacy if "_premarket_" not in p.name and "_postclose_" not in p.name]
    return legacy[0] if legacy else None


def _normalize_holding(entry) -> dict:
    """A holding may be a bare ticker string or a dict with optional name/sector/
    role. Missing fields stay empty — the brief infers them; the user is not
    expected to supply narrative direction."""
    if isinstance(entry, str):
        return {"ticker": entry, "name": "", "sector": "", "role": ""}
    return {
        "ticker": entry["ticker"],
        "name": entry.get("name", ""),
        "sector": entry.get("sector", ""),
        "role": entry.get("role", ""),
    }


def load_config() -> dict:
    """Load config/tickers.yaml — the single source of holdings.

    Missing config is fatal on purpose. An earlier version silently fell back to
    a second file, which meant a typo in the filename produced a confident brief
    about someone else's holdings. Better to stop than to be wrong quietly.
    """
    path = ROOT / "config/tickers.yaml"
    if not path.exists():
        console.print(f"[red]Config not found: {path}\n"
                      f"[/red]Create it from the template:\n"
                      f"  cp config/tickers.example.yaml config/tickers.yaml")
        sys.exit(1)
    raw = yaml.safe_load(path.read_text()) or {}

    return {
        "owner": (raw.get("owner") or "").strip(),
        "holdings": [_normalize_holding(h) for h in (raw.get("holdings") or [])],
        "watchlist": [{"ticker": w if isinstance(w, str) else w["ticker"]}
                      for w in (raw.get("watchlist") or [])],
        "macro_themes": raw.get("macro_themes") or [],
        "_source": path.name,
    }


def run(skip_collect: bool = False, skip_per_asset: bool = False,
        email_to: str | None = None, report_type: str | None = None,
        report_date=None) -> None:
    config = load_config()

    # Decide report type + trading day: explicit override wins, else the ET-clock rule.
    rt, rd = resolve_report()
    report_type = report_type or rt
    report_date = report_date or rd
    console.rule(f"[bold white]Pipeline · {report_type.upper()} · {report_date}")

    # Stage 1: collect
    if skip_collect:
        path = _find_intermediate("raw", report_type, report_date)
        if path is None:
            console.print("[red]No raw file found. Run without --skip-collect first.")
            sys.exit(1)
        raw = RawMaterial.model_validate_json(path.read_text())
        console.print(f"[dim]Skipped collect — loaded {path.name}")
    else:
        raw = collect_all(config, report_date, report_type)

    # Stage 2: per-asset summaries
    if skip_per_asset:
        path = _find_intermediate("per_asset", report_type, report_date)
        if path is None:
            console.print("[red]No per_asset file found. Run without --skip-per-asset first.")
            sys.exit(1)
        data = json.loads(path.read_text())
        summaries = {ticker: PerAssetSummary(**v) for ticker, v in data.items()}
        console.print(f"[dim]Skipped per-asset — loaded {path.name}")
    else:
        summaries = run_per_asset(raw, config)

    # Stage 3: synthesis — dispatch by report type
    if report_type == POSTCLOSE:
        from src.pipeline.synthesize_postclose import run_synthesize_postclose
        brief = run_synthesize_postclose(raw, summaries, config)
    else:
        brief = run_synthesize(raw, summaries, config)

    # Stage 4: render — only the email-safe HTML is written to disk.
    # Markdown is still rendered in-memory as the email's plain-text alternative.
    owner = config.get("owner", "")
    legal = config.get("legal", {})
    md_text = render_markdown_text(brief, owner=owner, legal=legal)
    email_html_path = render_email_html(brief, owner=owner, legal=legal)
    console.rule("[bold green]Done")
    console.print(f"Email    → [bold]{email_html_path}[/bold]")

    # Stage 5: deliver (opt-in). The email-safe MJML build is what we send.
    if email_to:
        try:
            send_brief_email(brief, email_html_path, email_to, md_text=md_text)
        except EmailConfigError as e:
            console.print(f"[red]Email not sent: {e}")
            sys.exit(2)
        except Exception as e:  # smtplib auth/connection errors
            console.print(f"[red]Email send failed: {e}")
            sys.exit(2)


def _parse_args(argv: list[str]) -> dict:
    """Tiny hand-rolled parser. Supports:
      --skip-collect / --skip-per-asset   reuse cached intermediates
      --email <addr>                       send the brief to <addr>
      --send                               send to EMAIL_TO from .env
    """
    import os

    opts: dict[str, object] = {"skip_collect": False, "skip_per_asset": False, "email_to": None,
                               "report_type": None, "report_date": None}
    it = iter(argv)
    for arg in it:
        if arg == "--skip-collect":
            opts["skip_collect"] = True
        elif arg == "--skip-per-asset":
            opts["skip_per_asset"] = True
        elif arg == "--report":
            val = next(it, None)
            if val not in ("premarket", "postclose"):
                console.print("[red]--report must be 'premarket' or 'postclose'")
                sys.exit(1)
            opts["report_type"] = val
        elif arg.startswith("--report="):
            opts["report_type"] = arg.split("=", 1)[1]
        elif arg == "--date":
            opts["report_date"] = _date.fromisoformat(next(it, ""))
        elif arg.startswith("--date="):
            opts["report_date"] = _date.fromisoformat(arg.split("=", 1)[1])
        elif arg == "--email":
            opts["email_to"] = next(it, None)
            if not opts["email_to"]:
                console.print("[red]--email requires an address, e.g. --email you@example.com")
                sys.exit(1)
        elif arg.startswith("--email="):
            opts["email_to"] = arg.split("=", 1)[1]
        elif arg == "--send":
            opts["email_to"] = os.environ.get("EMAIL_TO")
            if not opts["email_to"]:
                console.print("[red]--send needs EMAIL_TO set in .env (or use --email <addr>)")
                sys.exit(1)
        else:
            console.print(f"[yellow]Ignoring unknown argument: {arg}")
    return opts


if __name__ == "__main__":
    run(**_parse_args(sys.argv[1:]))
