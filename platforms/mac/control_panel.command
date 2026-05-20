#!/bin/zsh
set -u

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
exec "$ROOT/Codex Proxy Control.app/Contents/MacOS/Codex Proxy Control"
