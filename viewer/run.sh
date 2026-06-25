#!/usr/bin/env bash
# Build the frontend (only if missing or stale) and launch the viewer backend.
set -euo pipefail
cd "$(dirname "$0")/.."

# ponytail: rebuild only when dist is older than newest source; install only when deps are missing.
if [[ ! -d viewer/web/dist || -n "$(find viewer/web/src viewer/web/index.html -newer viewer/web/dist 2>/dev/null)" ]]; then
  [[ -d viewer/web/node_modules ]] || (cd viewer/web && npm install)
  (cd viewer/web && npm run build)
fi

exec uv run python -m viewer.server "$@"
