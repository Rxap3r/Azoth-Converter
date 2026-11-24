#!/usr/bin/env bash
# Start of every chat: bring the local `dev` up to date with GitHub's `dev`.
# Never throws work away: with uncommitted changes or commits that are not on
# GitHub yet, it changes nothing and prints a warning for Claude to pass on.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

warn() { echo "SYNC-DEV WARNING (tell the owner): $*"; exit 0; }

ok=
for wait in 0 2 4 8; do
  sleep "$wait"
  git fetch -q origin dev 2>/dev/null && { ok=1; break; }
done
[ -n "$ok" ] || warn "could not fetch dev from GitHub; the local copy may be old."

branch=$(git branch --show-current)
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  warn "uncommitted changes on '${branch:-detached}'; dev was NOT updated. $(git status --short --untracked-files=no | head -5 | tr '\n' ' ')"
fi
for b in dev "$branch"; do
  [ -n "$b" ] && git rev-parse -q --verify "refs/heads/$b" >/dev/null || continue
  extra=$(git rev-list --count "origin/dev..$b")
  [ "$extra" -eq 0 ] || warn "local '$b' has $extra commit(s) not on GitHub's dev; dev was NOT updated. Merge them into dev (see CLAUDE.md)."
done

git checkout -q -B dev origin/dev && echo "sync-dev: on dev at $(git log -1 --format='%h %s' HEAD) (same as GitHub)."
