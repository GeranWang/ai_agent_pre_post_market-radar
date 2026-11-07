# Pre-market Radar — runner

**Keep this repository private.** Its Actions logs print holdings, prices and
brief previews, and `state/` holds the sent ledger and every brief.

This repo holds no code. On every scheduled tick, `.github/workflows/radar.yml`
checks out the code repo named by the `APP_REPO` variable (branch `APP_REF`,
default `main`), writes `.env` and `config/tickers.yaml` from this repo's
secrets, runs `python -m src.autorun`, and commits the ledger and briefs back
into `state/`.

| Path | What it is |
|---|---|
| `state/autorun.json` | The sent ledger, the only thing preventing duplicate emails |
| `state/intermediate/brief_*.json` | Every brief; the post-close scorecard reads the same day's pre-market one |

Created and managed from the code repo with `scripts/cloud_runner.sh`
(`create` / `secrets` / `run` / `status`). Raw and per-asset intermediates and the
email HTML are uploaded as a run artifact for 14 days.

## On-time triggers

GitHub's `schedule` is best-effort and, for a new low-traffic repo, far worse
than the docs suggest: on this runner's first day 2 of 18 cron ticks fired, each
4–5 hours late. The cron lines stay as a backup, but delivery time comes from an
external cron that calls the `workflow_dispatch` API. Extra or overlapping ticks
are harmless: the ledger decides whether anything is due.

1. **Token.** Create a fine-grained personal access token limited to this
   repository, with one permission: *Actions → Read and write*.
2. **Cron job** (e.g. cron-job.org), time zone `America/New_York`:

   | Field | Value |
   |---|---|
   | URL | `https://api.github.com/repos/<owner>/<runner-repo>/actions/workflows/radar.yml/dispatches` |
   | Schedule | Mon–Fri, hours 8, 9, 17, minutes 3, 33 |
   | Method | `POST` |
   | Headers | `Accept: application/vnd.github+json` · `Authorization: Bearer <token>` · `X-GitHub-Api-Version: 2022-11-28` · `Content-Type: application/json` |
   | Body | `{"ref":"main","inputs":{"mode":"tick"}}` |

   That is 08:33 / 09:03 / 09:33 for the pre-market and 17:03 / 17:33 for the
   post-close; 08:03 falls outside every window and does nothing. A successful
   call returns `204 No Content`. A `401` means the token expired.
