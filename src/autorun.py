"""Unattended scheduler tick — the entry point launchd calls every 5 minutes.

This is deliberately **not** a "fire once at exactly 08:45" job. It is a cheap
tick that asks two questions — *which report is due right now (ET)?* and *has it
already been sent?* — and only then runs the pipeline. Everything a laptop makes
hard falls out of that shape for free:

  * **DST**       — windows are evaluated in ET, so a US clock shift needs no edit
                    (a fixed Asia/Shanghai cron would drift an hour twice a year)
  * **sleep**     — a tick missed while the Mac slept fires on wake and catches up
  * **flaky net** — a failed attempt never writes "sent", so the next tick retries
  * **holidays**  — the trading day is *probed* (Yahoo marketState / last completed
                    session), never read from a hardcoded calendar

Send windows (ET), one job at most per tick:

    17:00 → 23:59   post-close, for today
    00:00 → 08:29   post-close, for yesterday   ← the wake-up catch-up window
    08:30 → 11:59   pre-market, for today
    12:00 → 16:59   nothing due (a "pre-market" brief past noon is worthless)

A tick that finds nothing due — the overwhelming majority — does no network I/O
at all, which is what makes a 5-minute poll interval cheap enough to buy the
timing precision a 19-minute pipeline needs.

Usage:
    python -m src.autorun              # normal tick (what launchd runs)
    python -m src.autorun --dry-run    # report the decision, run nothing
    python -m src.autorun --force      # ignore recorded state, run the due job
    python -m src.autorun --status     # print the state file
"""
import fcntl
import json
import os
import signal
import sys
import traceback
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.timeutil import POSTCLOSE, PREMARKET, now_utc, to_et

ROOT = Path(__file__).parent.parent
STATE_DIR = ROOT / "output/state"
STATE_FILE = STATE_DIR / "autorun.json"
LOCK_FILE = STATE_DIR / "autorun.lock"
LOG_FILE = ROOT / "output/logs/autorun.log"

# --- Send windows (ET). See module docstring. ---
# 08:30 is the earliest honest start: the 8:30 ET economic releases (CPI/NFP/PCE)
# must already be out or collect would fetch a calendar without actuals. It is
# also the *latest* start that still makes 09:00 — a full run measured 19 min
# (17 of them in collect, which fetches every source sequentially). Shrinking
# collect is the real fix; until then this window has no slack.
PREMARKET_OPEN = time(8, 30)
PREMARKET_CUTOFF = time(12, 0)
POSTCLOSE_OPEN = time(17, 0)     # 1h after the close: settled prices + after-hours earnings

# A transient failure (network, LLM timeout) is retried on the next tick.
MAX_ATTEMPTS = 6

# Hard wall-clock ceiling for one run. Without it a wedged socket would hold the
# lock forever and every later tick would exit "another tick is still running" —
# silent death, the one failure mode a daily brief cannot have. Generous vs the
# 19-min observed run so a merely slow day is never killed.
RUN_TIMEOUT_SEC = 45 * 60


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------

LOG_MAX_BYTES = 1_000_000


def log(msg: str, to_file: bool = True) -> None:
    """One line to stdout (captured by launchd) and to the rolling log file.

    `to_file=False` keeps the ~280 idle ticks a day out of autorun.log, so that
    file stays a readable ledger of things that actually happened; the verbose
    stream is still in launchd.out.log.
    """
    stamp = to_et(now_utc()).strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    if not to_file:
        return
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.1"))
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # logging must never be the reason a brief doesn't go out


# --------------------------------------------------------------------------
# what is due
# --------------------------------------------------------------------------

def due_job(now_et: datetime) -> tuple[str, date] | None:
    """(report_type, report_date) due at this ET moment, or None.

    Pure function of the clock — no I/O — so the window logic is testable and
    the same call decides both the dry-run preview and the real run.
    """
    t = now_et.time()
    d = now_et.date()

    if t >= POSTCLOSE_OPEN:
        job = (POSTCLOSE, d)                      # tonight's close
    elif t < PREMARKET_OPEN:
        job = (POSTCLOSE, d - timedelta(days=1))  # catch-up for last night's close
    elif t < PREMARKET_CUTOFF:
        job = (PREMARKET, d)
    else:
        return None

    # The report date must be a weekday; weekend catch-up windows resolve to
    # Saturday/Sunday "sessions" that never existed. Holidays are handled by
    # the empirical probe below, not here.
    return job if job[1].weekday() < 5 else None


def is_trading_session(report_type: str, report_date: date) -> bool | None:
    """Did / does `report_date` have a real US equity session? None = unknown.

    Post-close: the last completed session must *be* that date — on a holiday
    the feed still points at an earlier day. Pre-market: before the open there is
    no session to inspect, so we read Yahoo's live marketState, which is CLOSED
    on holidays and weekends and PRE once the pre-market session is running.
    """
    from src.sources.yfinance_prices import last_session_date, market_state

    if report_type == POSTCLOSE:
        last = last_session_date()
        return None if last is None else last == report_date

    state = market_state()
    return None if state is None else state != "CLOSED"


