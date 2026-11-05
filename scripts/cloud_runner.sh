#!/bin/bash
# Pre-market Radar — cloud scheduler (GitHub Actions) control.
#
#   ./scripts/cloud_runner.sh create         create the PRIVATE runner repo + upload secrets
#   ./scripts/cloud_runner.sh secrets        re-upload .env + config/tickers.yaml after editing them
#   ./scripts/cloud_runner.sh sync           push deploy/actions-runner/ changes to the runner repo
#   ./scripts/cloud_runner.sh run [mode]     trigger now: tick | dry-run | force | preview (no email)
#   ./scripts/cloud_runner.sh status         recent runs + the sent ledger
#
# The runner repo holds only a copy of the workflow (deploy/actions-runner/) and
# the state it commits back; `sync` refreshes that copy after a template change. Code is checked out from this repo's origin on every run, so
# a change reaches the cloud when it is pushed to main. The runner repo must stay
# private: its logs print holdings and prices.
#
# Needs the GitHub CLI: brew install gh && gh auth login
# Runner repo defaults to <your login>/market-radar-runner; override with RADAR_RUNNER.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO/deploy/actions-runner"

die() { echo "$*" >&2; exit 1; }

command -v gh >/dev/null || die "GitHub CLI not found — brew install gh && gh auth login"
gh auth status >/dev/null 2>&1 || die "gh is not logged in — run: gh auth login"
RUNNER="${RADAR_RUNNER:-$(gh api user -q .login)/market-radar-runner}"
APP="$(git -C "$REPO" remote get-url origin | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"

# Commit in a scratch clone as this repo's identity — without it git falls back
# to user@hostname, which leaks the machine name into the runner's history.
commit() {
    git -C "$1" -c user.name="$(git -C "$REPO" config user.name)" \
        -c user.email="$(git -C "$REPO" config user.email)" commit -q -m "$2"
}

upload_secrets() {
    [ -f "$REPO/.env" ] || die "missing $REPO/.env"
    [ -f "$REPO/config/tickers.yaml" ] || die "missing $REPO/config/tickers.yaml"
    gh secret set -f "$REPO/.env" -R "$RUNNER"
    gh secret set TICKERS_YAML -R "$RUNNER" < "$REPO/config/tickers.yaml"
}

cmd="${1:-status}"

case "$cmd" in
create)
    gh repo view "$RUNNER" >/dev/null 2>&1 && die "$RUNNER already exists — use: $0 secrets"
    [ -n "$APP" ] || die "cannot read the code repo from git remote 'origin'"

    work="$(mktemp -d)"
    cp -R "$TEMPLATE/." "$work/"
    git -C "$work" init -q -b main
    git -C "$work" add -A
    commit "$work" "Runner for $APP"

    gh repo create "$RUNNER" --private --source "$work" --push
    gh variable set APP_REPO -R "$RUNNER" -b "$APP"
    upload_secrets
    rm -rf "$work"

    echo
    echo "created: https://github.com/$RUNNER  (private, code from $APP@main)"
    echo "smoke test without email:  $0 run preview"
    echo "do NOT also install the launchd agent — two ledgers mean two emails"
    ;;

secrets)
    upload_secrets
    echo "secrets updated on $RUNNER"
    ;;

sync)
    work="$(mktemp -d)"
    gh repo clone "$RUNNER" "$work" -- -q
    cp -R "$TEMPLATE/." "$work/"
    git -C "$work" add -A
    if git -C "$work" diff --cached --quiet; then
        echo "$RUNNER already matches deploy/actions-runner/"
    else
        git -C "$work" diff --cached --stat
        commit "$work" "Sync workflow from $APP"
        git -C "$work" push -q
        echo "synced → $RUNNER"
    fi
    rm -rf "$work"
    ;;

run)
    gh workflow run radar.yml -R "$RUNNER" -f mode="${2:-tick}"
    echo "triggered ${2:-tick} on $RUNNER — follow it with: gh run watch -R $RUNNER"
    ;;

status)
    gh run list -R "$RUNNER" --workflow radar.yml -L 10
    echo
    gh api -H "Accept: application/vnd.github.raw" "repos/$RUNNER/contents/state/autorun.json" 2>/dev/null \
        || echo "(no ledger yet — nothing has been sent)"
    ;;

*)
    sed -n '2,8p' "${BASH_SOURCE[0]}"
    exit 1
    ;;
esac
