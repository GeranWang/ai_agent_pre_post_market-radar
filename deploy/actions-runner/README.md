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