# --------------------------------------------------------------------------
# state (idempotency + retry budget)
# --------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    """Atomic write — a tick killed mid-save must not corrupt the ledger."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _record(key: str, **fields) -> None:
    state = _load_state()
    entry = state.get(key, {})
    entry.update(fields)
    entry["at"] = to_et(now_utc()).isoformat()
    state[key] = entry
    # Keep the ledger from growing forever: 60 most recent keys is ~6 weeks.
    if len(state) > 60:
        state = dict(sorted(state.items(), key=lambda kv: kv[1].get("at", ""))[-60:])
    _save_state(state)


# --------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------

@contextmanager
def _deadline(seconds: int):
    """Turn a wedged run into an ordinary failure the retry path can handle.

    SIGALRM interrupts blocking socket reads, which per-request HTTP timeouts
    don't cover when a source retries in a loop. Main thread only — that is
    where the pipeline runs.
    """
    def _fire(signum, frame):
        raise TimeoutError(f"run exceeded {seconds}s wall clock")

    previous = signal.signal(signal.SIGALRM, _fire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _alert(subject: str, body: str, recipient: str | None) -> None:
    """Best-effort failure notification. Never raises — an alert that fails
    must not mask the original error in the log."""
    if not recipient:
        return
    try:
        from src.deliver.mailer import send_alert_email
        send_alert_email(subject, body, recipient)
        log(f"alert email sent → {recipient}")
    except Exception as e:
        log(f"alert email failed: {e}")


def tick(force: bool = False, dry_run: bool = False) -> int:
    now = to_et(now_utc())
    job = due_job(now)
    if job is None:
        log(f"no report due at {now:%H:%M} ET", to_file=False)
        return 0

    report_type, report_date = job
    key = f"{report_type}:{report_date}"
    entry = _load_state().get(key, {})
    status = entry.get("status")

    if not force and status in ("sent", "skipped", "gave_up"):
        log(f"{key} already {status} — nothing to do", to_file=False)
        return 0

    trading = is_trading_session(report_type, report_date)
    if trading is False:
        log(f"{key} skipped — not a trading session (market closed)")
        _record(key, status="skipped", reason="not a trading session")
        return 0
    if trading is None:
        log(f"{key} — trading-day probe unavailable, proceeding anyway")

    recipient = os.environ.get("EMAIL_TO")
    if not recipient:
        log(f"{key} ABORT — EMAIL_TO is not set in .env; nothing to send to")
        _record(key, status="gave_up", error="EMAIL_TO not set")
        return 1

    attempts = int(entry.get("attempts", 0)) + 1
    if dry_run:
        log(f"[dry-run] would run {key} → {recipient} (attempt {attempts}/{MAX_ATTEMPTS})")
        return 0

    log(f"running {key} → {recipient} (attempt {attempts}/{MAX_ATTEMPTS})")
    _record(key, status="running", attempts=attempts)

    from src.main import run
    try:
        with _deadline(RUN_TIMEOUT_SEC):
            run(email_to=recipient, report_type=report_type, report_date=report_date)
    except SystemExit as e:          # main.run() exits non-zero on send failure
        err = f"pipeline exited with code {e.code}"
        return _handle_failure(key, attempts, err, "", recipient)
    except Exception as e:
        return _handle_failure(key, attempts, f"{type(e).__name__}: {e}",
                               traceback.format_exc(), recipient)

    log(f"{key} sent ✓")
    _record(key, status="sent", attempts=attempts, error=None)
    return 0


def _handle_failure(key: str, attempts: int, err: str, tb: str, recipient: str) -> int:
    log(f"{key} FAILED (attempt {attempts}/{MAX_ATTEMPTS}): {err}")
    if tb:
        log(tb.rstrip())

    if attempts >= MAX_ATTEMPTS:
        _record(key, status="gave_up", attempts=attempts, error=err)
        log(f"{key} giving up after {attempts} attempts")
        _alert(
            f"Pre-market Radar · 自动运行失败 · {key}",
            f"{key} 连续 {attempts} 次失败，已放弃本次投递。\n\n"
            f"最后一次错误:\n{err}\n\n"
            f"日志: {LOG_FILE}\n"
            f"手动重跑: cd {ROOT} && .venv/bin/python -m src.autorun --force\n",
            recipient,
        )
    else:
        _record(key, status="failed", attempts=attempts, error=err)
        log("will retry on the next tick")
    return 1


def main(argv: list[str]) -> int:
    if "--status" in argv:
        now = to_et(now_utc())
        print(f"now: {now.isoformat()}   due: {due_job(now)}")
        print(json.dumps(_load_state(), indent=2, ensure_ascii=False))
        return 0

    force = "--force" in argv
    dry_run = "--dry-run" in argv

    # One tick at a time. A pipeline run takes minutes; ticks are 15 min apart,
    # so a slow run must not have a second copy started on top of it.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another tick is still running — exiting")
            return 0
        return tick(force=force, dry_run=dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
