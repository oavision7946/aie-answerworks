#!/usr/bin/env bash
# check_private_leaks.sh: local guard against leaking private project material
# into the public repo.
#
# Usage (normally invoked by pre-commit, see .pre-commit-config.yaml):
#   scripts/check_private_leaks.sh staged
#   scripts/check_private_leaks.sh commit-msg <message-file>
#
# Checks:
#   1. Staged paths that must never be committed: .internal/, CLAUDE.local.md,
#      and real .env files.
#   2. Terms from .internal/denylist.txt in staged file names, staged added
#      lines, and the commit message. If the denylist is not available (for
#      example an outside contributor without access to the internal repo),
#      this check is skipped with a note.
#
# Output is meant for your local terminal only. Do not send it to public CI logs.

set -euo pipefail

MODE="${1:-staged}"
MSG_FILE="${2:-}"

ROOT="$(git rev-parse --show-toplevel)"
DENYLIST="$ROOT/.internal/denylist.txt"
FORBIDDEN_PATHS='(^|/)\.internal(/|$)|(^|/)CLAUDE\.local\.md$|(^|/)\.env$|(^|/)\.env\.(local|prod|production|staging)$'

fail=0
terms="$(mktemp)"
trap 'rm -f "$terms"' EXIT

# Loads non-empty, non-comment denylist terms into $terms.
# Returns 1 (with a note) if the denylist is missing or empty.
load_denylist() {
  if [ ! -f "$DENYLIST" ]; then
    echo "note: .internal/denylist.txt not found; term scan skipped." >&2
    return 1
  fi
  grep -vE '^[[:space:]]*(#|$)' "$DENYLIST" > "$terms" || true
  if [ ! -s "$terms" ]; then
    echo "note: .internal/denylist.txt has no terms; term scan skipped." >&2
    return 1
  fi
  return 0
}

indent() { sed 's/^/  /' >&2; }

check_staged() {
  local files bad hits
  files="$(git diff --cached --name-only --diff-filter=ACMR)"
  [ -z "$files" ] && return 0

  # 1. Forbidden paths
  bad="$(printf '%s\n' "$files" | grep -E "$FORBIDDEN_PATHS" || true)"
  if [ -n "$bad" ]; then
    echo "BLOCKED: private or local-only paths are staged:" >&2
    printf '%s\n' "$bad" | indent
    fail=1
  fi

  # 2. Denylisted terms
  if load_denylist; then
    hits="$(printf '%s\n' "$files" | grep -iFf "$terms" || true)"
    if [ -n "$hits" ]; then
      echo "BLOCKED: staged file names contain denylisted terms:" >&2
      printf '%s\n' "$hits" | head -20 | indent
      fail=1
    fi

    hits="$(git diff --cached -U0 --no-color --diff-filter=ACMR \
      | grep -E '^\+' | grep -vE '^\+\+\+ ' \
      | grep -iFf "$terms" || true)"
    if [ -n "$hits" ]; then
      echo "BLOCKED: staged changes contain denylisted terms:" >&2
      printf '%s\n' "$hits" | head -20 | indent
      fail=1
    fi
  fi
}

check_msg() {
  if [ -z "$MSG_FILE" ] || [ ! -f "$MSG_FILE" ]; then
    echo "usage: $0 commit-msg <message-file>" >&2
    exit 2
  fi
  if load_denylist; then
    if grep -vE '^#' "$MSG_FILE" | grep -iFf "$terms" > /dev/null; then
      echo "BLOCKED: commit message contains denylisted terms." >&2
      fail=1
    fi
  fi
}

case "$MODE" in
  staged)     check_staged ;;
  commit-msg) check_msg ;;
  *)
    echo "usage: $0 {staged|commit-msg <message-file>}" >&2
    exit 2
    ;;
esac

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "Commit aborted. Fix the content, or update .internal/denylist.txt if this is a false positive." >&2
  exit 1
fi
